"""Signed PDF materialization helpers for signing requests.

The artifact renderer walks the immutable source PDF once and applies overlay
content only to pages that contain signing anchors, so the overall work is
O(page_count + anchor_count). Anchors are authored in DullyPDF's top-left PDF
point coordinates, while PDF drawing libraries use bottom-left coordinates, so
the overlay builder normalizes that translation in one place.
"""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
from datetime import datetime
import hashlib
from io import BytesIO
from typing import Any, Dict, Iterable, List, Optional

from pypdf import PdfReader, PdfWriter
from reportlab.lib.colors import Color
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfgen import canvas
from PIL import Image, ImageChops, ImageOps, UnidentifiedImageError

from backend.services.pdf_export_service import flatten_pdf_form_widgets
from backend.services.signing_service import (
    SIGNATURE_ADOPTED_MODE_DRAWN,
    SIGNATURE_ADOPTED_MODE_UPLOADED,
    normalize_signature_adopted_mode,
)


SIGNATURE_FONT = "Helvetica-Oblique"
BODY_FONT = "Helvetica"
SIGNATURE_COLOR = Color(0.07, 0.16, 0.32)
BODY_COLOR = Color(0.12, 0.12, 0.12)
SIGNATURE_IMAGE_MAX_INPUT_BYTES = 512_000
SIGNATURE_IMAGE_MAX_OUTPUT_BYTES = 256_000
SIGNATURE_IMAGE_MAX_DIMENSIONS = (1200, 400)


@dataclass(frozen=True)
class NormalizedSignatureImage:
    data_url: str
    sha256: str
    width: int
    height: int


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


def _decode_signature_image_payload(value: str) -> bytes:
    normalized = str(value or "").strip()
    if not normalized.startswith("data:image/") or ";base64," not in normalized:
        raise ValueError("Signature image must be a PNG or JPEG data URL.")
    header, encoded = normalized.split(",", 1)
    media_type = header[5:].split(";", 1)[0].strip().lower()
    if media_type not in {"image/png", "image/jpeg"}:
        raise ValueError("Signature image must be a PNG or JPEG data URL.")
    try:
        raw_bytes = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("Signature image data URL contains invalid base64 content.") from exc
    if not raw_bytes:
        raise ValueError("Signature image data URL is empty.")
    if len(raw_bytes) > SIGNATURE_IMAGE_MAX_INPUT_BYTES:
        raise ValueError("Signature image is too large. Keep uploaded or drawn signatures under 512 KB.")
    return raw_bytes


def _crop_signature_image(image: Image.Image) -> Image.Image:
    alpha_bbox = image.getchannel("A").getbbox() if "A" in image.getbands() else None
    if alpha_bbox:
        return image.crop(alpha_bbox)
    white_background = Image.new("RGB", image.size, "white")
    difference_bbox = ImageChops.difference(image.convert("RGB"), white_background).getbbox()
    if difference_bbox:
        return image.crop(difference_bbox)
    raise ValueError("Draw or upload a visible signature mark before continuing.")


def normalize_signature_image_data_url(value: Optional[str]) -> NormalizedSignatureImage:
    raw_bytes = _decode_signature_image_payload(str(value or ""))
    try:
        with Image.open(BytesIO(raw_bytes)) as opened_image:
            normalized_image = ImageOps.exif_transpose(opened_image).convert("RGBA")
            cropped_image = _crop_signature_image(normalized_image)
            cropped_image.thumbnail(SIGNATURE_IMAGE_MAX_DIMENSIONS, Image.Resampling.LANCZOS)
            output = BytesIO()
            cropped_image.save(output, format="PNG", optimize=True)
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        if isinstance(exc, ValueError):
            raise
        raise ValueError("Signature image could not be decoded as a supported PNG or JPEG file.") from exc
    png_bytes = output.getvalue()
    if not png_bytes:
        raise ValueError("Signature image normalization produced an empty PNG.")
    if len(png_bytes) > SIGNATURE_IMAGE_MAX_OUTPUT_BYTES:
        raise ValueError("Signature image is too large after normalization. Use a tighter crop or smaller upload.")
    return NormalizedSignatureImage(
        data_url="data:image/png;base64," + base64.b64encode(png_bytes).decode("ascii"),
        sha256=hashlib.sha256(png_bytes).hexdigest(),
        width=cropped_image.width,
        height=cropped_image.height,
    )


def _draw_image_within_rect(
    pdf_canvas: canvas.Canvas,
    *,
    image: NormalizedSignatureImage,
    rect: Dict[str, float],
    page_height: float,
) -> None:
    png_bytes = _decode_signature_image_payload(image.data_url)
    image_reader = ImageReader(BytesIO(png_bytes))
    padding = max(min(rect["height"] * 0.14, 6.0), 2.0)
    available_width = max(rect["width"] - padding * 2.0, 6.0)
    available_height = max(rect["height"] - padding * 2.0, 6.0)
    width_scale = available_width / max(float(image.width), 1.0)
    height_scale = available_height / max(float(image.height), 1.0)
    scale = min(width_scale, height_scale)
    draw_width = max(image.width * scale, 1.0)
    draw_height = max(image.height * scale, 1.0)
    left = rect["x"] + padding + max((available_width - draw_width) / 2.0, 0.0)
    bottom = (
        page_height
        - rect["y"]
        - rect["height"]
        + padding
        + max((available_height - draw_height) / 2.0, 0.0)
    )
    pdf_canvas.drawImage(
        image_reader,
        left,
        bottom,
        width=draw_width,
        height=draw_height,
        preserveAspectRatio=True,
        mask="auto",
    )


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
    signature_adopted_mode: str | None = None,
    signature_image_data_url: str | None = None,
) -> SigningPdfRenderResult:
    """Stamp the signer-adopted values into the immutable source PDF."""

    reader = PdfReader(BytesIO(source_pdf_bytes))
    writer = PdfWriter()
    grouped_anchors = _group_anchors_by_page(anchors, page_count=len(reader.pages))
    signed_date = _normalize_signed_date(completed_at)
    initials = _resolve_initials(adopted_name)
    normalized_adopted_mode = normalize_signature_adopted_mode(signature_adopted_mode)
    normalized_signature_image = normalize_signature_image_data_url(signature_image_data_url) if signature_image_data_url else None
    signature_uses_image = normalized_adopted_mode in {
        SIGNATURE_ADOPTED_MODE_DRAWN,
        SIGNATURE_ADOPTED_MODE_UPLOADED,
    } and normalized_signature_image is not None
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
                    if signature_uses_image:
                        _draw_image_within_rect(
                            overlay_canvas,
                            image=normalized_signature_image,
                            rect=rect,
                            page_height=page_height,
                        )
                        applied_anchor_count += 1
                        continue
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
