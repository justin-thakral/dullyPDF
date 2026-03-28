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
from typing import Any, Callable, Dict, List, Optional, TypeVar

from firebase_admin import firestore as firebase_firestore
from google.api_core import exceptions as google_api_exceptions

from backend.logging_config import get_logger
from ..time_utils import now_iso
from .firestore_query_utils import where_equals
from .firebase_service import get_firestore_client


logger = get_logger(__name__)

TEMPLATE_API_ENDPOINTS_COLLECTION = "template_api_endpoints"
TEMPLATE_API_ENDPOINT_EVENTS_COLLECTION = "template_api_endpoint_events"
TEMPLATE_API_USAGE_COUNTERS_COLLECTION = "template_api_usage_counters"
TEMPLATE_API_ENDPOINT_GUARDS_COLLECTION = "template_api_endpoint_guards"
_TEMPLATE_API_ENDPOINT_METADATA_FIELD_PATHS = [
    "user_id",
    "template_id",
    "template_name",
    "status",
    "snapshot_version",
    "key_prefix",
    "secret_hash",
    "created_at",
    "updated_at",
    "published_at",
    "last_used_at",
    "usage_count",
    "current_usage_month",
    "current_month_usage_count",
    "auth_failure_count",
    "validation_failure_count",
    "runtime_failure_count",
    "suspicious_failure_count",
    "last_failure_at",
    "last_failure_reason",
    "audit_event_count",
]

_T = TypeVar("_T")


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
    runtime_failure_count: int
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


class TemplateApiActiveEndpointLimitError(RuntimeError):
    """Raised when a publish request would exceed the active-endpoint cap."""


class TemplateApiEndpointStatusError(RuntimeError):
    """Raised when an endpoint lifecycle action is invalid for the current status."""


class TemplateApiMonthlyLimitExceededError(RuntimeError):
    """Raised when a successful fill would exceed the owner's monthly quota."""


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
        runtime_failure_count=max(0, int(data.get("runtime_failure_count") or 0)),
        suspicious_failure_count=max(0, int(data.get("suspicious_failure_count") or 0)),
        last_failure_at=data.get("last_failure_at"),
        last_failure_reason=(str(data.get("last_failure_reason") or "").strip() or None),
        audit_event_count=max(0, int(data.get("audit_event_count") or 0)),
    )


def _serialize_template_api_endpoint_data(
    endpoint_id: str,
    data: Dict[str, Any],
) -> TemplateApiEndpointRecord:
    class _InlineEndpointSnapshot:
        def __init__(self, doc_id: str, payload: Dict[str, Any]):
            self.id = doc_id
            self._payload = dict(payload)

        def to_dict(self) -> Dict[str, Any]:
            return dict(self._payload)

    return _serialize_template_api_endpoint(_InlineEndpointSnapshot(endpoint_id, data))


def _endpoint_record_to_document(record: TemplateApiEndpointRecord) -> Dict[str, Any]:
    return {
        "user_id": record.user_id,
        "template_id": record.template_id,
        "template_name": record.template_name,
        "status": record.status,
        "snapshot_version": record.snapshot_version,
        "key_prefix": record.key_prefix,
        "secret_hash": record.secret_hash,
        "snapshot": dict(record.snapshot) if isinstance(record.snapshot, dict) else None,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
        "published_at": record.published_at,
        "last_used_at": record.last_used_at,
        "usage_count": record.usage_count,
        "current_usage_month": record.current_usage_month,
        "current_month_usage_count": record.current_month_usage_count,
        "auth_failure_count": record.auth_failure_count,
        "validation_failure_count": record.validation_failure_count,
        "runtime_failure_count": record.runtime_failure_count,
        "suspicious_failure_count": record.suspicious_failure_count,
        "last_failure_at": record.last_failure_at,
        "last_failure_reason": record.last_failure_reason,
        "audit_event_count": record.audit_event_count,
    }


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


def _sort_template_api_endpoint_events_desc(
    records: List[TemplateApiEndpointAuditEventRecord],
) -> List[TemplateApiEndpointAuditEventRecord]:
    return sorted(
        records,
        key=lambda record: (str(record.created_at or ""), str(record.id or "")),
        reverse=True,
    )


def _get_template_api_endpoint_snapshot(
    endpoint_id: str,
    *,
    field_paths: Optional[List[str]] = None,
):
    normalized_endpoint_id = str(endpoint_id or "").strip()
    if not normalized_endpoint_id:
        return None
    client = get_firestore_client()
    doc_ref = client.collection(TEMPLATE_API_ENDPOINTS_COLLECTION).document(normalized_endpoint_id)
    snapshot = doc_ref.get(field_paths=field_paths)
    if not snapshot.exists:
        return None
    return snapshot


def _set_document_payload(
    doc_ref,
    payload: Dict[str, Any],
    *,
    transaction: Optional[firebase_firestore.Transaction] = None,
    merge: bool = False,
) -> None:
    if transaction is None:
        doc_ref.set(payload, merge=merge)
        return
    transaction.set(doc_ref, payload, merge=merge)


def _run_document_transaction(
    doc_ref,
    operation: Callable[[Optional[firebase_firestore.Transaction], Any], _T],
) -> _T:
    """Run a transaction when supported, with a direct fallback for test fakes."""

    client = get_firestore_client()
    transaction = client.transaction()
    if not isinstance(transaction, firebase_firestore.Transaction):
        snapshot = doc_ref.get()
        return operation(None, snapshot)

    @firebase_firestore.transactional
    def _wrapped(txn: firebase_firestore.Transaction) -> _T:
        snapshot = doc_ref.get(transaction=txn)
        return operation(txn, snapshot)

    return _wrapped(transaction)


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


def _get_query_snapshots(query: Any, *, transaction: Optional[firebase_firestore.Transaction] = None):
    if transaction is None:
        return query.get()
    try:
        return query.get(transaction=transaction)
    except TypeError:
        pass
    try:
        return list(transaction.get(query))
    except AttributeError:
        return query.get()


def _endpoint_recency_key(record: TemplateApiEndpointRecord) -> tuple[str, str, str]:
    """Prefer the most recently updated endpoint when healing duplicate active rows."""
    return (
        str(record.updated_at or record.created_at or ""),
        str(record.created_at or ""),
        record.id,
    )


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


def publish_or_republish_template_api_endpoint(
    *,
    user_id: str,
    template_id: str,
    template_name: Optional[str],
    snapshot: Dict[str, Any],
    active_limit: int,
    key_prefix: str,
    secret_hash: str,
) -> tuple[TemplateApiEndpointRecord, bool]:
    """Serialize create/republish for one user to avoid active-endpoint races.

    Firestore queries alone are not enough to prevent concurrent publish calls
    from creating duplicate active endpoints or temporarily exceeding the plan
    cap. Every publish/republish transaction therefore reads and updates a
    per-user guard document so concurrent owner operations for the same account
    conflict and retry against fresh state.
    """
    normalized_user_id = str(user_id or "").strip()
    normalized_template_id = str(template_id or "").strip()
    if not normalized_user_id:
        raise ValueError("user_id is required")
    if not normalized_template_id:
        raise ValueError("template_id is required")
    if active_limit <= 0:
        raise TemplateApiActiveEndpointLimitError("API Fill is unavailable on the current plan.")
    if not key_prefix:
        raise ValueError("key_prefix is required")
    if not secret_hash:
        raise ValueError("secret_hash is required")
    if not isinstance(snapshot, dict) or not snapshot:
        raise ValueError("snapshot is required")

    client = get_firestore_client()
    endpoints_collection = client.collection(TEMPLATE_API_ENDPOINTS_COLLECTION)
    guard_ref = client.collection(TEMPLATE_API_ENDPOINT_GUARDS_COLLECTION).document(normalized_user_id)
    created_doc_ref = endpoints_collection.document()

    def _publish(
        transaction: Optional[firebase_firestore.Transaction],
        _guard_snapshot,
    ) -> Dict[str, Any]:
        timestamp = now_iso()
        query = where_equals(endpoints_collection, "user_id", normalized_user_id)
        docs = _get_query_snapshots(query, transaction=transaction)
        records = [_serialize_template_api_endpoint(doc) for doc in docs]
        active_records = [record for record in records if record.status == "active"]
        template_active_records = [
            record for record in active_records if record.template_id == normalized_template_id
        ]
        existing_active = (
            max(template_active_records, key=_endpoint_recency_key)
            if template_active_records
            else None
        )

        if existing_active is not None:
            endpoint_ref = endpoints_collection.document(existing_active.id)
            updated_document = _endpoint_record_to_document(existing_active)
            updated_document.update(
                {
                    "template_name": template_name or None,
                    "snapshot": snapshot,
                    "snapshot_version": existing_active.snapshot_version + 1,
                    "published_at": timestamp,
                    "status": "active",
                    "updated_at": timestamp,
                }
            )
            _set_document_payload(
                endpoint_ref,
                updated_document,
                transaction=transaction,
            )
            for duplicate in template_active_records:
                if duplicate.id == existing_active.id:
                    continue
                duplicate_ref = endpoints_collection.document(duplicate.id)
                _set_document_payload(
                    duplicate_ref,
                    {
                        "status": "revoked",
                        "secret_hash": "",
                        "key_prefix": "",
                        "updated_at": timestamp,
                    },
                    transaction=transaction,
                    merge=True,
                )
            _set_document_payload(
                guard_ref,
                {"updated_at": timestamp},
                transaction=transaction,
                merge=True,
            )
            return {
                "record": _serialize_template_api_endpoint_data(existing_active.id, updated_document),
                "created": False,
            }

        if len(active_records) >= active_limit:
            raise TemplateApiActiveEndpointLimitError(
                f"Your plan allows up to {active_limit} active API Fill endpoints."
            )

        created_document = {
            "user_id": normalized_user_id,
            "template_id": normalized_template_id,
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
            "runtime_failure_count": 0,
            "suspicious_failure_count": 0,
            "last_failure_at": None,
            "last_failure_reason": None,
            "audit_event_count": 0,
        }
        _set_document_payload(
            created_doc_ref,
            created_document,
            transaction=transaction,
        )
        _set_document_payload(
            guard_ref,
            {"updated_at": timestamp},
            transaction=transaction,
            merge=True,
        )
        return {
            "record": _serialize_template_api_endpoint_data(created_doc_ref.id, created_document),
            "created": True,
        }

    publish_result = _run_document_transaction(guard_ref, _publish)
    return publish_result["record"], bool(publish_result["created"])


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


def get_template_api_endpoint_public_metadata(endpoint_id: str) -> Optional[TemplateApiEndpointRecord]:
    snapshot = _get_template_api_endpoint_snapshot(
        endpoint_id,
        field_paths=_TEMPLATE_API_ENDPOINT_METADATA_FIELD_PATHS,
    )
    if snapshot is None:
        return None
    return _serialize_template_api_endpoint(snapshot)


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


def revoke_template_api_endpoint_atomic(
    endpoint_id: str,
    user_id: str,
) -> Optional[TemplateApiEndpointRecord]:
    normalized_endpoint_id = str(endpoint_id or "").strip()
    normalized_user_id = str(user_id or "").strip()
    if not normalized_endpoint_id or not normalized_user_id:
        return None

    client = get_firestore_client()
    endpoints_collection = client.collection(TEMPLATE_API_ENDPOINTS_COLLECTION)
    endpoint_ref = endpoints_collection.document(normalized_endpoint_id)
    guard_ref = client.collection(TEMPLATE_API_ENDPOINT_GUARDS_COLLECTION).document(normalized_user_id)

    def _revoke(
        transaction: Optional[firebase_firestore.Transaction],
        _guard_snapshot,
    ) -> Optional[TemplateApiEndpointRecord]:
        endpoint_snapshot = endpoint_ref.get(transaction=transaction) if transaction is not None else endpoint_ref.get()
        if not endpoint_snapshot.exists:
            return None
        existing = _serialize_template_api_endpoint(endpoint_snapshot)
        if existing.user_id != normalized_user_id:
            logger.debug("Template API endpoint ownership mismatch blocked during revoke: %s", normalized_endpoint_id)
            return None

        timestamp = now_iso()
        query = where_equals(endpoints_collection, "user_id", normalized_user_id)
        docs = _get_query_snapshots(query, transaction=transaction)
        records = [_serialize_template_api_endpoint(doc) for doc in docs]
        active_template_records = [
            record
            for record in records
            if record.template_id == existing.template_id and record.status == "active"
        ]
        updated_document = _endpoint_record_to_document(existing)
        for active_record in active_template_records:
            active_ref = endpoints_collection.document(active_record.id)
            _set_document_payload(
                active_ref,
                {
                    "status": "revoked",
                    "secret_hash": "",
                    "key_prefix": "",
                    "updated_at": timestamp,
                },
                    transaction=transaction,
                    merge=True,
                )
            if active_record.id == normalized_endpoint_id:
                updated_document.update(
                    {
                        "status": "revoked",
                        "secret_hash": None,
                        "key_prefix": None,
                        "updated_at": timestamp,
                    }
                )
        _set_document_payload(
            guard_ref,
            {"updated_at": timestamp},
            transaction=transaction,
            merge=True,
        )
        return _serialize_template_api_endpoint_data(normalized_endpoint_id, updated_document)

    revoked_record = _run_document_transaction(guard_ref, _revoke)
    if revoked_record is None:
        return None
    return revoked_record


def rotate_template_api_endpoint_secret_atomic(
    endpoint_id: str,
    user_id: str,
    *,
    key_prefix: str,
    secret_hash: str,
) -> Optional[TemplateApiEndpointRecord]:
    normalized_endpoint_id = str(endpoint_id or "").strip()
    normalized_user_id = str(user_id or "").strip()
    normalized_key_prefix = str(key_prefix or "").strip()
    normalized_secret_hash = str(secret_hash or "").strip()
    if not normalized_endpoint_id or not normalized_user_id:
        return None
    if not normalized_key_prefix:
        raise ValueError("key_prefix is required")
    if not normalized_secret_hash:
        raise ValueError("secret_hash is required")

    client = get_firestore_client()
    endpoints_collection = client.collection(TEMPLATE_API_ENDPOINTS_COLLECTION)
    endpoint_ref = endpoints_collection.document(normalized_endpoint_id)
    guard_ref = client.collection(TEMPLATE_API_ENDPOINT_GUARDS_COLLECTION).document(normalized_user_id)

    def _rotate(
        transaction: Optional[firebase_firestore.Transaction],
        _guard_snapshot,
    ) -> Optional[TemplateApiEndpointRecord]:
        endpoint_snapshot = endpoint_ref.get(transaction=transaction) if transaction is not None else endpoint_ref.get()
        if not endpoint_snapshot.exists:
            return None
        existing = _serialize_template_api_endpoint(endpoint_snapshot)
        if existing.user_id != normalized_user_id:
            logger.debug("Template API endpoint ownership mismatch blocked during rotate: %s", normalized_endpoint_id)
            return None
        if existing.status != "active":
            raise TemplateApiEndpointStatusError("Only active API Fill endpoints can rotate keys.")

        timestamp = now_iso()
        updated_document = _endpoint_record_to_document(existing)
        updated_document.update(
            {
                "key_prefix": normalized_key_prefix,
                "secret_hash": normalized_secret_hash,
                "updated_at": timestamp,
            }
        )
        _set_document_payload(
            endpoint_ref,
            updated_document,
            transaction=transaction,
        )
        _set_document_payload(
            guard_ref,
            {"updated_at": timestamp},
            transaction=transaction,
            merge=True,
        )
        return _serialize_template_api_endpoint_data(normalized_endpoint_id, updated_document)

    rotated_record = _run_document_transaction(guard_ref, _rotate)
    if rotated_record is None:
        return None
    return rotated_record


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
        "runtime_failure_count": 0,
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
    runtime_failure_count: Optional[int] = None,
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
    if runtime_failure_count is not None:
        payload["runtime_failure_count"] = max(0, int(runtime_failure_count))
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
    endpoint_doc_ref = client.collection(TEMPLATE_API_ENDPOINTS_COLLECTION).document(normalized_endpoint_id)
    timestamp = created_at or now_iso()
    payload = {
        "endpoint_id": normalized_endpoint_id,
        "user_id": normalized_user_id,
        "template_id": normalized_template_id,
        "event_type": normalized_event_type,
        "outcome": str(outcome or "success").strip() or "success",
        "snapshot_version": int(snapshot_version) if snapshot_version is not None else None,
        "metadata": dict(metadata or {}),
        "created_at": timestamp,
    }

    def _create_event(
        transaction: Optional[firebase_firestore.Transaction],
        snapshot,
    ) -> bool:
        if not snapshot.exists:
            return False
        existing = _serialize_template_api_endpoint(snapshot)
        _set_document_payload(
            doc_ref,
            payload,
            transaction=transaction,
        )
        _set_document_payload(
            endpoint_doc_ref,
            {
                "updated_at": timestamp,
                "audit_event_count": existing.audit_event_count + 1,
            },
            transaction=transaction,
            merge=True,
        )
        return True

    created = _run_document_transaction(endpoint_doc_ref, _create_event)
    if not created:
        raise ValueError("endpoint_id is invalid")
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
    resolved_limit = max(1, int(limit or 20))
    client = get_firestore_client()
    base_query = where_equals(
        client.collection(TEMPLATE_API_ENDPOINT_EVENTS_COLLECTION),
        "endpoint_id",
        normalized_endpoint_id,
    )
    try:
        snapshot = (
            base_query
            .order_by("created_at", direction=firebase_firestore.Query.DESCENDING)
            .limit(resolved_limit)
            .get()
        )
        records = [_serialize_template_api_event(doc) for doc in snapshot]
    except google_api_exceptions.FailedPrecondition as exc:
        # Some environments do not have the composite index for
        # endpoint_id + created_at yet. Fall back to an endpoint-scoped fetch
        # and in-memory ordering so owner screens do not fail closed on a
        # missing index. This remains bounded to one endpoint's audit history.
        logger.warning(
            "Falling back to in-memory API Fill event ordering for endpoint %s because the Firestore index is unavailable: %s",
            normalized_endpoint_id,
            exc,
        )
        snapshot = base_query.get()
        records = _sort_template_api_endpoint_events_desc(
            [_serialize_template_api_event(doc) for doc in snapshot]
        )
    if user_id:
        normalized_user_id = str(user_id or "").strip()
        records = [record for record in records if record.user_id == normalized_user_id]
    return records[:resolved_limit]


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


def record_template_api_endpoint_success(
    endpoint_id: str,
    *,
    month_key: Optional[str] = None,
    monthly_limit: Optional[int] = None,
    metadata: Optional[Dict[str, Any]] = None,
    event_type: str = "fill_succeeded",
    outcome: str = "success",
) -> Optional[TemplateApiEndpointRecord]:
    normalized_endpoint_id = str(endpoint_id or "").strip()
    normalized_event_type = str(event_type or "").strip()
    normalized_outcome = str(outcome or "success").strip() or "success"
    normalized_month_key = _coerce_month_key(month_key) or _current_month_key()
    if not normalized_endpoint_id:
        return None
    if not normalized_event_type:
        raise ValueError("event_type is required")

    client = get_firestore_client()
    endpoint_doc_ref = client.collection(TEMPLATE_API_ENDPOINTS_COLLECTION).document(normalized_endpoint_id)
    event_doc_ref = client.collection(TEMPLATE_API_ENDPOINT_EVENTS_COLLECTION).document()

    def _record_success(
        transaction: Optional[firebase_firestore.Transaction],
        snapshot,
    ) -> Optional[TemplateApiEndpointRecord]:
        if not snapshot.exists:
            return None
        existing = _serialize_template_api_endpoint(snapshot)
        timestamp = now_iso()
        usage_count = None
        usage_created_at = None
        if monthly_limit is not None:
            if monthly_limit <= 0:
                raise TemplateApiMonthlyLimitExceededError("This account has reached its monthly API Fill request limit.")
            resolved_usage_doc_ref = client.collection(TEMPLATE_API_USAGE_COUNTERS_COLLECTION).document(
                _build_usage_counter_id(existing.user_id, normalized_month_key)
            )
            usage_snapshot = (
                resolved_usage_doc_ref.get(transaction=transaction)
                if transaction is not None
                else resolved_usage_doc_ref.get()
            )
            usage_data = usage_snapshot.to_dict() or {} if usage_snapshot.exists else {}
            usage_count = max(0, int(usage_data.get("request_count") or 0))
            if usage_count >= monthly_limit:
                raise TemplateApiMonthlyLimitExceededError("This account has reached its monthly API Fill request limit.")
            usage_created_at = usage_data.get("created_at") or timestamp
            _set_document_payload(
                resolved_usage_doc_ref,
                {
                    "user_id": existing.user_id,
                    "month_key": normalized_month_key,
                    "request_count": usage_count + 1,
                    "created_at": usage_created_at,
                    "updated_at": timestamp,
                },
                transaction=transaction,
            )
        next_month_usage = (
            existing.current_month_usage_count + 1
            if existing.current_usage_month == normalized_month_key
            else 1
        )
        _set_document_payload(
            event_doc_ref,
            {
                "endpoint_id": normalized_endpoint_id,
                "user_id": existing.user_id,
                "template_id": existing.template_id,
                "event_type": normalized_event_type,
                "outcome": normalized_outcome,
                "snapshot_version": existing.snapshot_version,
                "metadata": dict(metadata or {}),
                "created_at": timestamp,
            },
            transaction=transaction,
        )
        updated_document = _endpoint_record_to_document(existing)
        updated_document.update(
            {
                "updated_at": timestamp,
                "last_used_at": timestamp,
                "usage_count": existing.usage_count + 1,
                "current_usage_month": normalized_month_key,
                "current_month_usage_count": next_month_usage,
                "audit_event_count": existing.audit_event_count + 1,
            }
        )
        _set_document_payload(
            endpoint_doc_ref,
            updated_document,
            transaction=transaction,
        )
        return _serialize_template_api_endpoint_data(normalized_endpoint_id, updated_document)

    return _run_document_transaction(endpoint_doc_ref, _record_success)


def record_template_api_endpoint_failure(
    endpoint_id: str,
    *,
    auth_failure: bool = False,
    validation_failure: bool = False,
    runtime_failure: bool = False,
    suspicious: bool = False,
    reason: Optional[str] = None,
) -> Optional[TemplateApiEndpointRecord]:
    normalized_endpoint_id = str(endpoint_id or "").strip()
    if not normalized_endpoint_id:
        return None
    client = get_firestore_client()
    doc_ref = client.collection(TEMPLATE_API_ENDPOINTS_COLLECTION).document(normalized_endpoint_id)

    def _record_failure(
        transaction: Optional[firebase_firestore.Transaction],
        snapshot,
    ) -> Optional[TemplateApiEndpointRecord]:
        if not snapshot.exists:
            return None
        existing = _serialize_template_api_endpoint(snapshot)
        _set_document_payload(
            doc_ref,
            {
                "updated_at": now_iso(),
                "auth_failure_count": existing.auth_failure_count + (1 if auth_failure else 0),
                "validation_failure_count": existing.validation_failure_count + (1 if validation_failure else 0),
                "runtime_failure_count": existing.runtime_failure_count + (1 if runtime_failure else 0),
                "suspicious_failure_count": existing.suspicious_failure_count + (1 if suspicious else 0),
                "last_failure_at": now_iso(),
                "last_failure_reason": (str(reason or "").strip() or None),
            },
            transaction=transaction,
            merge=True,
        )
        return _serialize_template_api_endpoint(doc_ref.get())

    return _run_document_transaction(doc_ref, _record_failure)
