"""Signed PDF materialization helpers for signing requests.

The artifact renderer walks the immutable source PDF once and applies overlay
content only to pages that contain signing anchors, so the overall work is
O(page_count + anchor_count). Anchors are authored in DullyPDF's top-left PDF
point coordinates, while PDF drawing libraries use bottom-left coordinates, so
the overlay builder normalizes that translation in one place.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
from typing import Any, Dict, Iterable, List

from pypdf import PdfReader, PdfWriter
from reportlab.lib.colors import Color
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfgen import canvas

from backend.services.pdf_export_service import flatten_pdf_form_widgets


SIGNATURE_FONT = "Helvetica-Oblique"
BODY_FONT = "Helvetica"
SIGNATURE_COLOR = Color(0.07, 0.16, 0.32)
BODY_COLOR = Color(0.12, 0.12, 0.12)


@dataclass(frozen=True)
class SigningPdfRenderResult:
    pdf_bytes: bytes
    page_count: int
    applied_anchor_count: int


def _normalize_anchor_rect(anchor: Dict[str, Any]) -> Dict[str, float] | None:
    rect = anchor.get("rect")
    if not isinstance(rect, dict):
        return None
    try:
        x = float(rect.get("x"))
        y = float(rect.get("y"))
        width = float(rect.get("width"))
        height = float(rect.get("height"))
    except (TypeError, ValueError):
        return None
    if width <= 0 or height <= 0:
        return None
    return {"x": x, "y": y, "width": width, "height": height}


def _coerce_anchor_page(anchor: Dict[str, Any], page_count: int) -> int | None:
    try:
        page = int(anchor.get("page"))
    except (TypeError, ValueError):
        return None
    if page < 1 or page > page_count:
        return None
    return page


def _fit_font_size(text: str, *, font_name: str, max_width: float, max_height: float, preferred: float) -> float:
    safe_text = str(text or "").strip() or "Signed"
    size = min(preferred, max(max_height * 0.7, 6.0))
    while size > 6.0 and pdfmetrics.stringWidth(safe_text, font_name, size) > max_width:
        size -= 0.5
    return max(size, 6.0)


def _draw_text_within_rect(pdf_canvas: canvas.Canvas, *, text: str, rect: Dict[str, float], page_height: float, font_name: str) -> None:
    safe_text = str(text or "").strip()
    if not safe_text:
        return
    padding = max(min(rect["height"] * 0.18, 8.0), 2.0)
    font_size = _fit_font_size(
        safe_text,
        font_name=font_name,
        max_width=max(rect["width"] - padding * 2.0, 6.0),
        max_height=rect["height"] - padding * 2.0,
        preferred=rect["height"] * 0.52,
    )
    baseline_y = page_height - rect["y"] - rect["height"] + padding + max(font_size * 0.12, 0.0)
    pdf_canvas.setFont(font_name, font_size)
    pdf_canvas.setFillColor(SIGNATURE_COLOR if font_name == SIGNATURE_FONT else BODY_COLOR)
    pdf_canvas.drawString(rect["x"] + padding, baseline_y, safe_text)


def _normalize_signed_date(value: str | None) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return raw
    return dt.strftime("%b %-d, %Y")


def _resolve_initials(adopted_name: str | None) -> str:
    tokens = [token for token in str(adopted_name or "").strip().split() if token]
    if not tokens:
        return ""
    return "".join(token[0].upper() for token in tokens[:3])


def _group_anchors_by_page(anchors: Iterable[Dict[str, Any]], *, page_count: int) -> Dict[int, List[Dict[str, Any]]]:
    grouped: Dict[int, List[Dict[str, Any]]] = {}
    for anchor in anchors:
        if not isinstance(anchor, dict):
            continue
        page = _coerce_anchor_page(anchor, page_count)
        rect = _normalize_anchor_rect(anchor)
        if page is None or rect is None:
            continue
        grouped.setdefault(page, []).append({"kind": str(anchor.get("kind") or "").strip(), "rect": rect})
    return grouped


def build_signed_pdf(
    *,
    source_pdf_bytes: bytes,
    anchors: Iterable[Dict[str, Any]],
    adopted_name: str,
    completed_at: str | None,
) -> SigningPdfRenderResult:
    """Stamp the signer-adopted values into the immutable source PDF."""

    reader = PdfReader(BytesIO(source_pdf_bytes))
    writer = PdfWriter()
    grouped_anchors = _group_anchors_by_page(anchors, page_count=len(reader.pages))
    signed_date = _normalize_signed_date(completed_at)
    initials = _resolve_initials(adopted_name)
    applied_anchor_count = 0

    for page_index, page in enumerate(reader.pages, start=1):
        page_width = float(page.mediabox.width)
        page_height = float(page.mediabox.height)
        page_anchors = grouped_anchors.get(page_index, [])
        writer.add_page(page)
        writer_page = writer.pages[-1]
        if page_anchors:
            overlay_buffer = BytesIO()
            overlay_canvas = canvas.Canvas(overlay_buffer, pagesize=(page_width, page_height))
            for anchor in page_anchors:
                kind = str(anchor.get("kind") or "").strip().lower()
                rect = anchor["rect"]
                text = ""
                font_name = BODY_FONT
                if kind == "signature":
                    text = adopted_name
                    font_name = SIGNATURE_FONT
                elif kind == "signed_date":
                    text = signed_date
                elif kind == "initials":
                    text = initials
                    font_name = SIGNATURE_FONT
                if text:
                    _draw_text_within_rect(
                        overlay_canvas,
                        text=text,
                        rect=rect,
                        page_height=page_height,
                        font_name=font_name,
                    )
                    applied_anchor_count += 1
            overlay_canvas.save()
            overlay_reader = PdfReader(BytesIO(overlay_buffer.getvalue()))
            writer_page.merge_page(overlay_reader.pages[0])

    output = BytesIO()
    writer.write(output)
    return SigningPdfRenderResult(
        pdf_bytes=flatten_pdf_form_widgets(output.getvalue()),
        page_count=len(reader.pages),
        applied_anchor_count=applied_anchor_count,
    )
