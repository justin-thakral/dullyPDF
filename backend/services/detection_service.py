"""Detection orchestration shared by detection endpoints."""

from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import HTTPException

from backend.detection.status import (
    DETECTION_STATUS_COMPLETE,
    DETECTION_STATUS_FAILED,
    DETECTION_STATUS_QUEUED,
    DETECTION_STATUS_RUNNING,
)
from backend.detection.tasks import enqueue_detection_task, resolve_detector_profile, resolve_task_config
from backend.logging_config import get_logger
from backend.firebaseDB.detection_database import record_detection_request, update_detection_request
from backend.firebaseDB.firebase_service import RequestUser
from backend.sessions.session_store import store_session_entry as _store_session_entry, update_session_entry as _update_session_entry
from backend.time_utils import now_iso

from .pdf_service import get_pdf_page_count

logger = get_logger(__name__)


def run_local_detection(pdf_bytes: bytes) -> Dict[str, Any]:
    fd, temp_name = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)
    temp_path = Path(temp_name)
    try:
        temp_path.write_bytes(pdf_bytes)
        try:
            from backend.fieldDetecting.commonforms.commonForm import detect_commonforms_fields
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail="CommonForms dependencies are missing; set DETECTOR_MODE=tasks or install detector deps.",
            ) from exc
        resolved = detect_commonforms_fields(Path(temp_path))
    finally:
        temp_path.unlink(missing_ok=True)
    resolved["pipeline"] = "commonforms"
    return resolved


def enqueue_detection_job(
    pdf_bytes: bytes,
    source_pdf: str,
    user: Optional[RequestUser],
    *,
    page_count: Optional[int] = None,
) -> Dict[str, Any]:
    session_id = str(uuid.uuid4())
    resolved_page_count = page_count if page_count is not None else get_pdf_page_count(pdf_bytes)
    detector_profile = resolve_detector_profile(resolved_page_count)
    task_config = resolve_task_config(detector_profile)
    entry: Dict[str, Any] = {
        "pdf_bytes": pdf_bytes,
        "fields": [],
        "source_pdf": source_pdf,
        "result": {},
        "page_count": resolved_page_count,
        "user_id": user.app_user_id if user else None,
        "detection_status": DETECTION_STATUS_QUEUED,
        "detection_queued_at": now_iso(),
        "detection_error": "",
        "detection_profile": task_config["profile"],
        "detection_queue": task_config["queue"],
        "detection_service_url": task_config["service_url"],
    }
    _store_session_entry(
        session_id,
        entry,
        persist_fields=False,
        persist_result=False,
        persist_l1=False,
    )
    pdf_path = entry.get("pdf_path")
    if not pdf_path:
        raise HTTPException(status_code=500, detail="Session PDF storage failed")

    payload = {
        "sessionId": session_id,
        "pdfPath": pdf_path,
        "pipeline": "commonforms",
    }
    record_detection_request(
        request_id=session_id,
        session_id=session_id,
        user_id=user.app_user_id if user else None,
        status=DETECTION_STATUS_QUEUED,
        page_count=resolved_page_count,
    )
    try:
        task_name = enqueue_detection_task(payload, profile=task_config["profile"])
    except Exception as exc:
        entry["detection_status"] = DETECTION_STATUS_FAILED
        entry["detection_completed_at"] = now_iso()
        entry["detection_error"] = str(exc)
        _update_session_entry(session_id, entry)
        update_detection_request(
            request_id=session_id,
            status=DETECTION_STATUS_FAILED,
            error=str(exc),
        )
        raise HTTPException(status_code=500, detail="Failed to enqueue detection job") from exc

    entry["detection_task_name"] = task_name
    _update_session_entry(session_id, entry)
    return {
        "sessionId": session_id,
        "status": DETECTION_STATUS_QUEUED,
        "pipeline": "commonforms",
    }


__all__ = [
    "DETECTION_STATUS_COMPLETE",
    "DETECTION_STATUS_FAILED",
    "DETECTION_STATUS_QUEUED",
    "DETECTION_STATUS_RUNNING",
    "enqueue_detection_job",
    "run_local_detection",
]
