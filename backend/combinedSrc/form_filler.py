"""Offline form-field injector for sandbox debugging (not for server-side use)."""

import argparse
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from pypdf import PdfReader, PdfWriter
from pypdf.generic import (
    ArrayObject,
    BooleanObject,
    DecodedStreamObject,
    DictionaryObject,
    NameObject,
    NumberObject,
    TextStringObject,
)

from .calibration import compute_label_height_calibration
from .config import DEFAULT_THRESHOLDS, get_logger
from .output_layout import temp_prefix_from_pdf
from .heuristic_resolver import resolve_fields_heuristically

logger = get_logger(__name__)

# PDF field flag bits (see PDF spec): ReadOnly=1, Required=2.
FLAG_READ_ONLY = 1 << 0
FLAG_REQUIRED = 1 << 1

# Button field flags: NoToggleToOff=1<<14, Radio=1<<15, Pushbutton=1<<16.
FLAG_NO_TOGGLE_TO_OFF = 1 << 14
FLAG_RADIO = 1 << 15
FLAG_PUSHBUTTON = 1 << 16

# Choice field flag: Combo=1<<17.
FLAG_COMBO = 1 << 17

WIDGET_DEDUPE_TOL = float(os.getenv("SANDBOX_WIDGET_DEDUPE_TOL", "0.5"))
STRIP_EXISTING_FIELDS = os.getenv("SANDBOX_STRIP_EXISTING_FIELDS", "false").lower() == "true"
DEDUP_EXISTING_WIDGETS = os.getenv("SANDBOX_DEDUP_EXISTING_WIDGETS", "true").lower() == "true"


def _resolve_origin(template: Dict[str, Any]) -> str:
    coordinate_system = str(template.get("coordinateSystem") or "").lower()
    if "origintop" in coordinate_system or "top" in coordinate_system:
        return "top-left"
    if "originbottom" in coordinate_system or "bottom" in coordinate_system:
        return "bottom-left"
    origin = str(template.get("coordinateOrigin") or "").strip().lower()
    if origin:
        return origin
    return "top-left"


def _field_flags(field: Dict[str, Any]) -> int:
    flags = 0
    read_only = field.get("readonly") if "readonly" in field else field.get("readOnly")
    if read_only:
        flags |= FLAG_READ_ONLY
    if field.get("required"):
        flags |= FLAG_REQUIRED
    return flags


def _normalize_rect(field: Dict[str, Any]) -> Optional[List[float]]:
    rect = field.get("rect")
    if rect and isinstance(rect, list) and len(rect) == 4:
        return [float(v) for v in rect]

    x = field.get("x")
    y = field.get("y")
    width = field.get("width")
    height = field.get("height")
    if x is None or y is None or width is None or height is None:
        return None

    x1 = float(x)
    y1 = float(y)
    return [x1, y1, x1 + float(width), y1 + float(height)]


def _rects_nearly_equal(a: List[float], b: List[float], tol: float) -> bool:
    if len(a) != 4 or len(b) != 4:
        return False
    return all(abs(float(a[i]) - float(b[i])) <= tol for i in range(4))


def _normalize_field_kind(field_type: str) -> str:
    ft = (field_type or "").strip().lower()
    if ft in {"checkbox", "radio"}:
        return "button"
    if ft in {"combo", "combobox"}:
        return "choice"
    if ft == "signature":
        return "signature"
    return "text"


def _pdf_field_kind(field_type: Any) -> str:
    ft = str(field_type or "")
    mapping = {
        "/Tx": "text",
        "/Btn": "button",
        "/Ch": "choice",
        "/Sig": "signature",
    }
    return mapping.get(ft, "unknown")


def _collect_existing_widgets(writer: PdfWriter) -> Dict[int, List[Dict[str, Any]]]:
    existing: Dict[int, List[Dict[str, Any]]] = {}
    for page_idx, page in enumerate(writer.pages, start=1):
        annots = page.get("/Annots")
        if annots is None:
            continue
        try:
            annots = annots.get_object()
        except AttributeError:
            pass
        for annot_ref in list(annots):
            annot = annot_ref.get_object() if hasattr(annot_ref, "get_object") else annot_ref
            if annot.get("/Subtype") != "/Widget":
                continue
            rect = annot.get("/Rect")
            if not rect or len(rect) != 4:
                continue
            ft = annot.get("/FT")
            if ft is None and annot.get("/Parent") is not None:
                parent = annot.get("/Parent").get_object()
                ft = parent.get("/FT")
            existing.setdefault(page_idx, []).append(
                {
                    "rect": [float(v) for v in rect],
                    "kind": _pdf_field_kind(ft),
                }
            )
    return existing


def _strip_existing_widget_annots(writer: PdfWriter) -> int:
    removed = 0
    for page in writer.pages:
        annots = page.get("/Annots")
        if annots is None:
            continue
        try:
            annots = annots.get_object()
        except AttributeError:
            pass
        if not annots:
            continue
        filtered = ArrayObject()
        for annot_ref in list(annots):
            annot = annot_ref.get_object() if hasattr(annot_ref, "get_object") else annot_ref
            if annot.get("/Subtype") == "/Widget":
                removed += 1
                continue
            filtered.append(annot_ref)
        page[NameObject("/Annots")] = filtered
    return removed


def _reset_acroform_fields(acroform: DictionaryObject) -> None:
    acroform[NameObject("/Fields")] = ArrayObject()


def _dedupe_existing_widget_annots(writer: PdfWriter, tol: float) -> int:
    removed = 0
    for page in writer.pages:
        annots = page.get("/Annots")
        if annots is None:
            continue
        try:
            annots = annots.get_object()
        except AttributeError:
            pass
        if not annots:
            continue
        seen = []
        filtered = ArrayObject()
        for annot_ref in list(annots):
            annot = annot_ref.get_object() if hasattr(annot_ref, "get_object") else annot_ref
            if annot.get("/Subtype") != "/Widget":
                filtered.append(annot_ref)
                continue
            rect = annot.get("/Rect")
            if not rect or len(rect) != 4:
                filtered.append(annot_ref)
                continue
            field_type = annot.get("/FT")
            if field_type is None and annot.get("/Parent") is not None:
                parent = annot.get("/Parent").get_object()
                field_type = parent.get("/FT")
            field_kind = _pdf_field_kind(field_type)
            rect_vals = [float(v) for v in rect]
            is_dup = False
            for prev_kind, prev_rect in seen:
                if prev_kind not in {field_kind, "unknown"}:
                    continue
                if _rects_nearly_equal(prev_rect, rect_vals, tol):
                    is_dup = True
                    break
            if is_dup:
                removed += 1
                continue
            seen.append((field_kind, rect_vals))
            filtered.append(annot_ref)
        page[NameObject("/Annots")] = filtered
    return removed


def _has_duplicate_widget(
    existing: Dict[int, List[Dict[str, Any]]],
    page_idx: int,
    field_kind: str,
    rect: List[float],
) -> bool:
    for widget in existing.get(page_idx, []):
        widget_kind = widget.get("kind")
        if widget_kind not in {field_kind, "unknown"}:
            continue
        if _rects_nearly_equal(widget.get("rect") or [], rect, WIDGET_DEDUPE_TOL):
            return True
    return False


def _to_pdf_rect(
    rect: List[float],
    *,
    page_height: float,
    origin: str,
) -> List[float]:
    x1, y1, x2, y2 = rect
    if origin.startswith("top"):
        return [x1, page_height - y2, x2, page_height - y1]
    return [x1, y1, x2, y2]


def _ensure_acroform(writer: PdfWriter) -> DictionaryObject:
    root = writer._root_object  # pylint: disable=protected-access
    acroform = root.get("/AcroForm")
    if acroform is None:
        acroform = DictionaryObject()
        root[NameObject("/AcroForm")] = acroform
    else:
        acroform = acroform.get_object()

    fields = acroform.get("/Fields")
    if fields is None:
        acroform[NameObject("/Fields")] = ArrayObject()

    if "/DR" not in acroform:
        acroform[NameObject("/DR")] = DictionaryObject()
    if "/DA" not in acroform:
        acroform[NameObject("/DA")] = TextStringObject("/Helv 10 Tf 0 g")

    dr = acroform["/DR"].get_object()
    if "/Font" not in dr:
        dr[NameObject("/Font")] = DictionaryObject()
    font_dict = dr["/Font"].get_object()
    if "/Helv" not in font_dict:
        helv = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
        font_ref = writer._add_object(helv)  # pylint: disable=protected-access
        font_dict[NameObject("/Helv")] = font_ref

    acroform[NameObject("/NeedAppearances")] = BooleanObject(True)
    return acroform


def _add_annotation(page, annot_ref):
    annots = page.get("/Annots")
    if annots is None:
        annots = ArrayObject()
        page[NameObject("/Annots")] = annots
    else:
        annots = annots.get_object()
    annots.append(annot_ref)


def _register_field(acroform: DictionaryObject, field_ref):
    fields = acroform.get("/Fields")
    if fields is None:
        fields = ArrayObject()
        acroform[NameObject("/Fields")] = fields
    else:
        fields = fields.get_object()
    fields.append(field_ref)


def _checkbox_checked(value: Any, export_value: str) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    value_str = str(value).strip().lower()
    if value_str in {"true", "yes", "on", "1"}:
        return True
    return value_str == export_value.strip().lower()


def _fields_from_candidates(template: Dict[str, Any]) -> List[Dict[str, Any]]:
    candidates = template.get("candidates") or []
    if not candidates:
        return []

    labels_by_page: Dict[int, List[Dict[str, Any]]] = {}
    for page in candidates:
        page_idx = int(page.get("page") or 0)
        labels_by_page[page_idx] = list(page.get("labels") or [])

    calibrations = compute_label_height_calibration(labels_by_page)
    meta = {
        "session_id": template.get("sessionId", "debug"),
        "source_pdf": template.get("sourcePdf", "input.pdf"),
        "thresholds": template.get("thresholds") or DEFAULT_THRESHOLDS,
        "calibrations": calibrations,
    }
    resolved = resolve_fields_heuristically(candidates, meta, labels_by_page, calibrations)
    return list(resolved.get("fields") or [])


def _build_field_list(template: Dict[str, Any]) -> List[Dict[str, Any]]:
    fields = list(template.get("fields") or [])
    if fields:
        return fields
    logger.info("No fields provided; synthesizing from candidates.")
    return _fields_from_candidates(template)


def _add_text_field(
    writer: PdfWriter,
    page,
    acroform: DictionaryObject,
    *,
    name: str,
    rect: List[float],
    flags: int,
    value: Any = None,
):
    field = DictionaryObject(
        {
            NameObject("/FT"): NameObject("/Tx"),
            NameObject("/T"): TextStringObject(name),
            NameObject("/Rect"): ArrayObject([NumberObject(v) for v in rect]),
            NameObject("/Subtype"): NameObject("/Widget"),
            NameObject("/Ff"): NumberObject(flags),
        }
    )
    if value is not None:
        field[NameObject("/V")] = TextStringObject(str(value))
    field_ref = writer._add_object(field)  # pylint: disable=protected-access
    _add_annotation(page, field_ref)
    _register_field(acroform, field_ref)


def _add_checkbox_field(
    writer: PdfWriter,
    page,
    acroform: DictionaryObject,
    *,
    name: str,
    rect: List[float],
    flags: int,
    export_value: str,
    value: Any = None,
):
    # Create a visible widget appearance so viewers that ignore NeedAppearances
    # still show checkbox outlines (and optional check marks).
    width = float(rect[2]) - float(rect[0])
    height = float(rect[3]) - float(rect[1])
    ap_off = _build_checkbox_appearance(writer, width=width, height=height, checked=False)
    ap_on = _build_checkbox_appearance(writer, width=width, height=height, checked=True)
    checked = _checkbox_checked(value, export_value)
    field = DictionaryObject(
        {
            NameObject("/FT"): NameObject("/Btn"),
            NameObject("/T"): TextStringObject(name),
            NameObject("/Rect"): ArrayObject([NumberObject(v) for v in rect]),
            NameObject("/Subtype"): NameObject("/Widget"),
            NameObject("/Ff"): NumberObject(flags),
            NameObject("/AS"): NameObject(f"/{export_value}" if checked else "/Off"),
            NameObject("/V"): NameObject(f"/{export_value}" if checked else "/Off"),
        }
    )
    if ap_off is not None and ap_on is not None:
        field[NameObject("/AP")] = DictionaryObject(
            {
                NameObject("/N"): DictionaryObject(
                    {
                        NameObject("/Off"): ap_off,
                        NameObject(f"/{export_value}"): ap_on,
                    }
                )
            }
        )
    field_ref = writer._add_object(field)  # pylint: disable=protected-access
    _add_annotation(page, field_ref)
    _register_field(acroform, field_ref)


def _build_checkbox_appearance(
    writer: PdfWriter,
    *,
    width: float,
    height: float,
    checked: bool,
):
    if width <= 0.0 or height <= 0.0:
        return None
    inset = max(min(width, height) * 0.08, 0.6)
    border_width = max(min(width, height) * 0.08, 0.6)
    inner_w = max(width - (inset * 2.0), 0.0)
    inner_h = max(height - (inset * 2.0), 0.0)
    commands = [
        "0 0 0 RG",
        f"{border_width:.2f} w",
        f"{inset:.2f} {inset:.2f} {inner_w:.2f} {inner_h:.2f} re S",
    ]
    if checked:
        x1 = inset + inner_w * 0.20
        y1 = inset + inner_h * 0.55
        x2 = inset + inner_w * 0.45
        y2 = inset + inner_h * 0.25
        x3 = inset + inner_w * 0.80
        y3 = inset + inner_h * 0.75
        commands.append(
            f"{x1:.2f} {y1:.2f} m {x2:.2f} {y2:.2f} l {x3:.2f} {y3:.2f} l S"
        )
    stream = DecodedStreamObject()
    stream.set_data("\n".join(commands).encode("ascii"))
    stream.update(
        {
            NameObject("/Type"): NameObject("/XObject"),
            NameObject("/Subtype"): NameObject("/Form"),
            NameObject("/BBox"): ArrayObject(
                [
                    NumberObject(0),
                    NumberObject(0),
                    NumberObject(width),
                    NumberObject(height),
                ]
            ),
            NameObject("/Resources"): DictionaryObject(),
        }
    )
    return writer._add_object(stream)  # pylint: disable=protected-access


def _add_signature_field(
    writer: PdfWriter,
    page,
    acroform: DictionaryObject,
    *,
    name: str,
    rect: List[float],
    flags: int,
):
    field = DictionaryObject(
        {
            NameObject("/FT"): NameObject("/Sig"),
            NameObject("/T"): TextStringObject(name),
            NameObject("/Rect"): ArrayObject([NumberObject(v) for v in rect]),
            NameObject("/Subtype"): NameObject("/Widget"),
            NameObject("/Ff"): NumberObject(flags),
        }
    )
    field_ref = writer._add_object(field)  # pylint: disable=protected-access
    _add_annotation(page, field_ref)
    _register_field(acroform, field_ref)


def _add_combo_field(
    writer: PdfWriter,
    page,
    acroform: DictionaryObject,
    *,
    name: str,
    rect: List[float],
    flags: int,
    options: List[str],
    value: Any = None,
):
    opt_array = ArrayObject([TextStringObject(opt) for opt in options])
    field = DictionaryObject(
        {
            NameObject("/FT"): NameObject("/Ch"),
            NameObject("/T"): TextStringObject(name),
            NameObject("/Rect"): ArrayObject([NumberObject(v) for v in rect]),
            NameObject("/Subtype"): NameObject("/Widget"),
            NameObject("/Ff"): NumberObject(flags | FLAG_COMBO),
            NameObject("/Opt"): opt_array,
        }
    )
    if value is not None:
        field[NameObject("/V")] = TextStringObject(str(value))
        field[NameObject("/DV")] = TextStringObject(str(value))
    field_ref = writer._add_object(field)  # pylint: disable=protected-access
    _add_annotation(page, field_ref)
    _register_field(acroform, field_ref)


def _add_radio_field(
    writer: PdfWriter,
    page,
    acroform: DictionaryObject,
    *,
    group_name: str,
    rect: List[float],
    flags: int,
    export_value: str,
    value: Any = None,
    group_state: Dict[str, Any],
):
    group = group_state.get(group_name)
    if group is None:
        group_dict = DictionaryObject(
            {
                NameObject("/FT"): NameObject("/Btn"),
                NameObject("/T"): TextStringObject(group_name),
                NameObject("/Ff"): NumberObject(flags | FLAG_RADIO | FLAG_NO_TOGGLE_TO_OFF),
                NameObject("/Kids"): ArrayObject(),
            }
        )
        group_ref = writer._add_object(group_dict)  # pylint: disable=protected-access
        _register_field(acroform, group_ref)
        group = {"ref": group_ref, "dict": group_dict, "kids": group_dict["/Kids"]}
        group_state[group_name] = group

    checked = _checkbox_checked(value, export_value)
    widget = DictionaryObject(
        {
            NameObject("/Subtype"): NameObject("/Widget"),
            NameObject("/Rect"): ArrayObject([NumberObject(v) for v in rect]),
            NameObject("/Parent"): group["ref"],
            NameObject("/AS"): NameObject(f"/{export_value}" if checked else "/Off"),
        }
    )
    widget_ref = writer._add_object(widget)  # pylint: disable=protected-access
    group["kids"].append(widget_ref)
    _add_annotation(page, widget_ref)
    if checked:
        group["dict"][NameObject("/V")] = NameObject(f"/{export_value}")


def inject_fields(input_pdf: Path, json_path: Path, output_pdf: Path) -> None:
    template = json.loads(json_path.read_text(encoding="utf-8"))
    fields = _build_field_list(template)
    if not fields:
        raise SystemExit("No fields to inject (fields and candidates were empty).")

    origin = _resolve_origin(template)
    reader = PdfReader(str(input_pdf))
    writer = PdfWriter()
    writer.append_pages_from_reader(reader)

    acroform = _ensure_acroform(writer)
    if STRIP_EXISTING_FIELDS:
        removed = _strip_existing_widget_annots(writer)
        _reset_acroform_fields(acroform)
        logger.info("Stripped %s existing widget annotations before injection.", removed)
    elif DEDUP_EXISTING_WIDGETS:
        removed = _dedupe_existing_widget_annots(writer, WIDGET_DEDUPE_TOL)
        if removed:
            logger.info("Removed %s duplicate widget annotations before injection.", removed)
    radio_groups: Dict[str, Any] = {}
    existing_widgets = _collect_existing_widgets(writer)

    for field in fields:
        name = str(field.get("name") or "").strip()
        if not name:
            logger.warning("Skipping field without name: %s", field)
            continue
        page_idx = int(field.get("page") or 1)
        if page_idx < 1 or page_idx > len(writer.pages):
            logger.warning("Skipping field %s with invalid page index %s", name, page_idx)
            continue

        raw_rect = _normalize_rect(field)
        if raw_rect is None:
            logger.warning("Skipping field %s without rect/size", name)
            continue

        page = writer.pages[page_idx - 1]
        page_box = page.cropbox if page.cropbox else page.mediabox
        page_height = float(page_box.height)
        pdf_rect = _to_pdf_rect(raw_rect, page_height=page_height, origin=origin)

        flags = _field_flags(field)
        field_type = str(field.get("type") or "text").lower().strip()
        if field_type == "date":
            field_type = "text"
        field_kind = _normalize_field_kind(field_type)
        if _has_duplicate_widget(existing_widgets, page_idx, field_kind, pdf_rect):
            logger.debug(
                "Skipping duplicate %s field %s on page %s (rect=%s)",
                field_kind,
                name,
                page_idx,
                pdf_rect,
            )
            continue

        if field_type == "text":
            _add_text_field(
                writer,
                page,
                acroform,
                name=name,
                rect=pdf_rect,
                flags=flags,
                value=field.get("value"),
            )
        elif field_type == "checkbox":
            export_value = str(field.get("exportValue") or "Yes")
            _add_checkbox_field(
                writer,
                page,
                acroform,
                name=name,
                rect=pdf_rect,
                flags=flags,
                export_value=export_value,
                value=field.get("value"),
            )
        elif field_type == "radio":
            group_name = str(field.get("group") or name)
            export_value = str(field.get("exportValue") or name)
            _add_radio_field(
                writer,
                page,
                acroform,
                group_name=group_name,
                rect=pdf_rect,
                flags=flags,
                export_value=export_value,
                value=field.get("value"),
                group_state=radio_groups,
            )
        elif field_type == "signature":
            _add_signature_field(
                writer,
                page,
                acroform,
                name=name,
                rect=pdf_rect,
                flags=flags,
            )
        elif field_type in {"combo", "combobox"}:
            options = [str(opt) for opt in (field.get("options") or [])]
            _add_combo_field(
                writer,
                page,
                acroform,
                name=name,
                rect=pdf_rect,
                flags=flags,
                options=options,
                value=field.get("value"),
            )
        else:
            logger.warning("Unknown field type %s for %s; skipping.", field_type, name)
            continue
        existing_widgets.setdefault(page_idx, []).append({"rect": pdf_rect, "kind": field_kind})

    output_pdf.parent.mkdir(parents=True, exist_ok=True)
    with output_pdf.open("wb") as f:
        writer.write(f)
    logger.info("Wrote fillable PDF to %s", output_pdf)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Inject form fields into a PDF using a sandbox JSON template."
    )
    parser.add_argument("pdf", type=Path, help="Input PDF path")
    parser.add_argument("fields", type=Path, help="JSON template with field definitions")
    parser.add_argument(
        "--output",
        type=Path,
        help="Output PDF path (defaults to backend/forms/native/temp<first5><last5>.pdf)",
    )
    args = parser.parse_args()

    input_pdf = args.pdf
    if not input_pdf.exists():
        raise SystemExit(f"PDF not found: {input_pdf}")
    if not args.fields.exists():
        raise SystemExit(f"JSON template not found: {args.fields}")

    output = args.output
    if output is None:
        prefix = temp_prefix_from_pdf(input_pdf)
        output = Path("backend/forms/native") / f"{prefix}.pdf"

    inject_fields(input_pdf, args.fields, output)


if __name__ == "__main__":
    main()
