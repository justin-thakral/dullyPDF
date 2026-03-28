"""Firestore-backed detection request logging."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from backend.logging_config import get_logger
from .firebase_service import get_firestore_client
from .log_utils import log_expires_at, now_iso


logger = get_logger(__name__)

DETECTION_REQUESTS_COLLECTION = "detection_requests"


@dataclass(frozen=True)
class DetectionLogRecord:
    request_id: str
    session_id: str
    user_id: Optional[str]
    status: str
    dispatch_lane: Optional[str]
    detection_profile: Optional[str]
    detection_queue: Optional[str]
    detection_service_url: Optional[str]
    page_count: Optional[int]
    error: Optional[str]
    created_at: Optional[str]
    updated_at: Optional[str]


def record_detection_request(
    *,
    request_id: str,
    session_id: str,
    user_id: Optional[str],
    status: str,
    dispatch_lane: Optional[str] = None,
    detection_profile: Optional[str] = None,
    detection_queue: Optional[str] = None,
    detection_service_url: Optional[str] = None,
    page_count: Optional[int] = None,
    error: Optional[str] = None,
) -> None:
    if not request_id or not session_id:
        raise ValueError("request_id and session_id are required")
    payload = {
        "request_id": request_id,
        "session_id": session_id,
        "user_id": user_id,
        "status": status,
        "dispatch_lane": dispatch_lane or None,
        "detection_profile": detection_profile or None,
        "detection_queue": detection_queue or None,
        "detection_service_url": detection_service_url or None,
        "page_count": page_count,
        "error": error or None,
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    expires_at = log_expires_at()
    if expires_at:
        payload["expires_at"] = expires_at
    client = get_firestore_client()
    doc_ref = client.collection(DETECTION_REQUESTS_COLLECTION).document(request_id)
    doc_ref.set(payload)
    logger.debug("Detection log recorded: %s", request_id)


def update_detection_request(
    *,
    request_id: str,
    status: str,
    page_count: Optional[int] = None,
    error: Optional[str] = None,
) -> None:
    if not request_id:
        raise ValueError("request_id is required")
    updates = {
        "status": status,
        "updated_at": now_iso(),
    }
    if page_count is not None:
        updates["page_count"] = page_count
    if error is not None:
        updates["error"] = error or None
    client = get_firestore_client()
    doc_ref = client.collection(DETECTION_REQUESTS_COLLECTION).document(request_id)
    doc_ref.set(updates, merge=True)
    logger.debug("Detection log updated: %s", request_id)


def _parse_iso_datetime(value: Optional[str]) -> Optional[datetime]:
    raw = (value or "").strip()
    if not raw:
        return None
    normalized = raw.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def detection_lane_busy(
    lane: str,
    *,
    active_window_seconds: Optional[int] = None,
) -> bool:
    normalized_lane = (lane or "").strip().lower()
    if not normalized_lane:
        return False

    cutoff: Optional[datetime] = None
    if active_window_seconds is not None and active_window_seconds > 0:
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=active_window_seconds)

    client = get_firestore_client()
    collection = client.collection(DETECTION_REQUESTS_COLLECTION)
    for status in ("queued", "running"):
        for snapshot in collection.where("status", "==", status).get():
            payload = snapshot.to_dict() or {}
            if (payload.get("dispatch_lane") or "").strip().lower() != normalized_lane:
                continue
            if cutoff is not None:
                updated_at = _parse_iso_datetime(payload.get("updated_at"))
                created_at = _parse_iso_datetime(payload.get("created_at"))
                freshest = updated_at or created_at
                if freshest is not None and freshest < cutoff:
                    continue
            return True
    return False
