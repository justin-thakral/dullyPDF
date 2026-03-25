"""Authenticated owner endpoints for signing request setup."""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import Response, StreamingResponse

from backend.api.schemas import SigningRequestCreateRequest
from backend.firebaseDB.signing_database import (
    create_signing_request,
    invalidate_signing_request,
    get_signing_request_for_user,
    list_signing_requests,
    list_signing_events_for_request,
    mark_signing_request_invite_delivery,
    mark_signing_request_sent,
)
from backend.firebaseDB.storage_service import (
    build_signing_bucket_uri,
    delete_storage_object,
    download_storage_bytes,
    upload_signing_json,
    upload_signing_pdf_bytes,
)
from backend.services.auth_service import require_user
from backend.services.signing_invite_service import send_signing_invite_email
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
    SIGNING_STATUS_INVALIDATED,
    build_signing_public_path,
    build_signing_public_token,
    build_signing_audit_manifest_object_path,
    build_signing_audit_receipt_object_path,
    build_signing_signed_pdf_object_path,
    build_signing_source_pdf_object_path,
    build_signing_source_version,
    normalize_optional_sha256,
    normalize_signing_artifact_key,
    normalize_optional_text,
    normalize_signature_mode,
    normalize_signing_mode,
    sha256_hex_for_bytes,
    resolve_document_category_label,
    resolve_signing_disclosure_version,
    resolve_signing_public_status_message,
    serialize_signing_ceremony_state,
    serialize_signing_category_options,
    validate_document_category,
    validate_signing_source_type,
    validate_signing_sendable_record,
    validate_signer_email,
    validate_signer_name,
    validate_source_document_name,
)


router = APIRouter()


def _require_send_transition_applied(record, *, uploaded_source_path: str):
    if record is None:
        try:
            delete_storage_object(uploaded_source_path)
        except Exception:
            pass
        raise HTTPException(status_code=500, detail="Failed to send signing request")
    if record.status != "sent" or record.source_pdf_bucket_path != uploaded_source_path:
        try:
            delete_storage_object(uploaded_source_path)
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
        "manualFallbackEnabled": record.manual_fallback_enabled,
        "signerName": record.signer_name,
        "signerEmail": record.signer_email,
        "inviteDeliveryStatus": record.invite_delivery_status,
        "inviteLastAttemptAt": record.invite_last_attempt_at,
        "inviteSentAt": record.invite_sent_at,
        "inviteDeliveryError": record.invite_delivery_error,
        "status": record.status,
        "anchors": record.anchors,
        "disclosureVersion": record.disclosure_version,
        "createdAt": record.created_at,
        "updatedAt": record.updated_at,
        "ownerReviewConfirmedAt": record.owner_review_confirmed_at,
        "sentAt": record.sent_at,
        "completedAt": record.completed_at,
        "invalidatedAt": record.invalidated_at,
        "invalidationReason": record.invalidation_reason,
        "retentionUntil": record.retention_until,
        "artifacts": _serialize_owner_artifacts(record),
        **serialize_signing_ceremony_state(record),
        "publicToken": build_signing_public_token(record.id) if public_link_available else None,
        "publicPath": build_signing_public_path(record.id) if public_link_available else None,
    }


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
    authorization: Optional[str] = Header(default=None),
):
    user = require_user(authorization)
    record = get_signing_request_for_user(request_id, user.app_user_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Signing request not found")
    bucket_path, media_type, filename = _resolve_owner_artifact(record, artifact_key)
    try:
        body = download_storage_bytes(bucket_path)
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Failed to load signing artifact") from exc
    if media_type == "application/json":
        return Response(content=body, media_type=media_type, headers={"Content-Disposition": f'attachment; filename="{filename}"'})
    return StreamingResponse(
        iter([body]),
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
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
        signer_name = validate_signer_name(payload.signerName)
        signer_email = validate_signer_email(payload.signerEmail)
        source_document_name = validate_source_document_name(payload.sourceDocumentName)
        disclosure_version = resolve_signing_disclosure_version(signature_mode)
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
    )
    return {"request": _serialize_owner_request(record)}


@router.post("/api/signing/requests/{request_id}/send")
async def send_owner_signing_request(
    request_id: str,
    pdf: UploadFile = File(...),
    sourcePdfSha256: Optional[str] = Form(default=None),
    ownerReviewConfirmed: Optional[bool] = Form(default=None),
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    user = require_user(authorization)
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
    source_pdf_bucket_path = upload_signing_pdf_bytes(validation.pdf_bytes, source_pdf_object_path)
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
    sent_record = _require_send_transition_applied(sent_record, uploaded_source_path=source_pdf_bucket_path)
    invite_delivery = await send_signing_invite_email(
        signer_email=sent_record.signer_email,
        signer_name=sent_record.signer_name,
        document_name=sent_record.source_document_name,
        public_path=build_signing_public_path(sent_record.id),
        sender_email=user.email,
    )
    sent_record = mark_signing_request_invite_delivery(
        sent_record.id,
        user.app_user_id,
        delivery_status=invite_delivery.delivery_status,
        attempted_at=invite_delivery.attempted_at,
        sent_at=invite_delivery.sent_at,
        delivery_error=invite_delivery.error_message,
    ) or sent_record
    return {"request": _serialize_owner_request(sent_record)}
