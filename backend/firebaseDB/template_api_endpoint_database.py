"""Firestore-backed published template API endpoint metadata operations.

The template API feature needs two persistence layers beyond the endpoint record
itself:

1. Endpoint-local counters and failure state so owner screens can show current
   health without scanning large audit logs.
2. Lightweight append-only audit events plus month-bucket usage counters so the
   public runtime can enforce plan quotas and owners can review rotate/revoke
   history.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from backend.logging_config import get_logger
from ..time_utils import now_iso
from .firestore_query_utils import where_equals
from .firebase_service import get_firestore_client


logger = get_logger(__name__)

TEMPLATE_API_ENDPOINTS_COLLECTION = "template_api_endpoints"
TEMPLATE_API_ENDPOINT_EVENTS_COLLECTION = "template_api_endpoint_events"
TEMPLATE_API_USAGE_COUNTERS_COLLECTION = "template_api_usage_counters"


@dataclass(frozen=True)
class TemplateApiEndpointRecord:
    id: str
    user_id: str
    template_id: str
    template_name: Optional[str]
    status: str
    snapshot_version: int
    key_prefix: Optional[str]
    secret_hash: Optional[str]
    snapshot: Optional[Dict[str, Any]]
    created_at: Optional[str]
    updated_at: Optional[str]
    published_at: Optional[str]
    last_used_at: Optional[str]
    usage_count: int
    current_usage_month: Optional[str]
    current_month_usage_count: int
    auth_failure_count: int
    validation_failure_count: int
    suspicious_failure_count: int
    last_failure_at: Optional[str]
    last_failure_reason: Optional[str]
    audit_event_count: int


@dataclass(frozen=True)
class TemplateApiEndpointAuditEventRecord:
    id: str
    endpoint_id: str
    user_id: str
    template_id: str
    event_type: str
    outcome: str
    created_at: Optional[str]
    snapshot_version: Optional[int]
    metadata: Dict[str, Any]


@dataclass(frozen=True)
class TemplateApiMonthlyUsageRecord:
    id: str
    user_id: str
    month_key: str
    request_count: int
    created_at: Optional[str]
    updated_at: Optional[str]


def _coerce_optional_dict(value: Any) -> Optional[Dict[str, Any]]:
    return dict(value) if isinstance(value, dict) else None


def _current_month_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def _coerce_month_key(value: Any) -> Optional[str]:
    normalized = str(value or "").strip()
    if len(normalized) != 7:
        return None
    try:
        datetime.strptime(normalized, "%Y-%m")
    except ValueError:
        return None
    return normalized


def _build_usage_counter_id(user_id: str, month_key: str) -> str:
    return f"{str(user_id or '').strip()}__{month_key}"


def _serialize_template_api_endpoint(doc) -> TemplateApiEndpointRecord:
    data = doc.to_dict() or {}
    return TemplateApiEndpointRecord(
        id=doc.id,
        user_id=str(data.get("user_id") or "").strip(),
        template_id=str(data.get("template_id") or "").strip(),
        template_name=(str(data.get("template_name") or "").strip() or None),
        status=str(data.get("status") or "revoked").strip() or "revoked",
        snapshot_version=max(1, int(data.get("snapshot_version") or 1)),
        key_prefix=(str(data.get("key_prefix") or "").strip() or None),
        secret_hash=(str(data.get("secret_hash") or "").strip() or None),
        snapshot=_coerce_optional_dict(data.get("snapshot")),
        created_at=data.get("created_at"),
        updated_at=data.get("updated_at"),
        published_at=data.get("published_at"),
        last_used_at=data.get("last_used_at"),
        usage_count=max(0, int(data.get("usage_count") or 0)),
        current_usage_month=_coerce_month_key(data.get("current_usage_month")),
        current_month_usage_count=max(0, int(data.get("current_month_usage_count") or 0)),
        auth_failure_count=max(0, int(data.get("auth_failure_count") or 0)),
        validation_failure_count=max(0, int(data.get("validation_failure_count") or 0)),
        suspicious_failure_count=max(0, int(data.get("suspicious_failure_count") or 0)),
        last_failure_at=data.get("last_failure_at"),
        last_failure_reason=(str(data.get("last_failure_reason") or "").strip() or None),
        audit_event_count=max(0, int(data.get("audit_event_count") or 0)),
    )


def _serialize_template_api_event(doc) -> TemplateApiEndpointAuditEventRecord:
    data = doc.to_dict() or {}
    return TemplateApiEndpointAuditEventRecord(
        id=doc.id,
        endpoint_id=str(data.get("endpoint_id") or "").strip(),
        user_id=str(data.get("user_id") or "").strip(),
        template_id=str(data.get("template_id") or "").strip(),
        event_type=str(data.get("event_type") or "").strip(),
        outcome=str(data.get("outcome") or "success").strip() or "success",
        created_at=data.get("created_at"),
        snapshot_version=(int(data.get("snapshot_version")) if data.get("snapshot_version") is not None else None),
        metadata=dict(data.get("metadata") or {}) if isinstance(data.get("metadata"), dict) else {},
    )


def _serialize_monthly_usage(doc) -> TemplateApiMonthlyUsageRecord:
    data = doc.to_dict() or {}
    month_key = _coerce_month_key(data.get("month_key")) or _current_month_key()
    return TemplateApiMonthlyUsageRecord(
        id=doc.id,
        user_id=str(data.get("user_id") or "").strip(),
        month_key=month_key,
        request_count=max(0, int(data.get("request_count") or 0)),
        created_at=data.get("created_at"),
        updated_at=data.get("updated_at"),
    )


def _get_template_api_endpoint_snapshot(endpoint_id: str):
    normalized_endpoint_id = str(endpoint_id or "").strip()
    if not normalized_endpoint_id:
        return None
    client = get_firestore_client()
    doc_ref = client.collection(TEMPLATE_API_ENDPOINTS_COLLECTION).document(normalized_endpoint_id)
    snapshot = doc_ref.get()
    if not snapshot.exists:
        return None
    return snapshot


def _update_template_api_endpoint_document(
    endpoint_id: str,
    payload: Dict[str, Any],
) -> Optional[TemplateApiEndpointRecord]:
    snapshot = _get_template_api_endpoint_snapshot(endpoint_id)
    if snapshot is None:
        return None
    client = get_firestore_client()
    doc_ref = client.collection(TEMPLATE_API_ENDPOINTS_COLLECTION).document(endpoint_id)
    doc_ref.set(payload, merge=True)
    return _serialize_template_api_endpoint(doc_ref.get())


def list_template_api_endpoints(
    user_id: str,
    *,
    template_id: Optional[str] = None,
) -> List[TemplateApiEndpointRecord]:
    if not user_id:
        return []
    client = get_firestore_client()
    snapshot = where_equals(
        client.collection(TEMPLATE_API_ENDPOINTS_COLLECTION),
        "user_id",
        user_id,
    ).get()
    records = [_serialize_template_api_endpoint(doc) for doc in snapshot]
    if template_id:
        normalized_template_id = str(template_id or "").strip()
        records = [record for record in records if record.template_id == normalized_template_id]
    records.sort(key=lambda record: record.updated_at or record.created_at or "", reverse=True)
    return records


def count_active_template_api_endpoints(user_id: str) -> int:
    return sum(1 for record in list_template_api_endpoints(user_id) if record.status == "active")


def get_template_api_endpoint(endpoint_id: str, user_id: str) -> Optional[TemplateApiEndpointRecord]:
    if not endpoint_id or not user_id:
        return None
    snapshot = _get_template_api_endpoint_snapshot(endpoint_id)
    if snapshot is None:
        return None
    record = _serialize_template_api_endpoint(snapshot)
    if record.user_id != user_id:
        logger.debug("Template API endpoint ownership mismatch blocked: %s", endpoint_id)
        return None
    return record


def get_template_api_endpoint_public(endpoint_id: str) -> Optional[TemplateApiEndpointRecord]:
    snapshot = _get_template_api_endpoint_snapshot(endpoint_id)
    if snapshot is None:
        return None
    return _serialize_template_api_endpoint(snapshot)


def get_template_api_endpoint_for_secret(
    endpoint_id: str,
    *,
    key_prefix: Optional[str] = None,
) -> Optional[TemplateApiEndpointRecord]:
    record = get_template_api_endpoint_public(endpoint_id)
    if record is None:
        return None
    normalized_prefix = str(key_prefix or "").strip()
    if normalized_prefix and record.key_prefix and record.key_prefix != normalized_prefix:
        logger.debug("Template API endpoint key prefix mismatch blocked: %s", endpoint_id)
        return None
    return record


def get_active_template_api_endpoint_for_template(
    template_id: str,
    user_id: str,
) -> Optional[TemplateApiEndpointRecord]:
    normalized_template_id = str(template_id or "").strip()
    normalized_user_id = str(user_id or "").strip()
    if not normalized_template_id or not normalized_user_id:
        return None
    for record in list_template_api_endpoints(normalized_user_id, template_id=normalized_template_id):
        if record.status == "active":
            return record
    return None


def create_template_api_endpoint(
    *,
    user_id: str,
    template_id: str,
    template_name: Optional[str],
    key_prefix: str,
    secret_hash: str,
    snapshot: Dict[str, Any],
) -> TemplateApiEndpointRecord:
    if not user_id:
        raise ValueError("user_id is required")
    if not template_id:
        raise ValueError("template_id is required")
    if not key_prefix:
        raise ValueError("key_prefix is required")
    if not secret_hash:
        raise ValueError("secret_hash is required")
    if not isinstance(snapshot, dict) or not snapshot:
        raise ValueError("snapshot is required")
    client = get_firestore_client()
    doc_ref = client.collection(TEMPLATE_API_ENDPOINTS_COLLECTION).document()
    timestamp = now_iso()
    payload = {
        "user_id": user_id,
        "template_id": template_id,
        "template_name": template_name or None,
        "status": "active",
        "snapshot_version": 1,
        "key_prefix": key_prefix,
        "secret_hash": secret_hash,
        "snapshot": snapshot,
        "created_at": timestamp,
        "updated_at": timestamp,
        "published_at": timestamp,
        "last_used_at": None,
        "usage_count": 0,
        "current_usage_month": None,
        "current_month_usage_count": 0,
        "auth_failure_count": 0,
        "validation_failure_count": 0,
        "suspicious_failure_count": 0,
        "last_failure_at": None,
        "last_failure_reason": None,
        "audit_event_count": 0,
    }
    doc_ref.set(payload)
    return _serialize_template_api_endpoint(doc_ref.get())


def update_template_api_endpoint(
    endpoint_id: str,
    user_id: str,
    *,
    template_name: Optional[str] = None,
    status: Optional[str] = None,
    snapshot_version: Optional[int] = None,
    key_prefix: Optional[str] = None,
    secret_hash: Optional[str] = None,
    snapshot: Optional[Dict[str, Any]] = None,
    published_at: Optional[str] = None,
    last_used_at: Optional[str] = None,
    usage_count: Optional[int] = None,
    current_usage_month: Optional[str] = None,
    current_month_usage_count: Optional[int] = None,
    auth_failure_count: Optional[int] = None,
    validation_failure_count: Optional[int] = None,
    suspicious_failure_count: Optional[int] = None,
    last_failure_at: Optional[str] = None,
    last_failure_reason: Optional[str] = None,
    audit_event_count: Optional[int] = None,
) -> Optional[TemplateApiEndpointRecord]:
    existing = get_template_api_endpoint(endpoint_id, user_id)
    if not existing:
        return None
    payload: Dict[str, Any] = {"updated_at": now_iso()}
    if template_name is not None:
        payload["template_name"] = template_name or None
    if status is not None:
        payload["status"] = str(status or "").strip() or existing.status
    if snapshot_version is not None:
        payload["snapshot_version"] = max(1, int(snapshot_version))
    if key_prefix is not None:
        payload["key_prefix"] = key_prefix
    if secret_hash is not None:
        payload["secret_hash"] = secret_hash
    if snapshot is not None:
        payload["snapshot"] = snapshot
    if published_at is not None:
        payload["published_at"] = published_at
    if last_used_at is not None:
        payload["last_used_at"] = last_used_at
    if usage_count is not None:
        payload["usage_count"] = max(0, int(usage_count))
    if current_usage_month is not None:
        payload["current_usage_month"] = _coerce_month_key(current_usage_month)
    if current_month_usage_count is not None:
        payload["current_month_usage_count"] = max(0, int(current_month_usage_count))
    if auth_failure_count is not None:
        payload["auth_failure_count"] = max(0, int(auth_failure_count))
    if validation_failure_count is not None:
        payload["validation_failure_count"] = max(0, int(validation_failure_count))
    if suspicious_failure_count is not None:
        payload["suspicious_failure_count"] = max(0, int(suspicious_failure_count))
    if last_failure_at is not None:
        payload["last_failure_at"] = last_failure_at
    if last_failure_reason is not None:
        payload["last_failure_reason"] = (str(last_failure_reason or "").strip() or None)
    if audit_event_count is not None:
        payload["audit_event_count"] = max(0, int(audit_event_count))
    return _update_template_api_endpoint_document(endpoint_id, payload)


def create_template_api_endpoint_event(
    *,
    endpoint_id: str,
    user_id: str,
    template_id: str,
    event_type: str,
    outcome: str = "success",
    snapshot_version: Optional[int] = None,
    metadata: Optional[Dict[str, Any]] = None,
    created_at: Optional[str] = None,
) -> TemplateApiEndpointAuditEventRecord:
    normalized_endpoint_id = str(endpoint_id or "").strip()
    normalized_user_id = str(user_id or "").strip()
    normalized_template_id = str(template_id or "").strip()
    normalized_event_type = str(event_type or "").strip()
    if not normalized_endpoint_id:
        raise ValueError("endpoint_id is required")
    if not normalized_user_id:
        raise ValueError("user_id is required")
    if not normalized_template_id:
        raise ValueError("template_id is required")
    if not normalized_event_type:
        raise ValueError("event_type is required")
    client = get_firestore_client()
    doc_ref = client.collection(TEMPLATE_API_ENDPOINT_EVENTS_COLLECTION).document()
    timestamp = created_at or now_iso()
    doc_ref.set(
        {
            "endpoint_id": normalized_endpoint_id,
            "user_id": normalized_user_id,
            "template_id": normalized_template_id,
            "event_type": normalized_event_type,
            "outcome": str(outcome or "success").strip() or "success",
            "snapshot_version": int(snapshot_version) if snapshot_version is not None else None,
            "metadata": dict(metadata or {}),
            "created_at": timestamp,
        }
    )
    existing = get_template_api_endpoint_public(normalized_endpoint_id)
    if existing is not None:
        _update_template_api_endpoint_document(
            normalized_endpoint_id,
            {
                "updated_at": timestamp,
                "audit_event_count": existing.audit_event_count + 1,
            },
        )
    return _serialize_template_api_event(doc_ref.get())


def list_template_api_endpoint_events(
    endpoint_id: str,
    *,
    user_id: Optional[str] = None,
    limit: int = 20,
) -> List[TemplateApiEndpointAuditEventRecord]:
    normalized_endpoint_id = str(endpoint_id or "").strip()
    if not normalized_endpoint_id:
        return []
    client = get_firestore_client()
    snapshot = where_equals(
        client.collection(TEMPLATE_API_ENDPOINT_EVENTS_COLLECTION),
        "endpoint_id",
        normalized_endpoint_id,
    ).get()
    records = [_serialize_template_api_event(doc) for doc in snapshot]
    if user_id:
        normalized_user_id = str(user_id or "").strip()
        records = [record for record in records if record.user_id == normalized_user_id]
    records.sort(key=lambda record: record.created_at or "", reverse=True)
    return records[: max(1, int(limit or 20))]


def get_template_api_monthly_usage(
    user_id: str,
    *,
    month_key: Optional[str] = None,
) -> Optional[TemplateApiMonthlyUsageRecord]:
    normalized_user_id = str(user_id or "").strip()
    normalized_month_key = _coerce_month_key(month_key) or _current_month_key()
    if not normalized_user_id:
        return None
    client = get_firestore_client()
    snapshot = client.collection(TEMPLATE_API_USAGE_COUNTERS_COLLECTION).document(
        _build_usage_counter_id(normalized_user_id, normalized_month_key)
    ).get()
    if not snapshot.exists:
        return None
    return _serialize_monthly_usage(snapshot)


def increment_template_api_monthly_usage(
    user_id: str,
    *,
    month_key: Optional[str] = None,
    amount: int = 1,
) -> Optional[TemplateApiMonthlyUsageRecord]:
    normalized_user_id = str(user_id or "").strip()
    normalized_month_key = _coerce_month_key(month_key) or _current_month_key()
    increment_by = max(1, int(amount or 1))
    if not normalized_user_id:
        return None
    client = get_firestore_client()
    doc_ref = client.collection(TEMPLATE_API_USAGE_COUNTERS_COLLECTION).document(
        _build_usage_counter_id(normalized_user_id, normalized_month_key)
    )
    snapshot = doc_ref.get()
    existing = _serialize_monthly_usage(snapshot) if snapshot.exists else None
    timestamp = now_iso()
    doc_ref.set(
        {
            "user_id": normalized_user_id,
            "month_key": normalized_month_key,
            "request_count": (existing.request_count if existing else 0) + increment_by,
            "created_at": existing.created_at if existing else timestamp,
            "updated_at": timestamp,
        }
    )
    return _serialize_monthly_usage(doc_ref.get())


def record_template_api_endpoint_use(endpoint_id: str) -> Optional[TemplateApiEndpointRecord]:
    existing = get_template_api_endpoint_public(endpoint_id)
    if existing is None:
        return None
    timestamp = now_iso()
    current_month = _current_month_key()
    next_month_usage = (
        existing.current_month_usage_count + 1
        if existing.current_usage_month == current_month
        else 1
    )
    increment_template_api_monthly_usage(existing.user_id, month_key=current_month)
    return _update_template_api_endpoint_document(
        endpoint_id,
        {
            "updated_at": timestamp,
            "last_used_at": timestamp,
            "usage_count": existing.usage_count + 1,
            "current_usage_month": current_month,
            "current_month_usage_count": next_month_usage,
        },
    )


def record_template_api_endpoint_failure(
    endpoint_id: str,
    *,
    auth_failure: bool = False,
    validation_failure: bool = False,
    suspicious: bool = False,
    reason: Optional[str] = None,
) -> Optional[TemplateApiEndpointRecord]:
    existing = get_template_api_endpoint_public(endpoint_id)
    if existing is None:
        return None
    return _update_template_api_endpoint_document(
        endpoint_id,
        {
            "updated_at": now_iso(),
            "auth_failure_count": existing.auth_failure_count + (1 if auth_failure else 0),
            "validation_failure_count": existing.validation_failure_count + (1 if validation_failure else 0),
            "suspicious_failure_count": existing.suspicious_failure_count + (1 if suspicious else 0),
            "last_failure_at": now_iso(),
            "last_failure_reason": (str(reason or "").strip() or None),
        },
    )
