"""Session cache with in-process LRU (L1) and Firestore/GCS persistence (L2)."""

import threading
import time
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from fastapi import HTTPException

from ..env_utils import int_env as _int_env
from ..fieldDetecting.rename_pipeline.combinedSrc.config import get_logger
from ..firebaseDB.firebase_service import RequestUser
from ..firebaseDB.session_database import get_session_metadata, upsert_session_metadata
from ..firebaseDB.storage_service import (
    download_pdf_bytes,
    download_session_json,
    upload_session_json,
    upload_session_pdf_bytes,
)
from ..time_utils import now_iso


logger = get_logger(__name__)

SessionEntry = Dict[str, Any]

_SESSION_VERSION = 1

_API_SESSION_CACHE: "OrderedDict[str, SessionEntry]" = OrderedDict()
_SESSION_CACHE_LOCK = threading.Lock()

_SESSION_TTL_SECONDS = _int_env("SANDBOX_SESSION_TTL_SECONDS", 7200)
_SESSION_SWEEP_INTERVAL_SECONDS = _int_env("SANDBOX_SESSION_SWEEP_INTERVAL_SECONDS", 300)
_SESSION_MAX_ENTRIES = max(0, _int_env("SANDBOX_SESSION_MAX_ENTRIES", 200))
_SESSION_L2_TOUCH_SECONDS = max(0, _int_env("SANDBOX_SESSION_L2_TOUCH_SECONDS", 300))
_LAST_SESSION_SWEEP = 0.0


def _session_now() -> float:
    return time.monotonic()


def _session_last_access(entry: SessionEntry) -> float:
    raw = entry.get("last_access") or entry.get("created_at") or 0.0
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 0.0


def _prune_session_cache(now: float) -> None:
    global _LAST_SESSION_SWEEP
    if _SESSION_TTL_SECONDS <= 0:
        return
    if _SESSION_SWEEP_INTERVAL_SECONDS > 0 and (now - _LAST_SESSION_SWEEP) < _SESSION_SWEEP_INTERVAL_SECONDS:
        return
    cutoff = now - _SESSION_TTL_SECONDS
    expired_ids = [
        session_id
        for session_id, entry in _API_SESSION_CACHE.items()
        if _session_last_access(entry) < cutoff
    ]
    for session_id in expired_ids:
        _API_SESSION_CACHE.pop(session_id, None)
    _LAST_SESSION_SWEEP = now


def _trim_session_cache_size() -> None:
    if _SESSION_MAX_ENTRIES <= 0:
        return
    while len(_API_SESSION_CACHE) > _SESSION_MAX_ENTRIES:
        _API_SESSION_CACHE.popitem(last=False)


def _store_l1_entry(session_id: str, entry: SessionEntry) -> None:
    now = _session_now()
    entry["created_at"] = now
    entry["last_access"] = now
    with _SESSION_CACHE_LOCK:
        _prune_session_cache(now)
        _API_SESSION_CACHE[session_id] = entry
        _API_SESSION_CACHE.move_to_end(session_id)
        _trim_session_cache_size()


def _session_object_path(session_id: str, suffix: str) -> str:
    safe_id = (session_id or "").strip()
    if not safe_id:
        raise ValueError("Missing session_id")
    suffix_value = (suffix or "").strip().lstrip("/")
    if not suffix_value:
        raise ValueError("Missing session artifact suffix")
    return f"sessions/{safe_id}/{suffix_value}"


def _expires_at() -> Optional[datetime]:
    if _SESSION_TTL_SECONDS <= 0:
        return None
    return datetime.now(timezone.utc) + timedelta(seconds=_SESSION_TTL_SECONDS)


def _require_owner(entry: SessionEntry, user: RequestUser) -> None:
    owner_id = (entry.get("user_id") or "").strip()
    if not owner_id:
        raise HTTPException(status_code=403, detail="Session access denied")
    if owner_id != user.app_user_id:
        raise HTTPException(status_code=403, detail="Session access denied")


def _touch_l2_session(session_id: str, entry: SessionEntry, now: float) -> None:
    if _SESSION_TTL_SECONDS <= 0 or _SESSION_L2_TOUCH_SECONDS <= 0:
        return
    last_touch = entry.get("_l2_touch_at")
    if isinstance(last_touch, (int, float)) and (now - float(last_touch)) < _SESSION_L2_TOUCH_SECONDS:
        return
    payload: Dict[str, Any] = {"last_access_at": now_iso()}
    expires_at = _expires_at()
    if expires_at:
        payload["expires_at"] = expires_at
    try:
        upsert_session_metadata(session_id, payload)
        entry["_l2_touch_at"] = now
    except Exception as exc:
        logger.debug("Failed to touch L2 session %s: %s", session_id, exc)


def _missing_required_data(
    entry: SessionEntry,
    *,
    include_pdf_bytes: bool,
    include_fields: bool,
    include_result: bool,
    include_renames: bool,
    include_checkbox_rules: bool,
) -> bool:
    if include_pdf_bytes and not entry.get("pdf_bytes"):
        return True
    if include_fields and "fields" not in entry:
        return True
    if include_result and "result" not in entry and entry.get("result_path"):
        return True
    if include_renames and "renames" not in entry and entry.get("renames_path"):
        return True
    if include_checkbox_rules and "checkboxRules" not in entry and entry.get("checkbox_rules_path"):
        return True
    return False


def _hydrate_from_l2(
    session_id: str,
    *,
    include_pdf_bytes: bool,
    include_fields: bool,
    include_result: bool,
    include_renames: bool,
    include_checkbox_rules: bool,
) -> Optional[SessionEntry]:
    metadata = get_session_metadata(session_id)
    if not metadata:
        return None
    entry: SessionEntry = {
        "user_id": metadata.get("user_id"),
        "source_pdf": metadata.get("source_pdf"),
        "pdf_path": metadata.get("pdf_path"),
        "fields_path": metadata.get("fields_path"),
        "result_path": metadata.get("result_path"),
        "renames_path": metadata.get("renames_path"),
        "checkbox_rules_path": metadata.get("checkbox_rules_path"),
        "openai_credit_consumed": bool(metadata.get("openai_credit_consumed")),
        "openai_credit_pages": metadata.get("openai_credit_pages"),
        "openai_credit_mapping_used": bool(metadata.get("openai_credit_mapping_used")),
        "page_count": metadata.get("page_count"),
        "detection_status": metadata.get("detection_status"),
        "detection_error": metadata.get("detection_error"),
        "detection_queued_at": metadata.get("detection_queued_at"),
        "detection_started_at": metadata.get("detection_started_at"),
        "detection_completed_at": metadata.get("detection_completed_at"),
        "detection_task_name": metadata.get("detection_task_name"),
        "detection_profile": metadata.get("detection_profile"),
        "detection_queue": metadata.get("detection_queue"),
        "detection_service_url": metadata.get("detection_service_url"),
        "detection_duration_seconds": metadata.get("detection_duration_seconds"),
    }

    if include_pdf_bytes and entry.get("pdf_path"):
        entry["pdf_bytes"] = download_pdf_bytes(entry["pdf_path"])
    if include_fields and entry.get("fields_path"):
        entry["fields"] = download_session_json(entry["fields_path"]) or []
    if include_result and entry.get("result_path"):
        entry["result"] = download_session_json(entry["result_path"]) or {}
    if include_renames and entry.get("renames_path"):
        entry["renames"] = download_session_json(entry["renames_path"]) or {}
    if include_checkbox_rules and entry.get("checkbox_rules_path"):
        entry["checkboxRules"] = download_session_json(entry["checkbox_rules_path"]) or []

    return entry


def _ensure_l2_data(
    session_id: str,
    entry: SessionEntry,
    *,
    include_pdf_bytes: bool,
    include_fields: bool,
    include_result: bool,
    include_renames: bool,
    include_checkbox_rules: bool,
) -> None:
    if not _missing_required_data(
        entry,
        include_pdf_bytes=include_pdf_bytes,
        include_fields=include_fields,
        include_result=include_result,
        include_renames=include_renames,
        include_checkbox_rules=include_checkbox_rules,
    ):
        return
    hydrated = _hydrate_from_l2(
        session_id,
        include_pdf_bytes=include_pdf_bytes,
        include_fields=include_fields,
        include_result=include_result,
        include_renames=include_renames,
        include_checkbox_rules=include_checkbox_rules,
    )
    if hydrated:
        entry.update(hydrated)


def _persist_session_entry(
    session_id: str,
    entry: SessionEntry,
    *,
    persist_pdf: bool = False,
    persist_fields: bool = False,
    persist_result: bool = False,
    persist_renames: bool = False,
    persist_checkbox_rules: bool = False,
    include_created_at: bool = False,
) -> None:
    metadata: Dict[str, Any] = {
        "user_id": entry.get("user_id"),
        "source_pdf": entry.get("source_pdf"),
        "openai_credit_consumed": bool(entry.get("openai_credit_consumed")),
        "openai_credit_pages": entry.get("openai_credit_pages"),
        "openai_credit_mapping_used": bool(entry.get("openai_credit_mapping_used")),
        "page_count": entry.get("page_count"),
        "version": _SESSION_VERSION,
        "last_access_at": now_iso(),
    }
    for key in (
        "detection_status",
        "detection_error",
        "detection_queued_at",
        "detection_started_at",
        "detection_completed_at",
        "detection_task_name",
        "detection_profile",
        "detection_queue",
        "detection_service_url",
        "detection_duration_seconds",
    ):
        if key in entry and entry.get(key) is not None:
            metadata[key] = entry.get(key)

    if include_created_at:
        metadata["created_at"] = now_iso()

    if persist_pdf:
        pdf_bytes = entry.get("pdf_bytes")
        if not pdf_bytes:
            raise ValueError("Session PDF bytes missing")
        pdf_path = entry.get("pdf_path") or upload_session_pdf_bytes(
            pdf_bytes,
            _session_object_path(session_id, "source.pdf"),
        )
        entry["pdf_path"] = pdf_path
        metadata["pdf_path"] = pdf_path
    elif entry.get("pdf_path"):
        metadata["pdf_path"] = entry.get("pdf_path")

    if persist_fields:
        fields_path = upload_session_json(
            entry.get("fields") or [],
            _session_object_path(session_id, "fields.json"),
        )
        entry["fields_path"] = fields_path
        metadata["fields_path"] = fields_path
    elif entry.get("fields_path"):
        metadata["fields_path"] = entry.get("fields_path")

    if persist_result:
        result_path = upload_session_json(
            entry.get("result") or {},
            _session_object_path(session_id, "result.json"),
        )
        entry["result_path"] = result_path
        metadata["result_path"] = result_path
    elif entry.get("result_path"):
        metadata["result_path"] = entry.get("result_path")

    if persist_renames:
        renames_path = upload_session_json(
            entry.get("renames") or {},
            _session_object_path(session_id, "renames.json"),
        )
        entry["renames_path"] = renames_path
        metadata["renames_path"] = renames_path
    elif entry.get("renames_path"):
        metadata["renames_path"] = entry.get("renames_path")

    if persist_checkbox_rules:
        checkbox_path = upload_session_json(
            entry.get("checkboxRules") or [],
            _session_object_path(session_id, "checkbox-rules.json"),
        )
        entry["checkbox_rules_path"] = checkbox_path
        metadata["checkbox_rules_path"] = checkbox_path
    elif entry.get("checkbox_rules_path"):
        metadata["checkbox_rules_path"] = entry.get("checkbox_rules_path")

    expires_at = _expires_at()
    if expires_at:
        metadata["expires_at"] = expires_at

    upsert_session_metadata(session_id, metadata)
    entry["_l2_touch_at"] = _session_now()


def store_session_entry(
    session_id: str,
    entry: SessionEntry,
    *,
    persist_pdf: bool = True,
    persist_fields: bool = True,
    persist_result: bool = True,
    persist_l1: bool = True,
) -> None:
    """Store a new session in L2 and optionally cache it in L1."""
    _persist_session_entry(
        session_id,
        entry,
        persist_pdf=persist_pdf,
        persist_fields=persist_fields,
        persist_result=persist_result,
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
        )
        _require_owner(entry, user)
        if _missing_required_data(
            entry,
            include_pdf_bytes=include_pdf_bytes,
            include_fields=include_fields,
            include_result=include_result,
            include_renames=include_renames,
            include_checkbox_rules=include_checkbox_rules,
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
        )
        _require_owner(entry, user)
        if _missing_required_data(
            entry,
            include_pdf_bytes=include_pdf_bytes,
            include_fields=include_fields,
            include_result=include_result,
            include_renames=include_renames,
            include_checkbox_rules=include_checkbox_rules,
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
