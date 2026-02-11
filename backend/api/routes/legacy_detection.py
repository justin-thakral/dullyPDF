"""Legacy/dev detection endpoints preserved for compatibility."""

from __future__ import annotations

import io
import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from backend.detection_status import (
    DETECTION_STATUS_COMPLETE,
    DETECTION_STATUS_FAILED,
    DETECTION_STATUS_RUNNING,
)
from backend.firebaseDB.detection_database import record_detection_request, update_detection_request
from backend.sessions.session_store import (
    get_session_entry as _get_session_entry,
    store_session_entry as _store_session_entry,
)
from backend.time_utils import now_iso
from backend.firebaseDB.storage_service import stream_pdf

from backend.services.app_config import require_legacy_enabled, resolve_detection_mode
from backend.services.auth_service import require_user
from backend.services.detection_service import enqueue_detection_job, run_local_detection
from backend.services.limits_service import resolve_detect_max_pages, resolve_fillable_max_pages
from backend.services.pdf_service import (
    get_pdf_page_count,
    read_upload_bytes,
    resolve_upload_limit,
    safe_pdf_download_filename,
    validate_pdf_for_detection,
)

router = APIRouter()


@router.post("/api/process-pdf")
async def process_pdf(
    pdf: UploadFile = File(...),
    pipeline: Optional[str] = None,
    pipeline_form: Optional[str] = Form(None, alias="pipeline"),
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    """CommonForms-only detection endpoint for the upload UI."""
    require_legacy_enabled()
    user = require_user(authorization)
    if not pdf:
        raise HTTPException(status_code=400, detail="Missing PDF upload")

    source_pdf = pdf.filename or "upload.pdf"
    content_type = (pdf.content_type or "").lower()
    if not source_pdf.lower().endswith(".pdf") and content_type not in {"application/pdf", "application/octet-stream"}:
        raise HTTPException(status_code=400, detail="Only PDF uploads are supported")

    max_mb, max_bytes = resolve_upload_limit()
    pdf_bytes = await read_upload_bytes(
        pdf,
        max_bytes=max_bytes,
        limit_message=f"PDF exceeds {max_mb}MB upload limit",
    )
    if not pdf_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")
    validation = validate_pdf_for_detection(pdf_bytes)
    pdf_bytes = validation.pdf_bytes
    page_count = validation.page_count
    max_pages = resolve_detect_max_pages(user.role)
    if page_count > max_pages:
        raise HTTPException(
            status_code=403,
            detail=f"Detection limited to {max_pages} pages for your tier (got {page_count}).",
        )

    pipeline_choice = (pipeline or pipeline_form or "commonforms").strip().lower()
    if pipeline_choice != "commonforms":
        raise HTTPException(status_code=400, detail="Unsupported pipeline selection")
    detection_mode = resolve_detection_mode()

    if detection_mode == "local":
        session_id = str(uuid.uuid4())
        record_detection_request(
            request_id=session_id,
            session_id=session_id,
            user_id=user.app_user_id,
            status=DETECTION_STATUS_RUNNING,
            page_count=page_count,
        )
        try:
            resolved = run_local_detection(pdf_bytes)
            fields = resolved.get("fields", [])
            _store_session_entry(
                session_id,
                {
                    "pdf_bytes": pdf_bytes,
                    "fields": fields,
                    "source_pdf": source_pdf,
                    "result": resolved,
                    "page_count": page_count,
                    "user_id": user.app_user_id,
                    "detection_status": DETECTION_STATUS_COMPLETE,
                    "detection_completed_at": now_iso(),
                },
            )
            update_detection_request(
                request_id=session_id,
                status=DETECTION_STATUS_COMPLETE,
                page_count=page_count,
            )
            return {
                "success": True,
                "sessionId": session_id,
                "originalFilename": source_pdf,
                "pipeline": resolved.get("pipeline", pipeline_choice),
                "fieldCount": len(fields),
                "fields": fields,
                "result": resolved,
                "status": DETECTION_STATUS_COMPLETE,
            }
        except Exception as exc:
            update_detection_request(
                request_id=session_id,
                status=DETECTION_STATUS_FAILED,
                error=str(exc),
                page_count=page_count,
            )
            raise
    if detection_mode == "tasks":
        response = enqueue_detection_job(pdf_bytes, source_pdf, user, page_count=page_count)
        return {
            "success": True,
            "originalFilename": source_pdf,
            **response,
        }
    raise HTTPException(status_code=500, detail=f"Unsupported detection mode: {detection_mode}")


@router.post("/api/register-fillable")
async def register_fillable_pdf(
    pdf: UploadFile = File(...),
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    """Register a PDF for later field upload/merge flows without running detection."""
    require_legacy_enabled()
    user = require_user(authorization)
    if not pdf:
        raise HTTPException(status_code=400, detail="Missing PDF upload")

    source_pdf = pdf.filename or "upload.pdf"
    content_type = (pdf.content_type or "").lower()
    if not source_pdf.lower().endswith(".pdf") and content_type not in {"application/pdf", "application/octet-stream"}:
        raise HTTPException(status_code=400, detail="Only PDF uploads are supported")

    session_id = str(uuid.uuid4())
    max_mb, max_bytes = resolve_upload_limit()
    pdf_bytes = await read_upload_bytes(
        pdf,
        max_bytes=max_bytes,
        limit_message=f"PDF exceeds {max_mb}MB upload limit",
    )
    if not pdf_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    page_count = get_pdf_page_count(pdf_bytes)
    max_pages = resolve_fillable_max_pages(user.role)
    if page_count > max_pages:
        raise HTTPException(
            status_code=403,
            detail=f"Fillable upload limited to {max_pages} pages for your tier (got {page_count}).",
        )
    _store_session_entry(
        session_id,
        {
            "pdf_bytes": pdf_bytes,
            "fields": [],
            "source_pdf": source_pdf,
            "result": {},
            "page_count": page_count,
            "user_id": user.app_user_id,
        },
    )
    return {
        "success": True,
        "sessionId": session_id,
        "originalFilename": source_pdf,
    }


@router.get("/api/detected-fields")
async def get_detected_fields(
    sessionId: str,
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    """Return cached fields for a prior session."""
    require_legacy_enabled()
    user = require_user(authorization)
    entry = _get_session_entry(
        sessionId,
        user,
        include_pdf_bytes=False,
        include_result=False,
        include_renames=False,
        include_checkbox_rules=False,
        force_l2=True,
    )
    fields = entry.get("fields", [])
    return {
        "success": True,
        "sessionId": sessionId,
        "items": fields,
        "total": len(fields),
        "status": entry.get("detection_status") or DETECTION_STATUS_COMPLETE,
    }


@router.get("/download/{session_id}")
async def download_session_pdf(
    session_id: str,
    authorization: Optional[str] = Header(default=None),
):
    """Stream the original PDF bytes for a session."""
    require_legacy_enabled()
    user = require_user(authorization)
    entry = _get_session_entry(
        session_id,
        user,
        include_pdf_bytes=False,
        include_fields=False,
        include_result=False,
        include_renames=False,
        include_checkbox_rules=False,
    )
    filename = safe_pdf_download_filename(entry.get("source_pdf") or "document")
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    pdf_bytes = entry.get("pdf_bytes")
    if pdf_bytes:
        stream = io.BytesIO(pdf_bytes)
    else:
        pdf_path = entry.get("pdf_path")
        if not pdf_path:
            raise HTTPException(status_code=404, detail="Session PDF not found")
        stream = stream_pdf(pdf_path)
    return StreamingResponse(stream, media_type="application/pdf", headers=headers)
