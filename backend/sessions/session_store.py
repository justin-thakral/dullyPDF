"""Session cache with in-process LRU (L1) and Firestore/GCS persistence (L2).

Public API -- all internal helpers live in ``l1_cache`` and ``l2_persistence``.
"""

from typing import Any, Dict, Optional

from fastapi import HTTPException

from backend.logging_config import get_logger
from ..firebaseDB.firebase_service import RequestUser
from ..firebaseDB.session_database import get_session_metadata, upsert_session_metadata
from ..time_utils import now_iso

from .l1_cache import (
    SessionEntry,
    _API_SESSION_CACHE,
    _SESSION_CACHE_LOCK,
    _session_now,
    _prune_session_cache,
    _store_l1_entry,
)
from .l2_persistence import (
    _expires_at,
    _require_owner,
    _touch_l2_session,
    _missing_required_data,
    _hydrate_from_l2,
    _ensure_l2_data,
    _persist_session_entry,
)

logger = get_logger(__name__)


def store_session_entry(
    session_id: str,
    entry: SessionEntry,
    *,
    persist_pdf: bool = True,
    persist_fields: bool = True,
    persist_result: bool = True,
    persist_checkbox_hints: bool = False,
    persist_l1: bool = True,
) -> None:
    """Store a new session in L2 and optionally cache it in L1."""
    _persist_session_entry(
        session_id,
        entry,
        persist_pdf=persist_pdf,
        persist_fields=persist_fields,
        persist_result=persist_result,
        persist_checkbox_hints=persist_checkbox_hints,
        include_created_at=True,
    )
    if persist_l1:
        _store_l1_entry(session_id, entry)


def update_session_entry(
    session_id: str,
    entry: SessionEntry,
    *,
    persist_pdf: bool = False,
    persist_fields: bool = False,
    persist_result: bool = False,
    persist_renames: bool = False,
    persist_checkbox_rules: bool = False,
    persist_checkbox_hints: bool = False,
) -> None:
    """Persist session updates to L2.
    """
    _persist_session_entry(
        session_id,
        entry,
        persist_pdf=persist_pdf,
        persist_fields=persist_fields,
        persist_result=persist_result,
        persist_renames=persist_renames,
        persist_checkbox_rules=persist_checkbox_rules,
        persist_checkbox_hints=persist_checkbox_hints,
        include_created_at=False,
    )


def get_session_entry(
    session_id: str,
    user: RequestUser,
    *,
    include_pdf_bytes: bool = True,
    include_fields: bool = True,
    include_result: bool = True,
    include_renames: bool = True,
    include_checkbox_rules: bool = True,
    include_checkbox_hints: bool = False,
    force_l2: bool = False,
) -> SessionEntry:
    """Return a session entry, loading from L2 when needed.
    """
    if force_l2:
        entry = _hydrate_from_l2(
            session_id,
            include_pdf_bytes=include_pdf_bytes,
            include_fields=include_fields,
            include_result=include_result,
            include_renames=include_renames,
            include_checkbox_rules=include_checkbox_rules,
            include_checkbox_hints=include_checkbox_hints,
        )
        if not entry:
            raise HTTPException(status_code=404, detail="Session not found")
        _require_owner(entry, user)
        _store_l1_entry(session_id, entry)
        _touch_l2_session(session_id, entry, _session_now())
        return entry
    now = _session_now()
    entry: Optional[SessionEntry] = None
    with _SESSION_CACHE_LOCK:
        _prune_session_cache(now)
        entry = _API_SESSION_CACHE.get(session_id)
        if entry:
            _require_owner(entry, user)
            entry["last_access"] = now
            _API_SESSION_CACHE.move_to_end(session_id)

    if entry:
        _ensure_l2_data(
            session_id,
            entry,
            include_pdf_bytes=include_pdf_bytes,
            include_fields=include_fields,
            include_result=include_result,
            include_renames=include_renames,
            include_checkbox_rules=include_checkbox_rules,
            include_checkbox_hints=include_checkbox_hints,
        )
        _require_owner(entry, user)
        if _missing_required_data(
            entry,
            include_pdf_bytes=include_pdf_bytes,
            include_fields=include_fields,
            include_result=include_result,
            include_renames=include_renames,
            include_checkbox_rules=include_checkbox_rules,
            include_checkbox_hints=include_checkbox_hints,
        ):
            raise HTTPException(status_code=404, detail="Session data not found")
        _touch_l2_session(session_id, entry, now)
        return entry

    entry = _hydrate_from_l2(
        session_id,
        include_pdf_bytes=include_pdf_bytes,
        include_fields=include_fields,
        include_result=include_result,
        include_renames=include_renames,
        include_checkbox_rules=include_checkbox_rules,
        include_checkbox_hints=include_checkbox_hints,
    )
    if not entry:
        raise HTTPException(status_code=404, detail="Session not found")
    _require_owner(entry, user)
    _store_l1_entry(session_id, entry)
    _touch_l2_session(session_id, entry, _session_now())
    return entry


def get_session_entry_if_present(
    session_id: Optional[str],
    user: RequestUser,
    *,
    include_pdf_bytes: bool = True,
    include_fields: bool = True,
    include_result: bool = True,
    include_renames: bool = True,
    include_checkbox_rules: bool = True,
    include_checkbox_hints: bool = False,
    force_l2: bool = False,
) -> Optional[SessionEntry]:
    """Return a session entry when it exists and is owned by the caller.
    """
    if not session_id:
        return None
    if force_l2:
        entry = _hydrate_from_l2(
            session_id,
            include_pdf_bytes=include_pdf_bytes,
            include_fields=include_fields,
            include_result=include_result,
            include_renames=include_renames,
            include_checkbox_rules=include_checkbox_rules,
            include_checkbox_hints=include_checkbox_hints,
        )
        if not entry:
            return None
        _require_owner(entry, user)
        _store_l1_entry(session_id, entry)
        _touch_l2_session(session_id, entry, _session_now())
        return entry
    now = _session_now()
    entry: Optional[SessionEntry] = None
    with _SESSION_CACHE_LOCK:
        _prune_session_cache(now)
        entry = _API_SESSION_CACHE.get(session_id)
        if entry:
            _require_owner(entry, user)
            entry["last_access"] = now
            _API_SESSION_CACHE.move_to_end(session_id)

    if entry:
        _ensure_l2_data(
            session_id,
            entry,
            include_pdf_bytes=include_pdf_bytes,
            include_fields=include_fields,
            include_result=include_result,
            include_renames=include_renames,
            include_checkbox_rules=include_checkbox_rules,
            include_checkbox_hints=include_checkbox_hints,
        )
        _require_owner(entry, user)
        if _missing_required_data(
            entry,
            include_pdf_bytes=include_pdf_bytes,
            include_fields=include_fields,
            include_result=include_result,
            include_renames=include_renames,
            include_checkbox_rules=include_checkbox_rules,
            include_checkbox_hints=include_checkbox_hints,
        ):
            return None
        _touch_l2_session(session_id, entry, now)
        return entry

    entry = _hydrate_from_l2(
        session_id,
        include_pdf_bytes=include_pdf_bytes,
        include_fields=include_fields,
        include_result=include_result,
        include_renames=include_renames,
        include_checkbox_rules=include_checkbox_rules,
        include_checkbox_hints=include_checkbox_hints,
    )
    if not entry:
        return None
    _require_owner(entry, user)
    _store_l1_entry(session_id, entry)
    _touch_l2_session(session_id, entry, _session_now())
    return entry


def touch_session_entry(session_id: str, user: RequestUser) -> None:
    metadata = get_session_metadata(session_id)
    if not metadata:
        raise HTTPException(status_code=404, detail="Session not found")
    entry: SessionEntry = {
        "user_id": metadata.get("user_id"),
    }
    _require_owner(entry, user)
    payload: Dict[str, Any] = {"last_access_at": now_iso()}
    expires_at = _expires_at()
    if expires_at:
        payload["expires_at"] = expires_at
    try:
        upsert_session_metadata(session_id, payload)
    except Exception as exc:
        logger.warning("Failed to refresh session %s: %s", session_id, exc)
        raise HTTPException(status_code=503, detail="Failed to refresh session") from exc
    now = _session_now()
    with _SESSION_CACHE_LOCK:
        cached = _API_SESSION_CACHE.get(session_id)
        if cached:
            cached["last_access"] = now
            cached["_l2_touch_at"] = now
            _API_SESSION_CACHE.move_to_end(session_id)
