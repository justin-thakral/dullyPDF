"""Firestore-backed signing request metadata."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from uuid import uuid4

from backend.logging_config import get_logger
from backend.services.signing_service import (
    SIGNING_STATUS_COMPLETED,
    SIGNING_STATUS_DRAFT,
    SIGNING_STATUS_INVALIDATED,
    SIGNING_STATUS_SENT,
    parse_signing_public_token,
)
from backend.time_utils import now_iso
from .firebase_service import get_firestore_client
from .firestore_query_utils import where_equals


logger = get_logger(__name__)

SIGNING_REQUESTS_COLLECTION = "signing_requests"
SIGNING_EVENTS_COLLECTION = "signing_events"
SIGNING_SESSIONS_COLLECTION = "signing_sessions"


@dataclass(frozen=True)
class SigningRequestRecord:
    id: str
    user_id: str
    title: Optional[str]
    mode: str
    signature_mode: str
    source_type: str
    source_id: Optional[str]
    source_link_id: Optional[str]
    source_record_label: Optional[str]
    source_document_name: str
    source_template_id: Optional[str]
    source_template_name: Optional[str]
    source_pdf_sha256: Optional[str]
    source_pdf_bucket_path: Optional[str]
    source_version: Optional[str]
    document_category: str
    manual_fallback_enabled: bool
    signer_name: str
    signer_email: str
    invite_delivery_status: Optional[str]
    invite_last_attempt_at: Optional[str]
    invite_sent_at: Optional[str]
    invite_delivery_error: Optional[str]
    status: str
    anchors: List[Dict[str, Any]]
    disclosure_version: str
    created_at: Optional[str]
    updated_at: Optional[str]
    owner_review_confirmed_at: Optional[str]
    sent_at: Optional[str]
    opened_at: Optional[str]
    reviewed_at: Optional[str]
    consented_at: Optional[str]
    signature_adopted_at: Optional[str]
    signature_adopted_name: Optional[str]
    manual_fallback_requested_at: Optional[str]
    manual_fallback_note: Optional[str]
    completed_at: Optional[str]
    completed_session_id: Optional[str]
    completed_ip_address: Optional[str]
    completed_user_agent: Optional[str]
    signed_pdf_bucket_path: Optional[str]
    signed_pdf_sha256: Optional[str]
    audit_manifest_bucket_path: Optional[str]
    audit_manifest_sha256: Optional[str]
    audit_receipt_bucket_path: Optional[str]
    audit_receipt_sha256: Optional[str]
    audit_signature_method: Optional[str]
    audit_signature_algorithm: Optional[str]
    audit_kms_key_resource_name: Optional[str]
    audit_kms_key_version_name: Optional[str]
    artifacts_generated_at: Optional[str]
    retention_until: Optional[str]
    invalidated_at: Optional[str]
    invalidation_reason: Optional[str]


@dataclass(frozen=True)
class SigningEventRecord:
    id: str
    request_id: str
    event_type: str
    session_id: Optional[str]
    link_token_id: Optional[str]
    client_ip: Optional[str]
    user_agent: Optional[str]
    details: Dict[str, Any]
    occurred_at: Optional[str]


@dataclass(frozen=True)
class SigningSessionRecord:
    id: str
    request_id: str
    link_token_id: Optional[str]
    client_ip: Optional[str]
    user_agent: Optional[str]
    created_at: Optional[str]
    updated_at: Optional[str]
    expires_at: Optional[str]
    completed_at: Optional[str]


def _coerce_optional_text(value: Any) -> Optional[str]:
    normalized = str(value or "").strip()
    return normalized or None


def _coerce_dict_list(value: Any) -> List[Dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(entry) for entry in value if isinstance(entry, dict)]


def _serialize_signing_request(doc) -> SigningRequestRecord:
    data = doc.to_dict() or {}
    return SigningRequestRecord(
        id=doc.id,
        user_id=str(data.get("user_id") or "").strip(),
        title=_coerce_optional_text(data.get("title")),
        mode=str(data.get("mode") or "sign").strip() or "sign",
        signature_mode=str(data.get("signature_mode") or "business").strip() or "business",
        source_type=str(data.get("source_type") or "workspace").strip() or "workspace",
        source_id=_coerce_optional_text(data.get("source_id")),
        source_link_id=_coerce_optional_text(data.get("source_link_id")),
        source_record_label=_coerce_optional_text(data.get("source_record_label")),
        source_document_name=str(data.get("source_document_name") or "").strip(),
        source_template_id=_coerce_optional_text(data.get("source_template_id")),
        source_template_name=_coerce_optional_text(data.get("source_template_name")),
        source_pdf_sha256=_coerce_optional_text(data.get("source_pdf_sha256")),
        source_pdf_bucket_path=_coerce_optional_text(data.get("source_pdf_bucket_path")),
        source_version=_coerce_optional_text(data.get("source_version")),
        document_category=str(data.get("document_category") or "").strip(),
        manual_fallback_enabled=bool(data.get("manual_fallback_enabled")),
        signer_name=str(data.get("signer_name") or "").strip(),
        signer_email=str(data.get("signer_email") or "").strip(),
        invite_delivery_status=_coerce_optional_text(data.get("invite_delivery_status")),
        invite_last_attempt_at=_coerce_optional_text(data.get("invite_last_attempt_at")),
        invite_sent_at=_coerce_optional_text(data.get("invite_sent_at")),
        invite_delivery_error=_coerce_optional_text(data.get("invite_delivery_error")),
        status=str(data.get("status") or SIGNING_STATUS_DRAFT).strip() or SIGNING_STATUS_DRAFT,
        anchors=_coerce_dict_list(data.get("anchors")),
        disclosure_version=str(data.get("disclosure_version") or "").strip(),
        created_at=_coerce_optional_text(data.get("created_at")),
        updated_at=_coerce_optional_text(data.get("updated_at")),
        owner_review_confirmed_at=_coerce_optional_text(data.get("owner_review_confirmed_at")),
        sent_at=_coerce_optional_text(data.get("sent_at")),
        opened_at=_coerce_optional_text(data.get("opened_at")),
        reviewed_at=_coerce_optional_text(data.get("reviewed_at")),
        consented_at=_coerce_optional_text(data.get("consented_at")),
        signature_adopted_at=_coerce_optional_text(data.get("signature_adopted_at")),
        signature_adopted_name=_coerce_optional_text(data.get("signature_adopted_name")),
        manual_fallback_requested_at=_coerce_optional_text(data.get("manual_fallback_requested_at")),
        manual_fallback_note=_coerce_optional_text(data.get("manual_fallback_note")),
        completed_at=_coerce_optional_text(data.get("completed_at")),
        completed_session_id=_coerce_optional_text(data.get("completed_session_id")),
        completed_ip_address=_coerce_optional_text(data.get("completed_ip_address")),
        completed_user_agent=_coerce_optional_text(data.get("completed_user_agent")),
        signed_pdf_bucket_path=_coerce_optional_text(data.get("signed_pdf_bucket_path")),
        signed_pdf_sha256=_coerce_optional_text(data.get("signed_pdf_sha256")),
        audit_manifest_bucket_path=_coerce_optional_text(data.get("audit_manifest_bucket_path")),
        audit_manifest_sha256=_coerce_optional_text(data.get("audit_manifest_sha256")),
        audit_receipt_bucket_path=_coerce_optional_text(data.get("audit_receipt_bucket_path")),
        audit_receipt_sha256=_coerce_optional_text(data.get("audit_receipt_sha256")),
        audit_signature_method=_coerce_optional_text(data.get("audit_signature_method")),
        audit_signature_algorithm=_coerce_optional_text(data.get("audit_signature_algorithm")),
        audit_kms_key_resource_name=_coerce_optional_text(data.get("audit_kms_key_resource_name")),
        audit_kms_key_version_name=_coerce_optional_text(data.get("audit_kms_key_version_name")),
        artifacts_generated_at=_coerce_optional_text(data.get("artifacts_generated_at")),
        retention_until=_coerce_optional_text(data.get("retention_until")),
        invalidated_at=_coerce_optional_text(data.get("invalidated_at")),
        invalidation_reason=_coerce_optional_text(data.get("invalidation_reason")),
    )


def _serialize_signing_event(doc) -> SigningEventRecord:
    data = doc.to_dict() or {}
    return SigningEventRecord(
        id=doc.id,
        request_id=str(data.get("request_id") or "").strip(),
        event_type=str(data.get("event_type") or "").strip(),
        session_id=_coerce_optional_text(data.get("session_id")),
        link_token_id=_coerce_optional_text(data.get("link_token_id")),
        client_ip=_coerce_optional_text(data.get("client_ip")),
        user_agent=_coerce_optional_text(data.get("user_agent")),
        details=dict(data.get("details") or {}) if isinstance(data.get("details"), dict) else {},
        occurred_at=_coerce_optional_text(data.get("occurred_at")),
    )


def _serialize_signing_session(doc) -> SigningSessionRecord:
    data = doc.to_dict() or {}
    return SigningSessionRecord(
        id=doc.id,
        request_id=str(data.get("request_id") or "").strip(),
        link_token_id=_coerce_optional_text(data.get("link_token_id")),
        client_ip=_coerce_optional_text(data.get("client_ip")),
        user_agent=_coerce_optional_text(data.get("user_agent")),
        created_at=_coerce_optional_text(data.get("created_at")),
        updated_at=_coerce_optional_text(data.get("updated_at")),
        expires_at=_coerce_optional_text(data.get("expires_at")),
        completed_at=_coerce_optional_text(data.get("completed_at")),
    )


def create_signing_request(
    *,
    user_id: str,
    title: Optional[str],
    mode: str,
    signature_mode: str,
    source_type: str,
    source_id: Optional[str],
    source_link_id: Optional[str],
    source_record_label: Optional[str],
    source_document_name: str,
    source_template_id: Optional[str],
    source_template_name: Optional[str],
    source_pdf_sha256: Optional[str],
    source_version: Optional[str],
    document_category: str,
    manual_fallback_enabled: bool,
    signer_name: str,
    signer_email: str,
    anchors: List[Dict[str, Any]],
    disclosure_version: str,
    client=None,
) -> SigningRequestRecord:
    firestore_client = client or get_firestore_client()
    now_value = now_iso()
    request_id = uuid4().hex
    payload = {
        "user_id": str(user_id or "").strip(),
        "title": title,
        "mode": mode,
        "signature_mode": signature_mode,
        "source_type": source_type,
        "source_id": source_id,
        "source_link_id": source_link_id,
        "source_record_label": source_record_label,
        "source_document_name": source_document_name,
        "source_template_id": source_template_id,
        "source_template_name": source_template_name,
        "source_pdf_sha256": source_pdf_sha256,
        "source_pdf_bucket_path": None,
        "source_version": source_version,
        "document_category": document_category,
        "manual_fallback_enabled": bool(manual_fallback_enabled),
        "signer_name": signer_name,
        "signer_email": signer_email,
        "invite_delivery_status": None,
        "invite_last_attempt_at": None,
        "invite_sent_at": None,
        "invite_delivery_error": None,
        "status": SIGNING_STATUS_DRAFT,
        "anchors": list(anchors or []),
        "disclosure_version": disclosure_version,
        "created_at": now_value,
        "updated_at": now_value,
        "owner_review_confirmed_at": None,
        "sent_at": None,
        "opened_at": None,
        "reviewed_at": None,
        "consented_at": None,
        "signature_adopted_at": None,
        "signature_adopted_name": None,
        "manual_fallback_requested_at": None,
        "manual_fallback_note": None,
        "completed_at": None,
        "completed_session_id": None,
        "completed_ip_address": None,
        "completed_user_agent": None,
        "signed_pdf_bucket_path": None,
        "signed_pdf_sha256": None,
        "audit_manifest_bucket_path": None,
        "audit_manifest_sha256": None,
        "audit_receipt_bucket_path": None,
        "audit_receipt_sha256": None,
        "audit_signature_method": None,
        "audit_signature_algorithm": None,
        "audit_kms_key_resource_name": None,
        "audit_kms_key_version_name": None,
        "artifacts_generated_at": None,
        "retention_until": None,
        "invalidated_at": None,
        "invalidation_reason": None,
    }
    doc_ref = firestore_client.collection(SIGNING_REQUESTS_COLLECTION).document(request_id)
    doc_ref.set(payload)
    return _serialize_signing_request(doc_ref.get())


def list_signing_requests(user_id: str, *, client=None) -> List[SigningRequestRecord]:
    normalized_user_id = str(user_id or "").strip()
    if not normalized_user_id:
        return []
    firestore_client = client or get_firestore_client()
    snapshot = where_equals(
        firestore_client.collection(SIGNING_REQUESTS_COLLECTION),
        "user_id",
        normalized_user_id,
    ).get()
    records = [_serialize_signing_request(doc) for doc in snapshot]
    return sorted(
        records,
        key=lambda entry: (entry.updated_at or "", entry.created_at or "", entry.id),
        reverse=True,
    )


def get_signing_request(request_id: str, *, client=None) -> Optional[SigningRequestRecord]:
    normalized_request_id = str(request_id or "").strip()
    if not normalized_request_id:
        return None
    firestore_client = client or get_firestore_client()
    snapshot = firestore_client.collection(SIGNING_REQUESTS_COLLECTION).document(normalized_request_id).get()
    if not snapshot.exists:
        return None
    return _serialize_signing_request(snapshot)


def get_signing_request_for_user(request_id: str, user_id: str, *, client=None) -> Optional[SigningRequestRecord]:
    record = get_signing_request(request_id, client=client)
    if record is None or record.user_id != str(user_id or "").strip():
        return None
    return record


def get_signing_request_by_public_token(token: str, *, client=None) -> Optional[SigningRequestRecord]:
    request_id = parse_signing_public_token(token)
    if not request_id:
        return None
    return get_signing_request(request_id, client=client)


def get_signing_session(session_id: str, *, client=None) -> Optional[SigningSessionRecord]:
    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        return None
    firestore_client = client or get_firestore_client()
    snapshot = firestore_client.collection(SIGNING_SESSIONS_COLLECTION).document(normalized_session_id).get()
    if not snapshot.exists:
        return None
    return _serialize_signing_session(snapshot)


def get_signing_session_for_request(session_id: str, request_id: str, *, client=None) -> Optional[SigningSessionRecord]:
    session = get_signing_session(session_id, client=client)
    if session is None or session.request_id != str(request_id or "").strip():
        return None
    return session


def create_signing_session(
    request_id: str,
    *,
    link_token_id: Optional[str],
    client_ip: Optional[str],
    user_agent: Optional[str],
    expires_at: str,
    client=None,
) -> SigningSessionRecord:
    firestore_client = client or get_firestore_client()
    now_value = now_iso()
    session_id = uuid4().hex
    doc_ref = firestore_client.collection(SIGNING_SESSIONS_COLLECTION).document(session_id)
    doc_ref.set(
        {
            "request_id": str(request_id or "").strip(),
            "link_token_id": _coerce_optional_text(link_token_id),
            "client_ip": _coerce_optional_text(client_ip),
            "user_agent": _coerce_optional_text(user_agent),
            "created_at": now_value,
            "updated_at": now_value,
            "expires_at": _coerce_optional_text(expires_at),
            "completed_at": None,
        }
    )
    return _serialize_signing_session(doc_ref.get())


def touch_signing_session(
    session_id: str,
    *,
    client_ip: Optional[str] = None,
    user_agent: Optional[str] = None,
    completed: bool = False,
    client=None,
) -> Optional[SigningSessionRecord]:
    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        return None
    firestore_client = client or get_firestore_client()
    doc_ref = firestore_client.collection(SIGNING_SESSIONS_COLLECTION).document(normalized_session_id)
    snapshot = doc_ref.get()
    if not snapshot.exists:
        return None
    now_value = now_iso()
    payload: Dict[str, Any] = {"updated_at": now_value}
    if client_ip is not None:
        payload["client_ip"] = _coerce_optional_text(client_ip)
    if user_agent is not None:
        payload["user_agent"] = _coerce_optional_text(user_agent)
    if completed:
        payload["completed_at"] = now_value
    doc_ref.set(payload, merge=True)
    return _serialize_signing_session(doc_ref.get())


def record_signing_event(
    request_id: str,
    *,
    event_type: str,
    session_id: Optional[str],
    link_token_id: Optional[str],
    client_ip: Optional[str],
    user_agent: Optional[str],
    details: Optional[Dict[str, Any]] = None,
    occurred_at: Optional[str] = None,
    client=None,
) -> SigningEventRecord:
    firestore_client = client or get_firestore_client()
    event_id = uuid4().hex
    event_time = _coerce_optional_text(occurred_at) or now_iso()
    doc_ref = firestore_client.collection(SIGNING_EVENTS_COLLECTION).document(event_id)
    doc_ref.set(
        {
            "request_id": str(request_id or "").strip(),
            "event_type": str(event_type or "").strip(),
            "session_id": _coerce_optional_text(session_id),
            "link_token_id": _coerce_optional_text(link_token_id),
            "client_ip": _coerce_optional_text(client_ip),
            "user_agent": _coerce_optional_text(user_agent),
            "details": dict(details or {}),
            "occurred_at": event_time,
        }
    )
    return _serialize_signing_event(doc_ref.get())


def list_signing_events_for_request(request_id: str, *, client=None) -> List[SigningEventRecord]:
    normalized_request_id = str(request_id or "").strip()
    if not normalized_request_id:
        return []
    firestore_client = client or get_firestore_client()
    snapshot = where_equals(
        firestore_client.collection(SIGNING_EVENTS_COLLECTION),
        "request_id",
        normalized_request_id,
    ).get()
    records = [_serialize_signing_event(doc) for doc in snapshot]
    return sorted(records, key=lambda entry: (entry.occurred_at or "", entry.id))


def _update_public_signing_request(
    request_id: str,
    *,
    allowed_statuses: Optional[set[str]] = None,
    updates: Dict[str, Any],
    client=None,
) -> Optional[SigningRequestRecord]:
    normalized_request_id = str(request_id or "").strip()
    if not normalized_request_id:
        return None
    firestore_client = client or get_firestore_client()
    doc_ref = firestore_client.collection(SIGNING_REQUESTS_COLLECTION).document(normalized_request_id)
    snapshot = doc_ref.get()
    if not snapshot.exists:
        return None
    data = snapshot.to_dict() or {}
    current_status = str(data.get("status") or "").strip()
    if allowed_statuses and current_status not in allowed_statuses:
        return _serialize_signing_request(snapshot)
    payload = dict(updates or {})
    payload["updated_at"] = now_iso()
    doc_ref.set(payload, merge=True)
    return _serialize_signing_request(doc_ref.get())


def mark_signing_request_sent(
    request_id: str,
    user_id: str,
    *,
    source_pdf_bucket_path: str,
    source_pdf_sha256: str,
    source_version: Optional[str],
    owner_review_confirmed_at: Optional[str] = None,
    client=None,
) -> Optional[SigningRequestRecord]:
    normalized_request_id = str(request_id or "").strip()
    normalized_user_id = str(user_id or "").strip()
    if not normalized_request_id or not normalized_user_id:
        return None
    firestore_client = client or get_firestore_client()
    doc_ref = firestore_client.collection(SIGNING_REQUESTS_COLLECTION).document(normalized_request_id)
    snapshot = doc_ref.get()
    if not snapshot.exists:
        return None
    data = snapshot.to_dict() or {}
    if str(data.get("user_id") or "").strip() != normalized_user_id:
        return None
    current_status = str(data.get("status") or "").strip()
    if current_status != SIGNING_STATUS_DRAFT:
        return _serialize_signing_request(snapshot)
    now_value = now_iso()
    doc_ref.set(
        {
            "status": SIGNING_STATUS_SENT,
            "source_pdf_bucket_path": str(source_pdf_bucket_path or "").strip() or None,
            "source_pdf_sha256": str(source_pdf_sha256 or "").strip() or None,
            "source_version": str(source_version or "").strip() or None,
            "invite_delivery_status": "pending",
            "invite_last_attempt_at": None,
            "invite_sent_at": None,
            "invite_delivery_error": None,
            "owner_review_confirmed_at": _coerce_optional_text(owner_review_confirmed_at),
            "sent_at": now_value,
            "opened_at": None,
            "reviewed_at": None,
            "consented_at": None,
            "signature_adopted_at": None,
            "signature_adopted_name": None,
            "manual_fallback_requested_at": None,
            "manual_fallback_note": None,
            "completed_at": None,
            "completed_session_id": None,
            "completed_ip_address": None,
            "completed_user_agent": None,
            "signed_pdf_bucket_path": None,
            "signed_pdf_sha256": None,
            "audit_manifest_bucket_path": None,
            "audit_manifest_sha256": None,
            "audit_receipt_bucket_path": None,
            "audit_receipt_sha256": None,
            "audit_signature_method": None,
            "audit_signature_algorithm": None,
            "audit_kms_key_resource_name": None,
            "audit_kms_key_version_name": None,
            "artifacts_generated_at": None,
            "retention_until": None,
            "invalidated_at": None,
            "invalidation_reason": None,
            "updated_at": now_value,
        },
        merge=True,
    )
    return _serialize_signing_request(doc_ref.get())


def mark_signing_request_invite_delivery(
    request_id: str,
    user_id: str,
    *,
    delivery_status: str,
    attempted_at: Optional[str] = None,
    sent_at: Optional[str] = None,
    delivery_error: Optional[str] = None,
    client=None,
) -> Optional[SigningRequestRecord]:
    normalized_request_id = str(request_id or "").strip()
    normalized_user_id = str(user_id or "").strip()
    normalized_status = str(delivery_status or "").strip().lower()
    if not normalized_request_id or not normalized_user_id or not normalized_status:
        return None
    firestore_client = client or get_firestore_client()
    doc_ref = firestore_client.collection(SIGNING_REQUESTS_COLLECTION).document(normalized_request_id)
    snapshot = doc_ref.get()
    if not snapshot.exists:
        return None
    data = snapshot.to_dict() or {}
    if str(data.get("user_id") or "").strip() != normalized_user_id:
        return None
    now_value = now_iso()
    doc_ref.set(
        {
            "invite_delivery_status": normalized_status,
            "invite_last_attempt_at": _coerce_optional_text(attempted_at) or now_value,
            "invite_sent_at": _coerce_optional_text(sent_at),
            "invite_delivery_error": _coerce_optional_text(delivery_error),
            "updated_at": now_value,
        },
        merge=True,
    )
    return _serialize_signing_request(doc_ref.get())


def mark_signing_request_opened(
    request_id: str,
    *,
    session_id: str,
    client_ip: Optional[str],
    user_agent: Optional[str],
    client=None,
) -> Optional[SigningRequestRecord]:
    now_value = now_iso()
    return _update_public_signing_request(
        request_id,
        allowed_statuses={SIGNING_STATUS_SENT},
        updates={
            "opened_at": now_value,
            "last_public_session_id": _coerce_optional_text(session_id),
            "last_public_ip": _coerce_optional_text(client_ip),
            "last_public_user_agent": _coerce_optional_text(user_agent),
        },
        client=client,
    )


def mark_signing_request_reviewed(
    request_id: str,
    *,
    session_id: str,
    client_ip: Optional[str],
    user_agent: Optional[str],
    client=None,
) -> Optional[SigningRequestRecord]:
    now_value = now_iso()
    return _update_public_signing_request(
        request_id,
        allowed_statuses={SIGNING_STATUS_SENT},
        updates={
            "reviewed_at": now_value,
            "last_public_session_id": _coerce_optional_text(session_id),
            "last_public_ip": _coerce_optional_text(client_ip),
            "last_public_user_agent": _coerce_optional_text(user_agent),
        },
        client=client,
    )


def mark_signing_request_consented(
    request_id: str,
    *,
    session_id: str,
    client_ip: Optional[str],
    user_agent: Optional[str],
    client=None,
) -> Optional[SigningRequestRecord]:
    now_value = now_iso()
    return _update_public_signing_request(
        request_id,
        allowed_statuses={SIGNING_STATUS_SENT},
        updates={
            "consented_at": now_value,
            "last_public_session_id": _coerce_optional_text(session_id),
            "last_public_ip": _coerce_optional_text(client_ip),
            "last_public_user_agent": _coerce_optional_text(user_agent),
        },
        client=client,
    )


def mark_signing_request_signature_adopted(
    request_id: str,
    *,
    session_id: str,
    adopted_name: str,
    client_ip: Optional[str],
    user_agent: Optional[str],
    client=None,
) -> Optional[SigningRequestRecord]:
    now_value = now_iso()
    return _update_public_signing_request(
        request_id,
        allowed_statuses={SIGNING_STATUS_SENT},
        updates={
            "signature_adopted_at": now_value,
            "signature_adopted_name": _coerce_optional_text(adopted_name),
            "last_public_session_id": _coerce_optional_text(session_id),
            "last_public_ip": _coerce_optional_text(client_ip),
            "last_public_user_agent": _coerce_optional_text(user_agent),
        },
        client=client,
    )


def mark_signing_request_manual_fallback_requested(
    request_id: str,
    *,
    session_id: str,
    note: Optional[str],
    client_ip: Optional[str],
    user_agent: Optional[str],
    client=None,
) -> Optional[SigningRequestRecord]:
    now_value = now_iso()
    return _update_public_signing_request(
        request_id,
        allowed_statuses={SIGNING_STATUS_SENT},
        updates={
            "manual_fallback_requested_at": now_value,
            "manual_fallback_note": _coerce_optional_text(note),
            "last_public_session_id": _coerce_optional_text(session_id),
            "last_public_ip": _coerce_optional_text(client_ip),
            "last_public_user_agent": _coerce_optional_text(user_agent),
        },
        client=client,
    )


def complete_signing_request(
    request_id: str,
    *,
    session_id: str,
    client_ip: Optional[str],
    user_agent: Optional[str],
    completed_at: Optional[str] = None,
    artifact_updates: Optional[Dict[str, Any]] = None,
    client=None,
) -> Optional[SigningRequestRecord]:
    now_value = _coerce_optional_text(completed_at) or now_iso()
    normalized_artifact_updates = dict(artifact_updates or {})
    return _update_public_signing_request(
        request_id,
        allowed_statuses={SIGNING_STATUS_SENT},
        updates={
            "status": SIGNING_STATUS_COMPLETED,
            "completed_at": now_value,
            "completed_session_id": _coerce_optional_text(session_id),
            "completed_ip_address": _coerce_optional_text(client_ip),
            "completed_user_agent": _coerce_optional_text(user_agent),
            **normalized_artifact_updates,
        },
        client=client,
    )


def invalidate_signing_request(
    request_id: str,
    user_id: str,
    *,
    reason: str,
    client=None,
) -> Optional[SigningRequestRecord]:
    normalized_request_id = str(request_id or "").strip()
    normalized_user_id = str(user_id or "").strip()
    normalized_reason = str(reason or "").strip() or "Signing request invalidated."
    if not normalized_request_id or not normalized_user_id:
        return None
    firestore_client = client or get_firestore_client()
    doc_ref = firestore_client.collection(SIGNING_REQUESTS_COLLECTION).document(normalized_request_id)
    snapshot = doc_ref.get()
    if not snapshot.exists:
        return None
    data = snapshot.to_dict() or {}
    if str(data.get("user_id") or "").strip() != normalized_user_id:
        return None
    now_value = now_iso()
    doc_ref.set(
        {
            "status": SIGNING_STATUS_INVALIDATED,
            "invalidated_at": now_value,
            "invalidation_reason": normalized_reason,
            "updated_at": now_value,
        },
        merge=True,
    )
    return _serialize_signing_request(doc_ref.get())
