"""Firestore-backed bookkeeping for failed OpenAI credit refunds."""

from __future__ import annotations

import uuid
from typing import Any, Dict, Optional

from backend.logging_config import get_logger

from .firebase_service import get_firestore_client
from .log_utils import log_expires_at, now_iso


logger = get_logger(__name__)

CREDIT_REFUND_FAILURES_COLLECTION = "credit_refund_failures"
CREDIT_REFUND_STATUS_PENDING = "pending"
CREDIT_REFUND_STATUS_RESOLVED = "resolved"


def _coerce_positive_int(value: Any, *, default: int = 0) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _normalize_credit_breakdown(raw: Optional[Dict[str, Any]]) -> Dict[str, int]:
    payload = raw if isinstance(raw, dict) else {}
    return {
        "base": _coerce_positive_int(payload.get("base"), default=0),
        "monthly": _coerce_positive_int(payload.get("monthly"), default=0),
        "refill": _coerce_positive_int(payload.get("refill"), default=0),
    }


def record_credit_refund_failure(
    *,
    user_id: str,
    credits: int,
    role: Optional[str],
    source: str,
    error_message: str,
    attempts: int,
    credit_breakdown: Optional[Dict[str, Any]] = None,
    request_id: Optional[str] = None,
    job_id: Optional[str] = None,
) -> str:
    """Persist a failed credit refund for later reconciliation."""
    normalized_user_id = (user_id or "").strip()
    if not normalized_user_id:
        raise ValueError("user_id is required")
    normalized_source = (source or "").strip()
    if not normalized_source:
        raise ValueError("source is required")

    record_id = uuid.uuid4().hex
    now = now_iso()
    payload: Dict[str, Any] = {
        "record_id": record_id,
        "status": CREDIT_REFUND_STATUS_PENDING,
        "user_id": normalized_user_id,
        "credits": _coerce_positive_int(credits, default=1),
        "role": (role or "").strip().lower() or None,
        "source": normalized_source,
        "request_id": (request_id or "").strip() or None,
        "job_id": (job_id or "").strip() or None,
        "attempts": _coerce_positive_int(attempts, default=1),
        "last_error": (error_message or "").strip() or "Unknown refund failure",
        "credit_breakdown": _normalize_credit_breakdown(credit_breakdown),
        "created_at": now,
        "updated_at": now,
        "last_attempt_at": now,
    }
    expires_at = log_expires_at()
    if expires_at:
        payload["expires_at"] = expires_at

    client = get_firestore_client()
    client.collection(CREDIT_REFUND_FAILURES_COLLECTION).document(record_id).set(payload, merge=False)
    logger.error(
        "Recorded pending credit refund failure (record_id=%s, user_id=%s, source=%s).",
        record_id,
        normalized_user_id,
        normalized_source,
    )
    return record_id


def mark_credit_refund_failure_resolved(record_id: str, *, resolution_note: Optional[str] = None) -> None:
    """Mark a previously failed refund record as resolved."""
    normalized_id = (record_id or "").strip()
    if not normalized_id:
        raise ValueError("record_id is required")
    updates: Dict[str, Any] = {
        "status": CREDIT_REFUND_STATUS_RESOLVED,
        "updated_at": now_iso(),
    }
    if resolution_note is not None:
        updates["resolution_note"] = (resolution_note or "").strip() or None
    client = get_firestore_client()
    client.collection(CREDIT_REFUND_FAILURES_COLLECTION).document(normalized_id).set(updates, merge=True)

