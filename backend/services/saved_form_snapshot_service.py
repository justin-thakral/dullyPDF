"""Validation and storage helpers for saved-form editor snapshots."""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

from backend.firebaseDB.storage_service import (
    download_saved_form_snapshot_json,
    upload_saved_form_snapshot_json,
)
from backend.logging_config import get_logger
from backend.time_utils import now_iso


logger = get_logger(__name__)

SAVED_FORM_EDITOR_SNAPSHOT_VERSION = 2
MAX_SAVED_FORM_EDITOR_SNAPSHOT_BYTES = 1_500_000
SAVED_FORM_EDITOR_SNAPSHOT_METADATA_KEY = "editorSnapshot"
ALLOWED_FIELD_TYPES = {"text", "checkbox", "radio", "signature", "date"}


def _coerce_bool(value: Any, *, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes"}:
            return True
        if lowered in {"false", "0", "no"}:
            return False
    return bool(value)


def _coerce_float(value: Any, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be numeric") from exc
    if result < 0:
        raise ValueError(f"{label} must be non-negative")
    return result


def _coerce_positive_float(value: Any, label: str) -> float:
    result = _coerce_float(value, label)
    if result <= 0:
        raise ValueError(f"{label} must be positive")
    return result


def _normalize_rect(value: Any) -> Dict[str, float]:
    if not isinstance(value, dict):
        raise ValueError("field rect must be an object")
    return {
        "x": _coerce_float(value.get("x"), "field rect x"),
        "y": _coerce_float(value.get("y"), "field rect y"),
        "width": _coerce_positive_float(value.get("width"), "field rect width"),
        "height": _coerce_positive_float(value.get("height"), "field rect height"),
    }


def _normalize_field(value: Any) -> Dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("snapshot fields must contain objects")
    field_id = str(value.get("id") or "").strip()
    field_name = str(value.get("name") or "").strip()
    field_type = str(value.get("type") or "text").strip().lower()
    try:
        page = int(value.get("page"))
    except (TypeError, ValueError) as exc:
        raise ValueError("field page must be an integer") from exc
    if not field_id:
        raise ValueError("field id is required")
    if not field_name:
        raise ValueError("field name is required")
    if field_type not in ALLOWED_FIELD_TYPES:
        raise ValueError(f"field type must be one of {sorted(ALLOWED_FIELD_TYPES)}")
    if page < 1:
        raise ValueError("field page must be at least 1")

    normalized: Dict[str, Any] = {
        "id": field_id,
        "name": field_name,
        "type": field_type,
        "page": page,
        "rect": _normalize_rect(value.get("rect")),
    }

    for key in (
        "groupKey",
        "optionKey",
        "optionLabel",
        "groupLabel",
        "radioGroupId",
        "radioGroupKey",
        "radioGroupLabel",
        "radioOptionKey",
        "radioOptionLabel",
        "radioGroupSource",
    ):
        raw = value.get(key)
        if raw is None:
            continue
        normalized[key] = str(raw)

    for key in ("fieldConfidence", "mappingConfidence", "renameConfidence", "radioOptionOrder"):
        raw = value.get(key)
        if raw is None:
            continue
        normalized[key] = float(raw)

    raw_value = value.get("value")
    if raw_value is None or isinstance(raw_value, (str, int, float, bool)):
        normalized["value"] = raw_value
    else:
        normalized["value"] = str(raw_value)
    return normalized


def _normalize_radio_group_option(value: Any) -> Dict[str, str]:
    if not isinstance(value, dict):
        raise ValueError("radio group options must contain objects")
    field_id = str(value.get("fieldId") or "").strip()
    option_key = str(value.get("optionKey") or "").strip()
    option_label = str(value.get("optionLabel") or "").strip()
    if not field_id:
        raise ValueError("radio group option fieldId is required")
    if not option_key:
        raise ValueError("radio group option optionKey is required")
    if not option_label:
        raise ValueError("radio group option optionLabel is required")
    return {
        "fieldId": field_id,
        "optionKey": option_key,
        "optionLabel": option_label,
    }


def _normalize_radio_groups(value: Any) -> list[Dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("radioGroups must be a list")

    normalized_groups: list[Dict[str, Any]] = []
    for entry in value:
        if not isinstance(entry, dict):
            raise ValueError("radioGroups must contain objects")
        group_id = str(entry.get("id") or "").strip()
        group_key = str(entry.get("key") or "").strip()
        group_label = str(entry.get("label") or "").strip()
        source = str(entry.get("source") or "manual").strip() or "manual"
        if not group_id:
            raise ValueError("radio group id is required")
        if not group_key:
            raise ValueError("radio group key is required")
        if not group_label:
            raise ValueError("radio group label is required")
        raw_options = entry.get("options")
        if not isinstance(raw_options, list) or not raw_options:
            raise ValueError("radio group options must be a non-empty list")
        options = [_normalize_radio_group_option(option) for option in raw_options]
        raw_order = entry.get("optionOrder")
        option_order = [str(item).strip() for item in raw_order] if isinstance(raw_order, list) else []
        if not option_order:
            option_order = [option["optionKey"] for option in options]

        normalized_group: Dict[str, Any] = {
            "id": group_id,
            "key": group_key,
            "label": group_label,
            "source": source,
            "optionOrder": option_order,
            "options": options,
        }
        raw_page = entry.get("page")
        if raw_page is not None:
            try:
                page = int(raw_page)
            except (TypeError, ValueError) as exc:
                raise ValueError("radio group page must be an integer") from exc
            if page < 1:
                raise ValueError("radio group page must be at least 1")
            normalized_group["page"] = page
        normalized_groups.append(normalized_group)
    return normalized_groups


def _normalize_page_sizes(value: Any, page_count: int) -> Dict[str, Dict[str, float]]:
    if not isinstance(value, dict):
        raise ValueError("pageSizes must be an object")
    normalized: Dict[str, Dict[str, float]] = {}
    for page_number in range(1, page_count + 1):
        raw_page = value.get(str(page_number), value.get(page_number))
        if not isinstance(raw_page, dict):
            raise ValueError(f"pageSizes missing entry for page {page_number}")
        normalized[str(page_number)] = {
            "width": _coerce_positive_float(raw_page.get("width"), f"pageSizes[{page_number}].width"),
            "height": _coerce_positive_float(raw_page.get("height"), f"pageSizes[{page_number}].height"),
        }
    return normalized


def normalize_saved_form_editor_snapshot_payload(payload: Any) -> Dict[str, Any]:
    """Validate and normalize a saved-form editor snapshot payload."""
    if not isinstance(payload, dict):
        raise ValueError("editor snapshot must be an object")
    try:
        page_count = int(payload.get("pageCount"))
    except (TypeError, ValueError) as exc:
        raise ValueError("pageCount must be an integer") from exc
    if page_count < 1:
        raise ValueError("pageCount must be at least 1")

    version = payload.get("version", SAVED_FORM_EDITOR_SNAPSHOT_VERSION)
    try:
        version_value = int(version)
    except (TypeError, ValueError) as exc:
        raise ValueError("version must be an integer") from exc
    if version_value not in {1, SAVED_FORM_EDITOR_SNAPSHOT_VERSION}:
        raise ValueError("editor snapshot version is not supported")

    raw_fields = payload.get("fields")
    if not isinstance(raw_fields, list):
        raise ValueError("fields must be a list")

    normalized = {
        "version": SAVED_FORM_EDITOR_SNAPSHOT_VERSION,
        "pageCount": page_count,
        "pageSizes": _normalize_page_sizes(payload.get("pageSizes"), page_count),
        "fields": [_normalize_field(field) for field in raw_fields],
        "radioGroups": _normalize_radio_groups(payload.get("radioGroups")),
        "hasRenamedFields": _coerce_bool(payload.get("hasRenamedFields"), default=False),
        "hasMappedSchema": _coerce_bool(payload.get("hasMappedSchema"), default=False),
    }
    return normalized


def parse_saved_form_editor_snapshot_form_value(raw_value: Optional[str]) -> Optional[Dict[str, Any]]:
    """Parse a form-data snapshot payload into a normalized dict."""
    if raw_value is None:
        return None
    raw_text = str(raw_value).strip()
    if not raw_text:
        return None
    if len(raw_text.encode("utf-8")) > MAX_SAVED_FORM_EDITOR_SNAPSHOT_BYTES:
        raise ValueError("editor snapshot payload is too large")
    return normalize_saved_form_editor_snapshot_payload(json.loads(raw_text))


def build_saved_form_editor_snapshot_storage_path(
    user_id: str,
    form_id: str,
    *,
    timestamp_ms: int,
) -> str:
    """Return the storage path used for a saved-form editor snapshot JSON blob."""
    return f"users/{user_id}/saved-form-snapshots/{timestamp_ms}-{form_id}.json"


def build_saved_form_editor_snapshot_manifest(
    bucket_path: str,
    snapshot: Dict[str, Any],
) -> Dict[str, Any]:
    """Build the small metadata manifest stored on the template record."""
    return {
        "version": SAVED_FORM_EDITOR_SNAPSHOT_VERSION,
        "path": bucket_path,
        "fieldCount": len(snapshot.get("fields") or []),
        "pageCount": snapshot.get("pageCount"),
        "updatedAt": now_iso(),
    }


def upload_saved_form_editor_snapshot(
    *,
    user_id: str,
    form_id: str,
    timestamp_ms: int,
    snapshot: Dict[str, Any],
) -> tuple[str, Dict[str, Any]]:
    """Persist a saved-form editor snapshot JSON blob and return its manifest."""
    destination_path = build_saved_form_editor_snapshot_storage_path(
        user_id,
        form_id,
        timestamp_ms=timestamp_ms,
    )
    bucket_path = upload_saved_form_snapshot_json(snapshot, destination_path)
    return bucket_path, build_saved_form_editor_snapshot_manifest(bucket_path, snapshot)


def get_saved_form_editor_snapshot_path(metadata: Optional[Dict[str, Any]]) -> Optional[str]:
    """Extract the snapshot storage path from template metadata when present."""
    if not isinstance(metadata, dict):
        return None
    manifest = metadata.get(SAVED_FORM_EDITOR_SNAPSHOT_METADATA_KEY)
    if not isinstance(manifest, dict):
        return None
    raw_path = manifest.get("path")
    if isinstance(raw_path, str) and raw_path.strip():
        return raw_path.strip()
    return None


def load_saved_form_editor_snapshot(metadata: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Load and validate a stored editor snapshot referenced by template metadata."""
    snapshot_path = get_saved_form_editor_snapshot_path(metadata)
    if not snapshot_path:
        return None
    try:
        raw_snapshot = download_saved_form_snapshot_json(snapshot_path)
        return normalize_saved_form_editor_snapshot_payload(raw_snapshot)
    except Exception as exc:
        logger.warning("Failed to load saved-form editor snapshot path=%s error=%s", snapshot_path, exc)
        return None
