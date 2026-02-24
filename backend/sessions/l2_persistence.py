"""L2 Firestore/GCS session persistence."""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from fastapi import HTTPException

from backend.logging_config import get_logger
from .l1_cache import (
    SessionEntry,
    _SESSION_VERSION,
    _SESSION_TTL_SECONDS,
    _SESSION_L2_TOUCH_SECONDS,
    _session_now,
)
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
    include_checkbox_hints: bool,
    include_text_transform_rules: bool,
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
    if include_checkbox_hints and "checkboxHints" not in entry and entry.get("checkbox_hints_path"):
        return True
    if include_text_transform_rules and "textTransformRules" not in entry and entry.get("text_transform_rules_path"):
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
    include_checkbox_hints: bool,
    include_text_transform_rules: bool,
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
        "checkbox_hints_path": metadata.get("checkbox_hints_path"),
        "text_transform_rules_path": metadata.get("text_transform_rules_path"),
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
    if include_checkbox_hints and entry.get("checkbox_hints_path"):
        entry["checkboxHints"] = download_session_json(entry["checkbox_hints_path"]) or []
    if include_text_transform_rules and entry.get("text_transform_rules_path"):
        entry["textTransformRules"] = download_session_json(entry["text_transform_rules_path"]) or []

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
    include_checkbox_hints: bool,
    include_text_transform_rules: bool,
) -> None:
    if not _missing_required_data(
        entry,
        include_pdf_bytes=include_pdf_bytes,
        include_fields=include_fields,
        include_result=include_result,
        include_renames=include_renames,
        include_checkbox_rules=include_checkbox_rules,
        include_checkbox_hints=include_checkbox_hints,
        include_text_transform_rules=include_text_transform_rules,
    ):
        return
    hydrated = _hydrate_from_l2(
        session_id,
        include_pdf_bytes=include_pdf_bytes,
        include_fields=include_fields,
        include_result=include_result,
        include_renames=include_renames,
        include_checkbox_rules=include_checkbox_rules,
        include_checkbox_hints=include_checkbox_hints,
        include_text_transform_rules=include_text_transform_rules,
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
    persist_checkbox_hints: bool = False,
    persist_text_transform_rules: bool = False,
    include_created_at: bool = False,
) -> None:
    metadata: Dict[str, Any] = {
        "user_id": entry.get("user_id"),
        "source_pdf": entry.get("source_pdf"),
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

    if persist_checkbox_hints:
        checkbox_hints_path = upload_session_json(
            entry.get("checkboxHints") or [],
            _session_object_path(session_id, "checkbox-hints.json"),
        )
        entry["checkbox_hints_path"] = checkbox_hints_path
        metadata["checkbox_hints_path"] = checkbox_hints_path
    elif entry.get("checkbox_hints_path"):
        metadata["checkbox_hints_path"] = entry.get("checkbox_hints_path")

    if persist_text_transform_rules:
        text_transform_rules_path = upload_session_json(
            entry.get("textTransformRules") or [],
            _session_object_path(session_id, "text-transform-rules.json"),
        )
        entry["text_transform_rules_path"] = text_transform_rules_path
        metadata["text_transform_rules_path"] = text_transform_rules_path
    elif entry.get("text_transform_rules_path"):
        metadata["text_transform_rules_path"] = entry.get("text_transform_rules_path")

    expires_at = _expires_at()
    if expires_at:
        metadata["expires_at"] = expires_at

    upsert_session_metadata(session_id, metadata)
    entry["_l2_touch_at"] = _session_now()
