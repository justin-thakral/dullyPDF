"""Detector service for CommonForms field detection."""

import os
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import FastAPI, Header, HTTPException
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token
from pydantic import BaseModel, Field

from .status import (
    DETECTION_STATUS_COMPLETE,
    DETECTION_STATUS_FAILED,
    DETECTION_STATUS_RUNNING,
)
from ..env_utils import env_truthy, env_value, int_env
from ..fieldDetecting.commonforms.commonForm import detect_commonforms_fields
from backend.logging_config import get_logger
from ..firebaseDB.detection_database import update_detection_request
from ..firebaseDB.session_database import get_session_metadata, upsert_session_metadata
from ..firebaseDB.storage_service import download_pdf_bytes, is_gcs_path
from .pdf_validation import PdfValidationError, preflight_pdf_bytes
from ..sessions.session_store import update_session_entry
from ..time_utils import now_iso


def _is_prod() -> bool:
    return env_value("ENV").lower() in {"prod", "production"}


logger = get_logger(__name__)


def _allow_unauthenticated() -> bool:
    if not env_truthy("DETECTOR_ALLOW_UNAUTHENTICATED"):
        return False
    if _is_prod():
        logger.warning("DETECTOR_ALLOW_UNAUTHENTICATED is ignored in prod.")
        return False
    env_name = env_value("ENV").lower()
    if env_name not in {"dev", "development", "local", "test"}:
        logger.warning(
            "DETECTOR_ALLOW_UNAUTHENTICATED is ignored for ENV=%s.",
            env_name or "unset",
        )
        return False
    return True


_ALLOW_UNAUTHENTICATED = _allow_unauthenticated()

app = FastAPI(title="DullyPDF Detector")


class DetectJobRequest(BaseModel):
    sessionId: str = Field(..., min_length=1)
    pdfPath: str = Field(..., min_length=1)
    pipeline: str = "commonforms"


def _parse_retry_count(raw: Optional[str]) -> int:
    if raw is None:
        return 0
    try:
        value = int(str(raw).strip())
    except ValueError:
        return 0
    return max(0, value)


def _max_task_attempts() -> Optional[int]:
    value = int_env("DETECTOR_TASKS_MAX_ATTEMPTS", 0)
    return value if value > 0 else None


def _should_finalize_failure(retry_count: int) -> bool:
    max_attempts = _max_task_attempts()
    if not max_attempts:
        return False
    # Cloud Tasks uses retry count starting at 0 for the first attempt.
    return retry_count >= max_attempts - 1


def _retry_headers() -> Dict[str, str]:
    retry_after = int_env("DETECTOR_RETRY_AFTER_SECONDS", 5)
    headers = {"X-Dully-Retry": "true"}
    if retry_after > 0:
        headers["Retry-After"] = str(retry_after)
    return headers


def _finish_detection_failure(session_id: str, error_message: str) -> Dict[str, Any]:
    upsert_session_metadata(
        session_id,
        {
            "detection_status": DETECTION_STATUS_FAILED,
            "detection_completed_at": now_iso(),
            "detection_error": error_message,
        },
    )
    update_detection_request(
        request_id=session_id,
        status=DETECTION_STATUS_FAILED,
        error=error_message,
    )
    return {
        "sessionId": session_id,
        "status": DETECTION_STATUS_FAILED,
        "error": error_message,
    }


def _require_internal_auth(authorization: Optional[str]) -> Dict[str, Any]:
    if _ALLOW_UNAUTHENTICATED:
        return {}
    raw = (authorization or "").strip()
    if not raw.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing detector auth token")
    token = raw.split(" ", 1)[1].strip()
    audience = env_value("DETECTOR_TASKS_AUDIENCE") or env_value("DETECTOR_SERVICE_URL")
    if not audience:
        raise HTTPException(status_code=500, detail="Detector audience is not configured")
    try:
        payload = id_token.verify_oauth2_token(token, google_requests.Request(), audience=audience)
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid detector auth token") from exc
    allowed_email = env_value("DETECTOR_CALLER_SERVICE_ACCOUNT")
    if _is_prod() and not allowed_email:
        raise HTTPException(
            status_code=500,
            detail="Detector caller service account is not configured",
        )
    if allowed_email and payload.get("email") != allowed_email:
        raise HTTPException(status_code=403, detail="Detector caller not allowed")
    return payload


@app.get("/health")
async def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.post("/internal/detect")
async def run_detection(
    payload: DetectJobRequest,
    authorization: Optional[str] = Header(default=None),
    x_cloud_tasks_taskretrycount: Optional[str] = Header(
        default=None,
        alias="X-CloudTasks-TaskRetryCount",
    ),
) -> Dict[str, Any]:
    metadata: Dict[str, Any]
    try:
        _require_internal_auth(authorization)
        if payload.pipeline != "commonforms":
            raise HTTPException(status_code=400, detail="Unsupported detection pipeline")
        if not is_gcs_path(payload.pdfPath):
            raise HTTPException(status_code=400, detail="Invalid PDF storage path")

        metadata = get_session_metadata(payload.sessionId)
        if not metadata:
            raise HTTPException(status_code=404, detail="Session metadata not found")
        stored_path = metadata.get("pdf_path")
        if stored_path and stored_path != payload.pdfPath:
            raise HTTPException(status_code=400, detail="Session PDF path mismatch")

        upsert_session_metadata(
            payload.sessionId,
            {
                "detection_status": DETECTION_STATUS_RUNNING,
                "detection_started_at": now_iso(),
                "detection_error": "",
            },
        )
        update_detection_request(
            request_id=payload.sessionId,
            status=DETECTION_STATUS_RUNNING,
        )
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, str) else "Detector request rejected"
        if exc.status_code in {401, 403}:
            logger.warning("Detector auth rejected: %s", detail)
            raise
        logger.warning("Detector session %s rejected: %s", payload.sessionId, detail)
        return _finish_detection_failure(payload.sessionId, str(detail))

    try:
        detect_started = time.monotonic()
        pdf_bytes = download_pdf_bytes(payload.pdfPath)
        validation = preflight_pdf_bytes(pdf_bytes)
        pdf_bytes = validation.pdf_bytes
        if validation.was_decrypted:
            logger.info("Detector session %s PDF decrypted with empty password.", payload.sessionId)
        fd, temp_name = tempfile.mkstemp(suffix=".pdf")
        os.close(fd)
        temp_path = Path(temp_name)
        try:
            temp_path.write_bytes(pdf_bytes)
            resolved = detect_commonforms_fields(Path(temp_path))
        finally:
            temp_path.unlink(missing_ok=True)
        resolved["pipeline"] = "commonforms"
        fields = resolved.get("fields", [])
        duration_seconds = max(0.0, time.monotonic() - detect_started)
        entry: Dict[str, Any] = {
            "user_id": metadata.get("user_id"),
            "source_pdf": metadata.get("source_pdf"),
            "pdf_path": metadata.get("pdf_path") or payload.pdfPath,
            "fields": fields,
            "result": resolved,
            "page_count": metadata.get("page_count"),
            "detection_status": DETECTION_STATUS_COMPLETE,
            "detection_completed_at": now_iso(),
            "detection_error": "",
            "detection_duration_seconds": duration_seconds,
        }
        update_session_entry(
            payload.sessionId,
            entry,
            persist_fields=True,
            persist_result=True,
        )
        update_detection_request(
            request_id=payload.sessionId,
            status=DETECTION_STATUS_COMPLETE,
            page_count=entry.get("page_count"),
        )
        logger.info(
            "Detector session %s -> %s final fields produced in %.2fs",
            payload.sessionId,
            len(fields),
            duration_seconds,
        )
        return {
            "sessionId": payload.sessionId,
            "status": DETECTION_STATUS_COMPLETE,
            "fieldCount": len(fields),
        }
    except PdfValidationError as exc:
        logger.info("Detector session %s rejected: %s", payload.sessionId, exc)
        return _finish_detection_failure(payload.sessionId, str(exc))
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, str) else "Detector request rejected"
        logger.warning("Detector session %s rejected: %s", payload.sessionId, detail)
        return _finish_detection_failure(payload.sessionId, str(detail))
    except Exception as exc:
        logger.exception("Detector session %s failed: %s", payload.sessionId, exc)
        retry_count = _parse_retry_count(x_cloud_tasks_taskretrycount)
        if _should_finalize_failure(retry_count):
            message = f"Detector failed after {retry_count + 1} attempts: {exc}"
            return _finish_detection_failure(payload.sessionId, message)
        raise HTTPException(
            status_code=500,
            detail="Detector failed; retrying",
            headers=_retry_headers(),
        ) from exc
