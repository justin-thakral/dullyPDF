"""Detection orchestration shared by detection endpoints."""

from __future__ import annotations

import os
import tempfile
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from fastapi import HTTPException

from backend.ai.prewarm import prewarm_openai_services
from backend.detection.status import (
    DETECTION_STATUS_COMPLETE,
    DETECTION_STATUS_FAILED,
    DETECTION_STATUS_QUEUED,
    DETECTION_STATUS_RUNNING,
)
from backend.detection.tasks import enqueue_detection_task, resolve_detector_profile, resolve_task_config
from backend.env_utils import int_env
from backend.logging_config import get_logger
from backend.firebaseDB.detection_database import record_detection_request, update_detection_request
from backend.firebaseDB.firebase_service import RequestUser
from backend.sessions.session_store import store_session_entry as _store_session_entry, update_session_entry as _update_session_entry
from backend.time_utils import now_iso

from .pdf_service import get_pdf_page_count

logger = get_logger(__name__)
_LOCAL_DETECTION_EXECUTOR = ThreadPoolExecutor(
    max_workers=max(1, int_env("LOCAL_DETECTION_MAX_WORKERS", 1)),
    thread_name_prefix="local-detect",
)


def run_local_detection(
    pdf_bytes: bytes,
    *,
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> Dict[str, Any]:
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
        resolved = detect_commonforms_fields(Path(temp_path), progress_callback=progress_callback)
    finally:
        temp_path.unlink(missing_ok=True)
    resolved["pipeline"] = "commonforms"
    return resolved


def _run_local_detection_job(
    session_id: str,
    *,
    pdf_bytes: bytes,
    source_pdf: str,
    user_id: Optional[str],
    page_count: Optional[int],
    prewarm_rename: bool,
    prewarm_remap: bool,
) -> None:
    _update_session_entry(
        session_id,
        {
            "user_id": user_id,
            "source_pdf": source_pdf,
            "page_count": page_count,
            "detection_status": DETECTION_STATUS_RUNNING,
            "detection_started_at": now_iso(),
            "detection_error": "",
        },
    )
    update_detection_request(request_id=session_id, status=DETECTION_STATUS_RUNNING)
    detect_started = time.monotonic()

    try:
        prewarm_remaining_pages = max(0, int_env("OPENAI_PREWARM_REMAINING_PAGES", 3))
        prewarm_triggered = False

        def _maybe_prewarm(processed_pages: int, total_pages: int) -> None:
            nonlocal prewarm_triggered
            if prewarm_triggered:
                return
            if not (prewarm_rename or prewarm_remap):
                return
            remaining = max(0, int(total_pages) - int(processed_pages))
            if remaining > prewarm_remaining_pages:
                return
            prewarm_openai_services(
                page_count=total_pages,
                prewarm_rename=prewarm_rename,
                prewarm_remap=prewarm_remap,
            )
            prewarm_triggered = True

        resolved = run_local_detection(pdf_bytes, progress_callback=_maybe_prewarm)
        if (prewarm_rename or prewarm_remap) and not prewarm_triggered:
            prewarm_openai_services(
                page_count=page_count,
                prewarm_rename=prewarm_rename,
                prewarm_remap=prewarm_remap,
            )
        fields = resolved.get("fields", [])
        duration_seconds = max(0.0, time.monotonic() - detect_started)
        _update_session_entry(
            session_id,
            {
                "user_id": user_id,
                "source_pdf": source_pdf,
                "page_count": page_count,
                "fields": fields,
                "result": resolved,
                "detection_status": DETECTION_STATUS_COMPLETE,
                "detection_completed_at": now_iso(),
                "detection_error": "",
                "detection_duration_seconds": duration_seconds,
            },
            persist_fields=True,
            persist_result=True,
        )
        update_detection_request(
            request_id=session_id,
            status=DETECTION_STATUS_COMPLETE,
            page_count=page_count,
        )
        logger.info(
            "Local detector session %s -> %s final fields produced in %.2fs",
            session_id,
            len(fields),
            duration_seconds,
        )
    except Exception as exc:
        logger.exception("Local detector session %s failed: %s", session_id, exc)
        _update_session_entry(
            session_id,
            {
                "user_id": user_id,
                "source_pdf": source_pdf,
                "page_count": page_count,
                "detection_status": DETECTION_STATUS_FAILED,
                "detection_completed_at": now_iso(),
                "detection_error": str(exc),
            },
        )
        update_detection_request(
            request_id=session_id,
            status=DETECTION_STATUS_FAILED,
            error=str(exc),
            page_count=page_count,
        )


def enqueue_local_detection_job(
    pdf_bytes: bytes,
    source_pdf: str,
    user: Optional[RequestUser],
    *,
    page_count: Optional[int] = None,
    prewarm_rename: bool = False,
    prewarm_remap: bool = False,
) -> Dict[str, Any]:
    session_id = str(uuid.uuid4())
    resolved_page_count = page_count if page_count is not None else get_pdf_page_count(pdf_bytes)
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
        "detection_profile": "local",
        "detection_queue": "local",
        "detection_service_url": "local",
        "openai_prewarm_rename": bool(prewarm_rename),
        "openai_prewarm_remap": bool(prewarm_remap),
    }
    _store_session_entry(
        session_id,
        entry,
        persist_fields=False,
        persist_result=False,
        persist_l1=False,
    )
    record_detection_request(
        request_id=session_id,
        session_id=session_id,
        user_id=user.app_user_id if user else None,
        status=DETECTION_STATUS_QUEUED,
        page_count=resolved_page_count,
    )
    _LOCAL_DETECTION_EXECUTOR.submit(
        _run_local_detection_job,
        session_id,
        pdf_bytes=pdf_bytes,
        source_pdf=source_pdf,
        user_id=user.app_user_id if user else None,
        page_count=resolved_page_count,
        prewarm_rename=bool(prewarm_rename),
        prewarm_remap=bool(prewarm_remap),
    )
    return {
        "sessionId": session_id,
        "status": DETECTION_STATUS_QUEUED,
        "pipeline": "commonforms",
    }


def enqueue_detection_job(
    pdf_bytes: bytes,
    source_pdf: str,
    user: Optional[RequestUser],
    *,
    page_count: Optional[int] = None,
    prewarm_rename: bool = False,
    prewarm_remap: bool = False,
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
        "openai_prewarm_rename": bool(prewarm_rename),
        "openai_prewarm_remap": bool(prewarm_remap),
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
        "prewarmRename": bool(prewarm_rename),
        "prewarmRemap": bool(prewarm_remap),
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
    "enqueue_local_detection_job",
    "enqueue_detection_job",
    "run_local_detection",
]
