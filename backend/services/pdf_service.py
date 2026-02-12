"""PDF upload, validation, and payload-shape helpers."""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, UploadFile
import fitz

from backend.detection.pdf_validation import PdfValidationError, PdfValidationResult, preflight_pdf_bytes


def sanitize_basename_segment(value: str, fallback: str) -> str:
    """Sanitize a filename segment to prevent header injection or path traversal."""
    raw = (value or fallback or "file").strip()
    base = os.path.basename(raw)
    cleaned = re.sub(r"[\r\n]", "", base)
    cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "_", cleaned)
    cleaned = re.sub(r"^\.+", "", cleaned)
    return cleaned or fallback


def safe_pdf_download_filename(name: str, fallback: str = "document") -> str:
    """Normalize filenames so browsers receive a safe, short, PDF-only value."""
    safe_base = sanitize_basename_segment(name, fallback)
    if not safe_base.lower().endswith(".pdf"):
        safe_base = f"{safe_base}.pdf"
    if len(safe_base) > 180:
        trimmed = safe_base[:180]
        if not trimmed.lower().endswith(".pdf"):
            trimmed = f"{trimmed[:176]}.pdf"
        return trimmed
    return safe_base


def log_pdf_label(name: str) -> str:
    """Return a stable, non-sensitive identifier for PDF logging."""
    safe = sanitize_basename_segment(name, "document")
    digest = hashlib.sha256(safe.encode("utf-8")).hexdigest()[:10]
    suffix = ".pdf" if safe.lower().endswith(".pdf") else ""
    return f"pdf{suffix}#{digest}"


def cleanup_paths(paths: List[Path]) -> None:
    """Best-effort cleanup for temp files."""
    for path in paths:
        try:
            path.unlink(missing_ok=True)
        except Exception:
            continue


def rect_list_from_xywh(x: Any, y: Any, width: Any, height: Any) -> Optional[List[float]]:
    """Convert x/y/width/height into [x1, y1, x2, y2] or return None on invalid inputs."""
    try:
        x1 = float(x)
        y1 = float(y)
        w = float(width)
        h = float(height)
    except (TypeError, ValueError):
        return None
    return [x1, y1, x1 + w, y1 + h]


def rect_list_from_corners(x1: Any, y1: Any, x2: Any, y2: Any) -> Optional[List[float]]:
    """Convert corner coordinates into [x1, y1, x2, y2] or return None on invalid inputs."""
    try:
        return [float(x1), float(y1), float(x2), float(y2)]
    except (TypeError, ValueError):
        return None


def coerce_field_payloads(raw_fields: List[Any]) -> List[Dict[str, Any]]:
    """Normalize incoming field payloads to the expected dict shape."""
    cleaned: List[Dict[str, Any]] = []
    for entry in raw_fields:
        if not isinstance(entry, dict):
            continue
        payload = dict(entry)
        rect_list: Optional[List[float]] = None
        rect = payload.get("rect")
        if isinstance(rect, dict):
            if {"x", "y", "width", "height"}.issubset(rect):
                rect_list = rect_list_from_xywh(rect.get("x"), rect.get("y"), rect.get("width"), rect.get("height"))
                for key in ("x", "y", "width", "height"):
                    if key not in payload and key in rect:
                        payload[key] = rect[key]
            elif {"x1", "y1", "x2", "y2"}.issubset(rect):
                rect_list = rect_list_from_corners(rect.get("x1"), rect.get("y1"), rect.get("x2"), rect.get("y2"))
        elif isinstance(rect, (list, tuple)) and len(rect) == 4:
            rect_list = rect_list_from_corners(rect[0], rect[1], rect[2], rect[3])

        if rect_list is None:
            rect_list = rect_list_from_xywh(
                payload.get("x"),
                payload.get("y"),
                payload.get("width"),
                payload.get("height"),
            )

        if rect_list is not None:
            payload["rect"] = rect_list
            x1, y1, x2, y2 = rect_list
            payload.setdefault("x", x1)
            payload.setdefault("y", y1)
            payload.setdefault("width", x2 - x1)
            payload.setdefault("height", y2 - y1)
        elif isinstance(rect, dict):
            payload["rect"] = None
        cleaned.append(payload)
    return cleaned


def get_pdf_page_count(pdf_bytes: bytes) -> int:
    """Return the number of pages in a PDF byte stream."""
    if not pdf_bytes:
        return 0
    with fitz.open(stream=io.BytesIO(pdf_bytes), filetype="pdf") as doc:
        return max(1, int(doc.page_count))


def validate_pdf_for_detection(pdf_bytes: bytes) -> PdfValidationResult:
    try:
        return preflight_pdf_bytes(pdf_bytes)
    except PdfValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def resolve_upload_limit() -> tuple[int, int]:
    """Resolve the max upload size for PDFs."""
    try:
        max_mb = int(os.getenv("SANDBOX_MAX_UPLOAD_MB", "50"))
    except ValueError:
        max_mb = 50
    if max_mb < 1:
        max_mb = 1
    return max_mb, max_mb * 1024 * 1024


def parse_json_list_form_field(raw: Optional[str], field_name: str) -> Optional[List[Dict[str, Any]]]:
    """Parse an optional JSON list payload from a multipart form field."""
    if raw is None:
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid {field_name} payload") from exc
    if not isinstance(parsed, list):
        raise HTTPException(status_code=400, detail=f"{field_name} must be a JSON array")
    return [entry for entry in parsed if isinstance(entry, dict)]


async def read_upload_bytes(upload: UploadFile, *, max_bytes: int, limit_message: str) -> bytes:
    """Read an UploadFile into memory with a hard size cap."""
    chunk_size = 1024 * 1024
    buffer = bytearray()
    total = 0
    while True:
        chunk = await upload.read(chunk_size)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(status_code=413, detail=limit_message)
        buffer.extend(chunk)
    return bytes(buffer)


def write_upload_to_temp(upload: UploadFile, *, max_bytes: int, limit_message: str) -> Path:
    """Write UploadFile to a temp PDF while enforcing a max byte limit."""
    suffix = ".pdf" if (upload.filename or "").lower().endswith(".pdf") else ""
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        total = 0
        while True:
            chunk = upload.file.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                tmp.flush()
                tmp.close()
                Path(tmp.name).unlink(missing_ok=True)
                raise HTTPException(status_code=413, detail=limit_message)
            tmp.write(chunk)
        return Path(tmp.name)
