"""Artifact download and completion helpers for the public signing ceremony.

The public route needs deterministic artifact naming, private response headers,
and a repeatable way to assemble completion artifacts from the immutable source
PDF. This module keeps those mechanics together so the route can focus on
request validation and state transitions.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Dict, Iterable, Optional

from backend.services.app_config import resolve_stream_cors_headers
from backend.services.signing_audit_service import build_signing_audit_bundle
from backend.services.signing_pdf_digital_service import async_apply_digital_pdf_signature
from backend.services.signing_pdf_service import build_signed_pdf
from backend.services.signing_service import (
    SIGNING_ARTIFACT_AUDIT_RECEIPT,
    SIGNING_ARTIFACT_SIGNED_PDF,
    SIGNING_EVENT_COMPLETED,
    SIGNING_STATUS_COMPLETED,
    build_signing_audit_manifest_object_path,
    build_signing_audit_receipt_object_path,
    build_signing_signed_pdf_object_path,
    sha256_hex_for_bytes,
)

@dataclass(frozen=True)
class PublicSigningArtifactDescriptor:
    bucket_path: str
    media_type: str
    filename: str


@dataclass(frozen=True)
class PreparedPublicSigningCompletion:
    completed_at: str
    completed_verification_method: Optional[str]
    completed_verification_completed_at: Optional[str]
    completed_verification_session_id: Optional[str]
    signed_pdf_render: Any
    signed_pdf_bytes: bytes
    signed_pdf_digital_signature: Any
    signed_pdf_object_path: str
    signed_pdf_bucket_path: str
    audit_manifest_object_path: str
    audit_manifest_bucket_path: str
    audit_receipt_object_path: str
    audit_receipt_bucket_path: str
    signed_pdf_sha256: str
    completed_record: Any
    synthetic_completed_event: Dict[str, Any]
    audit_bundle: Any
    artifact_updates: Dict[str, Any]


def is_public_signing_storage_not_found_error(exc: Exception) -> bool:
    if isinstance(exc, FileNotFoundError):
        return True
    status_code = getattr(exc, "status_code", None)
    if status_code is None:
        status_code = getattr(exc, "code", None)
    if status_code == 404:
        return True
    return exc.__class__.__name__.lower() == "notfound"


def cleanup_public_signing_completion_uploads(delete_storage_object, bucket_paths: list[str]) -> None:
    """Best-effort cleanup for completion artifacts uploaded before a stale commit.

    Completion writes a fixed set of artifacts. Cleanup is O(k) in uploaded
    objects, where k is bounded to three in this workflow.
    """

    for bucket_path in bucket_paths:
        try:
            delete_storage_object(bucket_path)
        except Exception:
            pass


def build_public_signing_stream_headers(origin: Optional[str], *, content_disposition: str) -> Dict[str, str]:
    headers = {
        "Content-Disposition": content_disposition,
        "Cache-Control": "private, no-store",
    }
    headers.update(resolve_stream_cors_headers(origin))
    return headers


def resolve_public_signing_artifact(record, *, artifact_key: str, signed_pdf_filename: str, audit_receipt_filename: str) -> PublicSigningArtifactDescriptor:
    if record.status != SIGNING_STATUS_COMPLETED:
        raise ValueError("Signed artifacts are available only after the request is completed.")
    if artifact_key == SIGNING_ARTIFACT_SIGNED_PDF and record.signed_pdf_bucket_path:
        return PublicSigningArtifactDescriptor(
            bucket_path=record.signed_pdf_bucket_path,
            media_type="application/pdf",
            filename=signed_pdf_filename,
        )
    if artifact_key == SIGNING_ARTIFACT_AUDIT_RECEIPT and record.audit_receipt_bucket_path:
        return PublicSigningArtifactDescriptor(
            bucket_path=record.audit_receipt_bucket_path,
            media_type="application/pdf",
            filename=audit_receipt_filename,
        )
    raise FileNotFoundError("Signing artifact is not available.")


async def _apply_digital_pdf_signature(
    *,
    pdf_bytes: bytes,
    signer_name: str,
    source_document_name: str,
) -> Any:
    return await async_apply_digital_pdf_signature(
        pdf_bytes=pdf_bytes,
        signer_name=signer_name,
        source_document_name=source_document_name,
    )


async def prepare_public_signing_completion(
    *,
    record,
    session,
    client_ip: Optional[str],
    user_agent: Optional[str],
    completed_at: str,
    source_pdf_bytes: bytes,
    existing_events: Iterable[Any],
    build_bucket_uri,
) -> PreparedPublicSigningCompletion:
    completed_verification_method = record.verification_method if session.verification_completed_at else None
    completed_verification_completed_at = session.verification_completed_at if session.verification_completed_at else None
    completed_verification_session_id = session.id if session.verification_completed_at else None
    signed_pdf_render = build_signed_pdf(
        source_pdf_bytes=source_pdf_bytes,
        anchors=record.anchors or [],
        adopted_name=record.signature_adopted_name or record.signer_name,
        completed_at=completed_at,
        signature_adopted_mode=getattr(record, "signature_adopted_mode", None),
        signature_image_data_url=getattr(record, "signature_adopted_image_data_url", None),
    )
    digitally_signed_pdf = await _apply_digital_pdf_signature(
        pdf_bytes=signed_pdf_render.pdf_bytes,
        signer_name=record.signature_adopted_name or record.signer_name,
        source_document_name=record.source_document_name,
    )
    signed_pdf_object_path = build_signing_signed_pdf_object_path(
        user_id=record.user_id,
        request_id=record.id,
        source_document_name=record.source_document_name,
    )
    signed_pdf_bucket_path = build_bucket_uri(signed_pdf_object_path)
    audit_manifest_object_path = build_signing_audit_manifest_object_path(
        user_id=record.user_id,
        request_id=record.id,
        source_document_name=record.source_document_name,
    )
    audit_manifest_bucket_path = build_bucket_uri(audit_manifest_object_path)
    audit_receipt_object_path = build_signing_audit_receipt_object_path(
        user_id=record.user_id,
        request_id=record.id,
        source_document_name=record.source_document_name,
    )
    audit_receipt_bucket_path = build_bucket_uri(audit_receipt_object_path)
    signed_pdf_sha256 = sha256_hex_for_bytes(digitally_signed_pdf.pdf_bytes)

    completed_record = replace(
        record,
        status=SIGNING_STATUS_COMPLETED,
        completed_at=completed_at,
        completed_session_id=session.id,
        completed_ip_address=client_ip,
        completed_user_agent=user_agent,
        completed_verification_method=completed_verification_method,
        completed_verification_completed_at=completed_verification_completed_at,
        completed_verification_session_id=completed_verification_session_id,
        signed_pdf_bucket_path=signed_pdf_bucket_path,
        signed_pdf_sha256=signed_pdf_sha256,
        signed_pdf_digital_signature_method=digitally_signed_pdf.signature_info.signature_method,
        signed_pdf_digital_signature_algorithm=digitally_signed_pdf.signature_info.signature_algorithm,
        signed_pdf_digital_signature_field_name=digitally_signed_pdf.signature_info.field_name,
        signed_pdf_digital_signature_subfilter=digitally_signed_pdf.signature_info.subfilter,
        signed_pdf_digital_signature_timestamped=digitally_signed_pdf.signature_info.timestamped,
        signed_pdf_digital_certificate_subject=digitally_signed_pdf.signature_info.certificate_subject,
        signed_pdf_digital_certificate_issuer=digitally_signed_pdf.signature_info.certificate_issuer,
        signed_pdf_digital_certificate_serial_number=digitally_signed_pdf.signature_info.certificate_serial_number,
        signed_pdf_digital_certificate_fingerprint_sha256=digitally_signed_pdf.signature_info.certificate_fingerprint_sha256,
        audit_manifest_bucket_path=audit_manifest_bucket_path,
        audit_receipt_bucket_path=audit_receipt_bucket_path,
        artifacts_generated_at=completed_at,
    )
    synthetic_completed_event = {
        "eventType": SIGNING_EVENT_COMPLETED,
        "sessionId": session.id,
        "linkTokenId": session.link_token_id,
        "clientIp": client_ip,
        "userAgent": user_agent,
        "occurredAt": completed_at,
        "details": {
            "sourcePdfSha256": record.source_pdf_sha256,
            "sourceVersion": record.source_version,
            "adoptedName": record.signature_adopted_name,
            "adoptedMode": getattr(record, "signature_adopted_mode", None),
            "signatureImageSha256": getattr(record, "signature_adopted_image_sha256", None),
            "signedPdfSha256": signed_pdf_sha256,
            "pdfDigitalSignatureMethod": digitally_signed_pdf.signature_info.signature_method,
            "pdfDigitalSignatureAlgorithm": digitally_signed_pdf.signature_info.signature_algorithm,
            "pdfDigitalSignatureTimestamped": digitally_signed_pdf.signature_info.timestamped,
            "pdfDigitalCertificateFingerprintSha256": digitally_signed_pdf.signature_info.certificate_fingerprint_sha256,
        },
    }
    audit_bundle = build_signing_audit_bundle(
        record=completed_record,
        events=[*existing_events, synthetic_completed_event],
        signed_pdf_sha256=signed_pdf_sha256,
        signed_pdf_bucket_path=signed_pdf_bucket_path,
        source_pdf_bucket_path=record.source_pdf_bucket_path,
        signed_pdf_page_count=signed_pdf_render.page_count,
        applied_anchor_count=signed_pdf_render.applied_anchor_count,
    )
    artifact_updates = {
        "signed_pdf_bucket_path": signed_pdf_bucket_path,
        "signed_pdf_sha256": signed_pdf_sha256,
        "signed_pdf_digital_signature_method": digitally_signed_pdf.signature_info.signature_method,
        "signed_pdf_digital_signature_algorithm": digitally_signed_pdf.signature_info.signature_algorithm,
        "signed_pdf_digital_signature_field_name": digitally_signed_pdf.signature_info.field_name,
        "signed_pdf_digital_signature_subfilter": digitally_signed_pdf.signature_info.subfilter,
        "signed_pdf_digital_signature_timestamped": digitally_signed_pdf.signature_info.timestamped,
        "signed_pdf_digital_certificate_subject": digitally_signed_pdf.signature_info.certificate_subject,
        "signed_pdf_digital_certificate_issuer": digitally_signed_pdf.signature_info.certificate_issuer,
        "signed_pdf_digital_certificate_serial_number": digitally_signed_pdf.signature_info.certificate_serial_number,
        "signed_pdf_digital_certificate_fingerprint_sha256": digitally_signed_pdf.signature_info.certificate_fingerprint_sha256,
        "audit_manifest_bucket_path": audit_manifest_bucket_path,
        "audit_manifest_sha256": audit_bundle.envelope_sha256,
        "audit_receipt_bucket_path": audit_receipt_bucket_path,
        "audit_receipt_sha256": audit_bundle.receipt_pdf_sha256,
        "audit_signature_method": audit_bundle.signature.get("method"),
        "audit_signature_algorithm": audit_bundle.signature.get("algorithm"),
        "audit_kms_key_resource_name": audit_bundle.signature.get("keyResourceName"),
        "audit_kms_key_version_name": audit_bundle.signature.get("keyVersionName"),
        "artifacts_generated_at": completed_at,
        "retention_until": audit_bundle.retention_until,
        "completed_verification_method": completed_verification_method,
        "completed_verification_completed_at": completed_verification_completed_at,
        "completed_verification_session_id": completed_verification_session_id,
    }
    return PreparedPublicSigningCompletion(
        completed_at=completed_at,
        completed_verification_method=completed_verification_method,
        completed_verification_completed_at=completed_verification_completed_at,
        completed_verification_session_id=completed_verification_session_id,
        signed_pdf_render=signed_pdf_render,
        signed_pdf_bytes=digitally_signed_pdf.pdf_bytes,
        signed_pdf_digital_signature=digitally_signed_pdf.signature_info,
        signed_pdf_object_path=signed_pdf_object_path,
        signed_pdf_bucket_path=signed_pdf_bucket_path,
        audit_manifest_object_path=audit_manifest_object_path,
        audit_manifest_bucket_path=audit_manifest_bucket_path,
        audit_receipt_object_path=audit_receipt_object_path,
        audit_receipt_bucket_path=audit_receipt_bucket_path,
        signed_pdf_sha256=signed_pdf_sha256,
        completed_record=completed_record,
        synthetic_completed_event=synthetic_completed_event,
        audit_bundle=audit_bundle,
        artifact_updates=artifact_updates,
    )
