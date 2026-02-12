"""Fillable/template session endpoints."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, BackgroundTasks, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
import fitz
import uuid

from backend.detection.status import DETECTION_STATUS_COMPLETE
from backend.fieldDetecting.rename_pipeline.combinedSrc.form_filler import inject_fields
from backend.sessions.session_store import store_session_entry as _store_session_entry
from backend.time_utils import now_iso
from backend.services.app_config import resolve_stream_cors_headers
from backend.services.auth_service import require_user
from backend.services.limits_service import resolve_fillable_max_pages
from backend.services.pdf_service import (
    cleanup_paths,
    coerce_field_payloads,
    read_upload_bytes,
    resolve_upload_limit,
    safe_pdf_download_filename,
    validate_pdf_for_detection,
    write_upload_to_temp,
)

router = APIRouter()


@router.post("/api/forms/materialize")
async def materialize_form(
    background_tasks: BackgroundTasks,
    request: Request,
    pdf: UploadFile = File(...),
    fields: str = Form(...),
    authorization: Optional[str] = Header(default=None),
):
    """Inject fields into a PDF and return a fillable PDF download."""
    user = require_user(authorization)
    if not pdf:
        raise HTTPException(status_code=400, detail="No PDF file uploaded")

    filename = pdf.filename or "form.pdf"
    content_type = (pdf.content_type or "").lower()
    if not filename.lower().endswith(".pdf") and content_type not in {"application/pdf", "application/octet-stream"}:
        raise HTTPException(status_code=400, detail="Only PDF uploads are supported")

    try:
        raw_payload = json.loads(fields)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid fields payload") from exc

    if isinstance(raw_payload, dict):
        template = dict(raw_payload)
        raw_fields = list(template.get("fields") or [])
    elif isinstance(raw_payload, list):
        template = {}
        raw_fields = list(raw_payload)
    else:
        raise HTTPException(status_code=400, detail="Invalid fields payload")

    max_mb, max_bytes = resolve_upload_limit()
    temp_path = write_upload_to_temp(
        pdf,
        max_bytes=max_bytes,
        limit_message=f"PDF exceeds {max_mb}MB upload limit",
    )
    try:
        with fitz.open(str(temp_path)) as doc:
            page_count = max(1, int(doc.page_count))
    except Exception as exc:
        cleanup_paths([temp_path])
        raise HTTPException(status_code=400, detail="Invalid PDF upload") from exc
    max_pages = resolve_fillable_max_pages(user.role)
    if page_count > max_pages:
        cleanup_paths([temp_path])
        raise HTTPException(
            status_code=403,
            detail=f"Fillable upload limited to {max_pages} pages for your tier (got {page_count}).",
        )

    if not raw_fields:
        background_tasks.add_task(cleanup_paths, [temp_path])
        output_name = safe_pdf_download_filename(filename, "form")
        response = FileResponse(
            str(temp_path),
            media_type="application/pdf",
            filename=output_name,
            background=background_tasks,
        )
        response.headers.update(resolve_stream_cors_headers(request.headers.get("origin")))
        return response

    template.setdefault("coordinateSystem", "originTop")
    template["fields"] = coerce_field_payloads(raw_fields)

    template_fd, template_name = tempfile.mkstemp(suffix=".json")
    os.close(template_fd)
    template_path = Path(template_name)
    cleanup_targets = [temp_path, template_path]

    try:
        output_fd, output_name = tempfile.mkstemp(suffix=".pdf")
        os.close(output_fd)
        output_path = Path(output_name)
        cleanup_targets.append(output_path)
        template_path.write_text(json.dumps(template), encoding="utf-8")
        inject_fields(temp_path, template_path, output_path)
    except Exception as exc:
        cleanup_paths(cleanup_targets)
        raise HTTPException(status_code=500, detail="Failed to generate fillable PDF") from exc
    background_tasks.add_task(cleanup_paths, cleanup_targets)

    stem = os.path.splitext(filename)[0] or "form"
    output_name = safe_pdf_download_filename(f"{stem}-fillable", "form")
    response = FileResponse(
        str(output_path),
        media_type="application/pdf",
        filename=output_name,
        background=background_tasks,
    )
    response.headers.update(resolve_stream_cors_headers(request.headers.get("origin")))
    return response


@router.post("/api/templates/session")
async def create_template_session(
    pdf: UploadFile = File(...),
    fields: str = Form(...),
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    """Create a session for a fillable template upload so OpenAI rename/mapping can run."""
    user = require_user(authorization)
    if not pdf:
        raise HTTPException(status_code=400, detail="Missing PDF upload")

    source_pdf = pdf.filename or "upload.pdf"
    content_type = (pdf.content_type or "").lower()
    if not source_pdf.lower().endswith(".pdf") and content_type not in {"application/pdf", "application/octet-stream"}:
        raise HTTPException(status_code=400, detail="Only PDF uploads are supported")

    try:
        raw_payload = json.loads(fields)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid fields payload") from exc

    if isinstance(raw_payload, dict):
        raw_fields = list(raw_payload.get("fields") or [])
    elif isinstance(raw_payload, list):
        raw_fields = list(raw_payload)
    else:
        raise HTTPException(status_code=400, detail="Invalid fields payload")

    template_fields = coerce_field_payloads(raw_fields)
    if not template_fields:
        raise HTTPException(status_code=400, detail="No fields provided for template session")

    max_mb, max_bytes = resolve_upload_limit()
    pdf_bytes = await read_upload_bytes(
        pdf,
        max_bytes=max_bytes,
        limit_message=f"PDF exceeds {max_mb}MB upload limit",
    )
    if not pdf_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    validation = validate_pdf_for_detection(pdf_bytes)
    max_pages = resolve_fillable_max_pages(user.role)
    if validation.page_count > max_pages:
        raise HTTPException(
            status_code=403,
            detail=f"Fillable upload limited to {max_pages} pages for your tier (got {validation.page_count}).",
        )
    session_id = str(uuid.uuid4())
    entry: Dict[str, Any] = {
        "user_id": user.app_user_id,
        "source_pdf": source_pdf,
        "pdf_bytes": validation.pdf_bytes,
        "fields": template_fields,
        "page_count": validation.page_count,
        "detection_status": DETECTION_STATUS_COMPLETE,
        "detection_completed_at": now_iso(),
    }
    _store_session_entry(
        session_id,
        entry,
        persist_pdf=True,
        persist_fields=True,
        persist_result=False,
    )
    return {
        "success": True,
        "sessionId": session_id,
        "fieldCount": len(template_fields),
        "pageCount": validation.page_count,
    }
