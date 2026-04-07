"""Authenticated owner endpoints for signing request setup."""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import Response, StreamingResponse

from backend.api.schemas import SigningRequestCreateRequest, SigningEnvelopeCreateRequest
from backend.firebaseDB.signing_database import (
    create_signing_envelope,
    create_signing_request,
    ENVELOPE_STATUS_COMPLETED,
    get_signing_envelope,
    get_signing_envelope_for_user,
    invalidate_signing_request,
    get_signing_request_for_user,
    list_signing_envelopes,
    list_signing_requests,
    list_signing_requests_for_envelope,
    mark_signing_request_manual_link_shared,
    mark_signing_request_sent,
    record_signing_event,
    reissue_signing_request,
    rollback_signing_request_sent,
    update_signing_envelope,
    ENVELOPE_STATUS_DRAFT,
    ENVELOPE_STATUS_INVALIDATED,
    ENVELOPE_STATUS_SENT,
    SIGNING_MODE_PARALLEL,
    SIGNING_MODE_SEQUENTIAL,
)
from backend.firebaseDB.storage_service import (
    build_signing_bucket_uri,
    delete_storage_object,
    download_storage_bytes,
)
from backend.firebaseDB.template_database import get_template
from backend.services.app_config import resolve_stream_cors_headers
from backend.services.auth_service import require_user
from backend.services.downgrade_retention_service import get_user_retention_pending_template_ids
from backend.logging_config import get_logger
from backend.services.contact_service import resolve_client_ip
from backend.services.signing_consumer_consent_service import (
    persist_business_disclosure_artifact,
    persist_consumer_disclosure_artifact,
)
from backend.services.signing_invite_service import (
    deliver_signing_invite_for_request,
    resolve_signing_invite_event_type,
    resolve_signing_invite_origin,
)
from backend.services.signing_provenance_service import record_signing_provenance_event
from backend.services.signing_dispute_package_service import (
    build_owner_dispute_package,
    owner_dispute_package_available,
)
from backend.services.signing_webhook_service import dispatch_signing_webhook_event
from backend.services.signing_storage_service import (
    ensure_signing_storage_configuration,
    is_signing_storage_not_found_error,
    promote_signing_staged_object,
    resolve_signing_stage_bucket_path,
    resolve_signing_storage_read_bucket_path,
    upload_signing_staging_pdf_bytes_for_final,
)
from backend.services.limits_service import (
    resolve_fillable_max_pages,
    resolve_signing_requests_monthly_limit,
)
from backend.services.pdf_export_service import pdf_has_form_widgets
from backend.services.pdf_service import (
    read_upload_bytes,
    resolve_upload_limit,
    safe_pdf_download_filename,
    sanitize_basename_segment,
    validate_pdf_for_detection,
)
from backend.time_utils import now_iso
from backend.services.signing_service import (
    SIGNING_ARTIFACT_SOURCE_PDF,
    SIGNING_ARTIFACT_AUDIT_MANIFEST,
    SIGNING_ARTIFACT_AUDIT_RECEIPT,
    SIGNING_ARTIFACT_DISPUTE_PACKAGE,
    SIGNING_ARTIFACT_SIGNED_PDF,
    SIGNING_MODE_FILL_AND_SIGN,
    SIGNING_MODE_SIGN,
    SIGNING_STATUS_COMPLETED,
    SIGNING_STATUS_DRAFT,
    SIGNING_STATUS_INVALIDATED,
    SIGNING_STATUS_SENT,
    SIGNING_INVITE_METHOD_EMAIL,
    SIGNING_INVITE_METHOD_MANUAL_LINK,
    SIGNING_EVENT_LINK_REISSUED,
    SIGNING_EVENT_LINK_REVOKED,
    SIGNING_EVENT_MANUAL_LINK_SHARED,
    SIGNING_EVENT_OWNER_ARTIFACT_DOWNLOADED,
    SIGNING_EVENT_REQUEST_CREATED,
    SIGNING_EVENT_REQUEST_SENT,
    build_signing_public_path,
    build_signing_public_token,
    build_signing_audit_manifest_object_path,
    build_signing_audit_receipt_object_path,
    build_signing_link_token_id,
    build_signing_signed_pdf_object_path,
    build_signing_source_pdf_object_path,
    build_signing_source_version,
    build_signing_validation_path,
    normalize_optional_sha256,
    normalize_signing_artifact_key,
    normalize_optional_text,
    normalize_signing_user_agent,
    normalize_signature_mode,
    normalize_signing_mode,
    resolve_signing_consumer_disclosure_fields,
    resolve_signing_company_authority_attestation,
    sha256_hex_for_bytes,
    resolve_document_category_label,
    resolve_signing_disclosure_version,
    resolve_signing_public_link_version,
    resolve_signing_public_status_message,
    validate_esign_eligibility_confirmation,
    signing_request_is_expired,
    serialize_signing_ceremony_state,
    serialize_signing_category_options,
    validate_document_category,
    validate_signing_reissuable_record,
    validate_signing_source_type,
    validate_signing_sendable_record,
    validate_signer_email,
    validate_signer_name,
    validate_source_document_name,
)
from backend.services.signing_quota_service import SigningRequestMonthlyLimitError


router = APIRouter()
logger = get_logger(__name__)


def upload_signing_pdf_bytes(pdf_bytes: bytes, destination_path: str) -> str:
    """Compatibility wrapper that stages bytes but returns the final signing URI."""
    upload_signing_staging_pdf_bytes_for_final(pdf_bytes, destination_path)
    return build_signing_bucket_uri(destination_path)


def _is_storage_not_found_error(exc: Exception) -> bool:
    return is_signing_storage_not_found_error(exc)


def _ensure_signing_template_is_accessible(user_id: str, source_template_id: Optional[str]) -> None:
    normalized_template_id = str(source_template_id or "").strip()
    if not normalized_template_id:
        return
    locked_template_ids = get_user_retention_pending_template_ids(user_id)
    if normalized_template_id in locked_template_ids:
        raise HTTPException(
            status_code=409,
            detail=(
                "This signing request cannot proceed because its saved form is locked on the base plan. Upgrade "
                "to reactivate that saved form before creating or sending signing drafts."
            ),
        )


def _ensure_signing_send_source_template_exists(user, record) -> None:
    normalized_template_id = str(record.source_template_id or "").strip()
    if not normalized_template_id:
        return
    if get_template(normalized_template_id, user.app_user_id) is not None:
        return
    invalidated = invalidate_signing_request(
        record.id,
        user.app_user_id,
        reason="This signing draft can no longer be sent because its saved form was deleted.",
    )
    detail = (
        invalidated.invalidation_reason
        if invalidated is not None and getattr(invalidated, "invalidation_reason", None)
        else "This signing draft can no longer be sent because its saved form was deleted."
    )
    raise HTTPException(status_code=409, detail=detail)


def _invalidate_signing_envelope_drafts(envelope, user, *, reason: str) -> None:
    normalized_reason = str(reason or "").strip() or "This signing envelope is no longer valid."
    child_requests = list_signing_requests_for_envelope(envelope.id)
    for child_request in child_requests:
        if child_request.status in {SIGNING_STATUS_COMPLETED, SIGNING_STATUS_INVALIDATED}:
            continue
        invalidate_signing_request(
            child_request.id,
            user.app_user_id,
            reason=normalized_reason,
        )
    update_signing_envelope(envelope.id, {"status": ENVELOPE_STATUS_INVALIDATED})


def _ensure_signing_envelope_send_source_template_exists(user, envelope) -> None:
    normalized_template_id = str(envelope.source_template_id or "").strip()
    if not normalized_template_id:
        return
    if get_template(normalized_template_id, user.app_user_id) is not None:
        return
    reason = "This signing envelope can no longer be sent because its saved form was deleted."
    _invalidate_signing_envelope_drafts(envelope, user, reason=reason)
    raise HTTPException(status_code=409, detail=reason)


def _rollback_signing_envelope_send(
    sent_records,
    *,
    user_id: str,
    source_pdf_bucket_path: Optional[str],
    source_pdf_sha256: Optional[str],
) -> None:
    for record in reversed(list(sent_records or [])):
        try:
            rollback_signing_request_sent(
                record.id,
                user_id,
                expected_source_pdf_bucket_path=source_pdf_bucket_path,
                expected_source_pdf_sha256=source_pdf_sha256,
            )
        except Exception as exc:
            logger.warning(
                "Failed to roll back envelope child request %s during send rollback: %s",
                getattr(record, "id", None),
                exc,
            )


def _cleanup_signing_source_upload(bucket_path: Optional[str]) -> None:
    normalized_bucket_path = str(bucket_path or "").strip()
    if not normalized_bucket_path:
        return
    candidate_paths = [normalized_bucket_path]
    try:
        readable_bucket_path = resolve_signing_storage_read_bucket_path(
            normalized_bucket_path,
            retain_until=None,
        )
    except Exception:
        readable_bucket_path = None
    if readable_bucket_path:
        candidate_paths.append(readable_bucket_path)
    try:
        staged_bucket_path = resolve_signing_stage_bucket_path(normalized_bucket_path)
    except ValueError:
        staged_bucket_path = None
    if staged_bucket_path:
        candidate_paths.append(staged_bucket_path)
    for candidate in dict.fromkeys(candidate_paths):
        try:
            delete_storage_object(candidate)
        except Exception as exc:
            logger.warning("Failed to delete signing source object %s during cleanup: %s", candidate, exc)


def _require_send_transition_applied(record, *, staged_source_path: str, expected_source_path: str):
    if record is None:
        try:
            delete_storage_object(staged_source_path)
        except Exception:
            pass
        raise HTTPException(status_code=500, detail="Failed to send signing request")
    if record.status != "sent" or record.source_pdf_bucket_path != expected_source_path:
        try:
            delete_storage_object(staged_source_path)
        except Exception:
            pass
        raise HTTPException(
            status_code=409,
            detail=resolve_signing_public_status_message(record.status, record.invalidation_reason),
        )
    return record


def _serialize_owner_artifacts(record) -> Dict[str, Any]:
    generated_at = record.artifacts_generated_at
    retention_until = record.retention_until
    dispute_package_available = owner_dispute_package_available(record)
    return {
        "sourcePdf": {
            "available": bool(record.source_pdf_bucket_path),
            "sha256": record.source_pdf_sha256,
            "bucketPath": record.source_pdf_bucket_path,
            "downloadPath": (
                f"/api/signing/requests/{record.id}/artifacts/{SIGNING_ARTIFACT_SOURCE_PDF}"
                if record.source_pdf_bucket_path
                else None
            ),
            "generatedAt": record.sent_at,
            "retentionUntil": retention_until,
        },
        "signedPdf": {
            "available": bool(record.signed_pdf_bucket_path),
            "sha256": record.signed_pdf_sha256,
            "bucketPath": record.signed_pdf_bucket_path,
            "downloadPath": (
                f"/api/signing/requests/{record.id}/artifacts/{SIGNING_ARTIFACT_SIGNED_PDF}"
                if record.signed_pdf_bucket_path
                else None
            ),
            "generatedAt": generated_at,
            "retentionUntil": retention_until,
            "digitalSignature": {
                "available": bool(record.signed_pdf_digital_signature_field_name),
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
        "auditManifest": {
            "available": bool(record.audit_manifest_bucket_path),
            "sha256": record.audit_manifest_sha256,
            "bucketPath": record.audit_manifest_bucket_path,
            "downloadPath": (
                f"/api/signing/requests/{record.id}/artifacts/{SIGNING_ARTIFACT_AUDIT_MANIFEST}"
                if record.audit_manifest_bucket_path
                else None
            ),
            "generatedAt": generated_at,
            "retentionUntil": retention_until,
            "signatureMethod": record.audit_signature_method,
            "signatureAlgorithm": record.audit_signature_algorithm,
            "kmsKeyResourceName": record.audit_kms_key_resource_name,
            "kmsKeyVersionName": record.audit_kms_key_version_name,
        },
        "auditReceipt": {
            "available": bool(record.audit_receipt_bucket_path),
            "sha256": record.audit_receipt_sha256,
            "bucketPath": record.audit_receipt_bucket_path,
            "downloadPath": (
                f"/api/signing/requests/{record.id}/artifacts/{SIGNING_ARTIFACT_AUDIT_RECEIPT}"
                if record.audit_receipt_bucket_path
                else None
            ),
            "generatedAt": generated_at,
            "retentionUntil": retention_until,
        },
        "disputePackage": {
            "available": dispute_package_available,
            "downloadPath": (
                f"/api/signing/requests/{record.id}/artifacts/{SIGNING_ARTIFACT_DISPUTE_PACKAGE}"
                if dispute_package_available
                else None
            ),
            "generatedAt": generated_at,
            "retentionUntil": retention_until,
        },
    }


def _serialize_owner_request(record) -> Dict[str, Any]:
    public_link_version = resolve_signing_public_link_version(record)
    public_link_available = record.status in {"sent", "completed"}
    return {
        "id": record.id,
        "title": record.title,
        "mode": record.mode,
        "signatureMode": record.signature_mode,
        "sourceType": record.source_type,
        "sourceId": record.source_id,
        "sourceLinkId": record.source_link_id,
        "sourceRecordLabel": record.source_record_label,
        "sourceDocumentName": record.source_document_name,
        "sourceTemplateId": record.source_template_id,
        "sourceTemplateName": record.source_template_name,
        "sourcePdfSha256": record.source_pdf_sha256,
        "sourcePdfPath": record.source_pdf_bucket_path,
        "sourceVersion": record.source_version,
        "documentCategory": record.document_category,
        "documentCategoryLabel": resolve_document_category_label(record.document_category),
        "esignEligibilityConfirmedAt": getattr(record, "esign_eligibility_confirmed_at", None),
        "esignEligibilityConfirmedSource": getattr(record, "esign_eligibility_confirmed_source", None),
        "companyBindingEnabled": bool(getattr(record, "company_binding_enabled", False)),
        "authorityAttestationVersion": getattr(record, "authority_attestation_version", None),
        "authorityAttestationText": getattr(record, "authority_attestation_text", None),
        "authorityAttestationSha256": getattr(record, "authority_attestation_sha256", None),
        "manualFallbackEnabled": record.manual_fallback_enabled,
        "signerName": record.signer_name,
        "signerEmail": record.signer_email,
        "signerContactMethod": getattr(record, "signer_contact_method", None),
        "signerAuthMethod": getattr(record, "signer_auth_method", None),
        "ownerUserId": record.user_id,
        "senderDisplayName": getattr(record, "sender_display_name", None),
        "senderEmail": getattr(record, "sender_email", None),
        "senderContactEmail": getattr(record, "sender_contact_email", None),
        "consumerPaperCopyProcedure": getattr(record, "consumer_paper_copy_procedure", None),
        "consumerPaperCopyFeeDescription": getattr(record, "consumer_paper_copy_fee_description", None),
        "consumerWithdrawalProcedure": getattr(record, "consumer_withdrawal_procedure", None),
        "consumerWithdrawalConsequences": getattr(record, "consumer_withdrawal_consequences", None),
        "consumerContactUpdateProcedure": getattr(record, "consumer_contact_update_procedure", None),
        "consumerConsentScopeDescription": getattr(record, "consumer_consent_scope_override", None),
        "inviteMethod": getattr(record, "invite_method", None),
        "inviteProvider": getattr(record, "invite_provider", None),
        "inviteProviderMessageId": getattr(record, "invite_message_id", None),
        "inviteDeliveryStatus": record.invite_delivery_status,
        "inviteLastAttemptAt": record.invite_last_attempt_at,
        "inviteSentAt": record.invite_sent_at,
        "inviteDeliveryError": record.invite_delivery_error,
        "inviteDeliveryErrorCode": getattr(record, "invite_delivery_error_code", None),
        "manualLinkSharedAt": getattr(record, "manual_link_shared_at", None),
        "status": record.status,
        "anchors": record.anchors,
        "disclosureVersion": record.disclosure_version,
        "createdAt": record.created_at,
        "updatedAt": record.updated_at,
        "ownerReviewConfirmedAt": record.owner_review_confirmed_at,
        "sentAt": record.sent_at,
        "completedAt": record.completed_at,
        "expiresAt": getattr(record, "expires_at", None),
        "isExpired": signing_request_is_expired(record),
        "publicLinkVersion": public_link_version,
        "publicLinkRevokedAt": getattr(record, "public_link_revoked_at", None),
        "publicLinkLastReissuedAt": getattr(record, "public_link_last_reissued_at", None),
        "validationPath": build_signing_validation_path(record.id),
        "invalidatedAt": record.invalidated_at,
        "invalidationReason": record.invalidation_reason,
        "retentionUntil": record.retention_until,
        "artifacts": _serialize_owner_artifacts(record),
        **serialize_signing_ceremony_state(record),
        "publicToken": build_signing_public_token(record.id, public_link_version) if public_link_available else None,
        "publicPath": build_signing_public_path(record.id, public_link_version) if public_link_available else None,
        "envelopeId": getattr(record, "envelope_id", None),
        "signerOrder": getattr(record, "signer_order", 1),
        "turnActivatedAt": getattr(record, "turn_activated_at", None),
    }

def _record_owner_request_created_event(
    record,
    *,
    sender_email: Optional[str],
    client_ip: Optional[str],
    user_agent: Optional[str],
    source: str,
) -> None:
    record_signing_provenance_event(
        record,
        event_type=SIGNING_EVENT_REQUEST_CREATED,
        sender_email=sender_email,
        invite_method=SIGNING_INVITE_METHOD_EMAIL,
        source=source,
        client_ip=client_ip,
        user_agent=user_agent,
        include_link_token=False,
        extra={
            "statusAfter": record.status,
            "sourceType": record.source_type,
            "sourceId": record.source_id,
        },
        occurred_at=record.created_at,
    )


def _record_owner_request_sent_event(
    record,
    *,
    sender_email: Optional[str],
    client_ip: Optional[str],
    user_agent: Optional[str],
    source: str,
) -> None:
    record_signing_provenance_event(
        record,
        event_type=SIGNING_EVENT_REQUEST_SENT,
        sender_email=sender_email,
        invite_method=SIGNING_INVITE_METHOD_EMAIL,
        source=source,
        client_ip=client_ip,
        user_agent=user_agent,
        extra={
            "statusBefore": SIGNING_STATUS_DRAFT,
            "statusAfter": record.status,
            "publicLinkVersion": resolve_signing_public_link_version(record),
            "expiresAt": record.expires_at,
        },
        occurred_at=record.sent_at,
    )


def _record_owner_invite_delivery_event(
    record,
    *,
    delivery,
    sender_email: Optional[str],
    client_ip: Optional[str],
    user_agent: Optional[str],
    source: str,
) -> None:
    event_type = resolve_signing_invite_event_type(getattr(delivery, "delivery_status", None))
    if not event_type:
        return
    record_signing_provenance_event(
        record,
        event_type=event_type,
        sender_email=sender_email,
        invite_method=SIGNING_INVITE_METHOD_EMAIL,
        source=source,
        client_ip=client_ip,
        user_agent=user_agent,
        extra={
            "provider": getattr(delivery, "provider", None),
            "providerMessageId": getattr(delivery, "invite_message_id", None),
            "deliveryStatus": getattr(delivery, "delivery_status", None),
            "deliveryErrorCode": getattr(delivery, "error_code", None),
            "deliveryErrorSummary": getattr(delivery, "error_message", None),
            "publicLinkVersion": resolve_signing_public_link_version(record),
        },
        occurred_at=getattr(delivery, "sent_at", None) or getattr(delivery, "attempted_at", None),
    )


def _resolve_owner_artifact(record, artifact_key: str) -> tuple[str, str, str]:
    normalized_key = normalize_signing_artifact_key(artifact_key)
    if normalized_key == SIGNING_ARTIFACT_SOURCE_PDF and record.source_pdf_bucket_path:
        filename = safe_pdf_download_filename(f"{record.source_document_name or 'document'}-source", "source-document")
        return record.source_pdf_bucket_path, "application/pdf", filename
    if normalized_key == SIGNING_ARTIFACT_SIGNED_PDF and record.signed_pdf_bucket_path:
        filename = safe_pdf_download_filename(f"{record.source_document_name or 'document'}-signed", "signed-document")
        return record.signed_pdf_bucket_path, "application/pdf", filename
    if normalized_key == SIGNING_ARTIFACT_AUDIT_RECEIPT and record.audit_receipt_bucket_path:
        filename = safe_pdf_download_filename(f"{record.source_document_name or 'document'}-audit-receipt", "audit-receipt")
        return record.audit_receipt_bucket_path, "application/pdf", filename
    if normalized_key == SIGNING_ARTIFACT_AUDIT_MANIFEST and record.audit_manifest_bucket_path:
        base_name = sanitize_basename_segment(f"{record.source_document_name or 'document'}-audit-manifest", "audit-manifest")
        return record.audit_manifest_bucket_path, "application/json", f"{base_name}.json"
    raise HTTPException(status_code=404, detail="Signing artifact is not available")


@router.get("/api/signing/options")
async def get_signing_options(authorization: Optional[str] = Header(default=None)) -> Dict[str, Any]:
    require_user(authorization)
    return {
        "modes": [
            {"key": "sign", "label": "Sign"},
            {"key": "fill_and_sign", "label": "Fill and Sign"},
        ],
        "signatureModes": [
            {"key": "business", "label": "Business"},
            {"key": "consumer", "label": "Consumer"},
        ],
        "categories": serialize_signing_category_options(),
    }


@router.get("/api/signing/requests")
async def list_owner_signing_requests(authorization: Optional[str] = Header(default=None)) -> Dict[str, Any]:
    user = require_user(authorization)
    records = list_signing_requests(user.app_user_id)
    return {"requests": [_serialize_owner_request(record) for record in records]}


@router.get("/api/signing/requests/{request_id}")
async def get_owner_signing_request(
    request_id: str,
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    user = require_user(authorization)
    record = get_signing_request_for_user(request_id, user.app_user_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Signing request not found")
    return {"request": _serialize_owner_request(record)}


@router.get("/api/signing/requests/{request_id}/artifacts")
async def get_owner_signing_artifacts(
    request_id: str,
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    user = require_user(authorization)
    record = get_signing_request_for_user(request_id, user.app_user_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Signing request not found")
    return {
        "requestId": record.id,
        "retentionUntil": record.retention_until,
        "artifacts": _serialize_owner_artifacts(record),
    }


@router.get("/api/signing/requests/{request_id}/artifacts/{artifact_key}")
async def download_owner_signing_artifact(
    request_id: str,
    artifact_key: str,
    request: Request,
    authorization: Optional[str] = Header(default=None),
):
    user = require_user(authorization)
    ensure_signing_storage_configuration(validate_remote=False)
    record = get_signing_request_for_user(request_id, user.app_user_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Signing request not found")
    normalized_key = normalize_signing_artifact_key(artifact_key)
    if getattr(record, "envelope_id", None) and normalized_key in {
        SIGNING_ARTIFACT_SIGNED_PDF,
        SIGNING_ARTIFACT_AUDIT_RECEIPT,
        SIGNING_ARTIFACT_AUDIT_MANIFEST,
        SIGNING_ARTIFACT_DISPUTE_PACKAGE,
    }:
        envelope = get_signing_envelope_for_user(record.envelope_id, user.app_user_id)
        if envelope:
            if envelope.completed_signer_count < envelope.signer_count:
                remaining = envelope.signer_count - envelope.completed_signer_count
                raise HTTPException(
                    status_code=409,
                    detail=f"{remaining} {'signer' if remaining == 1 else 'signers'} still {'needs' if remaining == 1 else 'need'} to sign before the signed PDF is available.",
                )
            if envelope.status != ENVELOPE_STATUS_COMPLETED:
                raise HTTPException(
                    status_code=409,
                    detail="Envelope artifacts are still being finalized. Try again shortly.",
                )
    bucket_path: Optional[str] = None
    media_type: str
    filename: str
    body: bytes
    if normalized_key == SIGNING_ARTIFACT_DISPUTE_PACKAGE:
        try:
            package = await build_owner_dispute_package(record)
        except Exception as exc:
            if _is_storage_not_found_error(exc):
                raise HTTPException(status_code=404, detail="Signing artifact is not available") from exc
            raise HTTPException(status_code=500, detail="Failed to load signing artifact") from exc
        media_type = package.media_type
        filename = package.filename
        body = package.body
    else:
        bucket_path, media_type, filename = _resolve_owner_artifact(record, normalized_key)
        try:
            readable_bucket_path = resolve_signing_storage_read_bucket_path(
                bucket_path,
                retain_until=record.retention_until,
            )
            body = download_storage_bytes(readable_bucket_path)
        except Exception as exc:
            if _is_storage_not_found_error(exc):
                raise HTTPException(status_code=404, detail="Signing artifact is not available") from exc
            raise HTTPException(status_code=500, detail="Failed to load signing artifact") from exc
    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Cache-Control": "private, no-store",
    }
    headers.update(resolve_stream_cors_headers(request.headers.get("origin")))
    record_signing_provenance_event(
        record,
        event_type=SIGNING_EVENT_OWNER_ARTIFACT_DOWNLOADED,
        sender_email=user.email,
        source="owner_artifact_download",
        client_ip=resolve_client_ip(request),
        user_agent=normalize_signing_user_agent(request.headers.get("user-agent")),
        extra={
            "artifactKey": normalized_key,
            "bucketPath": bucket_path,
            "mediaType": media_type,
        },
    )
    if media_type == "application/json":
        return Response(content=body, media_type=media_type, headers=headers)
    return StreamingResponse(
        iter([body]),
        media_type=media_type,
        headers=headers,
    )


@router.post("/api/signing/requests", status_code=201)
async def create_owner_signing_request(
    payload: SigningRequestCreateRequest,
    request: Request,
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    user = require_user(authorization)
    try:
        mode = normalize_signing_mode(payload.mode)
        signature_mode = normalize_signature_mode(payload.signatureMode)
        source_type = validate_signing_source_type(
            mode=mode,
            source_type=payload.sourceType,
            source_id=payload.sourceId,
        )
        document_category = validate_document_category(payload.documentCategory)
        validate_esign_eligibility_confirmation(payload.esignEligibilityConfirmed)
        signer_name = validate_signer_name(payload.signerName)
        signer_email = validate_signer_email(payload.signerEmail)
        source_document_name = validate_source_document_name(payload.sourceDocumentName)
        disclosure_version = resolve_signing_disclosure_version(signature_mode)
        authority_attestation = resolve_signing_company_authority_attestation(payload.companyBindingEnabled)
        consumer_disclosure_fields = resolve_signing_consumer_disclosure_fields(
            signature_mode=signature_mode,
            sender_display_name=user.display_name,
            sender_email=user.email,
            paper_copy_procedure=payload.consumerPaperCopyProcedure,
            paper_copy_fee_description=payload.consumerPaperCopyFeeDescription,
            withdrawal_procedure=payload.consumerWithdrawalProcedure,
            withdrawal_consequences=payload.consumerWithdrawalConsequences,
            contact_update_procedure=payload.consumerContactUpdateProcedure,
            consent_scope_description=payload.consumerConsentScopeDescription,
            require_complete=True,
        )
        source_pdf_sha256 = normalize_optional_sha256(payload.sourcePdfSha256)
        if not source_pdf_sha256:
            raise ValueError("Signing drafts must include the current immutable source PDF SHA-256.")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    anchors = [anchor.model_dump(exclude_none=True) for anchor in payload.anchors]
    _ensure_signing_template_is_accessible(
        user.app_user_id,
        normalize_optional_text(payload.sourceTemplateId, maximum_length=160),
    )
    source_version = build_signing_source_version(
        source_type=source_type,
        source_id=normalize_optional_text(payload.sourceId, maximum_length=160),
        source_template_id=normalize_optional_text(payload.sourceTemplateId, maximum_length=160),
        source_pdf_sha256=source_pdf_sha256,
    )
    record = create_signing_request(
        user_id=user.app_user_id,
        title=normalize_optional_text(payload.title),
        mode=mode,
        signature_mode=signature_mode,
        source_type=source_type,
        source_id=normalize_optional_text(payload.sourceId, maximum_length=160),
        source_link_id=normalize_optional_text(payload.sourceLinkId, maximum_length=160),
        source_record_label=normalize_optional_text(payload.sourceRecordLabel),
        source_document_name=source_document_name,
        source_template_id=normalize_optional_text(payload.sourceTemplateId, maximum_length=160),
        source_template_name=normalize_optional_text(payload.sourceTemplateName),
        source_pdf_sha256=source_pdf_sha256,
        source_version=source_version,
        document_category=document_category,
        company_binding_enabled=bool(payload.companyBindingEnabled),
        authority_attestation_version=authority_attestation.get("version") if authority_attestation else None,
        authority_attestation_text=authority_attestation.get("text") if authority_attestation else None,
        authority_attestation_sha256=authority_attestation.get("sha256") if authority_attestation else None,
        manual_fallback_enabled=bool(payload.manualFallbackEnabled),
        signer_name=signer_name,
        signer_email=signer_email,
        anchors=anchors,
        disclosure_version=disclosure_version,
        sender_display_name=consumer_disclosure_fields["sender_display_name"] or user.display_name,
        esign_eligibility_confirmed_source="owner_request_create",
        sender_email=user.email,
        sender_contact_email=consumer_disclosure_fields["sender_contact_email"] or user.email,
        consumer_paper_copy_procedure=consumer_disclosure_fields["paper_copy_procedure"],
        consumer_paper_copy_fee_description=consumer_disclosure_fields["paper_copy_fee_description"],
        consumer_withdrawal_procedure=consumer_disclosure_fields["withdrawal_procedure"],
        consumer_withdrawal_consequences=consumer_disclosure_fields["withdrawal_consequences"],
        consumer_contact_update_procedure=consumer_disclosure_fields["contact_update_procedure"],
        consumer_consent_scope_override=consumer_disclosure_fields["consent_scope_description"],
        invite_method=SIGNING_INVITE_METHOD_EMAIL,
    )
    _record_owner_request_created_event(
        record,
        sender_email=user.email,
        client_ip=resolve_client_ip(request),
        user_agent=normalize_signing_user_agent(request.headers.get("user-agent")),
        source="owner_ui",
    )
    return {"request": _serialize_owner_request(record)}


@router.post("/api/signing/requests/{request_id}/revoke")
async def revoke_owner_signing_request(
    request_id: str,
    request: Request,
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    user = require_user(authorization)
    record = get_signing_request_for_user(request_id, user.app_user_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Signing request not found")
    if record.status == SIGNING_STATUS_COMPLETED:
        raise HTTPException(status_code=409, detail="Completed signing requests cannot be revoked.")
    if record.status == SIGNING_STATUS_INVALIDATED:
        return {"request": _serialize_owner_request(record)}
    reason = (
        "This signing draft was canceled by the sender."
        if record.status == "draft"
        else "This signing request was revoked by the sender."
    )
    public_link_version = resolve_signing_public_link_version(record)
    revoked_record = invalidate_signing_request(
        record.id,
        user.app_user_id,
        reason=reason,
        mark_public_link_revoked=record.status == "sent",
    )
    if revoked_record is None:
        raise HTTPException(status_code=500, detail="Failed to revoke the signing request.")
    if record.status == "sent":
        link_token = build_signing_public_token(record.id, public_link_version)
        record_signing_event(
            record.id,
            event_type=SIGNING_EVENT_LINK_REVOKED,
            session_id=None,
            link_token_id=build_signing_link_token_id(link_token),
            client_ip=resolve_client_ip(request),
            user_agent=normalize_signing_user_agent(request.headers.get("user-agent")),
            details={
                "publicLinkVersion": public_link_version,
                "reason": reason,
                "statusBefore": record.status,
            },
            occurred_at=revoked_record.public_link_revoked_at or revoked_record.invalidated_at,
        )
        dispatch_signing_webhook_event(
            revoked_record,
            event_type=SIGNING_EVENT_LINK_REVOKED,
            details={
                "publicLinkVersion": public_link_version,
                "reason": reason,
                "statusBefore": record.status,
            },
            occurred_at=revoked_record.public_link_revoked_at or revoked_record.invalidated_at,
        )
    return {"request": _serialize_owner_request(revoked_record)}


@router.post("/api/signing/requests/{request_id}/send")
async def send_owner_signing_request(
    request_id: str,
    request: Request,
    pdf: UploadFile = File(...),
    sourcePdfSha256: Optional[str] = Form(default=None),
    ownerReviewConfirmed: Optional[bool] = Form(default=None),
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    user = require_user(authorization)
    ensure_signing_storage_configuration(validate_remote=False)
    record = get_signing_request_for_user(request_id, user.app_user_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Signing request not found")
    try:
        validate_signing_sendable_record(record, owner_review_confirmed=bool(ownerReviewConfirmed))
    except ValueError as exc:
        status_code = 409 if record.status == SIGNING_STATUS_INVALIDATED else 400
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    _ensure_signing_template_is_accessible(user.app_user_id, record.source_template_id)
    _ensure_signing_send_source_template_exists(user, record)

    if not pdf:
        raise HTTPException(status_code=400, detail="Missing PDF upload")
    filename = pdf.filename or "signing-source.pdf"
    content_type = (pdf.content_type or "").lower()
    if not filename.lower().endswith(".pdf") and content_type not in {"application/pdf", "application/octet-stream"}:
        raise HTTPException(status_code=400, detail="Only PDF uploads are supported")

    max_mb, max_bytes = resolve_upload_limit()
    pdf_bytes = await read_upload_bytes(
        pdf,
        max_bytes=max_bytes,
        limit_message=f"PDF exceeds {max_mb}MB upload limit",
    )
    if not pdf_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")
    validation = validate_pdf_for_detection(pdf_bytes)
    max_pages = resolve_fillable_max_pages(user.role)
    if validation.page_count > max_pages:
        raise HTTPException(
            status_code=403,
            detail=f"Signing upload limited to {max_pages} pages for your tier (got {validation.page_count}).",
        )

    if pdf_has_form_widgets(validation.pdf_bytes):
        raise HTTPException(
            status_code=400,
            detail="Uploaded signing source PDF must already be flattened before send. Refresh the workspace and try again.",
        )

    current_sha256 = sha256_hex_for_bytes(validation.pdf_bytes)
    try:
        normalized_client_sha256 = normalize_optional_sha256(sourcePdfSha256)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if normalized_client_sha256 and normalized_client_sha256 != current_sha256:
        raise HTTPException(status_code=400, detail="Uploaded PDF hash does not match the claimed source PDF SHA-256.")

    if current_sha256 != record.source_pdf_sha256:
        invalidated = invalidate_signing_request(
            record.id,
            user.app_user_id,
            reason="The source PDF changed after this signing draft was created. Create a new draft before sending.",
        )
        detail = invalidated.invalidation_reason if invalidated else "Signing request invalidated because the source PDF changed."
        raise HTTPException(status_code=409, detail=detail)

    source_version = build_signing_source_version(
        source_type=record.source_type,
        source_id=record.source_id,
        source_template_id=record.source_template_id,
        source_pdf_sha256=current_sha256,
    )
    source_pdf_object_path = build_signing_source_pdf_object_path(
        user_id=user.app_user_id,
        request_id=record.id,
        source_document_name=record.source_document_name or filename,
    )
    source_pdf_bucket_path = upload_signing_pdf_bytes(
        validation.pdf_bytes,
        source_pdf_object_path,
    )
    public_app_origin = resolve_signing_invite_origin(
        request_origin=request.headers.get("origin") or request.headers.get("referer"),
    )
    normalized_client_ip = resolve_client_ip(request)
    owner_user_agent = normalize_signing_user_agent(request.headers.get("user-agent"))
    try:
        staged_source_pdf_bucket_path = resolve_signing_stage_bucket_path(source_pdf_bucket_path)
    except ValueError:
        staged_source_pdf_bucket_path = source_pdf_bucket_path
    try:
        sent_record = mark_signing_request_sent(
            record.id,
            user.app_user_id,
            source_pdf_bucket_path=source_pdf_bucket_path,
            source_pdf_sha256=current_sha256,
            source_version=source_version,
            monthly_limit=resolve_signing_requests_monthly_limit(user.role),
            owner_review_confirmed_at=(
                now_iso()
                if record.mode == SIGNING_MODE_FILL_AND_SIGN and bool(ownerReviewConfirmed)
                else record.owner_review_confirmed_at
            ),
            public_app_origin=public_app_origin,
        )
    except SigningRequestMonthlyLimitError as exc:
        try:
            delete_storage_object(staged_source_pdf_bucket_path)
        except Exception:
            logger.warning(
                "Failed to delete staged signing source PDF after quota rejection for request %s: %s",
                record.id,
                staged_source_pdf_bucket_path,
            )
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    sent_record = _require_send_transition_applied(
        sent_record,
        staged_source_path=staged_source_pdf_bucket_path,
        expected_source_path=source_pdf_bucket_path,
    )
    try:
        promote_signing_staged_object(
            source_pdf_bucket_path,
            retain_until=sent_record.retention_until,
        )
    except Exception as exc:
        logger.warning(
            "Owner signing source promotion failed for request %s (%s): %s",
            record.id,
            source_pdf_bucket_path,
            exc,
        )
        rollback_signing_request_sent(
            sent_record.id,
            user.app_user_id,
            expected_source_pdf_bucket_path=source_pdf_bucket_path,
            expected_source_pdf_sha256=current_sha256,
        )
        try:
            delete_storage_object(staged_source_pdf_bucket_path)
        except Exception:
            logger.warning(
                "Failed to delete staged signing source PDF after promotion failure for request %s: %s",
                record.id,
                staged_source_pdf_bucket_path,
            )
        raise HTTPException(
            status_code=503,
            detail="Failed to finalize the retained source PDF for this signing request. Please try again.",
        ) from exc
    sent_record = persist_business_disclosure_artifact(sent_record) or sent_record
    sent_record = persist_consumer_disclosure_artifact(sent_record) or sent_record
    _record_owner_request_sent_event(
        sent_record,
        sender_email=user.email,
        client_ip=normalized_client_ip,
        user_agent=owner_user_agent,
        source="owner_ui",
    )
    invite_attempt = await deliver_signing_invite_for_request(
        record=sent_record,
        user_id=user.app_user_id,
        sender_email=user.email,
        request_origin=request.headers.get("origin") or request.headers.get("referer"),
    )
    _record_owner_invite_delivery_event(
        invite_attempt.record,
        delivery=invite_attempt.delivery,
        sender_email=user.email,
        client_ip=normalized_client_ip,
        user_agent=owner_user_agent,
        source="owner_ui",
    )
    return {"request": _serialize_owner_request(invite_attempt.record)}


@router.post("/api/signing/requests/{request_id}/reissue")
async def reissue_owner_signing_request(
    request_id: str,
    request: Request,
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    user = require_user(authorization)
    record = get_signing_request_for_user(request_id, user.app_user_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Signing request not found")
    try:
        validate_signing_reissuable_record(record)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    previous_public_link_version = resolve_signing_public_link_version(record)
    previous_public_token = build_signing_public_token(record.id, previous_public_link_version)
    sequential_waiting_turn = False
    if getattr(record, "envelope_id", None):
        envelope = get_signing_envelope(record.envelope_id)
        sequential_waiting_turn = bool(
            envelope is not None
            and envelope.signing_mode == SIGNING_MODE_SEQUENTIAL
            and not getattr(record, "turn_activated_at", None)
        )
    reissued_record = reissue_signing_request(
        record.id,
        user.app_user_id,
        public_app_origin=resolve_signing_invite_origin(
            request_origin=request.headers.get("origin") or request.headers.get("referer"),
        ),
        invite_delivery_status="queued" if sequential_waiting_turn else "pending",
    )
    if reissued_record is None:
        raise HTTPException(status_code=500, detail="Failed to reissue the signing link.")
    next_public_link_version = resolve_signing_public_link_version(reissued_record)
    if reissued_record.status != "sent" or next_public_link_version <= previous_public_link_version:
        raise HTTPException(
            status_code=409,
            detail=resolve_signing_public_status_message(reissued_record.status, reissued_record.invalidation_reason),
        )
    reissued_record = persist_business_disclosure_artifact(reissued_record) or reissued_record
    reissued_record = persist_consumer_disclosure_artifact(reissued_record) or reissued_record
    client_ip = resolve_client_ip(request)
    user_agent = normalize_signing_user_agent(request.headers.get("user-agent"))

    next_public_token = build_signing_public_token(reissued_record.id, next_public_link_version)
    record_signing_event(
        reissued_record.id,
        event_type=SIGNING_EVENT_LINK_REISSUED,
        session_id=None,
        link_token_id=build_signing_link_token_id(next_public_token),
        client_ip=client_ip,
        user_agent=user_agent,
        details={
            "previousPublicLinkVersion": previous_public_link_version,
            "publicLinkVersion": next_public_link_version,
            "previousLinkTokenId": build_signing_link_token_id(previous_public_token),
            "statusBefore": record.status,
            "previousExpiresAt": record.expires_at,
            "previousRevokedAt": getattr(record, "public_link_revoked_at", None),
            "wasExpired": signing_request_is_expired(record),
        },
        occurred_at=getattr(reissued_record, "public_link_last_reissued_at", None) or reissued_record.sent_at,
    )
    dispatch_signing_webhook_event(
        reissued_record,
        event_type=SIGNING_EVENT_LINK_REISSUED,
        details={
            "previousPublicLinkVersion": previous_public_link_version,
            "publicLinkVersion": next_public_link_version,
            "previousLinkTokenId": build_signing_link_token_id(previous_public_token),
            "statusBefore": record.status,
            "previousExpiresAt": record.expires_at,
            "previousRevokedAt": getattr(record, "public_link_revoked_at", None),
            "wasExpired": signing_request_is_expired(record),
        },
        occurred_at=getattr(reissued_record, "public_link_last_reissued_at", None) or reissued_record.sent_at,
    )
    if sequential_waiting_turn:
        return {"request": _serialize_owner_request(reissued_record)}

    invite_attempt = await deliver_signing_invite_for_request(
        record=reissued_record,
        user_id=user.app_user_id,
        sender_email=user.email,
        request_origin=request.headers.get("origin") or request.headers.get("referer"),
    )
    _record_owner_invite_delivery_event(
        invite_attempt.record,
        delivery=invite_attempt.delivery,
        sender_email=user.email,
        client_ip=client_ip,
        user_agent=user_agent,
        source="owner_reissue",
    )
    return {"request": _serialize_owner_request(invite_attempt.record)}


@router.post("/api/signing/requests/{request_id}/manual-share")
async def record_owner_signing_manual_share(
    request_id: str,
    request: Request,
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    user = require_user(authorization)
    record = get_signing_request_for_user(request_id, user.app_user_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Signing request not found")
    if record.status not in {SIGNING_STATUS_SENT, SIGNING_STATUS_COMPLETED}:
        raise HTTPException(status_code=409, detail="Only active or completed signing requests can be shared manually.")
    if record.status == SIGNING_STATUS_SENT and signing_request_is_expired(record):
        raise HTTPException(status_code=409, detail="Expired signer links cannot be shared. Reissue the request first.")

    shared_record = mark_signing_request_manual_link_shared(
        record.id,
        user.app_user_id,
        sender_email=user.email,
    )
    if shared_record is None:
        raise HTTPException(status_code=500, detail="Failed to record signer link sharing.")
    record_signing_provenance_event(
        shared_record,
        event_type=SIGNING_EVENT_MANUAL_LINK_SHARED,
        sender_email=user.email,
        invite_method=SIGNING_INVITE_METHOD_MANUAL_LINK,
        source="owner_manual_share",
        client_ip=resolve_client_ip(request),
        user_agent=normalize_signing_user_agent(request.headers.get("user-agent")),
        extra={
            "publicLinkVersion": resolve_signing_public_link_version(shared_record),
            "statusAtShare": shared_record.status,
        },
        occurred_at=getattr(shared_record, "manual_link_shared_at", None),
    )
    return {"request": _serialize_owner_request(shared_record)}


# ---------------------------------------------------------------------------
# Signing envelope endpoints
# ---------------------------------------------------------------------------


def _serialize_owner_envelope(envelope) -> Dict[str, Any]:
    return {
        "id": envelope.id,
        "title": envelope.title,
        "mode": envelope.mode,
        "signatureMode": envelope.signature_mode,
        "signingMode": envelope.signing_mode,
        "signerCount": envelope.signer_count,
        "completedSignerCount": envelope.completed_signer_count,
        "status": envelope.status,
        "sourceDocumentName": envelope.source_document_name,
        "sourcePdfSha256": envelope.source_pdf_sha256,
        "signedPdfSha256": getattr(envelope, "signed_pdf_sha256", None),
        "createdAt": envelope.created_at,
        "updatedAt": envelope.updated_at,
        "completedAt": envelope.completed_at,
        "expiresAt": envelope.expires_at,
    }


def _group_envelope_anchors_by_recipient_order(
    anchors: list[Dict[str, Any]],
    recipients,
) -> Dict[int, list[Dict[str, Any]]]:
    """Validate recipient assignments once, then bucket anchors by signer order.

    Multi-signer rendering is deterministic only when each overlay belongs to a
    specific signer. Rejecting unassigned or unknown recipient orders here keeps
    creation-time validation O(anchor_count + recipient_count) and avoids later
    send-time failures or duplicated overlay content across child requests.
    """

    recipient_orders = sorted({int(recipient.order) for recipient in recipients})
    anchors_by_order: Dict[int, list[Dict[str, Any]]] = {
        order: [] for order in recipient_orders
    }
    signature_anchor_counts = {order: 0 for order in recipient_orders}

    for anchor in anchors:
        assigned_order = anchor.get("assignedSignerOrder")
        if assigned_order is None:
            raise HTTPException(
                status_code=400,
                detail="Every envelope anchor must be assigned to a signer.",
            )
        normalized_order = int(assigned_order)
        if normalized_order not in anchors_by_order:
            raise HTTPException(
                status_code=400,
                detail=f"Anchor assigned to signer order {normalized_order}, but no recipient has that order.",
            )
        anchors_by_order[normalized_order].append(anchor)
        if str(anchor.get("kind") or "").strip() == "signature":
            signature_anchor_counts[normalized_order] += 1

    missing_signature_orders = [
        order for order in recipient_orders if signature_anchor_counts[order] <= 0
    ]
    if missing_signature_orders:
        if len(missing_signature_orders) == 1:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Recipient order {missing_signature_orders[0]} must have at least "
                    "one signature anchor before creating this signing envelope."
                ),
            )
        missing_orders_label = ", ".join(str(order) for order in missing_signature_orders)
        raise HTTPException(
            status_code=400,
            detail=(
                f"Recipient orders {missing_orders_label} must each have at least one "
                "signature anchor before creating this signing envelope."
            ),
        )

    return anchors_by_order


@router.post("/api/signing/envelopes", status_code=201)
async def create_owner_signing_envelope(
    payload: SigningEnvelopeCreateRequest,
    request: Request,
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    user = require_user(authorization)
    try:
        mode = normalize_signing_mode(payload.mode)
        signature_mode = normalize_signature_mode(payload.signatureMode)
        source_type = validate_signing_source_type(
            mode=mode,
            source_type=payload.sourceType,
            source_id=payload.sourceId,
        )
        document_category = validate_document_category(payload.documentCategory)
        validate_esign_eligibility_confirmation(payload.esignEligibilityConfirmed)
        source_document_name = validate_source_document_name(payload.sourceDocumentName)
        disclosure_version = resolve_signing_disclosure_version(signature_mode)
        authority_attestation = resolve_signing_company_authority_attestation(payload.companyBindingEnabled)
        consumer_disclosure_fields = resolve_signing_consumer_disclosure_fields(
            signature_mode=signature_mode,
            sender_display_name=user.display_name,
            sender_email=user.email,
            paper_copy_procedure=payload.consumerPaperCopyProcedure,
            paper_copy_fee_description=payload.consumerPaperCopyFeeDescription,
            withdrawal_procedure=payload.consumerWithdrawalProcedure,
            withdrawal_consequences=payload.consumerWithdrawalConsequences,
            contact_update_procedure=payload.consumerContactUpdateProcedure,
            consent_scope_description=payload.consumerConsentScopeDescription,
            require_complete=True,
        )
        source_pdf_sha256 = normalize_optional_sha256(payload.sourcePdfSha256)
        if not source_pdf_sha256:
            raise ValueError("Signing envelopes must include the current immutable source PDF SHA-256.")
        recipients = payload.recipients
        if not recipients:
            raise ValueError("At least one recipient is required.")
        for r in recipients:
            validate_signer_name(r.name)
            validate_signer_email(r.email)
        recipient_orders = [r.order for r in recipients]
        if len(set(recipient_orders)) != len(recipient_orders):
            raise ValueError("Signing envelope recipients must use unique order values.")
        expected_orders = list(range(1, len(recipients) + 1))
        if sorted(recipient_orders) != expected_orders:
            raise ValueError(
                f"Signing envelope recipient orders must be consecutive starting at 1 ({expected_orders})."
            )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    anchors = [anchor.model_dump(exclude_none=True) for anchor in payload.anchors]
    anchors_by_order = _group_envelope_anchors_by_recipient_order(anchors, recipients)
    _ensure_signing_template_is_accessible(
        user.app_user_id,
        normalize_optional_text(payload.sourceTemplateId, maximum_length=160),
    )
    source_version = build_signing_source_version(
        source_type=source_type,
        source_id=normalize_optional_text(payload.sourceId, maximum_length=160),
        source_template_id=normalize_optional_text(payload.sourceTemplateId, maximum_length=160),
        source_pdf_sha256=source_pdf_sha256,
    )

    envelope = create_signing_envelope(
        user_id=user.app_user_id,
        title=normalize_optional_text(payload.title),
        mode=mode,
        signature_mode=signature_mode,
        signing_mode=payload.signingMode,
        signer_count=len(recipients),
        source_type=source_type,
        source_document_name=source_document_name,
        document_category=document_category,
        manual_fallback_enabled=bool(payload.manualFallbackEnabled),
        anchors=anchors,
        source_id=normalize_optional_text(payload.sourceId, maximum_length=160),
        source_link_id=normalize_optional_text(payload.sourceLinkId, maximum_length=160),
        source_record_label=normalize_optional_text(payload.sourceRecordLabel),
        source_template_id=normalize_optional_text(payload.sourceTemplateId, maximum_length=160),
        source_template_name=normalize_optional_text(payload.sourceTemplateName),
        source_pdf_sha256=source_pdf_sha256,
        source_version=source_version,
        company_binding_enabled=bool(payload.companyBindingEnabled),
        consumer_paper_copy_procedure=consumer_disclosure_fields["paper_copy_procedure"],
        consumer_paper_copy_fee_description=consumer_disclosure_fields["paper_copy_fee_description"],
        consumer_withdrawal_procedure=consumer_disclosure_fields["withdrawal_procedure"],
        consumer_withdrawal_consequences=consumer_disclosure_fields["withdrawal_consequences"],
        consumer_contact_update_procedure=consumer_disclosure_fields["contact_update_procedure"],
        consumer_consent_scope_override=consumer_disclosure_fields["consent_scope_description"],
    )

    created_requests = []
    for recipient in recipients:
        signer_anchors = list(anchors_by_order.get(recipient.order, ()))
        record = create_signing_request(
            user_id=user.app_user_id,
            title=normalize_optional_text(payload.title),
            mode=mode,
            signature_mode=signature_mode,
            source_type=source_type,
            source_id=normalize_optional_text(payload.sourceId, maximum_length=160),
            source_link_id=normalize_optional_text(payload.sourceLinkId, maximum_length=160),
            source_record_label=normalize_optional_text(payload.sourceRecordLabel),
            source_document_name=source_document_name,
            source_template_id=normalize_optional_text(payload.sourceTemplateId, maximum_length=160),
            source_template_name=normalize_optional_text(payload.sourceTemplateName),
            source_pdf_sha256=source_pdf_sha256,
            source_version=source_version,
            document_category=document_category,
            company_binding_enabled=bool(payload.companyBindingEnabled),
            authority_attestation_version=authority_attestation.get("version") if authority_attestation else None,
            authority_attestation_text=authority_attestation.get("text") if authority_attestation else None,
            authority_attestation_sha256=authority_attestation.get("sha256") if authority_attestation else None,
            manual_fallback_enabled=bool(payload.manualFallbackEnabled),
            signer_name=recipient.name,
            signer_email=recipient.email,
            anchors=signer_anchors,
            disclosure_version=disclosure_version,
            sender_display_name=consumer_disclosure_fields["sender_display_name"] or user.display_name,
            esign_eligibility_confirmed_source="owner_envelope_create",
            sender_email=user.email,
            sender_contact_email=consumer_disclosure_fields["sender_contact_email"] or user.email,
            consumer_paper_copy_procedure=consumer_disclosure_fields["paper_copy_procedure"],
            consumer_paper_copy_fee_description=consumer_disclosure_fields["paper_copy_fee_description"],
            consumer_withdrawal_procedure=consumer_disclosure_fields["withdrawal_procedure"],
            consumer_withdrawal_consequences=consumer_disclosure_fields["withdrawal_consequences"],
            consumer_contact_update_procedure=consumer_disclosure_fields["contact_update_procedure"],
            consumer_consent_scope_override=consumer_disclosure_fields["consent_scope_description"],
            invite_method=SIGNING_INVITE_METHOD_EMAIL,
            envelope_id=envelope.id,
            signer_order=recipient.order,
        )
        _record_owner_request_created_event(
            record,
            sender_email=user.email,
            client_ip=resolve_client_ip(request),
            user_agent=normalize_signing_user_agent(request.headers.get("user-agent")),
            source="owner_envelope_create",
        )
        created_requests.append(record)

    return {
        "envelope": _serialize_owner_envelope(envelope),
        "requests": [_serialize_owner_request(r) for r in created_requests],
    }


@router.get("/api/signing/envelopes")
async def list_owner_signing_envelopes(
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    user = require_user(authorization)
    envelopes = list_signing_envelopes(user.app_user_id)
    return {"envelopes": [_serialize_owner_envelope(e) for e in envelopes]}


@router.get("/api/signing/envelopes/{envelope_id}")
async def get_owner_signing_envelope(
    envelope_id: str,
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    user = require_user(authorization)
    envelope = get_signing_envelope_for_user(envelope_id, user.app_user_id)
    if envelope is None:
        raise HTTPException(status_code=404, detail="Signing envelope not found")
    child_requests = list_signing_requests_for_envelope(envelope.id)
    return {
        "envelope": _serialize_owner_envelope(envelope),
        "requests": [_serialize_owner_request(r) for r in child_requests],
    }


@router.post("/api/signing/envelopes/{envelope_id}/send")
async def send_owner_signing_envelope(
    envelope_id: str,
    request: Request,
    pdf: UploadFile = File(...),
    sourcePdfSha256: Optional[str] = Form(default=None),
    ownerReviewConfirmed: Optional[bool] = Form(default=None),
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    user = require_user(authorization)
    ensure_signing_storage_configuration(validate_remote=False)
    envelope = get_signing_envelope_for_user(envelope_id, user.app_user_id)
    if envelope is None:
        raise HTTPException(status_code=404, detail="Signing envelope not found")
    if envelope.status != ENVELOPE_STATUS_DRAFT:
        raise HTTPException(status_code=409, detail="Envelope has already been sent or is no longer in draft state.")
    _ensure_signing_template_is_accessible(user.app_user_id, envelope.source_template_id)
    _ensure_signing_envelope_send_source_template_exists(user, envelope)

    max_mb, max_bytes = resolve_upload_limit()
    pdf_bytes = await read_upload_bytes(
        pdf,
        max_bytes=max_bytes,
        limit_message=f"PDF exceeds {max_mb}MB upload limit",
    )
    if not pdf_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")
    validation = validate_pdf_for_detection(pdf_bytes)
    max_pages = resolve_fillable_max_pages(user.role)
    if validation.page_count > max_pages:
        raise HTTPException(
            status_code=403,
            detail=f"Signing upload limited to {max_pages} pages for your tier (got {validation.page_count}).",
        )
    if pdf_has_form_widgets(validation.pdf_bytes):
        raise HTTPException(
            status_code=400,
            detail="Uploaded signing source PDF must already be flattened before send. Refresh the workspace and try again.",
        )

    child_requests = list_signing_requests_for_envelope(envelope.id)
    if not child_requests:
        raise HTTPException(status_code=409, detail="Envelope has no signers.")
    for child_request in child_requests:
        try:
            validate_signing_sendable_record(
                child_request,
                owner_review_confirmed=bool(ownerReviewConfirmed),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        normalized_client_sha256 = normalize_optional_sha256(sourcePdfSha256)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    current_sha256 = sha256_hex_for_bytes(validation.pdf_bytes)
    if normalized_client_sha256 and normalized_client_sha256 != current_sha256:
        raise HTTPException(status_code=400, detail="Uploaded PDF hash does not match the claimed source PDF SHA-256.")
    if current_sha256 != envelope.source_pdf_sha256:
        reason = "The source PDF changed after this signing envelope was created. Create a new envelope before sending."
        _invalidate_signing_envelope_drafts(envelope, user, reason=reason)
        raise HTTPException(status_code=409, detail=reason)

    source_pdf_object_path = build_signing_source_pdf_object_path(
        user_id=user.app_user_id,
        request_id=envelope.id,
        source_document_name=envelope.source_document_name,
    )
    source_pdf_bucket_path = upload_signing_pdf_bytes(
        validation.pdf_bytes,
        source_pdf_object_path,
    )

    client_ip = resolve_client_ip(request)
    user_agent = normalize_signing_user_agent(request.headers.get("user-agent"))
    source_version = build_signing_source_version(
        source_type=envelope.source_type,
        source_id=envelope.source_id,
        source_template_id=envelope.source_template_id,
        source_pdf_sha256=current_sha256,
    )
    owner_review_at = (
        now_iso()
        if envelope.mode == SIGNING_MODE_FILL_AND_SIGN and bool(ownerReviewConfirmed)
        else None
    )
    public_app_origin = resolve_signing_invite_origin(
        request_origin=request.headers.get("origin") or request.headers.get("referer"),
    )
    monthly_limit = resolve_signing_requests_monthly_limit(user.role)
    is_sequential_envelope = envelope.signing_mode == SIGNING_MODE_SEQUENTIAL

    sent_requests = []
    transitioned_requests = []
    source_retention_until: Optional[str] = None
    try:
        for child_request in child_requests:
            if child_request.status != SIGNING_STATUS_DRAFT:
                sent_requests.append(child_request)
                continue

            is_first_signer = child_request.signer_order == 1
            should_deliver_invite = not is_sequential_envelope or is_first_signer
            invite_delivery_status = "pending" if should_deliver_invite else "queued"

            sent_record = mark_signing_request_sent(
                child_request.id,
                user.app_user_id,
                source_pdf_bucket_path=source_pdf_bucket_path,
                source_pdf_sha256=current_sha256,
                source_version=source_version,
                invite_delivery_status=invite_delivery_status,
                monthly_limit=monthly_limit,
                owner_review_confirmed_at=owner_review_at or child_request.owner_review_confirmed_at,
                public_app_origin=public_app_origin,
            )
            if sent_record is None or sent_record.status != SIGNING_STATUS_SENT:
                sent_requests.append(child_request)
                continue

            sent_record = persist_business_disclosure_artifact(sent_record) or sent_record
            sent_record = persist_consumer_disclosure_artifact(sent_record) or sent_record
            transitioned_requests.append(sent_record)
            if not source_retention_until and sent_record.retention_until:
                source_retention_until = sent_record.retention_until

            _record_owner_request_sent_event(
                sent_record,
                sender_email=user.email,
                source="owner_envelope_send",
                client_ip=client_ip,
                user_agent=user_agent,
            )

            active_record = sent_record
            if is_sequential_envelope and is_first_signer:
                from backend.firebaseDB.signing_database import _update_public_signing_request
                activated_record = _update_public_signing_request(
                    sent_record.id,
                    allowed_statuses={SIGNING_STATUS_SENT},
                    updates={"turn_activated_at": now_iso()},
                )
                if activated_record is not None:
                    active_record = activated_record

            if should_deliver_invite:
                invite_attempt = await deliver_signing_invite_for_request(
                    record=active_record,
                    user_id=user.app_user_id,
                    sender_email=user.email,
                    request_origin=request.headers.get("origin") or request.headers.get("referer"),
                )
                _record_owner_invite_delivery_event(
                    invite_attempt.record,
                    delivery=invite_attempt.delivery,
                    sender_email=user.email,
                    source="owner_envelope_send",
                    client_ip=client_ip,
                    user_agent=user_agent,
                )
                sent_requests.append(invite_attempt.record)
                continue

            sent_requests.append(active_record)
    except SigningRequestMonthlyLimitError as exc:
        _rollback_signing_envelope_send(
            transitioned_requests,
            user_id=user.app_user_id,
            source_pdf_bucket_path=source_pdf_bucket_path,
            source_pdf_sha256=current_sha256,
        )
        _cleanup_signing_source_upload(source_pdf_bucket_path)
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except Exception as exc:
        _rollback_signing_envelope_send(
            transitioned_requests,
            user_id=user.app_user_id,
            source_pdf_bucket_path=source_pdf_bucket_path,
            source_pdf_sha256=current_sha256,
        )
        _cleanup_signing_source_upload(source_pdf_bucket_path)
        raise HTTPException(
            status_code=503,
            detail="Failed to send the signing envelope. Please try again.",
        ) from exc

    if source_retention_until:
        try:
            promote_signing_staged_object(source_pdf_bucket_path, retain_until=source_retention_until)
        except Exception as exc:
            _rollback_signing_envelope_send(
                transitioned_requests,
                user_id=user.app_user_id,
                source_pdf_bucket_path=source_pdf_bucket_path,
                source_pdf_sha256=current_sha256,
            )
            _cleanup_signing_source_upload(source_pdf_bucket_path)
            raise HTTPException(
                status_code=503,
                detail="Failed to finalize the retained source PDF for this signing envelope. Please try again.",
            ) from exc

    update_signing_envelope(envelope.id, {
        "status": ENVELOPE_STATUS_SENT,
        "source_pdf_bucket_path": source_pdf_bucket_path,
        "source_pdf_sha256": current_sha256,
        "source_version": source_version,
        "public_app_origin": public_app_origin,
    })
    updated_envelope = get_signing_envelope_for_user(envelope.id, user.app_user_id)
    fresh_requests = list_signing_requests_for_envelope(envelope.id)

    return {
        "envelope": _serialize_owner_envelope(updated_envelope or envelope),
        "requests": [_serialize_owner_request(r) for r in fresh_requests],
    }


@router.post("/api/signing/envelopes/{envelope_id}/revoke")
async def revoke_owner_signing_envelope(
    envelope_id: str,
    request: Request,
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    user = require_user(authorization)
    envelope = get_signing_envelope_for_user(envelope_id, user.app_user_id)
    if envelope is None:
        raise HTTPException(status_code=404, detail="Signing envelope not found")

    child_requests = list_signing_requests_for_envelope(envelope.id)
    if envelope.status == ENVELOPE_STATUS_INVALIDATED:
        return {
            "envelope": _serialize_owner_envelope(envelope),
            "requests": [_serialize_owner_request(r) for r in child_requests],
        }
    if envelope.status == ENVELOPE_STATUS_COMPLETED or any(
        child_request.status == SIGNING_STATUS_COMPLETED
        for child_request in child_requests
    ):
        raise HTTPException(
            status_code=409,
            detail="Envelopes with completed signers cannot be revoked.",
        )

    revoked_requests = []
    for child_request in child_requests:
        if child_request.status == SIGNING_STATUS_INVALIDATED:
            revoked_requests.append(child_request)
            continue
        revoked = invalidate_signing_request(
            child_request.id,
            user.app_user_id,
            reason="revoked by sender (envelope revoke)",
        )
        revoked_requests.append(revoked or child_request)

    update_signing_envelope(envelope.id, {"status": "invalidated"})
    updated_envelope = get_signing_envelope_for_user(envelope.id, user.app_user_id)

    return {
        "envelope": _serialize_owner_envelope(updated_envelope or envelope),
        "requests": [_serialize_owner_request(r) for r in revoked_requests],
    }
