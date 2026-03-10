"""Firestore-backed async OpenAI job metadata."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from backend.logging_config import get_logger

from .firebase_service import get_firestore_client
from .log_utils import log_expires_at, now_iso


logger = get_logger(__name__)

OPENAI_JOBS_COLLECTION = "openai_jobs"


class OpenAiJobAlreadyExistsError(RuntimeError):
    """Raised when an async OpenAI job document already exists."""


def is_openai_job_conflict_error(exc: Exception) -> bool:
    """Best-effort conflict detection across Firestore client variants."""
    if isinstance(exc, OpenAiJobAlreadyExistsError):
        return True
    status_code = getattr(exc, "status_code", None)
    if status_code == 409:
        return True
    code = getattr(exc, "code", None)
    if code == 409:
        return True
    grpc_code = getattr(code, "value", None)
    if grpc_code == 409:
        return True
    error_name = exc.__class__.__name__.strip().lower()
    if error_name in {"alreadyexists", "conflict"}:
        return True
    return "already exists" in str(exc).strip().lower()


def create_openai_job(
    *,
    job_id: str,
    job_type: str,
    user_id: str,
    status: str,
    session_id: Optional[str] = None,
    schema_id: Optional[str] = None,
    template_id: Optional[str] = None,
    profile: Optional[str] = None,
    queue: Optional[str] = None,
    service_url: Optional[str] = None,
    page_count: Optional[int] = None,
    template_field_count: Optional[int] = None,
    credits: int = 0,
    credit_pricing: Optional[Dict[str, Any]] = None,
    credits_charged: bool = False,
    credit_breakdown: Optional[Dict[str, Any]] = None,
    user_role: Optional[str] = None,
    request_id: Optional[str] = None,
) -> None:
    if not job_id:
        raise ValueError("job_id is required")
    if not user_id:
        raise ValueError("user_id is required")
    if not job_type:
        raise ValueError("job_type is required")
    payload: Dict[str, Any] = {
        "job_id": job_id,
        "request_id": request_id or job_id,
        "job_type": job_type,
        "user_id": user_id,
        "session_id": session_id or None,
        "schema_id": schema_id or None,
        "template_id": template_id or None,
        "status": status,
        "error": None,
        "profile": profile or None,
        "queue": queue or None,
        "service_url": service_url or None,
        "page_count": page_count,
        "template_field_count": template_field_count,
        "credits": int(credits or 0),
        "credit_pricing": credit_pricing if isinstance(credit_pricing, dict) else None,
        "credits_charged": bool(credits_charged),
        "credit_breakdown": credit_breakdown if isinstance(credit_breakdown, dict) else None,
        "user_role": (user_role or "").strip() or None,
        "result": None,
        "openai_usage_summary": None,
        "openai_usage_events": [],
        "attempt_count": 0,
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    expires_at = log_expires_at()
    if expires_at:
        payload["expires_at"] = expires_at
    client = get_firestore_client()
    doc_ref = client.collection(OPENAI_JOBS_COLLECTION).document(job_id)
    try:
        doc_ref.create(payload)
    except Exception as exc:
        if is_openai_job_conflict_error(exc):
            raise OpenAiJobAlreadyExistsError(f"OpenAI job already exists: {job_id}") from exc
        raise
    logger.debug("OpenAI job recorded: %s", job_id)


def update_openai_job(
    *,
    job_id: str,
    status: Optional[str] = None,
    error: Optional[str] = None,
    result: Optional[Dict[str, Any]] = None,
    task_name: Optional[str] = None,
    started_at: Optional[str] = None,
    completed_at: Optional[str] = None,
    openai_usage_summary: Optional[Dict[str, Any]] = None,
    openai_usage_events: Optional[List[Dict[str, Any]]] = None,
    attempt_count: Optional[int] = None,
    credit_breakdown: Optional[Dict[str, Any]] = None,
) -> None:
    if not job_id:
        raise ValueError("job_id is required")
    updates: Dict[str, Any] = {
        "updated_at": now_iso(),
    }
    if status is not None:
        updates["status"] = status
    if error is not None:
        updates["error"] = (error or "").strip() or None
    if result is not None:
        updates["result"] = result
    if task_name is not None:
        updates["task_name"] = task_name
    if started_at is not None:
        updates["started_at"] = started_at
    if completed_at is not None:
        updates["completed_at"] = completed_at
    if openai_usage_summary is not None:
        updates["openai_usage_summary"] = openai_usage_summary
    if openai_usage_events is not None:
        updates["openai_usage_events"] = openai_usage_events
    if attempt_count is not None:
        updates["attempt_count"] = int(attempt_count)
    if credit_breakdown is not None:
        updates["credit_breakdown"] = credit_breakdown
    client = get_firestore_client()
    doc_ref = client.collection(OPENAI_JOBS_COLLECTION).document(job_id)
    doc_ref.set(updates, merge=True)
    logger.debug("OpenAI job updated: %s", job_id)


def get_openai_job(job_id: str) -> Optional[Dict[str, Any]]:
    if not job_id:
        return None
    client = get_firestore_client()
    snapshot = client.collection(OPENAI_JOBS_COLLECTION).document(job_id).get()
    if not snapshot.exists:
        return None
    data = snapshot.to_dict() or {}
    if "job_id" not in data:
        data["job_id"] = job_id
    return data
