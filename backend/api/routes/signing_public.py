"""Public signer ceremony endpoints."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hmac
from typing import Any, Dict, Optional

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import Response, StreamingResponse

from backend.api.schemas import (
    PublicSigningAdoptSignatureRequest,
    PublicSigningCompleteRequest,
    PublicSigningConsentRequest,
    PublicSigningConsentWithdrawRequest,
    PublicSigningManualFallbackRequest,
    PublicSigningReviewRequest,
    PublicSigningVerificationVerifyRequest,
)
from backend.logging_config import get_logger
from backend.firebaseDB.signing_database import (
    complete_signing_request_transactional,
    create_signing_session,
    get_signing_request,
    get_signing_request_by_public_token,
    get_signing_request_by_validation_token,
    get_signing_session_for_request,
    increment_signing_session_consumer_access_attempt,
    increment_signing_session_verification_attempt,
    list_signing_events_for_request,
    mark_signing_request_consent_withdrawn,
    mark_signing_request_consented,
    mark_signing_request_manual_fallback_requested,
    mark_signing_request_opened,
    mark_signing_request_reviewed,
    mark_signing_request_signature_adopted,
    mark_signing_session_verified,
    record_signing_event,
    rollback_completed_signing_request_transactional,
    reset_signing_session_consumer_access_attempts,
    set_signing_session_verification_challenge,
    touch_signing_session,
)
from backend.firebaseDB.storage_service import (
    build_signing_bucket_uri,
    delete_storage_object,
    download_storage_bytes,
    is_gcs_path,
    stream_pdf,
)
from backend.security.rate_limit import check_rate_limit
from backend.services.contact_service import resolve_client_ip
from backend.services.pdf_service import safe_pdf_download_filename
from backend.services.signing_consumer_consent_service import (
    render_consumer_access_pdf,
    resolve_consumer_disclosure_artifact,
)
from backend.services.signing_public_artifact_service import (
    build_public_signing_stream_headers,
    cleanup_public_signing_completion_uploads,
    is_public_signing_storage_not_found_error,
    prepare_public_signing_completion,
    resolve_public_signing_artifact,
)
from backend.services.signing_pdf_service import normalize_signature_image_data_url
from backend.services.signing_public_consumer_service import (
    build_public_signing_consumer_consent_event_details,
    build_public_signing_consumer_withdrawal_event_details,
    ensure_public_signing_consumer_disclosure_state,
    serialize_public_signing_disclosure,
)
from backend.services.signing_public_session_service import (
    normalize_public_signing_session_header,
    parse_public_signing_timestamp,
    resolve_public_signing_session_binding_mismatch,
    resolve_public_signing_verification_resend_available_at,
    serialize_public_signing_session,
    session_has_public_signing_email_verification,
)
from backend.services.signing_storage_service import (
    ensure_signing_storage_configuration,
    promote_signing_staged_object,
    resolve_signing_storage_read_bucket_path,
    upload_signing_staging_json_for_final,
    upload_signing_staging_pdf_bytes_for_final,
)
from backend.services.signing_validation_service import build_signing_validation_payload
from backend.services.signing_service import (
    SIGNING_ARTIFACT_AUDIT_RECEIPT,
    SIGNING_ARTIFACT_SIGNED_PDF,
    SIGNATURE_MODE_CONSUMER,
    SIGNING_EVENT_COMPLETED,
    SIGNING_EVENT_CONSUMER_ACCESS_FAILED,
    SIGNING_EVENT_CONSENT_ACCEPTED,
    SIGNING_EVENT_DOCUMENT_ACCESSED,
    SIGNING_EVENT_CONSENT_WITHDRAWN,
    SIGNING_EVENT_MANUAL_FALLBACK_REQUESTED,
    SIGNING_EVENT_OPENED,
    SIGNING_EVENT_REVIEW_CONFIRMED,
    SIGNING_EVENT_SESSION_STARTED,
    SIGNING_EVENT_SIGNATURE_ADOPTED,
    SIGNING_EVENT_VERIFICATION_FAILED,
    SIGNING_EVENT_VERIFICATION_PASSED,
    SIGNING_EVENT_VERIFICATION_RESENT,
    SIGNING_EVENT_VERIFICATION_STARTED,
    SIGNING_STATUS_COMPLETED,
    SIGNING_STATUS_SENT,
    SIGNING_VERIFICATION_METHOD_EMAIL_OTP,
    build_signing_consumer_access_code,
    build_signing_email_otp_hash,
    build_signing_public_artifact_token,
    build_signing_validation_path,
    build_signing_link_token_id,
    build_signing_public_session_token,
    build_signing_session_ip_scope,
    build_signing_user_agent_fingerprint,
    generate_signing_email_otp_code,
    mask_signing_email,
    normalize_signing_email_otp_code,
    normalize_signing_user_agent,
    parse_signing_public_session_token,
    parse_signing_public_artifact_token,
    resolve_document_category_label,
    resolve_signing_action_rate_limits,
    resolve_signing_artifact_token_ttl_seconds,
    resolve_signing_consumer_access_max_attempts,
    resolve_signing_consumer_access_rate_limits,
    resolve_signing_document_rate_limits,
    resolve_signing_verification_code_ttl_seconds,
    resolve_signing_verification_max_attempts,
    resolve_signing_public_status_message,
    resolve_signing_session_ttl_seconds,
    resolve_signing_verification_send_rate_limits,
    resolve_signing_verification_verify_rate_limits,
    resolve_signing_view_rate_limits,
    resolve_signature_adoption_payload,
    serialize_signing_ceremony_state,
    signing_record_requires_verification,
    signing_request_is_expired,
    validate_public_signing_actionable_record,
    validate_public_signing_adoptable_record,
    validate_public_signing_completable_record,
    validate_public_signing_consent_withdrawable_record,
    validate_public_signing_document_record,
    validate_public_signing_reviewable_record,
)
from backend.services.signing_verification_service import (
    SIGNING_VERIFICATION_DELIVERY_SENT,
    send_signing_verification_email,
)
from backend.services.signing_webhook_service import dispatch_signing_webhook_event
from backend.time_utils import now_iso


logger = get_logger(__name__)

router = APIRouter()


def _check_public_rate_limits(
    *,
    scope: str,
    client_ip: str,
    window_seconds: int,
    per_ip: int,
    global_limit: int,
) -> bool:
    if global_limit > 0:
        global_allowed = check_rate_limit(
            f"{scope}:global",
            limit=global_limit,
            window_seconds=window_seconds,
            fail_closed=True,
        )
        if not global_allowed:
            return False
    return check_rate_limit(
        f"{scope}:{client_ip}",
        limit=per_ip,
        window_seconds=window_seconds,
        fail_closed=True,
    )


def _serialize_public_request(record, *, token: str) -> Dict[str, Any]:
    disclosure_payload = serialize_public_signing_disclosure(record, public_token=token)
    return {
        "id": record.id,
        "title": record.title,
        "mode": record.mode,
        "signatureMode": record.signature_mode,
        "status": record.status,
        "statusMessage": resolve_signing_public_status_message(
            record.status,
            record.invalidation_reason,
            expires_at=getattr(record, "expires_at", None),
        ),
        "sourceDocumentName": record.source_document_name,
        "sourcePdfSha256": record.source_pdf_sha256,
        "sourceVersion": record.source_version,
        "documentCategory": record.document_category,
        "documentCategoryLabel": resolve_document_category_label(record.document_category),
        "manualFallbackEnabled": record.manual_fallback_enabled,
        "senderDisplayName": getattr(record, "sender_display_name", None),
        "senderContactEmail": getattr(record, "sender_contact_email", None) or getattr(record, "sender_email", None),
        "signerName": record.signer_name,
        "signerEmailHint": mask_signing_email(record.signer_email),
        "anchors": record.anchors,
        "disclosureVersion": record.disclosure_version,
        "disclosure": disclosure_payload,
        "documentPath": f"/api/signing/public/{token}/document",
        "artifacts": {
            "signedPdf": {
                "available": bool(record.signed_pdf_bucket_path),
                "sha256": record.signed_pdf_sha256,
                "downloadPath": None,
                "generatedAt": record.artifacts_generated_at,
                "digitalSignature": {
                    "available": bool(getattr(record, "signed_pdf_digital_signature_field_name", None)),
                    "method": getattr(record, "signed_pdf_digital_signature_method", None),
                    "algorithm": getattr(record, "signed_pdf_digital_signature_algorithm", None),
                    "fieldName": getattr(record, "signed_pdf_digital_signature_field_name", None),
                    "subfilter": getattr(record, "signed_pdf_digital_signature_subfilter", None),
                    "timestamped": bool(getattr(record, "signed_pdf_digital_signature_timestamped", False)),
                    "certificateSubject": getattr(record, "signed_pdf_digital_certificate_subject", None),
                    "certificateIssuer": getattr(record, "signed_pdf_digital_certificate_issuer", None),
                    "certificateSerialNumber": getattr(record, "signed_pdf_digital_certificate_serial_number", None),
                    "certificateFingerprintSha256": getattr(
                        record,
                        "signed_pdf_digital_certificate_fingerprint_sha256",
                        None,
                    ),
                },
            },
            "auditReceipt": {
                "available": bool(record.audit_receipt_bucket_path),
                "sha256": record.audit_receipt_sha256,
                "downloadPath": None,
                "generatedAt": record.artifacts_generated_at,
            },
        },
        "createdAt": record.created_at,
        "sentAt": record.sent_at,
        "completedAt": record.completed_at,
        "validationPath": build_signing_validation_path(record.id),
        "expiresAt": getattr(record, "expires_at", None),
        "isExpired": signing_request_is_expired(record),
        "invalidatedAt": record.invalidated_at,
        "invalidationReason": record.invalidation_reason,
        **serialize_signing_ceremony_state(record),
    }

def _get_public_record_or_404(token: str):
    record = get_signing_request_by_public_token(token)
    if record is None:
        raise HTTPException(status_code=404, detail="Signing request not found")
    return record


def _record_public_signing_event(
    record,
    *,
    event_type: str,
    session_id: Optional[str],
    link_token_id: Optional[str],
    client_ip: Optional[str],
    user_agent: Optional[str],
    details: Optional[Dict[str, Any]] = None,
    occurred_at: Optional[str] = None,
) -> None:
    event_details = dict(details or {})
    record_signing_event(
        record.id,
        event_type=event_type,
        session_id=session_id,
        link_token_id=link_token_id,
        client_ip=client_ip,
        user_agent=user_agent,
        details=event_details,
        occurred_at=occurred_at,
    )
    dispatch_signing_webhook_event(
        record,
        event_type=event_type,
        details=event_details,
        occurred_at=occurred_at,
    )


def _require_public_transition_applied(
    updated_record,
    *,
    expected_status: str,
    required_fields: tuple[str, ...] = (),
    expected_field_values: Optional[Dict[str, Any]] = None,
):
    """Reject stale action responses when the Firestore state no longer matches the attempted transition.

    Public signer actions are multi-step and can be retried or race with a second tab. The database helper
    returns the current record snapshot even when the status precondition no longer matches, so callers need
    to verify that the expected status/fields actually exist before recording success events. This keeps the
    audit trail O(1) per accepted action instead of appending misleading duplicate events from stale retries.
    """

    if updated_record is None:
        raise HTTPException(status_code=409, detail="This signing request changed before the action could be saved. Reload and try again.")
    if str(updated_record.status or "").strip().lower() != expected_status:
        raise HTTPException(
            status_code=409,
            detail=resolve_signing_public_status_message(updated_record.status, updated_record.invalidation_reason),
        )
    for field_name, expected_value in dict(expected_field_values or {}).items():
        if getattr(updated_record, field_name, None) != expected_value:
            try:
                validate_public_signing_actionable_record(updated_record)
            except ValueError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            raise HTTPException(
                status_code=409,
                detail="This signing request changed before the action could be saved. Reload and try again.",
            )
    for field_name in required_fields:
        if not getattr(updated_record, field_name, None):
            try:
                validate_public_signing_actionable_record(updated_record)
            except ValueError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            raise HTTPException(
                status_code=409,
                detail="This signing request changed before the action could be saved. Reload and try again.",
            )
    return updated_record


def _require_public_signing_session_verified(record, session) -> None:
    if not signing_record_requires_verification(record):
        return
    if session_has_public_signing_email_verification(session):
        return
    raise HTTPException(status_code=403, detail="Verify the email code before continuing this signing request.")


def _require_public_signing_session(
    *,
    token: str,
    x_signing_session: Optional[str],
    request: Request,
    allow_completed: bool = False,
):
    record = _get_public_record_or_404(token)
    if not (allow_completed and record.status == SIGNING_STATUS_COMPLETED):
        try:
            validate_public_signing_actionable_record(record)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    session_header = normalize_public_signing_session_header(x_signing_session)
    if not session_header:
        raise HTTPException(status_code=401, detail="Signing session is required. Reload the page and try again.")
    parsed = parse_signing_public_session_token(session_header)
    if parsed is None:
        raise HTTPException(status_code=401, detail="Signing session expired. Reload the page and try again.")
    request_id, session_id, _expires_at_epoch = parsed
    if request_id != record.id:
        raise HTTPException(status_code=401, detail="Signing session does not match this request.")
    session = get_signing_session_for_request(session_id, record.id)
    if session is None:
        raise HTTPException(status_code=401, detail="Signing session was not found. Reload the page and try again.")
    current_link_token_id = build_signing_link_token_id(token)
    if session.link_token_id != current_link_token_id:
        raise HTTPException(status_code=401, detail="Signing session expired. Reload the page and try again.")
    client_ip = resolve_client_ip(request)
    user_agent = normalize_signing_user_agent(request.headers.get("user-agent"))
    binding_mismatch = resolve_public_signing_session_binding_mismatch(
        session,
        client_ip=client_ip,
        user_agent=user_agent,
    )
    if binding_mismatch["reason"] == "ip_scope":
        logger.warning(
            "Signing session IP scope mismatch: session %s bound to %s, current request resolved to %s (request %s)",
            session.id,
            session.binding_ip_scope,
            binding_mismatch["currentIpScope"],
            record.id,
        )
        raise HTTPException(status_code=401, detail="Signing session does not match this device. Reload the page and try again.")
    if binding_mismatch["reason"] == "user_agent":
        logger.warning("Signing session user-agent mismatch for session %s (request %s)", session.id, record.id)
        raise HTTPException(status_code=401, detail="Signing session does not match this device. Reload the page and try again.")
    touch_signing_session(session.id, client_ip=client_ip, user_agent=user_agent)
    return record, session, client_ip, user_agent


def _require_public_signing_artifact_session(
    *,
    request_id: str,
    expected_session_id: str,
    x_signing_session: Optional[str],
    request: Request,
):
    record = get_signing_request(request_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Signing request not found")

    session_header = normalize_public_signing_session_header(x_signing_session)
    if not session_header:
        raise HTTPException(status_code=401, detail="Signing session is required. Reload the page and try again.")
    parsed = parse_signing_public_session_token(session_header)
    if parsed is None:
        raise HTTPException(status_code=401, detail="Signing session expired. Reload the page and try again.")
    parsed_request_id, session_id, _expires_at_epoch = parsed
    if parsed_request_id != record.id or session_id != expected_session_id:
        raise HTTPException(status_code=401, detail="Signing session does not match this download.")
    session = get_signing_session_for_request(session_id, record.id)
    if session is None:
        raise HTTPException(status_code=401, detail="Signing session was not found. Reload the page and try again.")
    client_ip = resolve_client_ip(request)
    user_agent = normalize_signing_user_agent(request.headers.get("user-agent"))
    binding_mismatch = resolve_public_signing_session_binding_mismatch(
        session,
        client_ip=client_ip,
        user_agent=user_agent,
    )
    if binding_mismatch["reason"] in {"ip_scope", "user_agent"}:
        raise HTTPException(status_code=401, detail="Signing session does not match this device. Reload the page and try again.")
    touch_signing_session(session.id, client_ip=client_ip, user_agent=user_agent)
    return record, session, client_ip, user_agent


@router.get("/api/signing/public/validation/{token}")
async def get_public_signing_validation(token: str) -> Dict[str, Any]:
    record = get_signing_request_by_validation_token(token)
    if record is None or record.status != SIGNING_STATUS_COMPLETED:
        raise HTTPException(status_code=404, detail="Completed signing record not found")
    return {"validation": await build_signing_validation_payload(record)}


@router.get("/api/signing/public/{token}")
async def get_public_signing_request(token: str, request: Request) -> Dict[str, Any]:
    client_ip = resolve_client_ip(request)
    window_seconds, per_ip, global_limit = resolve_signing_view_rate_limits()
    allowed = _check_public_rate_limits(
        scope="signing_view",
        client_ip=client_ip,
        window_seconds=window_seconds,
        per_ip=per_ip,
        global_limit=global_limit,
    )
    if not allowed:
        raise HTTPException(status_code=429, detail="Too many signing page loads. Please wait and try again.")
    record = _get_public_record_or_404(token)
    return {"request": _serialize_public_request(record, token=token)}


@router.post("/api/signing/public/{token}/bootstrap")
async def start_public_signing_session(token: str, request: Request) -> Dict[str, Any]:
    client_ip = resolve_client_ip(request)
    window_seconds, per_ip, global_limit = resolve_signing_action_rate_limits()
    allowed = _check_public_rate_limits(
        scope="signing_bootstrap",
        client_ip=client_ip,
        window_seconds=window_seconds,
        per_ip=per_ip,
        global_limit=global_limit,
    )
    if not allowed:
        raise HTTPException(status_code=429, detail="Too many signing session starts. Please wait and try again.")

    record = _get_public_record_or_404(token)
    if record.status not in {SIGNING_STATUS_SENT, SIGNING_STATUS_COMPLETED}:
        raise HTTPException(
            status_code=409,
            detail=resolve_signing_public_status_message(record.status, record.invalidation_reason),
        )
    if record.status == SIGNING_STATUS_SENT:
        try:
            validate_public_signing_actionable_record(record)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    ttl_seconds = resolve_signing_session_ttl_seconds()
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
    token_id = build_signing_link_token_id(token)
    user_agent = normalize_signing_user_agent(request.headers.get("user-agent"))
    session = create_signing_session(
        record.id,
        link_token_id=token_id,
        client_ip=client_ip,
        user_agent=user_agent,
        binding_ip_scope=build_signing_session_ip_scope(client_ip),
        binding_user_agent_hash=build_signing_user_agent_fingerprint(user_agent),
        expires_at=expires_at.isoformat(),
    )
    updated_record = record
    if record.status == SIGNING_STATUS_SENT:
        updated_record = mark_signing_request_opened(
            record.id,
            session_id=session.id,
            client_ip=client_ip,
            user_agent=user_agent,
        )
        updated_record = _require_public_transition_applied(
            updated_record,
            expected_status=SIGNING_STATUS_SENT,
            required_fields=("opened_at",),
        )
    updated_record = ensure_public_signing_consumer_disclosure_state(updated_record)
    _record_public_signing_event(
        updated_record,
        event_type=SIGNING_EVENT_SESSION_STARTED,
        session_id=session.id,
        link_token_id=token_id,
        client_ip=client_ip,
        user_agent=user_agent,
        details={"status": updated_record.status},
    )
    if record.status == SIGNING_STATUS_SENT:
        _record_public_signing_event(
            updated_record,
            event_type=SIGNING_EVENT_OPENED,
            session_id=session.id,
            link_token_id=token_id,
            client_ip=client_ip,
            user_agent=user_agent,
            details={
                "documentCategory": updated_record.document_category,
                "sourceVersion": updated_record.source_version,
            },
        )
    session_token = build_signing_public_session_token(
        updated_record.id,
        session.id,
        int(expires_at.timestamp()),
    )
    return {
        "request": _serialize_public_request(updated_record, token=token),
        "session": serialize_public_signing_session(session, session_token=session_token),
    }


@router.post("/api/signing/public/{token}/verification/send")
async def send_public_signing_verification_code(
    token: str,
    request: Request,
    x_signing_session: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    client_ip = resolve_client_ip(request)
    window_seconds, per_ip, global_limit = resolve_signing_verification_send_rate_limits()
    allowed = _check_public_rate_limits(
        scope="signing_verification_send",
        client_ip=client_ip,
        window_seconds=window_seconds,
        per_ip=per_ip,
        global_limit=global_limit,
    )
    if not allowed:
        raise HTTPException(status_code=429, detail="Too many verification code requests. Please wait and try again.")

    record, session, client_ip, user_agent = _require_public_signing_session(
        token=token,
        x_signing_session=x_signing_session,
        request=request,
        allow_completed=True,
    )
    if not signing_record_requires_verification(record):
        raise HTTPException(status_code=400, detail="Email verification is not required for this signing request.")

    session_token = normalize_public_signing_session_header(x_signing_session)
    if session_has_public_signing_email_verification(session):
        return {
            "request": _serialize_public_request(record, token=token),
            "session": serialize_public_signing_session(session, session_token=session_token),
        }

    resend_available_at = parse_public_signing_timestamp(
        resolve_public_signing_verification_resend_available_at(session)
    )
    current_time = datetime.now(timezone.utc)
    if resend_available_at is not None and resend_available_at > current_time:
        raise HTTPException(
            status_code=429,
            detail="Wait before requesting another verification code.",
        )

    verification_code = generate_signing_email_otp_code()
    expires_at = (current_time + timedelta(seconds=resolve_signing_verification_code_ttl_seconds())).isoformat()
    delivery = await send_signing_verification_email(
        signer_email=record.signer_email,
        signer_name=record.signer_name,
        document_name=record.source_document_name,
        verification_code=verification_code,
        expires_in_minutes=max(1, (resolve_signing_verification_code_ttl_seconds() + 59) // 60),
        signing_path=f"/sign/{token}",
        sender_email=getattr(record, "sender_email", None),
        request_origin=request.headers.get("origin"),
    )
    if delivery.delivery_status != SIGNING_VERIFICATION_DELIVERY_SENT:
        raise HTTPException(
            status_code=503,
            detail=delivery.error_message or "Failed to deliver the email verification code. Please try again.",
        )

    updated_session = set_signing_session_verification_challenge(
        session.id,
        record.id,
        code_hash=build_signing_email_otp_hash(session.id, verification_code),
        sent_at=delivery.sent_at or delivery.attempted_at,
        expires_at=expires_at,
        verification_message_id=delivery.message_id,
    )
    if updated_session is None:
        raise HTTPException(status_code=409, detail="Signing session changed before the verification code could be saved.")

    event_type = SIGNING_EVENT_VERIFICATION_STARTED if not session.verification_sent_at else SIGNING_EVENT_VERIFICATION_RESENT
    _record_public_signing_event(
        record,
        event_type=event_type,
        session_id=session.id,
        link_token_id=session.link_token_id,
        client_ip=client_ip,
        user_agent=user_agent,
        details={
            "verificationMethod": SIGNING_VERIFICATION_METHOD_EMAIL_OTP,
            "deliveryStatus": delivery.delivery_status,
            "sentAt": delivery.sent_at or delivery.attempted_at,
            "expiresAt": expires_at,
            "messageId": delivery.message_id,
        },
    )
    return {
        "request": _serialize_public_request(record, token=token),
        "session": serialize_public_signing_session(updated_session, session_token=session_token),
    }


@router.post("/api/signing/public/{token}/verification/verify")
async def verify_public_signing_verification_code(
    token: str,
    payload: PublicSigningVerificationVerifyRequest,
    request: Request,
    x_signing_session: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    client_ip = resolve_client_ip(request)
    window_seconds, per_ip, global_limit = resolve_signing_verification_verify_rate_limits()
    allowed = _check_public_rate_limits(
        scope="signing_verification_verify",
        client_ip=client_ip,
        window_seconds=window_seconds,
        per_ip=per_ip,
        global_limit=global_limit,
    )
    if not allowed:
        raise HTTPException(status_code=429, detail="Too many verification attempts. Please wait and try again.")

    record, session, client_ip, user_agent = _require_public_signing_session(
        token=token,
        x_signing_session=x_signing_session,
        request=request,
        allow_completed=True,
    )
    if not signing_record_requires_verification(record):
        raise HTTPException(status_code=400, detail="Email verification is not required for this signing request.")

    session_token = normalize_public_signing_session_header(x_signing_session)
    if session_has_public_signing_email_verification(session):
        refreshed_record = _get_public_record_or_404(token)
        return {
            "request": _serialize_public_request(refreshed_record, token=token),
            "session": serialize_public_signing_session(session, session_token=session_token),
        }

    try:
        normalized_code = normalize_signing_email_otp_code(payload.code)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    max_attempts = resolve_signing_verification_max_attempts()
    if session.verification_attempt_count >= max_attempts:
        raise HTTPException(status_code=429, detail="Too many failed verification attempts. Request a new code.")

    expires_at = parse_public_signing_timestamp(session.verification_expires_at)
    if not session.verification_code_hash or expires_at is None or expires_at <= datetime.now(timezone.utc):
        raise HTTPException(status_code=409, detail="Request a new verification code to continue.")

    expected_hash = build_signing_email_otp_hash(session.id, normalized_code)
    if not hmac.compare_digest(session.verification_code_hash, expected_hash):
        updated_session = increment_signing_session_verification_attempt(session.id, record.id) or session
        attempts_used = getattr(updated_session, "verification_attempt_count", session.verification_attempt_count + 1)
        attempts_remaining = max(0, max_attempts - attempts_used)
        _record_public_signing_event(
            record,
            event_type=SIGNING_EVENT_VERIFICATION_FAILED,
            session_id=session.id,
            link_token_id=session.link_token_id,
            client_ip=client_ip,
            user_agent=user_agent,
            details={
                "verificationMethod": SIGNING_VERIFICATION_METHOD_EMAIL_OTP,
                "attemptCount": attempts_used,
                "attemptsRemaining": attempts_remaining,
                "reason": "invalid_code",
            },
        )
        if attempts_used >= max_attempts:
            raise HTTPException(status_code=429, detail="Too many failed verification attempts. Request a new code.")
        raise HTTPException(status_code=400, detail="That verification code is invalid. Try again.")

    updated_session = mark_signing_session_verified(
        session.id,
        record.id,
        verification_method=SIGNING_VERIFICATION_METHOD_EMAIL_OTP,
    )
    if updated_session is None:
        raise HTTPException(status_code=409, detail="Signing session changed before verification could be saved.")
    refreshed_record = _get_public_record_or_404(token)
    _record_public_signing_event(
        refreshed_record,
        event_type=SIGNING_EVENT_VERIFICATION_PASSED,
        session_id=session.id,
        link_token_id=session.link_token_id,
        client_ip=client_ip,
        user_agent=user_agent,
        details={
            "verificationMethod": SIGNING_VERIFICATION_METHOD_EMAIL_OTP,
            "verifiedAt": updated_session.verification_completed_at,
        },
    )
    return {
        "request": _serialize_public_request(refreshed_record, token=token),
        "session": serialize_public_signing_session(updated_session, session_token=session_token),
    }


@router.get("/api/signing/public/{token}/consumer-access-pdf")
async def get_public_signing_consumer_access_pdf(token: str, request: Request):
    client_ip = resolve_client_ip(request)
    window_seconds, per_ip, global_limit = resolve_signing_document_rate_limits()
    allowed = _check_public_rate_limits(
        scope="signing_consumer_access_pdf",
        client_ip=client_ip,
        window_seconds=window_seconds,
        per_ip=per_ip,
        global_limit=global_limit,
    )
    if not allowed:
        raise HTTPException(status_code=429, detail="Too many document loads. Please wait and try again.")
    ensure_signing_storage_configuration(validate_remote=False)

    record = _get_public_record_or_404(token)
    if record.signature_mode != SIGNATURE_MODE_CONSUMER:
        raise HTTPException(status_code=400, detail="Consumer access proof is only available for consumer signing requests.")
    if record.status not in {SIGNING_STATUS_SENT, SIGNING_STATUS_COMPLETED}:
        raise HTTPException(
            status_code=409,
            detail=resolve_signing_public_status_message(record.status, record.invalidation_reason),
        )
    if signing_request_is_expired(record):
        raise HTTPException(status_code=409, detail="This signing request has expired. Contact the sender for a fresh signing link.")

    disclosure_payload = resolve_consumer_disclosure_artifact(record, public_token=token)["payload"]
    pdf_bytes = render_consumer_access_pdf(
        request_id=record.id,
        source_document_name=record.source_document_name or "DullyPDF document",
        disclosure_payload=disclosure_payload,
    )
    filename = safe_pdf_download_filename(
        f"{record.source_document_name or 'document'}-consumer-access-check",
        "consumer-access-check",
    )
    headers = build_public_signing_stream_headers(
        request.headers.get("origin"),
        content_disposition=f'inline; filename="{filename}"',
    )
    return Response(content=pdf_bytes, media_type="application/pdf", headers=headers)


@router.get("/api/signing/public/{token}/document")
async def get_public_signing_document(
    token: str,
    request: Request,
    x_signing_session: Optional[str] = Header(default=None),
):
    client_ip = resolve_client_ip(request)
    window_seconds, per_ip, global_limit = resolve_signing_document_rate_limits()
    allowed = _check_public_rate_limits(
        scope="signing_document",
        client_ip=client_ip,
        window_seconds=window_seconds,
        per_ip=per_ip,
        global_limit=global_limit,
    )
    if not allowed:
        raise HTTPException(status_code=429, detail="Too many document loads. Please wait and try again.")

    record = _get_public_record_or_404(token)
    try:
        validate_public_signing_document_record(record)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not record.source_pdf_bucket_path or not is_gcs_path(record.source_pdf_bucket_path):
        raise HTTPException(status_code=404, detail="Signing document is not available.")

    record, resolved_session, client_ip, user_agent = _require_public_signing_session(
        token=token,
        x_signing_session=x_signing_session,
        request=request,
        allow_completed=True,
    )
    if signing_record_requires_verification(record):
        _require_public_signing_session_verified(record, resolved_session)
    _record_public_signing_event(
        record,
        event_type=SIGNING_EVENT_DOCUMENT_ACCESSED,
        session_id=resolved_session.id,
        link_token_id=resolved_session.link_token_id,
        client_ip=client_ip,
        user_agent=user_agent,
        details={
            "sourcePdfSha256": record.source_pdf_sha256,
            "sourceVersion": record.source_version,
        },
    )

    try:
        readable_bucket_path = resolve_signing_storage_read_bucket_path(
            record.source_pdf_bucket_path,
            retain_until=record.retention_until,
        )
        stream = stream_pdf(readable_bucket_path)
    except Exception as exc:
        if is_public_signing_storage_not_found_error(exc):
            raise HTTPException(status_code=404, detail="Signing document is not available.") from exc
        raise HTTPException(status_code=500, detail="Failed to load signing document.") from exc

    filename = safe_pdf_download_filename(record.source_document_name or "signing-document", "signing-document")
    headers = build_public_signing_stream_headers(
        request.headers.get("origin"),
        content_disposition=f'inline; filename="{filename}"',
    )
    return StreamingResponse(stream, media_type="application/pdf", headers=headers)


@router.post("/api/signing/public/{token}/artifacts/{artifact_key}/issue")
async def issue_public_signing_artifact_download(
    token: str,
    artifact_key: str,
    request: Request,
    x_signing_session: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    client_ip = resolve_client_ip(request)
    window_seconds, per_ip, global_limit = resolve_signing_document_rate_limits()
    allowed = _check_public_rate_limits(
        scope="signing_artifact_issue",
        client_ip=client_ip,
        window_seconds=window_seconds,
        per_ip=per_ip,
        global_limit=global_limit,
    )
    if not allowed:
        raise HTTPException(status_code=429, detail="Too many artifact download requests. Please wait and try again.")
    ensure_signing_storage_configuration(validate_remote=False)
    record, session, _client_ip, _user_agent = _require_public_signing_session(
        token=token,
        x_signing_session=x_signing_session,
        request=request,
        allow_completed=True,
    )
    if signing_record_requires_verification(record):
        _require_public_signing_session_verified(record, session)
    try:
        artifact = resolve_public_signing_artifact(
            record,
            artifact_key=artifact_key,
            signed_pdf_filename=safe_pdf_download_filename(
                f"{record.source_document_name or 'document'}-signed",
                "signed-document",
            ),
            audit_receipt_filename=safe_pdf_download_filename(
                f"{record.source_document_name or 'document'}-audit-receipt",
                "audit-receipt",
            ),
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=resolve_signing_artifact_token_ttl_seconds())
    artifact_token = build_signing_public_artifact_token(
        record.id,
        session.id,
        artifact_key,
        int(expires_at.timestamp()),
    )
    return {
        "artifactKey": artifact_key,
        "downloadPath": f"/api/signing/public/artifacts/{artifact_token}",
        "expiresAt": expires_at.isoformat(),
        "mediaType": artifact.media_type,
    }


@router.get("/api/signing/public/artifacts/{artifact_token}")
async def get_public_signing_artifact(
    artifact_token: str,
    request: Request,
    x_signing_session: Optional[str] = Header(default=None),
):
    client_ip = resolve_client_ip(request)
    window_seconds, per_ip, global_limit = resolve_signing_document_rate_limits()
    allowed = _check_public_rate_limits(
        scope="signing_artifact",
        client_ip=client_ip,
        window_seconds=window_seconds,
        per_ip=per_ip,
        global_limit=global_limit,
    )
    if not allowed:
        raise HTTPException(status_code=429, detail="Too many artifact downloads. Please wait and try again.")
    parsed = parse_signing_public_artifact_token(artifact_token)
    if parsed is None:
        raise HTTPException(status_code=401, detail="Artifact download expired. Reload the page and try again.")
    request_id, session_id, artifact_key, _expires_at_epoch = parsed
    ensure_signing_storage_configuration(validate_remote=False)
    record, session, _client_ip, _user_agent = _require_public_signing_artifact_session(
        request_id=request_id,
        expected_session_id=session_id,
        x_signing_session=x_signing_session,
        request=request,
    )
    if signing_record_requires_verification(record):
        _require_public_signing_session_verified(record, session)
    try:
        artifact = resolve_public_signing_artifact(
            record,
            artifact_key=artifact_key,
            signed_pdf_filename=safe_pdf_download_filename(
                f"{record.source_document_name or 'document'}-signed",
                "signed-document",
            ),
            audit_receipt_filename=safe_pdf_download_filename(
                f"{record.source_document_name or 'document'}-audit-receipt",
                "audit-receipt",
            ),
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    try:
        readable_bucket_path = resolve_signing_storage_read_bucket_path(
            artifact.bucket_path,
            retain_until=record.retention_until,
        )
        body = download_storage_bytes(readable_bucket_path)
    except Exception as exc:
        if is_public_signing_storage_not_found_error(exc):
            raise HTTPException(status_code=404, detail="Signing artifact is not available.") from exc
        raise HTTPException(status_code=500, detail="Failed to load signing artifact.") from exc
    headers = build_public_signing_stream_headers(
        request.headers.get("origin"),
        content_disposition=f'attachment; filename="{artifact.filename}"',
    )
    if artifact.media_type == "application/json":
        return Response(content=body, media_type=artifact.media_type, headers=headers)
    return StreamingResponse(iter([body]), media_type=artifact.media_type, headers=headers)


@router.get("/api/signing/public/{token}/artifacts/{artifact_key}")
async def get_public_signing_artifact_legacy_path(token: str, artifact_key: str) -> None:
    raise HTTPException(
        status_code=410,
        detail="Artifact download links now expire quickly. Reload the signing page to generate a fresh download link.",
    )


@router.post("/api/signing/public/{token}/review")
async def review_public_signing_request(
    token: str,
    payload: PublicSigningReviewRequest,
    request: Request,
    x_signing_session: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    if not payload.reviewConfirmed:
        raise HTTPException(status_code=400, detail="Review acknowledgment is required.")
    reviewed_at = now_iso()
    record, session, client_ip, user_agent = _require_public_signing_session(
        token=token,
        x_signing_session=x_signing_session,
        request=request,
    )
    _require_public_signing_session_verified(record, session)
    try:
        validate_public_signing_reviewable_record(record)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    updated_record = mark_signing_request_reviewed(
        record.id,
        session_id=session.id,
        client_ip=client_ip,
        user_agent=user_agent,
        reviewed_at=reviewed_at,
    )
    updated_record = _require_public_transition_applied(
        updated_record,
        expected_status=SIGNING_STATUS_SENT,
        required_fields=("reviewed_at",),
        expected_field_values={"reviewed_at": reviewed_at},
    )
    _record_public_signing_event(
        updated_record,
        event_type=SIGNING_EVENT_REVIEW_CONFIRMED,
        session_id=session.id,
        link_token_id=session.link_token_id,
        client_ip=client_ip,
        user_agent=user_agent,
        details={
            "sourcePdfSha256": updated_record.source_pdf_sha256,
            "sourceVersion": updated_record.source_version,
        },
    )
    return {"request": _serialize_public_request(updated_record, token=token)}


@router.post("/api/signing/public/{token}/consent")
async def consent_public_signing_request(
    token: str,
    payload: PublicSigningConsentRequest,
    request: Request,
    x_signing_session: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    if not payload.accepted:
        raise HTTPException(status_code=400, detail="Electronic records consent is required to continue.")
    client_ip = resolve_client_ip(request)
    window_seconds, per_ip, global_limit = resolve_signing_consumer_access_rate_limits()
    allowed = _check_public_rate_limits(
        scope="signing_consumer_access_verify",
        client_ip=client_ip,
        window_seconds=window_seconds,
        per_ip=per_ip,
        global_limit=global_limit,
    )
    if not allowed:
        raise HTTPException(status_code=429, detail="Too many consumer access attempts. Please wait and try again.")
    consented_at = now_iso()
    record, session, client_ip, user_agent = _require_public_signing_session(
        token=token,
        x_signing_session=x_signing_session,
        request=request,
    )
    _require_public_signing_session_verified(record, session)
    if record.signature_mode != SIGNATURE_MODE_CONSUMER:
        raise HTTPException(status_code=400, detail="Consumer e-consent is only required for consumer signing requests.")
    max_attempts = resolve_signing_consumer_access_max_attempts()
    if getattr(session, "consumer_access_attempt_count", 0) >= max_attempts:
        raise HTTPException(status_code=429, detail="Too many failed consumer access code attempts. Reload the page to try again.")
    expected_access_code = build_signing_consumer_access_code(record.id)
    if payload.accessCode != expected_access_code:
        updated_session = increment_signing_session_consumer_access_attempt(session.id, record.id) or session
        attempts_used = getattr(updated_session, "consumer_access_attempt_count", getattr(session, "consumer_access_attempt_count", 0) + 1)
        attempts_remaining = max(0, max_attempts - attempts_used)
        _record_public_signing_event(
            record,
            event_type=SIGNING_EVENT_CONSUMER_ACCESS_FAILED,
            session_id=session.id,
            link_token_id=session.link_token_id,
            client_ip=client_ip,
            user_agent=user_agent,
            details={
                "attemptCount": attempts_used,
                "attemptsRemaining": attempts_remaining,
                "reason": "invalid_access_code",
            },
        )
        if attempts_used >= max_attempts:
            raise HTTPException(status_code=429, detail="Too many failed consumer access code attempts. Reload the page to try again.")
        raise HTTPException(
            status_code=400,
            detail="Open the consumer access PDF and enter the 6-character access code before consenting.",
        )
    updated_record = mark_signing_request_consented(
        record.id,
        session_id=session.id,
        client_ip=client_ip,
        user_agent=user_agent,
        consented_at=consented_at,
        consumer_access_demonstrated_at=consented_at,
        consumer_access_demonstration_method="consumer_access_pdf_code",
    )
    updated_record = _require_public_transition_applied(
        updated_record,
        expected_status=SIGNING_STATUS_SENT,
        required_fields=("consented_at",),
        expected_field_values={"consented_at": consented_at},
    )
    reset_signing_session_consumer_access_attempts(session.id, record.id)
    _record_public_signing_event(
        updated_record,
        event_type=SIGNING_EVENT_CONSENT_ACCEPTED,
        session_id=session.id,
        link_token_id=session.link_token_id,
        client_ip=client_ip,
        user_agent=user_agent,
        details=build_public_signing_consumer_consent_event_details(
            updated_record,
            public_token=token,
            access_code_length=len(expected_access_code),
        ),
    )
    return {"request": _serialize_public_request(updated_record, token=token)}


@router.post("/api/signing/public/{token}/withdraw-consent")
async def withdraw_public_signing_consent(
    token: str,
    payload: PublicSigningConsentWithdrawRequest,
    request: Request,
    x_signing_session: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    if not payload.confirmed:
        raise HTTPException(status_code=400, detail="Consent withdrawal confirmation is required.")
    withdrawn_at = now_iso()
    record, session, client_ip, user_agent = _require_public_signing_session(
        token=token,
        x_signing_session=x_signing_session,
        request=request,
    )
    _require_public_signing_session_verified(record, session)
    try:
        validate_public_signing_consent_withdrawable_record(record)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    updated_record = mark_signing_request_consent_withdrawn(
        record.id,
        session_id=session.id,
        client_ip=client_ip,
        user_agent=user_agent,
        withdrawn_at=withdrawn_at,
    )
    updated_record = _require_public_transition_applied(
        updated_record,
        expected_status=SIGNING_STATUS_SENT,
        required_fields=("consent_withdrawn_at",),
        expected_field_values={"consent_withdrawn_at": withdrawn_at},
    )
    _record_public_signing_event(
        updated_record,
        event_type=SIGNING_EVENT_CONSENT_WITHDRAWN,
        session_id=session.id,
        link_token_id=session.link_token_id,
        client_ip=client_ip,
        user_agent=user_agent,
        details=build_public_signing_consumer_withdrawal_event_details(
            updated_record,
            public_token=token,
        ),
    )
    return {"request": _serialize_public_request(updated_record, token=token)}


@router.post("/api/signing/public/{token}/manual-fallback")
async def request_public_signing_manual_fallback(
    token: str,
    payload: PublicSigningManualFallbackRequest,
    request: Request,
    x_signing_session: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    requested_at = now_iso()
    record, session, client_ip, user_agent = _require_public_signing_session(
        token=token,
        x_signing_session=x_signing_session,
        request=request,
    )
    _require_public_signing_session_verified(record, session)
    if not record.manual_fallback_enabled:
        raise HTTPException(status_code=409, detail="Manual fallback is not enabled for this signing request.")
    updated_record = mark_signing_request_manual_fallback_requested(
        record.id,
        session_id=session.id,
        note=payload.note,
        client_ip=client_ip,
        user_agent=user_agent,
        requested_at=requested_at,
    )
    updated_record = _require_public_transition_applied(
        updated_record,
        expected_status=SIGNING_STATUS_SENT,
        required_fields=("manual_fallback_requested_at",),
        expected_field_values={"manual_fallback_requested_at": requested_at},
    )
    _record_public_signing_event(
        updated_record,
        event_type=SIGNING_EVENT_MANUAL_FALLBACK_REQUESTED,
        session_id=session.id,
        link_token_id=session.link_token_id,
        client_ip=client_ip,
        user_agent=user_agent,
        details={"note": payload.note},
    )
    return {"request": _serialize_public_request(updated_record, token=token)}


@router.post("/api/signing/public/{token}/adopt-signature")
async def adopt_public_signing_signature(
    token: str,
    payload: PublicSigningAdoptSignatureRequest,
    request: Request,
    x_signing_session: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    record, session, client_ip, user_agent = _require_public_signing_session(
        token=token,
        x_signing_session=x_signing_session,
        request=request,
    )
    _require_public_signing_session_verified(record, session)
    try:
        validate_public_signing_adoptable_record(record)
        normalized_signature_image = (
            normalize_signature_image_data_url(payload.signatureImageDataUrl)
            if payload.signatureImageDataUrl
            else None
        )
        adopted_mode, adopted_name, signature_image_data_url = resolve_signature_adoption_payload(
            signer_name=record.signer_name,
            signature_type=payload.signatureType,
            adopted_name=payload.adoptedName,
            signature_image_data_url=normalized_signature_image.data_url if normalized_signature_image else None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    signature_adopted_at = now_iso()
    updated_record = mark_signing_request_signature_adopted(
        record.id,
        session_id=session.id,
        adopted_name=adopted_name,
        adopted_mode=adopted_mode,
        signature_image_data_url=signature_image_data_url,
        signature_image_sha256=normalized_signature_image.sha256 if normalized_signature_image else None,
        client_ip=client_ip,
        user_agent=user_agent,
        signature_adopted_at=signature_adopted_at,
    )
    updated_record = _require_public_transition_applied(
        updated_record,
        expected_status=SIGNING_STATUS_SENT,
        required_fields=("signature_adopted_at", "signature_adopted_name", "signature_adopted_mode"),
        expected_field_values={
            "signature_adopted_at": signature_adopted_at,
            "signature_adopted_name": adopted_name,
            "signature_adopted_mode": adopted_mode,
        },
    )
    _record_public_signing_event(
        updated_record,
        event_type=SIGNING_EVENT_SIGNATURE_ADOPTED,
        session_id=session.id,
        link_token_id=session.link_token_id,
        client_ip=client_ip,
        user_agent=user_agent,
        details={
            "adoptedName": adopted_name,
            "adoptedMode": adopted_mode,
            "anchorCount": len(updated_record.anchors or []),
            "signatureImageSha256": normalized_signature_image.sha256 if normalized_signature_image else None,
        },
    )
    return {"request": _serialize_public_request(updated_record, token=token)}


@router.post("/api/signing/public/{token}/complete")
async def complete_public_signing_request(
    token: str,
    payload: PublicSigningCompleteRequest,
    request: Request,
    x_signing_session: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    if not payload.intentConfirmed:
        raise HTTPException(status_code=400, detail="Confirm the final sign action to complete this request.")
    ensure_signing_storage_configuration(validate_remote=False)
    record, session, client_ip, user_agent = _require_public_signing_session(
        token=token,
        x_signing_session=x_signing_session,
        request=request,
    )
    _require_public_signing_session_verified(record, session)
    try:
        validate_public_signing_completable_record(record)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not record.source_pdf_bucket_path or not is_gcs_path(record.source_pdf_bucket_path):
        raise HTTPException(status_code=409, detail="The immutable source PDF is missing for this signing request.")
    try:
        readable_source_bucket_path = resolve_signing_storage_read_bucket_path(
            record.source_pdf_bucket_path,
            retain_until=record.retention_until,
        )
        source_pdf_bytes = download_storage_bytes(readable_source_bucket_path)
    except Exception as exc:
        if is_public_signing_storage_not_found_error(exc):
            raise HTTPException(status_code=409, detail="The immutable source PDF is missing for this signing request.") from exc
        raise HTTPException(status_code=500, detail="Failed to load the immutable source PDF.") from exc

    completed_at = now_iso()
    existing_events = list_signing_events_for_request(record.id)
    prepared_completion = await prepare_public_signing_completion(
        record=record,
        session=session,
        client_ip=client_ip,
        user_agent=user_agent,
        completed_at=completed_at,
        source_pdf_bytes=source_pdf_bytes,
        existing_events=existing_events,
        build_bucket_uri=build_signing_bucket_uri,
    )

    uploaded_bucket_paths: list[str] = []
    try:
        staged_signed_pdf_bucket_path = upload_signing_staging_pdf_bytes_for_final(
            prepared_completion.signed_pdf_bytes,
            prepared_completion.signed_pdf_object_path,
        )
        uploaded_bucket_paths.append(staged_signed_pdf_bucket_path)
        staged_audit_manifest_bucket_path = upload_signing_staging_json_for_final(
            prepared_completion.audit_bundle.envelope_payload,
            prepared_completion.audit_manifest_object_path,
        )
        uploaded_bucket_paths.append(staged_audit_manifest_bucket_path)
        staged_audit_receipt_bucket_path = upload_signing_staging_pdf_bytes_for_final(
            prepared_completion.audit_bundle.receipt_pdf_bytes,
            prepared_completion.audit_receipt_object_path,
        )
        uploaded_bucket_paths.append(staged_audit_receipt_bucket_path)

        updated_record = complete_signing_request_transactional(
            record.id,
            session_id=session.id,
            client_ip=client_ip,
            user_agent=user_agent,
            completed_at=completed_at,
            artifact_updates=prepared_completion.artifact_updates,
            required_present_fields=("reviewed_at", "signature_adopted_at", "signature_adopted_name"),
            required_absent_fields=("manual_fallback_requested_at", "consent_withdrawn_at"),
        )
        updated_record = _require_public_transition_applied(
            updated_record,
            expected_status=SIGNING_STATUS_COMPLETED,
            required_fields=(
                "completed_at",
                "signed_pdf_bucket_path",
                "audit_manifest_bucket_path",
                "audit_receipt_bucket_path",
            ),
            expected_field_values={
                "completed_at": completed_at,
                "completed_session_id": session.id,
                "completed_verification_completed_at": prepared_completion.completed_verification_completed_at,
            },
        )
    except Exception:
        cleanup_public_signing_completion_uploads(delete_storage_object, uploaded_bucket_paths)
        raise
    final_bucket_paths = [
        prepared_completion.signed_pdf_bucket_path,
        prepared_completion.audit_manifest_bucket_path,
        prepared_completion.audit_receipt_bucket_path,
    ]
    try:
        for final_bucket_path in final_bucket_paths:
            promote_signing_staged_object(
                final_bucket_path,
                retain_until=updated_record.retention_until,
            )
    except Exception as exc:
        logger.warning(
            "Signing completion artifact promotion failed for request %s (%s): %s",
            updated_record.id,
            final_bucket_path,
            exc,
        )
        cleanup_public_signing_completion_uploads(
            delete_storage_object,
            [*uploaded_bucket_paths, *final_bucket_paths],
        )
        try:
            rollback_completed_signing_request_transactional(
                updated_record.id,
                session_id=session.id,
                completed_at=completed_at,
            )
        except Exception as rollback_exc:
            logger.warning(
                "Signing completion rollback failed for request %s after storage promotion failure: %s",
                updated_record.id,
                rollback_exc,
            )
        raise HTTPException(
            status_code=503,
            detail="Failed to finalize retained signing artifacts. Please try again.",
        ) from exc
    touch_signing_session(session.id, client_ip=client_ip, user_agent=user_agent, completed=True)
    _record_public_signing_event(
        updated_record,
        event_type=SIGNING_EVENT_COMPLETED,
        session_id=session.id,
        link_token_id=session.link_token_id,
        client_ip=client_ip,
        user_agent=user_agent,
        occurred_at=completed_at,
        details={
            "sourcePdfSha256": updated_record.source_pdf_sha256,
            "sourceVersion": updated_record.source_version,
            "adoptedName": updated_record.signature_adopted_name,
            "adoptedMode": getattr(updated_record, "signature_adopted_mode", None),
            "signatureImageSha256": getattr(updated_record, "signature_adopted_image_sha256", None),
            "signedPdfSha256": updated_record.signed_pdf_sha256,
            "pdfDigitalCertificateFingerprintSha256": getattr(
                updated_record,
                "signed_pdf_digital_certificate_fingerprint_sha256",
                None,
            ),
            "auditManifestSha256": updated_record.audit_manifest_sha256,
            "auditReceiptSha256": updated_record.audit_receipt_sha256,
            "retentionUntil": updated_record.retention_until,
        },
    )
    return {"request": _serialize_public_request(updated_record, token=token)}
