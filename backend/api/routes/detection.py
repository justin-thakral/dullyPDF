"""Primary detection endpoints."""

from __future__ import annotations

import os
import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, File, Form, Header, HTTPException, Request, UploadFile

from backend.detection.status import (
    DETECTION_STATUS_COMPLETE,
    DETECTION_STATUS_FAILED,
    DETECTION_STATUS_QUEUED,
    DETECTION_STATUS_RUNNING,
)
from backend.logging_config import get_logger
from backend.firebaseDB.user_database import ensure_user
from backend.firebaseDB.firebase_service import RequestUser
from backend.firebaseDB.session_database import get_session_metadata
from backend.firebaseDB.storage_service import download_session_json
from backend.security.rate_limit import check_rate_limit
from backend.sessions.session_store import store_session_entry as _store_session_entry
from backend.time_utils import now_iso

from backend.services.app_config import resolve_detection_mode
from backend.services.auth_service import has_admin_override, verify_token
from backend.services.detection_service import enqueue_detection_job, run_local_detection
from backend.services.limits_service import resolve_detect_max_pages
from backend.services.pdf_service import (
    get_pdf_page_count,
    log_pdf_label,
    read_upload_bytes,
    validate_pdf_for_detection,
    resolve_upload_limit,
)
from backend.firebaseDB.detection_database import record_detection_request, update_detection_request

logger = get_logger(__name__)
router = APIRouter()


def _is_storage_not_found_error(exc: Exception) -> bool:
    if isinstance(exc, FileNotFoundError):
        return True
    status_code = getattr(exc, "status_code", None)
    if status_code is None:
        status_code = getattr(exc, "code", None)
    if status_code == 404:
        return True
    return exc.__class__.__name__.lower() == "notfound"


def _form_truthy(value: Optional[str]) -> bool:
    raw = str(value or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


@router.post("/detect-fields")
async def detect_fields(
    request: Request,
    file: UploadFile = File(...),
    pipeline: Optional[str] = None,
    pipeline_form: Optional[str] = Form(None, alias="pipeline"),
    prewarm_rename_form: Optional[str] = Form(None, alias="prewarmRename"),
    prewarm_remap_form: Optional[str] = Form(None, alias="prewarmRemap"),
    authorization: Optional[str] = Header(default=None),
    x_admin_token: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    """Main detection endpoint: CommonForms field detection only."""
    auth_payload: Optional[Dict[str, Any]] = getattr(request.state, "detect_auth_payload", None)
    user: Optional[RequestUser] = None
    admin_override = getattr(request.state, "detect_admin_override", False)
    if not admin_override:
        admin_override = has_admin_override(authorization, x_admin_token)
    if not admin_override:
        if auth_payload is None:
            auth_payload = verify_token(authorization)
        try:
            user = ensure_user(auth_payload or {})
        except Exception as exc:
            logger.error("Failed to sync Firebase user profile: %s", exc)
            raise HTTPException(status_code=500, detail="Failed to synchronize user profile") from exc
    if not file:
        raise HTTPException(status_code=400, detail="Missing PDF upload")

    if not admin_override and user:
        try:
            window_seconds = int(os.getenv("SANDBOX_DETECT_RATE_LIMIT_WINDOW_SECONDS", "30"))
        except ValueError:
            window_seconds = 30
        if window_seconds <= 0:
            window_seconds = 30
        try:
            user_rate = int(os.getenv("SANDBOX_DETECT_RATE_LIMIT_PER_USER", "6"))
        except ValueError:
            user_rate = 6
        if user_rate <= 0:
            user_rate = 6
        if not check_rate_limit(
            f"detect:user:{user.app_user_id}",
            limit=user_rate,
            window_seconds=window_seconds,
        ):
            raise HTTPException(status_code=429, detail="Rate limit exceeded for user")

    source_pdf = file.filename or "upload.pdf"
    content_type = (file.content_type or "").lower()
    if not source_pdf.lower().endswith(".pdf") and content_type not in {"application/pdf", "application/octet-stream"}:
        raise HTTPException(status_code=400, detail="Only PDF uploads are supported")

    max_mb, max_bytes = resolve_upload_limit()
    pdf_bytes = await read_upload_bytes(
        file,
        max_bytes=max_bytes,
        limit_message=f"PDF exceeds {max_mb}MB upload limit",
    )
    if not pdf_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")
    validation = validate_pdf_for_detection(pdf_bytes)
    pdf_bytes = validation.pdf_bytes
    page_count = validation.page_count
    if validation.was_decrypted:
        logger.info("Detection PDF decrypted with empty password.")
    if not admin_override and user:
        max_pages = resolve_detect_max_pages(user.role)
        if page_count > max_pages:
            raise HTTPException(
                status_code=403,
                detail=f"Detection limited to {max_pages} pages for your tier (got {page_count}).",
            )
    if auth_payload and auth_payload.get("uid"):
        logger.info("Detection request by %s", auth_payload["uid"])
    elif admin_override:
        logger.info("Detection request by admin override")
    logger.info("Starting detection for %s", log_pdf_label(source_pdf))

    pipeline_choice = (pipeline or pipeline_form or "commonforms").strip().lower()
    if pipeline_choice != "commonforms":
        raise HTTPException(status_code=400, detail="Unsupported pipeline selection")
    prewarm_rename = _form_truthy(prewarm_rename_form)
    prewarm_remap = _form_truthy(prewarm_remap_form)

    detection_mode = resolve_detection_mode()
    if detection_mode == "local":
        session_id = str(uuid.uuid4())
        record_detection_request(
            request_id=session_id,
            session_id=session_id,
            user_id=user.app_user_id if user else None,
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
                    "user_id": user.app_user_id if user else None,
                    "detection_status": DETECTION_STATUS_COMPLETE,
                    "detection_completed_at": now_iso(),
                },
            )
            update_detection_request(
                request_id=session_id,
                status=DETECTION_STATUS_COMPLETE,
                page_count=page_count,
            )
            logger.info(
                "Session %s -> %s final fields produced (commonforms pipeline)",
                session_id,
                len(fields),
            )
            return {
                **resolved,
                "sessionId": session_id,
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
        response = enqueue_detection_job(
            pdf_bytes,
            source_pdf,
            user,
            page_count=page_count,
            prewarm_rename=prewarm_rename,
            prewarm_remap=prewarm_remap,
        )
        logger.info("Session %s -> queued detection job", response.get("sessionId"))
        return response

    raise HTTPException(status_code=500, detail=f"Unsupported detection mode: {detection_mode}")


@router.get("/detect-fields/{session_id}")
async def get_detection_status(
    request: Request,
    session_id: str,
    authorization: Optional[str] = Header(default=None),
    x_admin_token: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    """Return detector job status and results when available."""
    user: Optional[RequestUser] = None
    admin_override = getattr(request.state, "detect_admin_override", False)
    if not admin_override:
        admin_override = has_admin_override(authorization, x_admin_token)
    if not admin_override:
        auth_payload = getattr(request.state, "detect_auth_payload", None)
        if auth_payload is None:
            auth_payload = verify_token(authorization)
        try:
            user = ensure_user(auth_payload)
        except Exception as exc:
            logger.error("Failed to sync Firebase user profile: %s", exc)
            raise HTTPException(status_code=500, detail="Failed to synchronize user profile") from exc

    metadata = get_session_metadata(session_id)
    if not metadata:
        raise HTTPException(status_code=404, detail="Session not found")
    owner_id = metadata.get("user_id")
    if not admin_override:
        if not owner_id:
            raise HTTPException(status_code=403, detail="Session access denied")
        if owner_id != user.app_user_id:
            raise HTTPException(status_code=403, detail="Session access denied")

    status = metadata.get("detection_status")
    if not status:
        status = DETECTION_STATUS_COMPLETE if metadata.get("fields_path") else DETECTION_STATUS_FAILED

    response: Dict[str, Any] = {
        "sessionId": session_id,
        "status": status,
        "pipeline": "commonforms",
        "sourcePdf": metadata.get("source_pdf"),
        "pageCount": metadata.get("page_count"),
        "detectionQueuedAt": metadata.get("detection_queued_at"),
        "detectionStartedAt": metadata.get("detection_started_at"),
        "detectionDurationSeconds": metadata.get("detection_duration_seconds"),
        "detectionProfile": metadata.get("detection_profile"),
        "detectionQueue": metadata.get("detection_queue"),
        "detectionServiceUrl": metadata.get("detection_service_url"),
    }

    if status == DETECTION_STATUS_FAILED:
        response["error"] = metadata.get("detection_error") or "Detection failed"
        return response

    if status != DETECTION_STATUS_COMPLETE:
        return response

    fields_path = metadata.get("fields_path")
    result_path = metadata.get("result_path")
    try:
        fields = download_session_json(fields_path) if fields_path else []
    except Exception as exc:
        if _is_storage_not_found_error(exc):
            raise HTTPException(status_code=404, detail="Session data not found") from exc
        raise HTTPException(status_code=500, detail="Failed to load session data") from exc
    response["fields"] = fields
    response["fieldCount"] = len(fields)
    if result_path:
        try:
            response["result"] = download_session_json(result_path) or {}
        except Exception as exc:
            if _is_storage_not_found_error(exc):
                raise HTTPException(status_code=404, detail="Session data not found") from exc
            raise HTTPException(status_code=500, detail="Failed to load session data") from exc
    return response
