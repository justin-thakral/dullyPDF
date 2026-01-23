"""Form-field injector for building fillable PDFs."""

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

from .config import get_logger
from .output_layout import temp_prefix_from_pdf

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
CONFIDENCE_TAG_PREFIX = "dullypdf:confidence="
ROOT_KEYS_TO_PRESERVE = (
    "/OCProperties",
    "/Metadata",
    "/ViewerPreferences",
    "/Names",
    "/PageLayout",
    "/PageMode",
    "/Outlines",
)


def _resolve_origin(template: Dict[str, Any]) -> str:
    """
    Determine the coordinate origin for template rects.
    """
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
    """
    Convert field metadata into PDF annotation flags.
    """
    flags = 0
    read_only = field.get("readonly") if "readonly" in field else field.get("readOnly")
    if read_only:
        flags |= FLAG_READ_ONLY
    if field.get("required"):
        flags |= FLAG_REQUIRED
    return flags


def _normalize_rect(field: Dict[str, Any]) -> Optional[List[float]]:
    """
    Normalize field rects into [x1, y1, x2, y2].
    """
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
    """
    Compare rectangles with a tolerance.
    """
    if len(a) != 4 or len(b) != 4:
        return False
    return all(abs(float(a[i]) - float(b[i])) <= tol for i in range(4))


def _normalize_field_kind(field_type: str) -> str:
    """
    Normalize field types into PDF widget kinds.
    """
    ft = (field_type or "").strip().lower()
    if ft in {"checkbox", "radio"}:
        return "button"
    if ft in {"combo", "combobox"}:
        return "choice"
    if ft == "signature":
        return "signature"
    return "text"


def _pdf_field_kind(field_type: Any) -> str:
    """
    Map PDF field type tokens to human-readable kinds.
    """
    ft = str(field_type or "")
    mapping = {
        "/Tx": "text",
        "/Btn": "button",
        "/Ch": "choice",
        "/Sig": "signature",
    }
    return mapping.get(ft, "unknown")


def _parse_confidence_value(value: Any) -> Optional[float]:
    """
    Parse and bound confidence values into [0, 1].
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        try:
            confidence = float(str(value).strip())
        except (TypeError, ValueError):
            return None
    if confidence != confidence:
        return None
    return max(0.0, min(1.0, confidence))


def _confidence_tag(field: Dict[str, Any]) -> Optional[str]:
    """
    Build a metadata tag encoding confidence for a widget.
    """
    confidence = _parse_confidence_value(field.get("confidence"))
    if confidence is None:
        return None
    return f"{CONFIDENCE_TAG_PREFIX}{confidence:.4f}"


def _apply_confidence_tag(field: DictionaryObject, confidence_tag: Optional[str]) -> None:
    """
    Attach the confidence tag to the field tooltip.
    """
    if confidence_tag:
        field[NameObject("/TU")] = TextStringObject(confidence_tag)


def _collect_existing_widgets(writer: PdfWriter) -> Dict[int, List[Dict[str, Any]]]:
    """
    Gather existing widget rectangles so we can de-duplicate injections.
    """
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
    """
    Remove widget annotations from pages while leaving other annotations.
    """
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
    """
    Reset the AcroForm field list.
    """
    acroform[NameObject("/Fields")] = ArrayObject()


def _dedupe_existing_widget_annots(writer: PdfWriter, tol: float) -> int:
    """
    Drop duplicate widgets by comparing rects within a tolerance.

    We keep the first widget per rect/kind and discard later overlaps.
    Time complexity: O(W^2) per page for W widget annotations.
    """
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
    """
    Check if a widget overlaps an existing one on the same page.
    """
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
    """
    Convert template rects to PDF coordinate space.
    """
    x1, y1, x2, y2 = rect
    if origin.startswith("top"):
        return [x1, page_height - y2, x2, page_height - y1]
    return [x1, y1, x2, y2]


def _ensure_acroform(writer: PdfWriter) -> DictionaryObject:
    """
    Ensure an AcroForm dictionary exists with default fonts and appearance.
    """
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
    """
    Append an annotation reference to the page annotations list.
    """
    annots = page.get("/Annots")
    if annots is None:
        annots = ArrayObject()
        page[NameObject("/Annots")] = annots
    else:
        annots = annots.get_object()
    annots.append(annot_ref)


def _register_field(acroform: DictionaryObject, field_ref):
    """
    Append a field reference to the AcroForm field list.
    """
    fields = acroform.get("/Fields")
    if fields is None:
        fields = ArrayObject()
        acroform[NameObject("/Fields")] = fields
    else:
        fields = fields.get_object()
    fields.append(field_ref)


def _pdf_escape_text(value: str) -> str:
    """
    Escape PDF string literals for content streams.
    """
    return str(value).replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)").replace("\r", " ").replace("\n", " ")


def _helv_font_ref(acroform: DictionaryObject):
    """
    Retrieve the Helvetica font reference from the AcroForm resource dict.
    """
    dr = acroform.get("/DR")
    if dr is None:
        return None
    try:
        dr = dr.get_object()
    except AttributeError:
        pass
    font_dict = dr.get("/Font")
    if font_dict is None:
        return None
    try:
        font_dict = font_dict.get_object()
    except AttributeError:
        pass
    return font_dict.get("/Helv")


def _build_text_appearance(
    writer: PdfWriter,
    *,
    width: float,
    height: float,
    value: str,
    font_ref,
):
    """
    Build a simple appearance stream for text widgets.
    """
    if width <= 0.0 or height <= 0.0:
        return None
    if not font_ref:
        return None

    safe_text = _pdf_escape_text(value)
    # Aim for a readable size while staying within the widget height.
    font_size = max(6.0, min(12.0, height * 0.65))
    x = max(1.0, min(4.0, width * 0.05))
    y = max(1.0, (height - font_size) * 0.45)

    commands = [
        "q",
        f"0 0 {width:.2f} {height:.2f} re W n",
        "BT",
        f"/Helv {font_size:.2f} Tf",
        "0 g",
        f"1 0 0 1 {x:.2f} {y:.2f} Tm",
        f"({safe_text}) Tj",
        "ET",
        "Q",
    ]

    resources = DictionaryObject(
        {
            NameObject("/Font"): DictionaryObject({NameObject("/Helv"): font_ref}),
        }
    )

    stream = DecodedStreamObject()
    stream.set_data("\n".join(commands).encode("utf-8"))
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
            NameObject("/Resources"): resources,
        }
    )
    return writer._add_object(stream)  # pylint: disable=protected-access


def _apply_checkbox_value(widget: DictionaryObject, *, export_value: str, value: Any) -> None:
    """
    Set checkbox widget state based on a value.
    """
    checked = _checkbox_checked(value, export_value)
    widget[NameObject("/AS")] = NameObject(f"/{export_value}" if checked else "/Off")
    widget[NameObject("/V")] = NameObject(f"/{export_value}" if checked else "/Off")


def _apply_text_value(field: DictionaryObject, *, value: Any) -> None:
    """
    Assign text values to a field dictionary.
    """
    field[NameObject("/V")] = TextStringObject(str(value))
    field[NameObject("/DV")] = TextStringObject(str(value))


def _apply_text_appearance(
    writer: PdfWriter,
    widget: DictionaryObject,
    acroform: DictionaryObject,
    *,
    rect: List[float],
    value: Any,
) -> None:
    """
    Attach an appearance stream for text fields.
    """
    width = float(rect[2]) - float(rect[0])
    height = float(rect[3]) - float(rect[1])
    ap = _build_text_appearance(
        writer,
        width=width,
        height=height,
        value=str(value),
        font_ref=_helv_font_ref(acroform),
    )
    if ap is not None:
        widget[NameObject("/AP")] = DictionaryObject({NameObject("/N"): ap})


def _update_existing_widget(
    writer: PdfWriter,
    page,
    acroform: DictionaryObject,
    *,
    rect: List[float],
    field_type: str,
    value: Any,
    export_value: str,
    new_name: Optional[str] = None,
    confidence_tag: Optional[str] = None,
) -> bool:
    """
    Update matching existing widgets instead of inserting duplicates.
    """
    field_type_norm = str(field_type or "").strip().lower()
    if field_type_norm == "date":
        field_type_norm = "text"
    if field_type_norm in {"combo", "combobox"}:
        field_type_norm = "text"

    annots = page.get("/Annots")
    if annots is None:
        return False
    try:
        annots = annots.get_object()
    except AttributeError:
        pass
    if not annots:
        return False

    updated_any = False
    for annot_ref in list(annots):
        annot = annot_ref.get_object() if hasattr(annot_ref, "get_object") else annot_ref
        if annot.get("/Subtype") != "/Widget":
            continue
        annot_rect = annot.get("/Rect")
        if not annot_rect or len(annot_rect) != 4:
            continue
        rect_vals = [float(v) for v in annot_rect]
        if not _rects_nearly_equal(rect_vals, rect, WIDGET_DEDUPE_TOL):
            continue

        field = annot
        parent = annot.get("/Parent")
        if parent is not None:
            try:
                parent = parent.get_object()
            except AttributeError:
                pass
            if isinstance(parent, DictionaryObject):
                field = parent

        if new_name:
            current_name = field.get("/T")
            if not current_name or str(current_name) != new_name:
                field[NameObject("/T")] = TextStringObject(new_name)
                updated_any = True

        if value is not None:
            if field_type_norm == "checkbox":
                _apply_checkbox_value(annot, export_value=export_value, value=value)
                if field is not annot:
                    # Keep parent and widget state aligned so viewers read consistent values.
                    field[NameObject("/V")] = annot.get("/V")
                updated_any = True
            elif field_type_norm == "text":
                _apply_text_value(field, value=value)
                _apply_text_appearance(writer, annot, acroform, rect=rect, value=value)
                if field is not annot:
                    # Copy down the value when the widget has a separate parent field.
                    annot[NameObject("/V")] = field.get("/V")
                updated_any = True
        if confidence_tag:
            _apply_confidence_tag(annot, confidence_tag)
            if field is not annot:
                _apply_confidence_tag(field, confidence_tag)
            updated_any = True

    return updated_any


def _checkbox_checked(value: Any, export_value: str) -> bool:
    """
    Interpret checkbox values across common bool/string formats.
    """
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


def _build_field_list(template: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Return the list of field definitions from the template.
    """
    return list(template.get("fields") or [])


def _add_text_field(
    writer: PdfWriter,
    page,
    acroform: DictionaryObject,
    *,
    name: str,
    rect: List[float],
    flags: int,
    value: Any = None,
    confidence_tag: Optional[str] = None,
):
    """
    Add a text field widget to the PDF.
    """
    field = DictionaryObject(
        {
            NameObject("/FT"): NameObject("/Tx"),
            NameObject("/T"): TextStringObject(name),
            NameObject("/Rect"): ArrayObject([NumberObject(v) for v in rect]),
            NameObject("/Subtype"): NameObject("/Widget"),
            NameObject("/Ff"): NumberObject(flags),
        }
    )
    _apply_confidence_tag(field, confidence_tag)
    if value is not None:
        field[NameObject("/V")] = TextStringObject(str(value))
        field[NameObject("/DV")] = TextStringObject(str(value))

        width = float(rect[2]) - float(rect[0])
        height = float(rect[3]) - float(rect[1])
        ap = _build_text_appearance(
            writer,
            width=width,
            height=height,
            value=str(value),
            font_ref=_helv_font_ref(acroform),
        )
        if ap is not None:
            field[NameObject("/AP")] = DictionaryObject({NameObject("/N"): ap})
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
    confidence_tag: Optional[str] = None,
):
    """
    Add a checkbox field widget to the PDF.
    """
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
    _apply_confidence_tag(field, confidence_tag)
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
    """
    Build an appearance stream for checkbox widgets.
    """
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
    confidence_tag: Optional[str] = None,
):
    """
    Add a signature widget placeholder.
    """
    field = DictionaryObject(
        {
            NameObject("/FT"): NameObject("/Sig"),
            NameObject("/T"): TextStringObject(name),
            NameObject("/Rect"): ArrayObject([NumberObject(v) for v in rect]),
            NameObject("/Subtype"): NameObject("/Widget"),
            NameObject("/Ff"): NumberObject(flags),
        }
    )
    _apply_confidence_tag(field, confidence_tag)
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
    confidence_tag: Optional[str] = None,
):
    """
    Add a combo box widget with option list.
    """
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
    _apply_confidence_tag(field, confidence_tag)
    if value is not None:
        field[NameObject("/V")] = TextStringObject(str(value))
        field[NameObject("/DV")] = TextStringObject(str(value))

        width = float(rect[2]) - float(rect[0])
        height = float(rect[3]) - float(rect[1])
        ap = _build_text_appearance(
            writer,
            width=width,
            height=height,
            value=str(value),
            font_ref=_helv_font_ref(acroform),
        )
        if ap is not None:
            field[NameObject("/AP")] = DictionaryObject({NameObject("/N"): ap})
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
    confidence_tag: Optional[str] = None,
):
    """
    Add a radio widget to a group, creating the group if needed.
    """
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
    _apply_confidence_tag(widget, confidence_tag)
    widget_ref = writer._add_object(widget)  # pylint: disable=protected-access
    group["kids"].append(widget_ref)
    _add_annotation(page, widget_ref)
    if checked:
        group["dict"][NameObject("/V")] = NameObject(f"/{export_value}")


def inject_fields_from_template(
    input_pdf: Path, template: Dict[str, Any], output_pdf: Path
) -> None:
    """
    Inject template fields into a PDF and write the result.

    This builds an index of existing widgets, then adds or updates fields per page.
    """
    fields = _build_field_list(template)
    if not fields:
        raise SystemExit("No fields to inject.")

    origin = _resolve_origin(template)
    reader = PdfReader(str(input_pdf))
    writer = PdfWriter()
    writer.append_pages_from_reader(reader)
    root_src = reader.trailer.get("/Root")
    if root_src is not None:
        try:
            root_src = root_src.get_object()
        except AttributeError:
            pass
        root_dst = writer._root_object  # pylint: disable=protected-access
        for key in ROOT_KEYS_TO_PRESERVE:
            if key in root_src:
                # Preserve root entries like optional content groups (layers).
                entry = root_src.raw_get(key) if hasattr(root_src, "raw_get") else None
                if entry is None:
                    entry = root_src.get(key)
                root_dst[NameObject(key)] = entry.clone(writer)

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
        confidence_tag = _confidence_tag(field)

        flags = _field_flags(field)
        field_type = str(field.get("type") or "text").lower().strip()
        if field_type == "date":
            field_type = "text"
        field_kind = _normalize_field_kind(field_type)
        if _has_duplicate_widget(existing_widgets, page_idx, field_kind, pdf_rect):
            value = field.get("value")
            export_value = str(field.get("exportValue") or "Yes")
            updated = _update_existing_widget(
                writer,
                page,
                acroform,
                rect=pdf_rect,
                field_type=field_type,
                value=value,
                export_value=export_value,
                new_name=name,
                confidence_tag=confidence_tag,
            )
            if updated:
                logger.debug("Updated existing %s field %s on page %s", field_kind, name, page_idx)
                continue
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
                confidence_tag=confidence_tag,
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
                confidence_tag=confidence_tag,
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
                confidence_tag=confidence_tag,
            )
        elif field_type == "signature":
            _add_signature_field(
                writer,
                page,
                acroform,
                name=name,
                rect=pdf_rect,
                flags=flags,
                confidence_tag=confidence_tag,
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
                confidence_tag=confidence_tag,
            )
        else:
            logger.warning("Unknown field type %s for %s; skipping.", field_type, name)
            continue
        existing_widgets.setdefault(page_idx, []).append({"rect": pdf_rect, "kind": field_kind})

    output_pdf.parent.mkdir(parents=True, exist_ok=True)
    with output_pdf.open("wb") as f:
        writer.write(f)
    logger.info("Wrote fillable PDF to %s", output_pdf)


def inject_fields(input_pdf: Path, json_path: Path, output_pdf: Path) -> None:
    """
    Load a JSON template file and inject fields into the PDF.
    """
    template = json.loads(json_path.read_text(encoding="utf-8"))
    inject_fields_from_template(input_pdf, template, output_pdf)


def main() -> None:
    """
    CLI entrypoint for field injection.
    """
    parser = argparse.ArgumentParser(
        description="Inject form fields into a PDF using a rename pipeline JSON template."
    )
    parser.add_argument("pdf", type=Path, help="Input PDF path")
    parser.add_argument("fields", type=Path, help="JSON template with field definitions")
    parser.add_argument(
        "--output",
        type=Path,
        help="Output PDF path (defaults to samples/fieldDetecting/forms/native/temp<first5><last5>.pdf)",
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
        output = Path("samples/fieldDetecting/forms/native") / f"{prefix}.pdf"

    inject_fields(input_pdf, args.fields, output)


if __name__ == "__main__":
    main()
