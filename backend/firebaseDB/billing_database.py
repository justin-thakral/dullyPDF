"""Firestore-backed Stripe webhook event bookkeeping."""

from __future__ import annotations

from datetime import datetime, timezone
import os
from typing import Any, Dict

from firebase_admin import firestore as firebase_firestore

from .firebase_service import get_firestore_client
from .log_utils import log_expires_at, now_iso


BILLING_EVENTS_COLLECTION = "billing_events"
BILLING_EVENT_STATUS_PROCESSING = "processing"
BILLING_EVENT_STATUS_PROCESSED = "processed"
BILLING_EVENT_STATUS_FAILED = "failed"
BILLING_EVENT_LOCK_TIMEOUT_SECONDS = int(os.getenv("BILLING_EVENT_LOCK_TIMEOUT_SECONDS", "120"))


class BillingEventInProgressError(RuntimeError):
    """Raised when another worker still owns a fresh billing event lock."""


def _coerce_attempts(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 0
    return parsed if parsed > 0 else 0


def _parse_updated_at(raw: Any) -> datetime | None:
    if isinstance(raw, datetime):
        parsed = raw
    elif isinstance(raw, str):
        text = raw.strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _processing_lock_is_stale(updated_at: Any) -> bool:
    timeout_seconds = BILLING_EVENT_LOCK_TIMEOUT_SECONDS
    if timeout_seconds <= 0:
        return False
    parsed = _parse_updated_at(updated_at)
    if parsed is None:
        return True
    age_seconds = (datetime.now(timezone.utc) - parsed).total_seconds()
    return age_seconds >= timeout_seconds


def get_billing_event(event_id: str) -> Dict[str, Any] | None:
    """Return billing event metadata when present."""
    normalized_id = (event_id or "").strip()
    if not normalized_id:
        return None
    client = get_firestore_client()
    snapshot = client.collection(BILLING_EVENTS_COLLECTION).document(normalized_id).get()
    if not snapshot.exists:
        return None
    data = snapshot.to_dict()
    return data if isinstance(data, dict) else {}


def start_billing_event(event_id: str, event_type: str) -> bool:
    """Acquire a processing lock for a Stripe event id.

    Returns False when the event has already been fully processed.
    """
    normalized_id = (event_id or "").strip()
    normalized_type = (event_type or "").strip()
    if not normalized_id:
        raise ValueError("event_id is required")
    if not normalized_type:
        raise ValueError("event_type is required")

    client = get_firestore_client()
    doc_ref = client.collection(BILLING_EVENTS_COLLECTION).document(normalized_id)
    transaction = client.transaction()

    @firebase_firestore.transactional
    def _start(txn: firebase_firestore.Transaction) -> bool:
        snapshot = doc_ref.get(transaction=txn)
        if snapshot.exists:
            data = snapshot.to_dict() or {}
            status = str(data.get("status") or "").strip().lower()
            if status == BILLING_EVENT_STATUS_PROCESSED:
                return False
            if status == BILLING_EVENT_STATUS_PROCESSING and not _processing_lock_is_stale(data.get("updated_at")):
                raise BillingEventInProgressError(f"Stripe event {normalized_id} is still processing.")
            payload: Dict[str, Any] = {
                "event_id": normalized_id,
                "event_type": normalized_type,
                "status": BILLING_EVENT_STATUS_PROCESSING,
                "updated_at": now_iso(),
                "attempts": _coerce_attempts(data.get("attempts")) + 1,
            }
            if not data.get("created_at"):
                payload["created_at"] = now_iso()
            expires_at = log_expires_at()
            if expires_at:
                payload["expires_at"] = expires_at
            txn.set(doc_ref, payload, merge=True)
            return True

        payload = {
            "event_id": normalized_id,
            "event_type": normalized_type,
            "status": BILLING_EVENT_STATUS_PROCESSING,
            "created_at": now_iso(),
            "updated_at": now_iso(),
            "attempts": 1,
        }
        expires_at = log_expires_at()
        if expires_at:
            payload["expires_at"] = expires_at
        txn.set(doc_ref, payload, merge=False)
        return True

    return _start(transaction)


def complete_billing_event(event_id: str) -> None:
    """Mark a Stripe event as successfully processed."""
    normalized_id = (event_id or "").strip()
    if not normalized_id:
        raise ValueError("event_id is required")
    client = get_firestore_client()
    client.collection(BILLING_EVENTS_COLLECTION).document(normalized_id).set(
        {
            "status": BILLING_EVENT_STATUS_PROCESSED,
            "updated_at": now_iso(),
        },
        merge=True,
    )


def clear_billing_event(event_id: str) -> None:
    """Mark a Stripe event as failed so a later retry can reclaim it safely."""
    normalized_id = (event_id or "").strip()
    if not normalized_id:
        return
    client = get_firestore_client()
    client.collection(BILLING_EVENTS_COLLECTION).document(normalized_id).set(
        {
            "status": BILLING_EVENT_STATUS_FAILED,
            "updated_at": now_iso(),
        },
        merge=True,
    )


def delete_billing_event(event_id: str) -> None:
    """Delete a Stripe event lock document as a fallback unlock path."""
    normalized_id = (event_id or "").strip()
    if not normalized_id:
        return
    client = get_firestore_client()
    client.collection(BILLING_EVENTS_COLLECTION).document(normalized_id).delete()
