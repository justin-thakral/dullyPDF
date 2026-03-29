"""Firestore-backed signing request metadata."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from firebase_admin import firestore as firebase_firestore

from backend.logging_config import get_logger
from backend.services.signing_quota_service import SigningRequestMonthlyLimitError
from backend.services.signing_service import (
    SIGNING_STATUS_COMPLETED,
    SIGNING_STATUS_DRAFT,
    SIGNING_STATUS_INVALIDATED,
    SIGNING_STATUS_SENT,
    normalize_signing_public_link_version,
    parse_signing_public_token_payload,
    parse_signing_validation_token,
    resolve_signing_retention_until,
    resolve_signing_signer_transport,
    resolve_signing_verification_policy,
    resolve_signing_request_expires_at,
)
from backend.time_utils import now_iso
from .firebase_service import get_firestore_client
from .firestore_query_utils import where_equals


logger = get_logger(__name__)

SIGNING_REQUESTS_COLLECTION = "signing_requests"
SIGNING_EVENTS_COLLECTION = "signing_events"
SIGNING_SESSIONS_COLLECTION = "signing_sessions"
SIGNING_USAGE_COUNTERS_COLLECTION = "signing_usage_counters"


def _supports_firestore_transaction(transaction: Any) -> bool:
    """Return True when the object looks like a real Firestore transaction."""

    return all(
        hasattr(transaction, attr)
        for attr in ("_read_only", "_commit", "_rollback", "_max_attempts")
    )


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


def _build_signing_usage_counter_id(user_id: str, month_key: str) -> str:
    return f"{str(user_id or '').strip().replace('/', '_')}__{month_key}"


def _signing_usage_counter_doc_ref(user_id: str, month_key: str, client):
    return client.collection(SIGNING_USAGE_COUNTERS_COLLECTION).document(
        _build_signing_usage_counter_id(user_id, month_key)
    )


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
    esign_eligibility_confirmed_at: Optional[str]
    esign_eligibility_confirmed_source: Optional[str]
    company_binding_enabled: bool
    authority_attestation_version: Optional[str]
    authority_attestation_text: Optional[str]
    authority_attestation_sha256: Optional[str]
    manual_fallback_enabled: bool
    signer_name: str
    signer_email: str
    signer_contact_method: Optional[str]
    signer_auth_method: Optional[str]
    sender_display_name: Optional[str]
    sender_email: Optional[str]
    sender_contact_email: Optional[str]
    consumer_paper_copy_procedure: Optional[str]
    consumer_paper_copy_fee_description: Optional[str]
    consumer_withdrawal_procedure: Optional[str]
    consumer_withdrawal_consequences: Optional[str]
    consumer_contact_update_procedure: Optional[str]
    consumer_consent_scope_override: Optional[str]
    invite_method: Optional[str]
    invite_provider: Optional[str]
    invite_delivery_status: Optional[str]
    invite_last_attempt_at: Optional[str]
    invite_sent_at: Optional[str]
    invite_delivery_error: Optional[str]
    invite_delivery_error_code: Optional[str]
    invite_message_id: Optional[str]
    manual_link_shared_at: Optional[str]
    verification_required: bool
    verification_method: Optional[str]
    verification_completed_at: Optional[str]
    status: str
    anchors: List[Dict[str, Any]]
    disclosure_version: str
    business_disclosure_payload: Optional[Dict[str, Any]]
    business_disclosure_sha256: Optional[str]
    consumer_disclosure_version: Optional[str]
    consumer_disclosure_payload: Optional[Dict[str, Any]]
    consumer_disclosure_sha256: Optional[str]
    consumer_disclosure_presented_at: Optional[str]
    consumer_consent_scope: Optional[str]
    consumer_access_demonstrated_at: Optional[str]
    consumer_access_demonstration_method: Optional[str]
    created_at: Optional[str]
    updated_at: Optional[str]
    owner_review_confirmed_at: Optional[str]
    sent_at: Optional[str]
    quota_consumed_at: Optional[str]
    quota_month_key: Optional[str]
    opened_at: Optional[str]
    reviewed_at: Optional[str]
    consented_at: Optional[str]
    signature_adopted_at: Optional[str]
    signature_adopted_name: Optional[str]
    signature_adopted_mode: Optional[str]
    signature_adopted_image_data_url: Optional[str]
    signature_adopted_image_sha256: Optional[str]
    representative_title: Optional[str]
    representative_company_name: Optional[str]
    authority_attested_at: Optional[str]
    manual_fallback_requested_at: Optional[str]
    manual_fallback_note: Optional[str]
    consent_withdrawn_at: Optional[str]
    completed_at: Optional[str]
    completed_session_id: Optional[str]
    completed_ip_address: Optional[str]
    completed_user_agent: Optional[str]
    completed_verification_method: Optional[str]
    completed_verification_completed_at: Optional[str]
    completed_verification_session_id: Optional[str]
    signed_pdf_bucket_path: Optional[str]
    signed_pdf_sha256: Optional[str]
    signed_pdf_digital_signature_method: Optional[str]
    signed_pdf_digital_signature_algorithm: Optional[str]
    signed_pdf_digital_signature_field_name: Optional[str]
    signed_pdf_digital_signature_subfilter: Optional[str]
    signed_pdf_digital_signature_timestamped: bool
    signed_pdf_digital_certificate_subject: Optional[str]
    signed_pdf_digital_certificate_issuer: Optional[str]
    signed_pdf_digital_certificate_serial_number: Optional[str]
    signed_pdf_digital_certificate_fingerprint_sha256: Optional[str]
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
    expires_at: Optional[str]
    public_link_version: int
    public_link_revoked_at: Optional[str]
    public_link_last_reissued_at: Optional[str]
    invalidated_at: Optional[str]
    invalidation_reason: Optional[str]
    public_app_origin: Optional[str] = None


@dataclass(frozen=True)
class SigningMonthlyUsageRecord:
    id: str
    user_id: str
    month_key: str
    request_count: int
    created_at: Optional[str]
    updated_at: Optional[str]


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
    binding_ip_scope: Optional[str]
    binding_user_agent_hash: Optional[str]
    created_at: Optional[str]
    updated_at: Optional[str]
    expires_at: Optional[str]
    completed_at: Optional[str]
    verification_code_hash: Optional[str]
    verification_sent_at: Optional[str]
    verification_expires_at: Optional[str]
    verification_attempt_count: int
    verification_resend_count: int
    verification_completed_at: Optional[str]
    verification_message_id: Optional[str]
    consumer_access_attempt_count: int


def _coerce_optional_text(value: Any) -> Optional[str]:
    normalized = str(value or "").strip()
    return normalized or None


def _coerce_nonnegative_int(value: Any) -> int:
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, normalized)


def _has_field_value(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return value is not None


def _coerce_dict_list(value: Any) -> List[Dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(entry) for entry in value if isinstance(entry, dict)]


def _coerce_optional_dict(value: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(value, dict):
        return None
    return dict(value)


def _coerce_public_link_version(value: Any) -> int:
    return normalize_signing_public_link_version(value)


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
        esign_eligibility_confirmed_at=_coerce_optional_text(data.get("esign_eligibility_confirmed_at")),
        esign_eligibility_confirmed_source=_coerce_optional_text(data.get("esign_eligibility_confirmed_source")),
        company_binding_enabled=bool(data.get("company_binding_enabled")),
        authority_attestation_version=_coerce_optional_text(data.get("authority_attestation_version")),
        authority_attestation_text=_coerce_optional_text(data.get("authority_attestation_text")),
        authority_attestation_sha256=_coerce_optional_text(data.get("authority_attestation_sha256")),
        manual_fallback_enabled=bool(data.get("manual_fallback_enabled")),
        signer_name=str(data.get("signer_name") or "").strip(),
        signer_email=str(data.get("signer_email") or "").strip(),
        signer_contact_method=_coerce_optional_text(data.get("signer_contact_method")),
        signer_auth_method=_coerce_optional_text(data.get("signer_auth_method")),
        sender_display_name=_coerce_optional_text(data.get("sender_display_name")),
        sender_email=_coerce_optional_text(data.get("sender_email")),
        sender_contact_email=_coerce_optional_text(data.get("sender_contact_email")),
        consumer_paper_copy_procedure=_coerce_optional_text(data.get("consumer_paper_copy_procedure")),
        consumer_paper_copy_fee_description=_coerce_optional_text(data.get("consumer_paper_copy_fee_description")),
        consumer_withdrawal_procedure=_coerce_optional_text(data.get("consumer_withdrawal_procedure")),
        consumer_withdrawal_consequences=_coerce_optional_text(data.get("consumer_withdrawal_consequences")),
        consumer_contact_update_procedure=_coerce_optional_text(data.get("consumer_contact_update_procedure")),
        consumer_consent_scope_override=_coerce_optional_text(data.get("consumer_consent_scope_override")),
        invite_method=_coerce_optional_text(data.get("invite_method")),
        invite_provider=_coerce_optional_text(data.get("invite_provider")),
        invite_delivery_status=_coerce_optional_text(data.get("invite_delivery_status")),
        invite_last_attempt_at=_coerce_optional_text(data.get("invite_last_attempt_at")),
        invite_sent_at=_coerce_optional_text(data.get("invite_sent_at")),
        invite_delivery_error=_coerce_optional_text(data.get("invite_delivery_error")),
        invite_delivery_error_code=_coerce_optional_text(data.get("invite_delivery_error_code")),
        invite_message_id=_coerce_optional_text(data.get("invite_message_id")),
        manual_link_shared_at=_coerce_optional_text(data.get("manual_link_shared_at")),
        verification_required=bool(data.get("verification_required")),
        verification_method=_coerce_optional_text(data.get("verification_method")),
        verification_completed_at=_coerce_optional_text(data.get("verification_completed_at")),
        status=str(data.get("status") or SIGNING_STATUS_DRAFT).strip() or SIGNING_STATUS_DRAFT,
        anchors=_coerce_dict_list(data.get("anchors")),
        disclosure_version=str(data.get("disclosure_version") or "").strip(),
        business_disclosure_payload=_coerce_optional_dict(data.get("business_disclosure_payload")),
        business_disclosure_sha256=_coerce_optional_text(data.get("business_disclosure_sha256")),
        consumer_disclosure_version=_coerce_optional_text(data.get("consumer_disclosure_version")),
        consumer_disclosure_payload=_coerce_optional_dict(data.get("consumer_disclosure_payload")),
        consumer_disclosure_sha256=_coerce_optional_text(data.get("consumer_disclosure_sha256")),
        consumer_disclosure_presented_at=_coerce_optional_text(data.get("consumer_disclosure_presented_at")),
        consumer_consent_scope=_coerce_optional_text(data.get("consumer_consent_scope")),
        consumer_access_demonstrated_at=_coerce_optional_text(data.get("consumer_access_demonstrated_at")),
        consumer_access_demonstration_method=_coerce_optional_text(data.get("consumer_access_demonstration_method")),
        created_at=_coerce_optional_text(data.get("created_at")),
        updated_at=_coerce_optional_text(data.get("updated_at")),
        owner_review_confirmed_at=_coerce_optional_text(data.get("owner_review_confirmed_at")),
        sent_at=_coerce_optional_text(data.get("sent_at")),
        quota_consumed_at=_coerce_optional_text(data.get("quota_consumed_at")),
        quota_month_key=_coerce_month_key(data.get("quota_month_key")),
        opened_at=_coerce_optional_text(data.get("opened_at")),
        reviewed_at=_coerce_optional_text(data.get("reviewed_at")),
        consented_at=_coerce_optional_text(data.get("consented_at")),
        signature_adopted_at=_coerce_optional_text(data.get("signature_adopted_at")),
        signature_adopted_name=_coerce_optional_text(data.get("signature_adopted_name")),
        signature_adopted_mode=_coerce_optional_text(data.get("signature_adopted_mode")),
        signature_adopted_image_data_url=_coerce_optional_text(data.get("signature_adopted_image_data_url")),
        signature_adopted_image_sha256=_coerce_optional_text(data.get("signature_adopted_image_sha256")),
        representative_title=_coerce_optional_text(data.get("representative_title")),
        representative_company_name=_coerce_optional_text(data.get("representative_company_name")),
        authority_attested_at=_coerce_optional_text(data.get("authority_attested_at")),
        manual_fallback_requested_at=_coerce_optional_text(data.get("manual_fallback_requested_at")),
        manual_fallback_note=_coerce_optional_text(data.get("manual_fallback_note")),
        consent_withdrawn_at=_coerce_optional_text(data.get("consent_withdrawn_at")),
        completed_at=_coerce_optional_text(data.get("completed_at")),
        completed_session_id=_coerce_optional_text(data.get("completed_session_id")),
        completed_ip_address=_coerce_optional_text(data.get("completed_ip_address")),
        completed_user_agent=_coerce_optional_text(data.get("completed_user_agent")),
        completed_verification_method=_coerce_optional_text(data.get("completed_verification_method")),
        completed_verification_completed_at=_coerce_optional_text(data.get("completed_verification_completed_at")),
        completed_verification_session_id=_coerce_optional_text(data.get("completed_verification_session_id")),
        signed_pdf_bucket_path=_coerce_optional_text(data.get("signed_pdf_bucket_path")),
        signed_pdf_sha256=_coerce_optional_text(data.get("signed_pdf_sha256")),
        signed_pdf_digital_signature_method=_coerce_optional_text(data.get("signed_pdf_digital_signature_method")),
        signed_pdf_digital_signature_algorithm=_coerce_optional_text(data.get("signed_pdf_digital_signature_algorithm")),
        signed_pdf_digital_signature_field_name=_coerce_optional_text(data.get("signed_pdf_digital_signature_field_name")),
        signed_pdf_digital_signature_subfilter=_coerce_optional_text(data.get("signed_pdf_digital_signature_subfilter")),
        signed_pdf_digital_signature_timestamped=bool(data.get("signed_pdf_digital_signature_timestamped")),
        signed_pdf_digital_certificate_subject=_coerce_optional_text(data.get("signed_pdf_digital_certificate_subject")),
        signed_pdf_digital_certificate_issuer=_coerce_optional_text(data.get("signed_pdf_digital_certificate_issuer")),
        signed_pdf_digital_certificate_serial_number=_coerce_optional_text(data.get("signed_pdf_digital_certificate_serial_number")),
        signed_pdf_digital_certificate_fingerprint_sha256=_coerce_optional_text(data.get("signed_pdf_digital_certificate_fingerprint_sha256")),
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
        expires_at=_coerce_optional_text(data.get("expires_at")),
        public_link_version=_coerce_public_link_version(data.get("public_link_version")),
        public_link_revoked_at=_coerce_optional_text(data.get("public_link_revoked_at")),
        public_link_last_reissued_at=_coerce_optional_text(data.get("public_link_last_reissued_at")),
        invalidated_at=_coerce_optional_text(data.get("invalidated_at")),
        invalidation_reason=_coerce_optional_text(data.get("invalidation_reason")),
        public_app_origin=_coerce_optional_text(data.get("public_app_origin")),
    )


def _serialize_signing_usage_counter(doc) -> SigningMonthlyUsageRecord:
    data = doc.to_dict() or {}
    month_key = _coerce_month_key(data.get("month_key")) or _current_month_key()
    return SigningMonthlyUsageRecord(
        id=doc.id,
        user_id=str(data.get("user_id") or "").strip(),
        month_key=month_key,
        request_count=_coerce_nonnegative_int(data.get("request_count")),
        created_at=_coerce_optional_text(data.get("created_at")),
        updated_at=_coerce_optional_text(data.get("updated_at")),
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
        binding_ip_scope=_coerce_optional_text(data.get("binding_ip_scope")),
        binding_user_agent_hash=_coerce_optional_text(data.get("binding_user_agent_hash")),
        created_at=_coerce_optional_text(data.get("created_at")),
        updated_at=_coerce_optional_text(data.get("updated_at")),
        expires_at=_coerce_optional_text(data.get("expires_at")),
        completed_at=_coerce_optional_text(data.get("completed_at")),
        verification_code_hash=_coerce_optional_text(data.get("verification_code_hash")),
        verification_sent_at=_coerce_optional_text(data.get("verification_sent_at")),
        verification_expires_at=_coerce_optional_text(data.get("verification_expires_at")),
        verification_attempt_count=_coerce_nonnegative_int(data.get("verification_attempt_count")),
        verification_resend_count=_coerce_nonnegative_int(data.get("verification_resend_count")),
        verification_completed_at=_coerce_optional_text(data.get("verification_completed_at")),
        verification_message_id=_coerce_optional_text(data.get("verification_message_id")),
        consumer_access_attempt_count=_coerce_nonnegative_int(data.get("consumer_access_attempt_count")),
    )


class _MergedSnapshot:
    """Lightweight stand-in that satisfies _serialize_signing_request(doc)."""

    def __init__(self, doc_id: str, merged_data: Dict[str, Any]):
        self.id = doc_id
        self._data = merged_data

    def to_dict(self):
        return self._data


def _serialize_merged_signing_request(snapshot, merged_data: Dict[str, Any]) -> SigningRequestRecord:
    return _serialize_signing_request(_MergedSnapshot(snapshot.id, merged_data))


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
    company_binding_enabled: bool = False,
    authority_attestation_version: Optional[str] = None,
    authority_attestation_text: Optional[str] = None,
    authority_attestation_sha256: Optional[str] = None,
    sender_display_name: Optional[str] = None,
    esign_eligibility_confirmed_at: Optional[str] = None,
    esign_eligibility_confirmed_source: Optional[str] = None,
    sender_email: Optional[str] = None,
    sender_contact_email: Optional[str] = None,
    consumer_paper_copy_procedure: Optional[str] = None,
    consumer_paper_copy_fee_description: Optional[str] = None,
    consumer_withdrawal_procedure: Optional[str] = None,
    consumer_withdrawal_consequences: Optional[str] = None,
    consumer_contact_update_procedure: Optional[str] = None,
    consumer_consent_scope_override: Optional[str] = None,
    invite_method: Optional[str] = None,
    client=None,
) -> SigningRequestRecord:
    firestore_client = client or get_firestore_client()
    now_value = now_iso()
    request_id = uuid4().hex
    transport = resolve_signing_signer_transport(source_type)
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
        "esign_eligibility_confirmed_at": _coerce_optional_text(esign_eligibility_confirmed_at) or now_value,
        "esign_eligibility_confirmed_source": _coerce_optional_text(esign_eligibility_confirmed_source),
        "company_binding_enabled": bool(company_binding_enabled),
        "authority_attestation_version": _coerce_optional_text(authority_attestation_version),
        "authority_attestation_text": _coerce_optional_text(authority_attestation_text),
        "authority_attestation_sha256": _coerce_optional_text(authority_attestation_sha256),
        "manual_fallback_enabled": bool(manual_fallback_enabled),
        "signer_name": signer_name,
        "signer_email": signer_email,
        "signer_contact_method": transport.signer_contact_method,
        "signer_auth_method": transport.signer_auth_method,
        "sender_display_name": _coerce_optional_text(sender_display_name),
        "sender_email": _coerce_optional_text(sender_email),
        "sender_contact_email": _coerce_optional_text(sender_contact_email),
        "consumer_paper_copy_procedure": _coerce_optional_text(consumer_paper_copy_procedure),
        "consumer_paper_copy_fee_description": _coerce_optional_text(consumer_paper_copy_fee_description),
        "consumer_withdrawal_procedure": _coerce_optional_text(consumer_withdrawal_procedure),
        "consumer_withdrawal_consequences": _coerce_optional_text(consumer_withdrawal_consequences),
        "consumer_contact_update_procedure": _coerce_optional_text(consumer_contact_update_procedure),
        "consumer_consent_scope_override": _coerce_optional_text(consumer_consent_scope_override),
        "invite_method": _coerce_optional_text(invite_method),
        "invite_provider": None,
        "invite_delivery_status": None,
        "invite_last_attempt_at": None,
        "invite_sent_at": None,
        "invite_delivery_error": None,
        "invite_delivery_error_code": None,
        "invite_message_id": None,
        "manual_link_shared_at": None,
        "verification_required": transport.verification_required,
        "verification_method": transport.verification_method,
        "verification_completed_at": None,
        "status": SIGNING_STATUS_DRAFT,
        "anchors": list(anchors or []),
        "disclosure_version": disclosure_version,
        "business_disclosure_payload": None,
        "business_disclosure_sha256": None,
        "consumer_disclosure_version": None,
        "consumer_disclosure_payload": None,
        "consumer_disclosure_sha256": None,
        "consumer_disclosure_presented_at": None,
        "consumer_consent_scope": None,
        "consumer_access_demonstrated_at": None,
        "consumer_access_demonstration_method": None,
        "created_at": now_value,
        "updated_at": now_value,
        "owner_review_confirmed_at": None,
        "sent_at": None,
        "quota_consumed_at": None,
        "quota_month_key": None,
        "opened_at": None,
        "reviewed_at": None,
        "consented_at": None,
        "signature_adopted_at": None,
        "signature_adopted_name": None,
        "signature_adopted_mode": None,
        "signature_adopted_image_data_url": None,
        "signature_adopted_image_sha256": None,
        "representative_title": None,
        "representative_company_name": None,
        "authority_attested_at": None,
        "manual_fallback_requested_at": None,
        "manual_fallback_note": None,
        "consent_withdrawn_at": None,
        "completed_at": None,
        "completed_session_id": None,
        "completed_ip_address": None,
        "completed_user_agent": None,
        "completed_verification_method": None,
        "completed_verification_completed_at": None,
        "completed_verification_session_id": None,
        "signed_pdf_bucket_path": None,
        "signed_pdf_sha256": None,
        "signed_pdf_digital_signature_method": None,
        "signed_pdf_digital_signature_algorithm": None,
        "signed_pdf_digital_signature_field_name": None,
        "signed_pdf_digital_signature_subfilter": None,
        "signed_pdf_digital_signature_timestamped": False,
        "signed_pdf_digital_certificate_subject": None,
        "signed_pdf_digital_certificate_issuer": None,
        "signed_pdf_digital_certificate_serial_number": None,
        "signed_pdf_digital_certificate_fingerprint_sha256": None,
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
        "expires_at": None,
        "public_link_version": 1,
        "public_link_revoked_at": None,
        "public_link_last_reissued_at": None,
        "invalidated_at": None,
        "invalidation_reason": None,
        "public_app_origin": None,
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


def get_signing_monthly_usage(
    user_id: str,
    *,
    month_key: Optional[str] = None,
    client=None,
) -> Optional[SigningMonthlyUsageRecord]:
    normalized_user_id = str(user_id or "").strip()
    normalized_month_key = _coerce_month_key(month_key) or _current_month_key()
    if not normalized_user_id:
        return None
    firestore_client = client or get_firestore_client()
    snapshot = _signing_usage_counter_doc_ref(normalized_user_id, normalized_month_key, firestore_client).get()
    if not snapshot.exists:
        return None
    return _serialize_signing_usage_counter(snapshot)

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
    parsed = parse_signing_public_token_payload(token)
    if not parsed:
        return None
    request_id, public_link_version = parsed
    record = get_signing_request(request_id, client=client)
    if record is None:
        return None
    if _coerce_public_link_version(record.public_link_version) != public_link_version:
        return None
    return record


def get_signing_request_by_validation_token(token: str, *, client=None) -> Optional[SigningRequestRecord]:
    request_id = parse_signing_validation_token(token)
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
    binding_ip_scope: Optional[str],
    binding_user_agent_hash: Optional[str],
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
            "binding_ip_scope": _coerce_optional_text(binding_ip_scope),
            "binding_user_agent_hash": _coerce_optional_text(binding_user_agent_hash),
            "created_at": now_value,
            "updated_at": now_value,
            "expires_at": _coerce_optional_text(expires_at),
            "completed_at": None,
            "verification_code_hash": None,
            "verification_sent_at": None,
            "verification_expires_at": None,
            "verification_attempt_count": 0,
            "verification_resend_count": 0,
            "verification_completed_at": None,
            "verification_message_id": None,
            "consumer_access_attempt_count": 0,
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


def set_signing_session_verification_challenge(
    session_id: str,
    request_id: str,
    *,
    code_hash: str,
    sent_at: Optional[str],
    expires_at: Optional[str],
    verification_message_id: Optional[str] = None,
    client=None,
) -> Optional[SigningSessionRecord]:
    normalized_session_id = str(session_id or "").strip()
    normalized_request_id = str(request_id or "").strip()
    if not normalized_session_id or not normalized_request_id:
        return None
    firestore_client = client or get_firestore_client()
    doc_ref = firestore_client.collection(SIGNING_SESSIONS_COLLECTION).document(normalized_session_id)
    snapshot = doc_ref.get()
    if not snapshot.exists:
        return None
    data = snapshot.to_dict() or {}
    if str(data.get("request_id") or "").strip() != normalized_request_id:
        return None
    now_value = now_iso()
    next_resend_count = _coerce_nonnegative_int(data.get("verification_resend_count")) + 1
    doc_ref.set(
        {
            "verification_code_hash": _coerce_optional_text(code_hash),
            "verification_sent_at": _coerce_optional_text(sent_at) or now_value,
            "verification_expires_at": _coerce_optional_text(expires_at),
            "verification_attempt_count": 0,
            "verification_resend_count": next_resend_count,
            "verification_completed_at": None,
            "verification_message_id": _coerce_optional_text(verification_message_id),
            "updated_at": now_value,
        },
        merge=True,
    )
    return _serialize_signing_session(doc_ref.get())


def increment_signing_session_verification_attempt(
    session_id: str,
    request_id: str,
    *,
    client=None,
) -> Optional[SigningSessionRecord]:
    normalized_session_id = str(session_id or "").strip()
    normalized_request_id = str(request_id or "").strip()
    if not normalized_session_id or not normalized_request_id:
        return None
    firestore_client = client or get_firestore_client()
    doc_ref = firestore_client.collection(SIGNING_SESSIONS_COLLECTION).document(normalized_session_id)
    snapshot = doc_ref.get()
    if not snapshot.exists:
        return None
    data = snapshot.to_dict() or {}
    if str(data.get("request_id") or "").strip() != normalized_request_id:
        return None
    doc_ref.set(
        {
            "verification_attempt_count": _coerce_nonnegative_int(data.get("verification_attempt_count")) + 1,
            "updated_at": now_iso(),
        },
        merge=True,
    )
    return _serialize_signing_session(doc_ref.get())


def mark_signing_session_verified(
    session_id: str,
    request_id: str,
    *,
    verification_method: Optional[str],
    verified_at: Optional[str] = None,
    client=None,
) -> Optional[SigningSessionRecord]:
    normalized_session_id = str(session_id or "").strip()
    normalized_request_id = str(request_id or "").strip()
    if not normalized_session_id or not normalized_request_id:
        return None
    firestore_client = client or get_firestore_client()
    session_ref = firestore_client.collection(SIGNING_SESSIONS_COLLECTION).document(normalized_session_id)
    snapshot = session_ref.get()
    if not snapshot.exists:
        return None
    data = snapshot.to_dict() or {}
    if str(data.get("request_id") or "").strip() != normalized_request_id:
        return None
    now_value = _coerce_optional_text(verified_at) or now_iso()
    session_ref.set(
        {
            "verification_code_hash": None,
            "verification_sent_at": None,
            "verification_expires_at": None,
            "verification_attempt_count": 0,
            "verification_resend_count": 0,
            "verification_completed_at": now_value,
            "verification_message_id": None,
            "updated_at": now_value,
        },
        merge=True,
    )
    request_ref = firestore_client.collection(SIGNING_REQUESTS_COLLECTION).document(normalized_request_id)
    request_snapshot = request_ref.get()
    if request_snapshot.exists:
        request_data = request_snapshot.to_dict() or {}
        if (
            not _coerce_optional_text(request_data.get("verification_completed_at"))
            and str(request_data.get("status") or "").strip() != SIGNING_STATUS_COMPLETED
        ):
            request_ref.set(
                {
                    "verification_method": _coerce_optional_text(verification_method),
                    "verification_completed_at": now_value,
                    "updated_at": now_value,
                },
                merge=True,
            )
    return _serialize_signing_session(session_ref.get())


def increment_signing_session_consumer_access_attempt(
    session_id: str,
    request_id: str,
    *,
    client=None,
) -> Optional[SigningSessionRecord]:
    normalized_session_id = str(session_id or "").strip()
    normalized_request_id = str(request_id or "").strip()
    if not normalized_session_id or not normalized_request_id:
        return None
    firestore_client = client or get_firestore_client()
    doc_ref = firestore_client.collection(SIGNING_SESSIONS_COLLECTION).document(normalized_session_id)
    snapshot = doc_ref.get()
    if not snapshot.exists:
        return None
    data = snapshot.to_dict() or {}
    if str(data.get("request_id") or "").strip() != normalized_request_id:
        return None
    doc_ref.set(
        {
            "consumer_access_attempt_count": _coerce_nonnegative_int(data.get("consumer_access_attempt_count")) + 1,
            "updated_at": now_iso(),
        },
        merge=True,
    )
    return _serialize_signing_session(doc_ref.get())


def reset_signing_session_consumer_access_attempts(
    session_id: str,
    request_id: str,
    *,
    client=None,
) -> Optional[SigningSessionRecord]:
    normalized_session_id = str(session_id or "").strip()
    normalized_request_id = str(request_id or "").strip()
    if not normalized_session_id or not normalized_request_id:
        return None
    firestore_client = client or get_firestore_client()
    doc_ref = firestore_client.collection(SIGNING_SESSIONS_COLLECTION).document(normalized_session_id)
    snapshot = doc_ref.get()
    if not snapshot.exists:
        return None
    data = snapshot.to_dict() or {}
    if str(data.get("request_id") or "").strip() != normalized_request_id:
        return None
    doc_ref.set(
        {
            "consumer_access_attempt_count": 0,
            "updated_at": now_iso(),
        },
        merge=True,
    )
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
    required_present_fields: tuple[str, ...] = (),
    required_absent_fields: tuple[str, ...] = (),
    updates: Dict[str, Any],
    client=None,
) -> Optional[SigningRequestRecord]:
    normalized_request_id = str(request_id or "").strip()
    if not normalized_request_id:
        return None
    firestore_client = client or get_firestore_client()
    doc_ref = firestore_client.collection(SIGNING_REQUESTS_COLLECTION).document(normalized_request_id)
    payload = dict(updates or {})
    payload["updated_at"] = _coerce_optional_text(payload.get("updated_at")) or now_iso()

    def _preconditions_met(data: Dict[str, Any], *, current_status: str) -> bool:
        if allowed_statuses and current_status not in allowed_statuses:
            return False
        if any(not _has_field_value(data.get(field_name)) for field_name in required_present_fields):
            return False
        if any(_has_field_value(data.get(field_name)) for field_name in required_absent_fields):
            return False
        return True

    transaction = firestore_client.transaction()
    if _supports_firestore_transaction(transaction):
        @firebase_firestore.transactional
        def _run(txn):
            snapshot = doc_ref.get(transaction=txn)
            if not snapshot.exists:
                return None
            data = snapshot.to_dict() or {}
            current_status = str(data.get("status") or "").strip()
            if not _preconditions_met(data, current_status=current_status):
                return _serialize_signing_request(snapshot)
            txn.set(doc_ref, payload, merge=True)
            merged = dict(data)
            merged.update(payload)
            return _serialize_merged_signing_request(snapshot, merged)

        return _run(transaction)

    snapshot = doc_ref.get()
    if not snapshot.exists:
        return None
    data = snapshot.to_dict() or {}
    current_status = str(data.get("status") or "").strip()
    if not _preconditions_met(data, current_status=current_status):
        return _serialize_signing_request(snapshot)
    doc_ref.set(payload, merge=True)
    return _serialize_signing_request(doc_ref.get())


def mark_signing_request_sent(
    request_id: str,
    user_id: str,
    *,
    source_pdf_bucket_path: str,
    source_pdf_sha256: str,
    source_version: Optional[str],
    monthly_limit: Optional[int] = None,
    owner_review_confirmed_at: Optional[str] = None,
    public_app_origin: Optional[str] = None,
    client=None,
) -> Optional[SigningRequestRecord]:
    normalized_request_id = str(request_id or "").strip()
    normalized_user_id = str(user_id or "").strip()
    if not normalized_request_id or not normalized_user_id:
        return None
    firestore_client = client or get_firestore_client()
    doc_ref = firestore_client.collection(SIGNING_REQUESTS_COLLECTION).document(normalized_request_id)
    normalized_monthly_limit = None if monthly_limit is None else max(0, int(monthly_limit))

    def _build_sent_payload(data: Dict[str, Any], *, now_value: str, quota_month_key: Optional[str]) -> Dict[str, Any]:
        request_expires_at = resolve_signing_request_expires_at(sent_at=now_value)
        retention_until = _coerce_optional_text(data.get("retention_until")) or resolve_signing_retention_until(now_value)
        transport = resolve_signing_signer_transport(
            _coerce_optional_text(data.get("source_type")) or "workspace",
            signer_contact_method=_coerce_optional_text(data.get("signer_contact_method")),
        )
        return {
            "status": SIGNING_STATUS_SENT,
            "source_pdf_bucket_path": str(source_pdf_bucket_path or "").strip() or None,
            "source_pdf_sha256": str(source_pdf_sha256 or "").strip() or None,
            "source_version": str(source_version or "").strip() or None,
            "signer_contact_method": transport.signer_contact_method,
            "signer_auth_method": transport.signer_auth_method,
            "invite_delivery_status": "pending",
            "invite_last_attempt_at": None,
            "invite_sent_at": None,
            "invite_delivery_error": None,
            "invite_delivery_error_code": None,
            "invite_provider": None,
            "invite_message_id": None,
            "verification_required": transport.verification_required,
            "verification_method": transport.verification_method,
            "verification_completed_at": None,
            "owner_review_confirmed_at": _coerce_optional_text(owner_review_confirmed_at),
            "sent_at": now_value,
            "quota_consumed_at": now_value if quota_month_key else None,
            "quota_month_key": quota_month_key,
            "business_disclosure_payload": None,
            "business_disclosure_sha256": None,
            "consumer_disclosure_version": None,
            "consumer_disclosure_payload": None,
            "consumer_disclosure_sha256": None,
            "consumer_disclosure_presented_at": None,
            "consumer_consent_scope": None,
            "consumer_access_demonstrated_at": None,
            "consumer_access_demonstration_method": None,
            "opened_at": None,
            "reviewed_at": None,
            "consented_at": None,
            "signature_adopted_at": None,
            "signature_adopted_name": None,
            "signature_adopted_mode": None,
            "signature_adopted_image_data_url": None,
            "signature_adopted_image_sha256": None,
            "manual_fallback_requested_at": None,
            "manual_fallback_note": None,
            "consent_withdrawn_at": None,
            "completed_at": None,
            "completed_session_id": None,
            "completed_ip_address": None,
            "completed_user_agent": None,
            "completed_verification_method": None,
            "completed_verification_completed_at": None,
            "completed_verification_session_id": None,
            "signed_pdf_bucket_path": None,
            "signed_pdf_sha256": None,
            "signed_pdf_digital_signature_method": None,
            "signed_pdf_digital_signature_algorithm": None,
            "signed_pdf_digital_signature_field_name": None,
            "signed_pdf_digital_signature_subfilter": None,
            "signed_pdf_digital_signature_timestamped": False,
            "signed_pdf_digital_certificate_subject": None,
            "signed_pdf_digital_certificate_issuer": None,
            "signed_pdf_digital_certificate_serial_number": None,
            "signed_pdf_digital_certificate_fingerprint_sha256": None,
            "audit_manifest_bucket_path": None,
            "audit_manifest_sha256": None,
            "audit_receipt_bucket_path": None,
            "audit_receipt_sha256": None,
            "audit_signature_method": None,
            "audit_signature_algorithm": None,
            "audit_kms_key_resource_name": None,
            "audit_kms_key_version_name": None,
            "artifacts_generated_at": None,
            "retention_until": retention_until,
            "expires_at": request_expires_at,
            "public_link_version": _coerce_public_link_version(data.get("public_link_version")),
            "public_link_revoked_at": None,
            "public_link_last_reissued_at": None,
            "invalidated_at": None,
            "invalidation_reason": None,
            "public_app_origin": _coerce_optional_text(public_app_origin),
            "updated_at": now_value,
        }

    def _reserve_monthly_quota_if_needed(
        data: Dict[str, Any],
        *,
        now_value: str,
        transaction=None,
    ) -> tuple[Optional[Dict[str, Any]], Optional[str]]:
        if normalized_monthly_limit is None:
            return None, None
        quota_consumed_at = _coerce_optional_text(data.get("quota_consumed_at"))
        quota_month_key = _coerce_month_key(data.get("quota_month_key"))
        if quota_consumed_at and quota_month_key:
            return None, quota_month_key
        if normalized_monthly_limit <= 0:
            raise SigningRequestMonthlyLimitError(limit=normalized_monthly_limit)
        month_key = _current_month_key()
        usage_doc_ref = _signing_usage_counter_doc_ref(normalized_user_id, month_key, firestore_client)
        usage_snapshot = usage_doc_ref.get(transaction=transaction) if transaction is not None else usage_doc_ref.get()
        usage_record = _serialize_signing_usage_counter(usage_snapshot) if usage_snapshot.exists else None
        current_usage = usage_record.request_count if usage_record is not None else 0
        if current_usage >= normalized_monthly_limit:
            raise SigningRequestMonthlyLimitError(limit=normalized_monthly_limit)
        usage_payload = {
            "user_id": normalized_user_id,
            "month_key": month_key,
            "request_count": current_usage + 1,
            "created_at": usage_record.created_at if usage_record is not None and usage_record.created_at else now_value,
            "updated_at": now_value,
        }
        return {"doc_ref": usage_doc_ref, "payload": usage_payload}, month_key

    def _merge_payload(data: Dict[str, Any], payload: Dict[str, Any]) -> Dict[str, Any]:
        merged = dict(data)
        merged.update(payload)
        return merged

    transaction = firestore_client.transaction()
    if _supports_firestore_transaction(transaction):
        @firebase_firestore.transactional
        def _run(txn):
            snapshot = doc_ref.get(transaction=txn)
            if not snapshot.exists:
                return None
            data = snapshot.to_dict() or {}
            if str(data.get("user_id") or "").strip() != normalized_user_id:
                return None
            current_status = str(data.get("status") or "").strip()
            if current_status != SIGNING_STATUS_DRAFT:
                return _serialize_signing_request(snapshot)
            now_value = now_iso()
            usage_update, quota_month_key = _reserve_monthly_quota_if_needed(data, now_value=now_value, transaction=txn)
            payload = _build_sent_payload(data, now_value=now_value, quota_month_key=quota_month_key)
            if usage_update is not None:
                txn.set(usage_update["doc_ref"], usage_update["payload"], merge=True)
            txn.set(doc_ref, payload, merge=True)
            return _serialize_merged_signing_request(snapshot, _merge_payload(data, payload))

        return _run(transaction)

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
    usage_update, quota_month_key = _reserve_monthly_quota_if_needed(data, now_value=now_value)
    payload = _build_sent_payload(data, now_value=now_value, quota_month_key=quota_month_key)
    if usage_update is not None:
        usage_update["doc_ref"].set(usage_update["payload"], merge=True)
    doc_ref.set(payload, merge=True)
    return _serialize_signing_request(doc_ref.get())


def rollback_signing_request_sent(
    request_id: str,
    user_id: str,
    *,
    expected_source_pdf_bucket_path: Optional[str] = None,
    expected_source_pdf_sha256: Optional[str] = None,
    client=None,
) -> Optional[SigningRequestRecord]:
    normalized_request_id = str(request_id or "").strip()
    normalized_user_id = str(user_id or "").strip()
    expected_bucket_path = _coerce_optional_text(expected_source_pdf_bucket_path)
    expected_sha256 = _coerce_optional_text(expected_source_pdf_sha256)
    if not normalized_request_id or not normalized_user_id:
        return None
    firestore_client = client or get_firestore_client()
    doc_ref = firestore_client.collection(SIGNING_REQUESTS_COLLECTION).document(normalized_request_id)
    payload = {
        "status": SIGNING_STATUS_DRAFT,
        "sent_at": None,
        "source_pdf_bucket_path": None,
        "source_pdf_sha256": None,
        "source_version": None,
        "signer_contact_method": None,
        "signer_auth_method": None,
        "invite_delivery_status": None,
        "invite_last_attempt_at": None,
        "invite_sent_at": None,
        "invite_delivery_error": None,
        "invite_delivery_error_code": None,
        "invite_provider": None,
        "invite_message_id": None,
        "verification_required": False,
        "verification_method": None,
        "verification_completed_at": None,
        "quota_consumed_at": None,
        "quota_month_key": None,
        "business_disclosure_payload": None,
        "business_disclosure_sha256": None,
        "consumer_disclosure_version": None,
        "consumer_disclosure_payload": None,
        "consumer_disclosure_sha256": None,
        "consumer_disclosure_presented_at": None,
        "consumer_consent_scope": None,
        "consumer_access_demonstrated_at": None,
        "consumer_access_demonstration_method": None,
        "opened_at": None,
        "reviewed_at": None,
        "consented_at": None,
        "signature_adopted_at": None,
        "signature_adopted_name": None,
        "signature_adopted_mode": None,
        "signature_adopted_image_data_url": None,
        "signature_adopted_image_sha256": None,
        "manual_fallback_requested_at": None,
        "manual_fallback_note": None,
        "consent_withdrawn_at": None,
        "completed_at": None,
        "completed_session_id": None,
        "completed_ip_address": None,
        "completed_user_agent": None,
        "completed_verification_method": None,
        "completed_verification_completed_at": None,
        "completed_verification_session_id": None,
        "signed_pdf_bucket_path": None,
        "signed_pdf_sha256": None,
        "signed_pdf_digital_signature_method": None,
        "signed_pdf_digital_signature_algorithm": None,
        "signed_pdf_digital_signature_field_name": None,
        "signed_pdf_digital_signature_subfilter": None,
        "signed_pdf_digital_signature_timestamped": False,
        "signed_pdf_digital_certificate_subject": None,
        "signed_pdf_digital_certificate_issuer": None,
        "signed_pdf_digital_certificate_serial_number": None,
        "signed_pdf_digital_certificate_fingerprint_sha256": None,
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
        "expires_at": None,
        "invalidated_at": None,
        "invalidation_reason": None,
        "public_app_origin": None,
        "updated_at": now_iso(),
    }

    def _build_usage_decrement(data: Dict[str, Any], *, now_value: str):
        quota_month_key = _coerce_month_key(data.get("quota_month_key"))
        if not quota_month_key or not _coerce_optional_text(data.get("quota_consumed_at")):
            return None
        usage_doc_ref = _signing_usage_counter_doc_ref(normalized_user_id, quota_month_key, firestore_client)
        return {"doc_ref": usage_doc_ref, "month_key": quota_month_key, "updated_at": now_value}

    def _preconditions_met(data: Dict[str, Any]) -> bool:
        if str(data.get("user_id") or "").strip() != normalized_user_id:
            return False
        if str(data.get("status") or "").strip() != SIGNING_STATUS_SENT:
            return False
        if expected_bucket_path and _coerce_optional_text(data.get("source_pdf_bucket_path")) != expected_bucket_path:
            return False
        if expected_sha256 and _coerce_optional_text(data.get("source_pdf_sha256")) != expected_sha256:
            return False
        return not any(
            _has_field_value(data.get(field_name))
            for field_name in (
                "opened_at",
                "reviewed_at",
                "consented_at",
                "signature_adopted_at",
                "manual_fallback_requested_at",
                "consent_withdrawn_at",
                "completed_at",
            )
        )

    transaction = firestore_client.transaction()
    if _supports_firestore_transaction(transaction):
        @firebase_firestore.transactional
        def _run(txn):
            snapshot = doc_ref.get(transaction=txn)
            if not snapshot.exists:
                return None
            data = snapshot.to_dict() or {}
            if not _preconditions_met(data):
                return _serialize_signing_request(snapshot)
            usage_decrement = _build_usage_decrement(data, now_value=payload["updated_at"])
            if usage_decrement is not None:
                usage_snapshot = usage_decrement["doc_ref"].get(transaction=txn)
                if usage_snapshot.exists:
                    usage_record = _serialize_signing_usage_counter(usage_snapshot)
                    txn.set(
                        usage_decrement["doc_ref"],
                        {
                            "user_id": normalized_user_id,
                            "month_key": usage_record.month_key,
                            "request_count": max(0, usage_record.request_count - 1),
                            "created_at": usage_record.created_at,
                            "updated_at": usage_decrement["updated_at"],
                        },
                        merge=True,
                    )
            txn.set(doc_ref, payload, merge=True)
            merged = dict(data)
            merged.update(payload)
            return _serialize_merged_signing_request(snapshot, merged)

        return _run(transaction)

    snapshot = doc_ref.get()
    if not snapshot.exists:
        return None
    data = snapshot.to_dict() or {}
    if not _preconditions_met(data):
        return _serialize_signing_request(snapshot)
    usage_decrement = _build_usage_decrement(data, now_value=payload["updated_at"])
    if usage_decrement is not None:
        usage_snapshot = usage_decrement["doc_ref"].get()
        if usage_snapshot.exists:
            usage_record = _serialize_signing_usage_counter(usage_snapshot)
            usage_decrement["doc_ref"].set(
                {
                    "user_id": normalized_user_id,
                    "month_key": usage_record.month_key,
                    "request_count": max(0, usage_record.request_count - 1),
                    "created_at": usage_record.created_at,
                    "updated_at": usage_decrement["updated_at"],
                },
                merge=True,
            )
    doc_ref.set(payload, merge=True)
    return _serialize_signing_request(doc_ref.get())


def store_signing_request_business_disclosure(
    request_id: str,
    *,
    disclosure_payload: Dict[str, Any],
    disclosure_sha256: Optional[str],
    client=None,
) -> Optional[SigningRequestRecord]:
    normalized_request_id = str(request_id or "").strip()
    if not normalized_request_id:
        return None
    return _update_public_signing_request(
        normalized_request_id,
        allowed_statuses={SIGNING_STATUS_SENT},
        updates={
            "business_disclosure_payload": dict(disclosure_payload or {}),
            "business_disclosure_sha256": _coerce_optional_text(disclosure_sha256),
        },
        client=client,
    )


def store_signing_request_consumer_disclosure(
    request_id: str,
    *,
    disclosure_version: Optional[str],
    disclosure_payload: Dict[str, Any],
    disclosure_sha256: Optional[str],
    consent_scope: Optional[str],
    reset_ceremony_progress: bool = False,
    client=None,
) -> Optional[SigningRequestRecord]:
    normalized_request_id = str(request_id or "").strip()
    if not normalized_request_id:
        return None
    updates = {
        "consumer_disclosure_version": _coerce_optional_text(disclosure_version),
        "consumer_disclosure_payload": dict(disclosure_payload or {}),
        "consumer_disclosure_sha256": _coerce_optional_text(disclosure_sha256),
        "consumer_consent_scope": _coerce_optional_text(consent_scope),
    }
    if reset_ceremony_progress:
        updates.update(
            {
                "consumer_disclosure_presented_at": None,
                "consented_at": None,
                "consumer_access_demonstrated_at": None,
                "consumer_access_demonstration_method": None,
                "reviewed_at": None,
                "signature_adopted_at": None,
                "signature_adopted_name": None,
                "signature_adopted_mode": None,
                "signature_adopted_image_data_url": None,
                "signature_adopted_image_sha256": None,
            }
        )
    return _update_public_signing_request(
        normalized_request_id,
        allowed_statuses={SIGNING_STATUS_SENT},
        updates=updates,
        client=client,
    )


def mark_signing_request_consumer_disclosure_presented(
    request_id: str,
    *,
    presented_at: Optional[str] = None,
    client=None,
) -> Optional[SigningRequestRecord]:
    now_value = _coerce_optional_text(presented_at) or now_iso()
    return _update_public_signing_request(
        request_id,
        allowed_statuses={SIGNING_STATUS_SENT},
        required_absent_fields=("consumer_disclosure_presented_at",),
        updates={
            "consumer_disclosure_presented_at": now_value,
            "updated_at": now_value,
        },
        client=client,
    )


def mark_signing_request_invite_delivery(
    request_id: str,
    user_id: str,
    *,
    delivery_status: str,
    sender_email: Optional[str] = None,
    invite_method: Optional[str] = None,
    invite_provider: Optional[str] = None,
    attempted_at: Optional[str] = None,
    sent_at: Optional[str] = None,
    delivery_error: Optional[str] = None,
    delivery_error_code: Optional[str] = None,
    invite_message_id: Optional[str] = None,
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
            "sender_email": _coerce_optional_text(sender_email),
            "invite_method": _coerce_optional_text(invite_method),
            "invite_provider": _coerce_optional_text(invite_provider),
            "invite_delivery_status": normalized_status,
            "invite_last_attempt_at": _coerce_optional_text(attempted_at) or now_value,
            "invite_sent_at": _coerce_optional_text(sent_at),
            "invite_delivery_error": _coerce_optional_text(delivery_error),
            "invite_delivery_error_code": _coerce_optional_text(delivery_error_code),
            "invite_message_id": _coerce_optional_text(invite_message_id),
            "updated_at": now_value,
        },
        merge=True,
    )
    return _serialize_signing_request(doc_ref.get())


def mark_signing_request_manual_link_shared(
    request_id: str,
    user_id: str,
    *,
    sender_email: Optional[str] = None,
    shared_at: Optional[str] = None,
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
    now_value = _coerce_optional_text(shared_at) or now_iso()
    doc_ref.set(
        {
            "sender_email": _coerce_optional_text(sender_email),
            "invite_method": "manual_link",
            "manual_link_shared_at": now_value,
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
    reviewed_at: Optional[str] = None,
    client=None,
) -> Optional[SigningRequestRecord]:
    now_value = _coerce_optional_text(reviewed_at) or now_iso()
    return _update_public_signing_request(
        request_id,
        allowed_statuses={SIGNING_STATUS_SENT},
        required_absent_fields=("manual_fallback_requested_at", "consent_withdrawn_at", "reviewed_at"),
        updates={
            "reviewed_at": now_value,
            "last_public_session_id": _coerce_optional_text(session_id),
            "last_public_ip": _coerce_optional_text(client_ip),
            "last_public_user_agent": _coerce_optional_text(user_agent),
            "updated_at": now_value,
        },
        client=client,
    )


def mark_signing_request_consented(
    request_id: str,
    *,
    session_id: str,
    client_ip: Optional[str],
    user_agent: Optional[str],
    consented_at: Optional[str] = None,
    consumer_access_demonstrated_at: Optional[str] = None,
    consumer_access_demonstration_method: Optional[str] = None,
    client=None,
) -> Optional[SigningRequestRecord]:
    now_value = _coerce_optional_text(consented_at) or now_iso()
    return _update_public_signing_request(
        request_id,
        allowed_statuses={SIGNING_STATUS_SENT},
        required_absent_fields=("manual_fallback_requested_at", "consent_withdrawn_at", "consented_at"),
        updates={
            "consented_at": now_value,
            "consumer_access_demonstrated_at": _coerce_optional_text(consumer_access_demonstrated_at) or now_value,
            "consumer_access_demonstration_method": _coerce_optional_text(consumer_access_demonstration_method),
            "last_public_session_id": _coerce_optional_text(session_id),
            "last_public_ip": _coerce_optional_text(client_ip),
            "last_public_user_agent": _coerce_optional_text(user_agent),
            "updated_at": now_value,
        },
        client=client,
    )


def mark_signing_request_signature_adopted(
    request_id: str,
    *,
    session_id: str,
    adopted_name: str,
    adopted_mode: Optional[str],
    signature_image_data_url: Optional[str],
    signature_image_sha256: Optional[str],
    client_ip: Optional[str],
    user_agent: Optional[str],
    signature_adopted_at: Optional[str] = None,
    client=None,
) -> Optional[SigningRequestRecord]:
    now_value = _coerce_optional_text(signature_adopted_at) or now_iso()
    return _update_public_signing_request(
        request_id,
        allowed_statuses={SIGNING_STATUS_SENT},
        required_present_fields=("reviewed_at",),
        required_absent_fields=("manual_fallback_requested_at", "consent_withdrawn_at", "signature_adopted_at"),
        updates={
            "signature_adopted_at": now_value,
            "signature_adopted_name": _coerce_optional_text(adopted_name),
            "signature_adopted_mode": _coerce_optional_text(adopted_mode),
            "signature_adopted_image_data_url": _coerce_optional_text(signature_image_data_url),
            "signature_adopted_image_sha256": _coerce_optional_text(signature_image_sha256),
            "last_public_session_id": _coerce_optional_text(session_id),
            "last_public_ip": _coerce_optional_text(client_ip),
            "last_public_user_agent": _coerce_optional_text(user_agent),
            "updated_at": now_value,
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
    requested_at: Optional[str] = None,
    client=None,
) -> Optional[SigningRequestRecord]:
    now_value = _coerce_optional_text(requested_at) or now_iso()
    return _update_public_signing_request(
        request_id,
        allowed_statuses={SIGNING_STATUS_SENT},
        required_absent_fields=("manual_fallback_requested_at", "consent_withdrawn_at"),
        updates={
            "manual_fallback_requested_at": now_value,
            "manual_fallback_note": _coerce_optional_text(note),
            "last_public_session_id": _coerce_optional_text(session_id),
            "last_public_ip": _coerce_optional_text(client_ip),
            "last_public_user_agent": _coerce_optional_text(user_agent),
            "updated_at": now_value,
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
    required_present_fields: tuple[str, ...] = (),
    required_absent_fields: tuple[str, ...] = (),
    client=None,
) -> Optional[SigningRequestRecord]:
    now_value = _coerce_optional_text(completed_at) or now_iso()
    normalized_artifact_updates = dict(artifact_updates or {})
    return _update_public_signing_request(
        request_id,
        allowed_statuses={SIGNING_STATUS_SENT},
        required_present_fields=required_present_fields,
        required_absent_fields=required_absent_fields,
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


def complete_signing_request_transactional(
    request_id: str,
    *,
    session_id: str,
    client_ip: Optional[str],
    user_agent: Optional[str],
    completed_at: Optional[str] = None,
    artifact_updates: Optional[Dict[str, Any]] = None,
    required_present_fields: tuple[str, ...] = (),
    required_absent_fields: tuple[str, ...] = (),
    client=None,
) -> Optional[SigningRequestRecord]:
    """Atomically transition a signing request from sent to completed using a Firestore transaction.

    Returns the updated record on success, or the current record (without modifications) if the
    status precondition is not met (e.g. another request already completed it).
    """

    normalized_request_id = str(request_id or "").strip()
    if not normalized_request_id:
        return None
    now_value = _coerce_optional_text(completed_at) or now_iso()
    normalized_artifact_updates = dict(artifact_updates or {})
    firestore_client = client or get_firestore_client()
    doc_ref = firestore_client.collection(SIGNING_REQUESTS_COLLECTION).document(normalized_request_id)
    transaction = firestore_client.transaction()
    if not _supports_firestore_transaction(transaction):
        return complete_signing_request(
            normalized_request_id,
            session_id=session_id,
            client_ip=client_ip,
            user_agent=user_agent,
            completed_at=now_value,
            artifact_updates=normalized_artifact_updates,
            required_present_fields=required_present_fields,
            required_absent_fields=required_absent_fields,
            client=firestore_client,
        )

    @firebase_firestore.transactional
    def _run(txn):
        snapshot = doc_ref.get(transaction=txn)
        if not snapshot.exists:
            return None
        data = snapshot.to_dict() or {}
        current_status = str(data.get("status") or "").strip()
        if current_status != SIGNING_STATUS_SENT:
            return _serialize_signing_request(snapshot)
        if any(not _has_field_value(data.get(field_name)) for field_name in required_present_fields):
            return _serialize_signing_request(snapshot)
        if any(_has_field_value(data.get(field_name)) for field_name in required_absent_fields):
            return _serialize_signing_request(snapshot)
        payload = {
            "status": SIGNING_STATUS_COMPLETED,
            "completed_at": now_value,
            "completed_session_id": _coerce_optional_text(session_id),
            "completed_ip_address": _coerce_optional_text(client_ip),
            "completed_user_agent": _coerce_optional_text(user_agent),
            "updated_at": now_value,
            **normalized_artifact_updates,
        }
        txn.set(doc_ref, payload, merge=True)
        merged = dict(data)
        merged.update(payload)
        return _serialize_merged_signing_request(snapshot, merged)

    return _run(transaction)


def rollback_completed_signing_request_transactional(
    request_id: str,
    *,
    session_id: Optional[str],
    completed_at: Optional[str] = None,
    client=None,
) -> Optional[SigningRequestRecord]:
    """Revert a just-completed request back to sent when artifact finalization fails.

    This helper is intentionally narrow: it only clears completion/artifact
    fields when the request is still marked completed for the same session and
    completion timestamp. That keeps the rollback O(1) and avoids clobbering a
    later successful completion attempt from another concurrent request.
    """

    normalized_request_id = str(request_id or "").strip()
    expected_session_id = _coerce_optional_text(session_id)
    expected_completed_at = _coerce_optional_text(completed_at)
    if not normalized_request_id:
        return None
    firestore_client = client or get_firestore_client()
    doc_ref = firestore_client.collection(SIGNING_REQUESTS_COLLECTION).document(normalized_request_id)
    transaction = firestore_client.transaction()
    if not _supports_firestore_transaction(transaction):
        snapshot = doc_ref.get()
        if not snapshot.exists:
            return None
        data = snapshot.to_dict() or {}
        if str(data.get("status") or "").strip() != SIGNING_STATUS_COMPLETED:
            return _serialize_signing_request(snapshot)
        if expected_session_id and _coerce_optional_text(data.get("completed_session_id")) != expected_session_id:
            return _serialize_signing_request(snapshot)
        if expected_completed_at and _coerce_optional_text(data.get("completed_at")) != expected_completed_at:
            return _serialize_signing_request(snapshot)
        payload = {
            "status": SIGNING_STATUS_SENT,
            "completed_at": None,
            "completed_session_id": None,
            "completed_ip_address": None,
            "completed_user_agent": None,
            "completed_verification_method": None,
            "completed_verification_completed_at": None,
            "completed_verification_session_id": None,
            "signed_pdf_bucket_path": None,
            "signed_pdf_sha256": None,
            "signed_pdf_digital_signature_method": None,
            "signed_pdf_digital_signature_algorithm": None,
            "signed_pdf_digital_signature_field_name": None,
            "signed_pdf_digital_signature_subfilter": None,
            "signed_pdf_digital_signature_timestamped": False,
            "signed_pdf_digital_certificate_subject": None,
            "signed_pdf_digital_certificate_issuer": None,
            "signed_pdf_digital_certificate_serial_number": None,
            "signed_pdf_digital_certificate_fingerprint_sha256": None,
            "audit_manifest_bucket_path": None,
            "audit_manifest_sha256": None,
            "audit_receipt_bucket_path": None,
            "audit_receipt_sha256": None,
            "audit_signature_method": None,
            "audit_signature_algorithm": None,
            "audit_kms_key_resource_name": None,
            "audit_kms_key_version_name": None,
            "artifacts_generated_at": None,
            "updated_at": now_iso(),
        }
        doc_ref.set(payload, merge=True)
        merged = dict(data)
        merged.update(payload)
        return _serialize_merged_signing_request(snapshot, merged)

    @firebase_firestore.transactional
    def _run(txn):
        snapshot = doc_ref.get(transaction=txn)
        if not snapshot.exists:
            return None
        data = snapshot.to_dict() or {}
        if str(data.get("status") or "").strip() != SIGNING_STATUS_COMPLETED:
            return _serialize_signing_request(snapshot)
        if expected_session_id and _coerce_optional_text(data.get("completed_session_id")) != expected_session_id:
            return _serialize_signing_request(snapshot)
        if expected_completed_at and _coerce_optional_text(data.get("completed_at")) != expected_completed_at:
            return _serialize_signing_request(snapshot)

        payload = {
            "status": SIGNING_STATUS_SENT,
            "completed_at": None,
            "completed_session_id": None,
            "completed_ip_address": None,
            "completed_user_agent": None,
            "completed_verification_method": None,
            "completed_verification_completed_at": None,
            "completed_verification_session_id": None,
            "signed_pdf_bucket_path": None,
            "signed_pdf_sha256": None,
            "signed_pdf_digital_signature_method": None,
            "signed_pdf_digital_signature_algorithm": None,
            "signed_pdf_digital_signature_field_name": None,
            "signed_pdf_digital_signature_subfilter": None,
            "signed_pdf_digital_signature_timestamped": False,
            "signed_pdf_digital_certificate_subject": None,
            "signed_pdf_digital_certificate_issuer": None,
            "signed_pdf_digital_certificate_serial_number": None,
            "signed_pdf_digital_certificate_fingerprint_sha256": None,
            "audit_manifest_bucket_path": None,
            "audit_manifest_sha256": None,
            "audit_receipt_bucket_path": None,
            "audit_receipt_sha256": None,
            "audit_signature_method": None,
            "audit_signature_algorithm": None,
            "audit_kms_key_resource_name": None,
            "audit_kms_key_version_name": None,
            "artifacts_generated_at": None,
            "updated_at": now_iso(),
        }
        txn.set(doc_ref, payload, merge=True)
        merged = dict(data)
        merged.update(payload)
        return _serialize_merged_signing_request(snapshot, merged)

    return _run(transaction)


def mark_signing_request_consent_withdrawn(
    request_id: str,
    *,
    session_id: str,
    client_ip: Optional[str],
    user_agent: Optional[str],
    withdrawn_at: Optional[str] = None,
    client=None,
) -> Optional[SigningRequestRecord]:
    now_value = _coerce_optional_text(withdrawn_at) or now_iso()
    return _update_public_signing_request(
        request_id,
        allowed_statuses={SIGNING_STATUS_SENT},
        required_present_fields=("consented_at",),
        required_absent_fields=("manual_fallback_requested_at", "consent_withdrawn_at"),
        updates={
            "consent_withdrawn_at": now_value,
            "last_public_session_id": _coerce_optional_text(session_id),
            "last_public_ip": _coerce_optional_text(client_ip),
            "last_public_user_agent": _coerce_optional_text(user_agent),
            "updated_at": now_value,
        },
        client=client,
    )


def invalidate_signing_request(
    request_id: str,
    user_id: str,
    *,
    reason: str,
    mark_public_link_revoked: bool = False,
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
    payload = {
        "status": SIGNING_STATUS_INVALIDATED,
        "invalidated_at": now_value,
        "invalidation_reason": normalized_reason,
        "updated_at": now_value,
    }
    if mark_public_link_revoked:
        payload["public_link_revoked_at"] = now_value
    doc_ref.set(payload, merge=True)
    return _serialize_signing_request(doc_ref.get())


def reissue_signing_request(
    request_id: str,
    user_id: str,
    *,
    public_app_origin: Optional[str] = None,
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
    current_revoked_at = _coerce_optional_text(data.get("public_link_revoked_at"))
    source_pdf_bucket_path = _coerce_optional_text(data.get("source_pdf_bucket_path"))
    if not source_pdf_bucket_path:
        return _serialize_signing_request(snapshot)
    if current_status == SIGNING_STATUS_INVALIDATED and not current_revoked_at:
        return _serialize_signing_request(snapshot)
    if current_status not in {SIGNING_STATUS_SENT, SIGNING_STATUS_INVALIDATED}:
        return _serialize_signing_request(snapshot)

    now_value = now_iso()
    request_expires_at = resolve_signing_request_expires_at(sent_at=now_value)
    retention_until = _coerce_optional_text(data.get("retention_until")) or resolve_signing_retention_until(now_value)
    next_public_link_version = _coerce_public_link_version(data.get("public_link_version")) + 1
    transport = resolve_signing_signer_transport(
        _coerce_optional_text(data.get("source_type")) or "workspace",
        signer_contact_method=_coerce_optional_text(data.get("signer_contact_method")),
    )
    doc_ref.set(
        {
            "status": SIGNING_STATUS_SENT,
            "public_link_version": next_public_link_version,
            "public_link_revoked_at": None,
            "public_link_last_reissued_at": now_value,
            "signer_contact_method": transport.signer_contact_method,
            "signer_auth_method": transport.signer_auth_method,
            "invite_delivery_status": "pending",
            "invite_last_attempt_at": None,
            "invite_sent_at": None,
            "invite_delivery_error": None,
            "invite_delivery_error_code": None,
            "invite_provider": None,
            "invite_message_id": None,
            "manual_link_shared_at": None,
            "verification_required": transport.verification_required,
            "verification_method": transport.verification_method,
            "verification_completed_at": None,
            "sent_at": now_value,
            "opened_at": None,
            "reviewed_at": None,
            "consented_at": None,
            "consumer_disclosure_version": None,
            "consumer_disclosure_payload": None,
            "consumer_disclosure_sha256": None,
            "consumer_disclosure_presented_at": None,
            "consumer_consent_scope": None,
            "consumer_access_demonstrated_at": None,
            "consumer_access_demonstration_method": None,
            "signature_adopted_at": None,
            "signature_adopted_name": None,
            "signature_adopted_mode": None,
            "signature_adopted_image_data_url": None,
            "signature_adopted_image_sha256": None,
            "manual_fallback_requested_at": None,
            "manual_fallback_note": None,
            "consent_withdrawn_at": None,
            "completed_at": None,
            "completed_session_id": None,
            "completed_ip_address": None,
            "completed_user_agent": None,
            "completed_verification_method": None,
            "completed_verification_completed_at": None,
            "completed_verification_session_id": None,
            "signed_pdf_bucket_path": None,
            "signed_pdf_sha256": None,
            "signed_pdf_digital_signature_method": None,
            "signed_pdf_digital_signature_algorithm": None,
            "signed_pdf_digital_signature_field_name": None,
            "signed_pdf_digital_signature_subfilter": None,
            "signed_pdf_digital_signature_timestamped": False,
            "signed_pdf_digital_certificate_subject": None,
            "signed_pdf_digital_certificate_issuer": None,
            "signed_pdf_digital_certificate_serial_number": None,
            "signed_pdf_digital_certificate_fingerprint_sha256": None,
            "audit_manifest_bucket_path": None,
            "audit_manifest_sha256": None,
            "audit_receipt_bucket_path": None,
            "audit_receipt_sha256": None,
            "audit_signature_method": None,
            "audit_signature_algorithm": None,
            "audit_kms_key_resource_name": None,
            "audit_kms_key_version_name": None,
            "artifacts_generated_at": None,
            "retention_until": retention_until,
            "expires_at": request_expires_at,
            "invalidated_at": None,
            "invalidation_reason": None,
            "public_app_origin": _coerce_optional_text(public_app_origin)
            or _coerce_optional_text(data.get("public_app_origin")),
            "updated_at": now_value,
        },
        merge=True,
    )
    return _serialize_signing_request(doc_ref.get())
