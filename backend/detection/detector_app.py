"""Detector service for CommonForms field detection."""

import os
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from ..ai.prewarm import prewarm_openai_services
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
from ..services.task_auth_service import resolve_task_audiences, verify_internal_oidc_token
from ..time_utils import now_iso


def _is_prod() -> bool:
    return env_value("ENV").lower() in {"prod", "production"}


logger = get_logger(__name__)
_WARNED_PROD_DEFAULT_TASK_ATTEMPTS = False


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
    prewarmRename: bool = False
    prewarmRemap: bool = False


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
    if value > 0:
        return value
    if _is_prod():
        global _WARNED_PROD_DEFAULT_TASK_ATTEMPTS
        if not _WARNED_PROD_DEFAULT_TASK_ATTEMPTS:
            logger.warning(
                "DETECTOR_TASKS_MAX_ATTEMPTS is unset in prod; defaulting to 5 to match the managed queues."
            )
            _WARNED_PROD_DEFAULT_TASK_ATTEMPTS = True
        return 5
    return None


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


def _reject_detection_request(session_id: str, error_message: str) -> Dict[str, Any]:
    return _finish_detection_failure(session_id, error_message)


def _require_internal_auth(authorization: Optional[str]) -> Dict[str, Any]:
    if _ALLOW_UNAUTHENTICATED:
        return {}
    raw = (authorization or "").strip()
    if not raw.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing detector auth token")
    token = raw.split(" ", 1)[1].strip()
    payload = verify_internal_oidc_token(
        token,
        audiences=resolve_task_audiences(
            audience_envs=[
                "DETECTOR_TASKS_AUDIENCE",
                "DETECTOR_TASKS_AUDIENCE_LIGHT",
                "DETECTOR_TASKS_AUDIENCE_HEAVY",
                "DETECTOR_TASKS_AUDIENCE_LIGHT_GPU",
                "DETECTOR_TASKS_AUDIENCE_HEAVY_GPU",
            ],
            service_url_envs=[
                "DETECTOR_SERVICE_URL",
                "DETECTOR_SERVICE_URL_LIGHT",
                "DETECTOR_SERVICE_URL_HEAVY",
                "DETECTOR_SERVICE_URL_LIGHT_GPU",
                "DETECTOR_SERVICE_URL_HEAVY_GPU",
            ],
        ),
        missing_audience_detail="Detector audience is not configured",
        invalid_token_detail="Invalid detector auth token",
    )
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
            logger.warning("Detector auth rejected for session %s: %s", payload.sessionId, detail)
        else:
            logger.warning("Detector session %s rejected: %s", payload.sessionId, detail)
        return _reject_detection_request(payload.sessionId, str(detail))

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
            prewarm_remaining_pages = max(0, int_env("OPENAI_PREWARM_REMAINING_PAGES", 3))
            should_prewarm_rename = bool(payload.prewarmRename)
            should_prewarm_remap = bool(payload.prewarmRemap)
            prewarm_triggered = False

            def _maybe_prewarm(processed_pages: int, total_pages: int) -> None:
                nonlocal prewarm_triggered
                if prewarm_triggered:
                    return
                if not (should_prewarm_rename or should_prewarm_remap):
                    return
                remaining = max(0, int(total_pages) - int(processed_pages))
                if remaining > prewarm_remaining_pages:
                    return
                prewarm_openai_services(
                    page_count=total_pages,
                    prewarm_rename=should_prewarm_rename,
                    prewarm_remap=should_prewarm_remap,
                )
                prewarm_triggered = True

            resolved = detect_commonforms_fields(
                Path(temp_path),
                progress_callback=_maybe_prewarm,
            )
            if (should_prewarm_rename or should_prewarm_remap) and not prewarm_triggered:
                prewarm_openai_services(
                    page_count=validation.page_count,
                    prewarm_rename=should_prewarm_rename,
                    prewarm_remap=should_prewarm_remap,
                )
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
