"""Firestore-backed detection request logging."""

from dataclasses import dataclass
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
