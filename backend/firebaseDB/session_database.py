"""Firestore-backed session metadata operations.
"""

from typing import Any, Dict, Optional

from ..fieldDetecting.rename_pipeline.combinedSrc.config import get_logger
from .firebase_service import get_firestore_client
from ..time_utils import now_iso


logger = get_logger(__name__)

SESSION_COLLECTION = "session_cache"


def get_session_metadata(session_id: str) -> Optional[Dict[str, Any]]:
    """Fetch a session metadata document if it exists.
    """
    if not session_id:
        return None
    client = get_firestore_client()
    snapshot = client.collection(SESSION_COLLECTION).document(session_id).get()
    if not snapshot.exists:
        return None
    return snapshot.to_dict() or {}


def upsert_session_metadata(session_id: str, payload: Dict[str, Any]) -> None:
    """Create or update session metadata with merge semantics.
    """
    if not session_id:
        raise ValueError("Missing session_id")
    client = get_firestore_client()
    doc_ref = client.collection(SESSION_COLLECTION).document(session_id)
    updates = dict(payload or {})
    if "updated_at" not in updates:
        updates["updated_at"] = now_iso()
    doc_ref.set(updates, merge=True)


def delete_session_metadata(session_id: str) -> None:
    """Delete a session metadata document.
    """
    if not session_id:
        return
    client = get_firestore_client()
    client.collection(SESSION_COLLECTION).document(session_id).delete()
