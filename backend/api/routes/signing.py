"""Authenticated owner endpoints for signing request setup."""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import Response, StreamingResponse

from backend.api.schemas import SigningRequestCreateRequest
from backend.firebaseDB.signing_database import (
    create_signing_request,
    invalidate_signing_request,
    get_signing_request_for_user,
    list_signing_requests,
    mark_signing_request_manual_link_shared,
    mark_signing_request_sent,
    record_signing_event,
    reissue_signing_request,
)
from backend.firebaseDB.storage_service import (
    build_signing_bucket_uri,
    delete_storage_object,
    download_storage_bytes,
)
from backend.services.app_config import resolve_stream_cors_headers
from backend.services.auth_service import require_user
from backend.logging_config import get_logger
from backend.services.signing_consumer_consent_service import persist_consumer_disclosure_artifact
from backend.services.signing_invite_service import (
    deliver_signing_invite_for_request,
    resolve_signing_invite_event_type,
)
from backend.services.signing_provenance_service import record_signing_provenance_event
from backend.services.signing_webhook_service import dispatch_signing_webhook_event
from backend.services.signing_request_limit_service import (
    SigningRequestDocumentLimitError,
    ensure_signing_request_limit_available,
)
from backend.services.signing_storage_service import (
    ensure_signing_storage_configuration,
    is_signing_storage_not_found_error,
    promote_signing_staged_object,
    resolve_signing_stage_bucket_path,
    resolve_signing_storage_read_bucket_path,
    upload_signing_staging_pdf_bytes_for_final,
)
from backend.services.limits_service import resolve_fillable_max_pages
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


router = APIRouter()
logger = get_logger(__name__)


def upload_signing_pdf_bytes(pdf_bytes: bytes, destination_path: str) -> str:
    """Compatibility wrapper that stages bytes but returns the final signing URI."""
    upload_signing_staging_pdf_bytes_for_final(pdf_bytes, destination_path)
    return build_signing_bucket_uri(destination_path)


def _is_storage_not_found_error(exc: Exception) -> bool:
    return is_signing_storage_not_found_error(exc)


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
    }

def _record_owner_request_created_event(
    record,
    *,
    sender_email: Optional[str],
    user_agent: Optional[str],
    source: str,
) -> None:
    record_signing_provenance_event(
        record,
        event_type=SIGNING_EVENT_REQUEST_CREATED,
        sender_email=sender_email,
        invite_method=SIGNING_INVITE_METHOD_EMAIL,
        source=source,
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
    user_agent: Optional[str],
    source: str,
) -> None:
    record_signing_provenance_event(
        record,
        event_type=SIGNING_EVENT_REQUEST_SENT,
        sender_email=sender_email,
        invite_method=SIGNING_INVITE_METHOD_EMAIL,
        source=source,
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
    bucket_path, media_type, filename = _resolve_owner_artifact(record, artifact_key)
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
    source_version = build_signing_source_version(
        source_type=source_type,
        source_id=normalize_optional_text(payload.sourceId, maximum_length=160),
        source_template_id=normalize_optional_text(payload.sourceTemplateId, maximum_length=160),
        source_pdf_sha256=source_pdf_sha256,
    )
    try:
        ensure_signing_request_limit_available(
            user_id=user.app_user_id,
            role=user.role,
            source_version=source_version,
            source_document_name=source_document_name,
        )
    except SigningRequestDocumentLimitError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
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
        user_agent=normalize_signing_user_agent(None),
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
            client_ip=None,
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
    try:
        staged_source_pdf_bucket_path = resolve_signing_stage_bucket_path(source_pdf_bucket_path)
    except ValueError:
        staged_source_pdf_bucket_path = source_pdf_bucket_path
    sent_record = mark_signing_request_sent(
        record.id,
        user.app_user_id,
        source_pdf_bucket_path=source_pdf_bucket_path,
        source_pdf_sha256=current_sha256,
        source_version=source_version,
        owner_review_confirmed_at=(
            now_iso()
            if record.mode == SIGNING_MODE_FILL_AND_SIGN and bool(ownerReviewConfirmed)
            else record.owner_review_confirmed_at
        ),
    )
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
            "Source PDF promotion to finalized signing storage failed for request %s: %s",
            record.id,
            exc,
        )
    sent_record = persist_consumer_disclosure_artifact(sent_record) or sent_record
    owner_user_agent = normalize_signing_user_agent(request.headers.get("user-agent"))
    _record_owner_request_sent_event(
        sent_record,
        sender_email=user.email,
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
    reissued_record = reissue_signing_request(record.id, user.app_user_id)
    if reissued_record is None:
        raise HTTPException(status_code=500, detail="Failed to reissue the signing link.")
    next_public_link_version = resolve_signing_public_link_version(reissued_record)
    if reissued_record.status != "sent" or next_public_link_version <= previous_public_link_version:
        raise HTTPException(
            status_code=409,
            detail=resolve_signing_public_status_message(reissued_record.status, reissued_record.invalidation_reason),
        )
    reissued_record = persist_consumer_disclosure_artifact(reissued_record) or reissued_record

    next_public_token = build_signing_public_token(reissued_record.id, next_public_link_version)
    record_signing_event(
        reissued_record.id,
        event_type=SIGNING_EVENT_LINK_REISSUED,
        session_id=None,
        link_token_id=build_signing_link_token_id(next_public_token),
        client_ip=None,
        user_agent=normalize_signing_user_agent(request.headers.get("user-agent")),
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
        user_agent=normalize_signing_user_agent(request.headers.get("user-agent")),
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
        user_agent=normalize_signing_user_agent(request.headers.get("user-agent")),
        extra={
            "publicLinkVersion": resolve_signing_public_link_version(shared_record),
            "statusAtShare": shared_record.status,
        },
        occurred_at=getattr(shared_record, "manual_link_shared_at", None),
    )
    return {"request": _serialize_owner_request(shared_record)}
