from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from .config import DEFAULT_THRESHOLDS, get_logger

logger = get_logger(__name__)


def _try_import_fitz():
    try:
        import fitz  # type: ignore
    except Exception:  # pragma: no cover - optional dependency in some installs
        return None
    return fitz


def _field_type_from_widget(widget_type: int, *, fitz_mod: Any) -> Optional[str]:
    if widget_type == fitz_mod.PDF_WIDGET_TYPE_TEXT:
        return "text"
    if widget_type == fitz_mod.PDF_WIDGET_TYPE_CHECKBOX:
        return "checkbox"
    if widget_type == fitz_mod.PDF_WIDGET_TYPE_RADIOBUTTON:
        return "radio"
    if widget_type == fitz_mod.PDF_WIDGET_TYPE_SIGNATURE:
        return "signature"
    if widget_type in {fitz_mod.PDF_WIDGET_TYPE_COMBOBOX, fitz_mod.PDF_WIDGET_TYPE_LISTBOX}:
        return "combo"
    return None


def _next_name(counts: Dict[str, int], base: str) -> str:
    n = counts.get(base, 0) + 1
    counts[base] = n
    return base if n == 1 else f"{base}_{n}"


def _category_for_confidence(confidence: float, thresholds: Dict[str, float]) -> str:
    if confidence >= thresholds["high"]:
        return "green"
    if confidence >= thresholds["medium"]:
        return "yellow"
    return "red"


def _normalized_field_type(field_type: str) -> str:
    lowered = (field_type or "").strip().lower()
    if lowered == "date":
        return "text"
    return lowered


def _rect_iou(a: List[float], b: List[float]) -> float:
    ax1, ay1, ax2, ay2 = [float(v) for v in a]
    bx1, by1, bx2, by2 = [float(v) for v in b]
    ix1 = max(ax1, bx1)
    iy1 = max(ay1, by1)
    ix2 = min(ax2, bx2)
    iy2 = min(ay2, by2)
    if ix2 <= ix1 or iy2 <= iy1:
        return 0.0
    inter = float(ix2 - ix1) * float(iy2 - iy1)
    area_a = max(0.0, float(ax2 - ax1)) * max(0.0, float(ay2 - ay1))
    area_b = max(0.0, float(bx2 - bx1)) * max(0.0, float(by2 - by1))
    union = area_a + area_b - inter
    if union <= 0.0:
        return 0.0
    return inter / union


def extract_form_fields(pdf_bytes: bytes) -> List[Dict[str, Any]]:
    """
    Extract AcroForm widget rectangles via PyMuPDF (fitz).

    Returns a list of field dicts that match the resolver output schema.
    """
    fitz_mod = _try_import_fitz()
    if fitz_mod is None:
        logger.warning("PyMuPDF (fitz) unavailable; skipping AcroForm extraction.")
        return []

    try:
        doc = fitz_mod.open(stream=pdf_bytes, filetype="pdf")
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Failed to open PDF for AcroForm extraction: %s", exc)
        return []

    fields: List[Dict[str, Any]] = []
    name_counts: Dict[str, int] = {}
    for page_idx in range(doc.page_count):
        page = doc[page_idx]
        widgets = list(page.widgets())
        if not widgets:
            continue
        for widget_idx, widget in enumerate(widgets, start=1):
            rect = getattr(widget, "rect", None)
            if rect is None:
                continue
            x0, y0, x1, y1 = float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y1)
            if x1 <= x0 or y1 <= y0:
                continue
            field_type = _field_type_from_widget(int(widget.field_type or 0), fitz_mod=fitz_mod)
            if not field_type:
                continue
            base_name = (widget.field_name or "").strip()
            if not base_name:
                base_name = f"acro_{field_type}_p{page_idx + 1}"
            name = _next_name(name_counts, base_name)
            field: Dict[str, Any] = {
                "name": name,
                "type": field_type,
                "page": page_idx + 1,
                "rect": [x0, y0, x1, y1],
                "confidence": 0.96,
                "category": _category_for_confidence(0.96, DEFAULT_THRESHOLDS),
                "source": "acroform",
                "candidateId": f"acro_{page_idx + 1}_{widget_idx}",
            }
            if field_type == "radio":
                field["group"] = base_name
                field["exportValue"] = str(widget.field_value or name)
            elif field_type == "checkbox" and widget.field_value:
                field["exportValue"] = str(widget.field_value)
            fields.append(field)

    if fields:
        logger.info("Extracted %s AcroForm widgets", len(fields))
    return fields


def merge_form_fields(
    fields: List[Dict[str, Any]],
    form_fields: List[Dict[str, Any]],
    *,
    iou_threshold: float = 0.72,
) -> int:
    """
    Merge AcroForm fields into the resolved fields list, avoiding duplicates.
    """
    if not fields or not form_fields:
        if form_fields and not fields:
            fields.extend(form_fields)
            return len(form_fields)
        return 0

    existing: List[Tuple[List[float], str]] = []
    for field in fields:
        rect = field.get("rect")
        if isinstance(rect, list) and len(rect) == 4:
            existing.append((rect, _normalized_field_type(str(field.get("type") or ""))))

    added = 0
    for form_field in form_fields:
        rect = form_field.get("rect")
        if not isinstance(rect, list) or len(rect) != 4:
            continue
        ftype = _normalized_field_type(str(form_field.get("type") or ""))
        if any(_rect_iou(rect, existing_rect) >= iou_threshold and ftype == etype for existing_rect, etype in existing):
            continue
        fields.append(form_field)
        existing.append((rect, ftype))
        added += 1

    if added:
        logger.info("Merged %s AcroForm fields into resolver output", added)
    return added
