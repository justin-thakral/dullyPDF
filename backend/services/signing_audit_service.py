"""Audit-manifest and receipt helpers for completed signing requests.

The manifest builder is intentionally deterministic: it canonicalizes nested
data and signs the exact UTF-8 JSON bytes so the same request/event history
reproduces the same digest later. Receipt generation is linear in the number of
rendered lines, which in practice is O(event_count).
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from io import BytesIO
from typing import Any, Dict, Iterable, List

from reportlab.graphics import renderPDF
from reportlab.graphics.barcode import createBarcodeDrawing
from reportlab.lib.pagesizes import letter
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfgen import canvas

from backend.services.cloud_kms_service import (
    AuditSignatureEnvelope,
    sign_audit_manifest_bytes,
    verify_audit_manifest_signature,
)
from backend.services.signing_consumer_consent_service import resolve_consumer_disclosure_artifact
from backend.services.signing_service import (
    SIGNATURE_MODE_CONSUMER,
    resolve_disclosure_text,
    resolve_document_category_label,
    resolve_signing_disclosure_payload_for_record,
    resolve_signing_retention_until,
    serialize_signing_sender_provenance,
)


AUDIT_MANIFEST_SCHEMA_VERSION = "dullypdf-signing-audit-v1"
AUDIT_ENVELOPE_SCHEMA_VERSION = "dullypdf-signing-audit-envelope-v1"


@dataclass(frozen=True)
class SigningAuditBundle:
    manifest_payload: Dict[str, Any]
    manifest_bytes: bytes
    manifest_sha256: str
    envelope_payload: Dict[str, Any]
    envelope_bytes: bytes
    envelope_sha256: str
    receipt_pdf_bytes: bytes
    receipt_pdf_sha256: str
    retention_until: str
    signature: Dict[str, Any]


@dataclass(frozen=True)
class _ReceiptWrappedLine:
    text: str
    x_offset: float = 0.0


def _canonicalize_json_bytes(payload: Dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _normalize_event_entry(event) -> Dict[str, Any]:
    if isinstance(event, dict):
        payload = dict(event)
        return {
            "eventType": str(payload.get("event_type") or payload.get("eventType") or ""),
            "sessionId": payload.get("session_id") or payload.get("sessionId"),
            "linkTokenId": payload.get("link_token_id") or payload.get("linkTokenId"),
            "clientIp": payload.get("client_ip") or payload.get("clientIp"),
            "userAgent": payload.get("user_agent") or payload.get("userAgent"),
            "occurredAt": payload.get("occurred_at") or payload.get("occurredAt"),
            "details": dict(payload.get("details") or {}),
        }
    return {
        "eventType": str(event.event_type),
        "sessionId": event.session_id,
        "linkTokenId": event.link_token_id,
        "clientIp": event.client_ip,
        "userAgent": event.user_agent,
        "occurredAt": event.occurred_at,
        "details": dict(event.details or {}),
    }


def build_signing_audit_manifest(
    *,
    record,
    events: Iterable[Any],
    signed_pdf_sha256: str,
    signed_pdf_bucket_path: str,
    source_pdf_bucket_path: str,
    retention_until: str,
    signed_pdf_page_count: int,
    applied_anchor_count: int,
) -> Dict[str, Any]:
    normalized_events = [_normalize_event_entry(event) for event in events]
    if str(getattr(record, "signature_mode", "") or "").strip() == SIGNATURE_MODE_CONSUMER:
        disclosure_artifact = resolve_consumer_disclosure_artifact(record)
        disclosure_payload = dict(disclosure_artifact.get("payload") or {})
        disclosure_version = disclosure_artifact.get("version") or record.disclosure_version
        disclosure_payload_sha256 = disclosure_artifact.get("sha256")
        consumer_consent_payload: Dict[str, Any] = {
            "disclosureVersion": disclosure_version,
            "disclosurePayload": disclosure_payload,
            "disclosureSha256": disclosure_payload_sha256,
            "disclosurePresentedAt": getattr(record, "consumer_disclosure_presented_at", None),
            "consentAcceptedAt": getattr(record, "consented_at", None),
            "consentScope": getattr(record, "consumer_consent_scope", None) or disclosure_artifact.get("scope"),
            "accessDemonstratedAt": getattr(record, "consumer_access_demonstrated_at", None),
            "accessDemonstrationMethod": getattr(record, "consumer_access_demonstration_method", None),
            "consentWithdrawnAt": getattr(record, "consent_withdrawn_at", None),
        }
    else:
        disclosure_payload = resolve_signing_disclosure_payload_for_record(record)
        disclosure_version = record.disclosure_version
        disclosure_payload_sha256 = None
        consumer_consent_payload = {}
    return {
        "schemaVersion": AUDIT_MANIFEST_SCHEMA_VERSION,
        "request": {
            "id": record.id,
            "title": record.title,
            "ownerUserId": getattr(record, "user_id", None),
            "mode": record.mode,
            "signatureMode": record.signature_mode,
            "status": record.status,
            "sourceType": record.source_type,
            "sourceId": record.source_id,
            "sourceTemplateId": record.source_template_id,
            "sourceTemplateName": record.source_template_name,
            "sourceDocumentName": record.source_document_name,
            "sourceVersion": record.source_version,
            "documentCategory": record.document_category,
            "documentCategoryLabel": resolve_document_category_label(record.document_category),
            "esignEligibilityConfirmedAt": getattr(record, "esign_eligibility_confirmed_at", None),
            "esignEligibilityConfirmedSource": getattr(record, "esign_eligibility_confirmed_source", None),
            "signerContactMethod": getattr(record, "signer_contact_method", None),
            "signerAuthMethod": getattr(record, "signer_auth_method", None),
            "disclosureVersion": record.disclosure_version,
            "inviteDeliveryStatus": getattr(record, "invite_delivery_status", None),
            "inviteLastAttemptAt": getattr(record, "invite_last_attempt_at", None),
            "inviteSentAt": getattr(record, "invite_sent_at", None),
            "inviteDeliveryError": getattr(record, "invite_delivery_error", None),
            "inviteMessageId": getattr(record, "invite_message_id", None),
            "publicLinkVersion": getattr(record, "public_link_version", None),
            "publicLinkRevokedAt": getattr(record, "public_link_revoked_at", None),
            "publicLinkLastReissuedAt": getattr(record, "public_link_last_reissued_at", None),
            "verificationRequired": bool(getattr(record, "verification_required", False)),
            "verificationMethod": getattr(record, "verification_method", None),
            "verificationCompletedAt": getattr(record, "verification_completed_at", None),
            "completedVerificationMethod": getattr(record, "completed_verification_method", None),
            "completedVerificationCompletedAt": getattr(record, "completed_verification_completed_at", None),
            "completedVerificationSessionId": getattr(record, "completed_verification_session_id", None),
        },
        "sender": serialize_signing_sender_provenance(record),
        "signer": {
            "name": record.signer_name,
            "email": record.signer_email,
            "adoptedName": record.signature_adopted_name,
            "adoptedMode": getattr(record, "signature_adopted_mode", None),
            "signatureImageSha256": getattr(record, "signature_adopted_image_sha256", None),
        },
        "ceremony": {
            "manualFallbackEnabled": bool(record.manual_fallback_enabled),
            "manualFallbackRequestedAt": record.manual_fallback_requested_at,
            "manualFallbackNote": record.manual_fallback_note,
            "openedAt": record.opened_at,
            "reviewedAt": record.reviewed_at,
            "consentedAt": record.consented_at,
            "consentWithdrawnAt": getattr(record, "consent_withdrawn_at", None),
            "verificationMethod": getattr(record, "completed_verification_method", None) or getattr(record, "verification_method", None),
            "verificationCompletedAt": (
                getattr(record, "completed_verification_completed_at", None)
                or getattr(record, "verification_completed_at", None)
            ),
            "verificationSessionId": getattr(record, "completed_verification_session_id", None),
            "signatureAdoptedAt": record.signature_adopted_at,
            "signatureAdoptedMode": getattr(record, "signature_adopted_mode", None),
            "completedAt": record.completed_at,
            "completedSessionId": record.completed_session_id,
            "completedIpAddress": record.completed_ip_address,
            "completedUserAgent": record.completed_user_agent,
        },
        "disclosure": {
            "version": disclosure_version,
            "text": (
                list(disclosure_payload.get("summaryLines") or [])
                if isinstance(disclosure_payload, dict) and disclosure_payload.get("summaryLines")
                else resolve_disclosure_text(record.disclosure_version)
            ),
            "payload": disclosure_payload,
            "payloadSha256": disclosure_payload_sha256,
        },
        "consumerConsent": consumer_consent_payload,
        "documentEvidence": {
            "sourcePdfSha256": record.source_pdf_sha256,
            "signedPdfSha256": signed_pdf_sha256,
            "sourcePdfBucketPath": source_pdf_bucket_path,
            "signedPdfBucketPath": signed_pdf_bucket_path,
            "signedPdfPageCount": int(signed_pdf_page_count),
            "appliedAnchorCount": int(applied_anchor_count),
            "pdfDigitalSignatureMethod": getattr(record, "signed_pdf_digital_signature_method", None),
            "pdfDigitalSignatureAlgorithm": getattr(record, "signed_pdf_digital_signature_algorithm", None),
            "pdfDigitalSignatureFieldName": getattr(record, "signed_pdf_digital_signature_field_name", None),
            "pdfDigitalSignatureSubfilter": getattr(record, "signed_pdf_digital_signature_subfilter", None),
            "pdfDigitalSignatureTimestamped": bool(getattr(record, "signed_pdf_digital_signature_timestamped", False)),
            "pdfDigitalCertificateSubject": getattr(record, "signed_pdf_digital_certificate_subject", None),
            "pdfDigitalCertificateIssuer": getattr(record, "signed_pdf_digital_certificate_issuer", None),
            "pdfDigitalCertificateSerialNumber": getattr(record, "signed_pdf_digital_certificate_serial_number", None),
            "pdfDigitalCertificateFingerprintSha256": getattr(
                record,
                "signed_pdf_digital_certificate_fingerprint_sha256",
                None,
            ),
            "retentionUntil": retention_until,
        },
        "anchors": list(record.anchors or []),
        "events": normalized_events,
    }


def wrap_signing_audit_manifest(manifest_payload: Dict[str, Any], signature: AuditSignatureEnvelope) -> Dict[str, Any]:
    manifest_bytes = _canonicalize_json_bytes(manifest_payload)
    return {
        "schemaVersion": AUDIT_ENVELOPE_SCHEMA_VERSION,
        "manifestSha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "manifest": manifest_payload,
        "signature": signature.to_dict(),
    }


def build_signing_audit_bundle(
    *,
    record,
    events: Iterable[Any],
    signed_pdf_sha256: str,
    signed_pdf_bucket_path: str,
    source_pdf_bucket_path: str,
    signed_pdf_page_count: int,
    applied_anchor_count: int,
) -> SigningAuditBundle:
    retention_until = str(getattr(record, "retention_until", "") or "").strip() or resolve_signing_retention_until(
        record.completed_at
    )
    manifest_payload = build_signing_audit_manifest(
        record=record,
        events=events,
        signed_pdf_sha256=signed_pdf_sha256,
        signed_pdf_bucket_path=signed_pdf_bucket_path,
        source_pdf_bucket_path=source_pdf_bucket_path,
        retention_until=retention_until,
        signed_pdf_page_count=signed_pdf_page_count,
        applied_anchor_count=applied_anchor_count,
    )
    manifest_bytes = _canonicalize_json_bytes(manifest_payload)
    signature = sign_audit_manifest_bytes(manifest_bytes)
    envelope_payload = wrap_signing_audit_manifest(manifest_payload, signature)
    envelope_bytes = _canonicalize_json_bytes(envelope_payload)
    receipt_pdf_bytes = render_signing_audit_receipt_pdf(envelope_payload)
    return SigningAuditBundle(
        manifest_payload=manifest_payload,
        manifest_bytes=manifest_bytes,
        manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
        envelope_payload=envelope_payload,
        envelope_bytes=envelope_bytes,
        envelope_sha256=hashlib.sha256(envelope_bytes).hexdigest(),
        receipt_pdf_bytes=receipt_pdf_bytes,
        receipt_pdf_sha256=hashlib.sha256(receipt_pdf_bytes).hexdigest(),
        retention_until=retention_until,
        signature=signature.to_dict(),
    )


def verify_signing_audit_envelope(envelope_payload: Dict[str, Any]) -> bool:
    manifest = dict((envelope_payload or {}).get("manifest") or {})
    signature = dict((envelope_payload or {}).get("signature") or {})
    manifest_bytes = _canonicalize_json_bytes(manifest)
    manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
    if manifest_sha256 != str((envelope_payload or {}).get("manifestSha256") or "").strip().lower():
        return False
    return verify_audit_manifest_signature(manifest_bytes, signature)


def _truncate_b64(value: str, max_display: int = 64) -> str:
    if not value or len(value) <= max_display:
        return value
    half = max_display // 2
    return f"{value[:half]}...{value[-half:]} ({len(value)} chars)"


def _receipt_lines(envelope_payload: Dict[str, Any]) -> List[str]:
    from backend.services.signing_validation_service import build_signing_validation_url

    manifest = dict((envelope_payload or {}).get("manifest") or {})
    request = dict(manifest.get("request") or {})
    sender = dict(manifest.get("sender") or {})
    signer = dict(manifest.get("signer") or {})
    ceremony = dict(manifest.get("ceremony") or {})
    consumer_consent = dict(manifest.get("consumerConsent") or {})
    document_evidence = dict(manifest.get("documentEvidence") or {})
    signature = dict((envelope_payload or {}).get("signature") or {})
    request_id = str(request.get("id") or "").strip()
    validation_url = build_signing_validation_url(request_id) if request_id else ""
    lines = [
        "DullyPDF Signature Audit Receipt",
        "",
        f"Request ID: {request.get('id') or ''}",
        f"Document: {request.get('sourceDocumentName') or ''}",
        f"Document Category: {request.get('documentCategoryLabel') or request.get('documentCategory') or ''}",
        f"Sender: {sender.get('senderEmail') or 'Owner account'}",
        f"Delivery Method: {sender.get('inviteMethod') or 'not recorded'}",
        f"Delivery Status: {sender.get('inviteDeliveryStatus') or 'not recorded'}",
        f"Delivery Attempted At: {sender.get('inviteLastAttemptAt') or ''}",
        f"Manual Link Shared At: {sender.get('manualLinkSharedAt') or ''}",
        f"Signer: {signer.get('name') or ''}",
        f"Adopted Signature: {signer.get('adoptedName') or ''}",
        f"Adopted Signature Mode: {signer.get('adoptedMode') or ''}",
        f"Completed At: {ceremony.get('completedAt') or ''}",
        "Detailed signer email, IP address, and user-agent evidence remain in the owner audit manifest.",
        "",
        f"Source PDF SHA-256: {document_evidence.get('sourcePdfSha256') or ''}",
        f"Signed PDF SHA-256: {document_evidence.get('signedPdfSha256') or ''}",
        f"PDF Signature Method: {document_evidence.get('pdfDigitalSignatureMethod') or ''}",
        f"PDF Signature Algorithm: {document_evidence.get('pdfDigitalSignatureAlgorithm') or ''}",
        f"PDF Timestamped: {'yes' if document_evidence.get('pdfDigitalSignatureTimestamped') else 'no'}",
        f"PDF Signature Subject: {document_evidence.get('pdfDigitalCertificateSubject') or ''}",
        f"PDF Signature Issuer: {document_evidence.get('pdfDigitalCertificateIssuer') or ''}",
        f"PDF Signature Serial: {document_evidence.get('pdfDigitalCertificateSerialNumber') or ''}",
        f"PDF Signature Fingerprint SHA-256: {document_evidence.get('pdfDigitalCertificateFingerprintSha256') or ''}",
        f"Manifest SHA-256: {envelope_payload.get('manifestSha256') or ''}",
        f"Retention Until: {document_evidence.get('retentionUntil') or ''}",
        f"Validation URL: {validation_url}",
        "",
        f"Signature Method: {signature.get('method') or ''}",
        f"Signature Algorithm: {signature.get('algorithm') or ''}",
        f"KMS Key Version: {signature.get('keyVersionName') or ''}",
        f"Signature Digest SHA-256: {signature.get('digestSha256') or ''}",
        f"Signature (Base64): {_truncate_b64(signature.get('signatureBase64') or '')}",
        "",
        "Event Timeline:",
    ]
    if any(consumer_consent.get(field) for field in ("disclosureVersion", "consentAcceptedAt", "accessDemonstratedAt")):
        consumer_lines = [
            f"Consumer Disclosure Version: {consumer_consent.get('disclosureVersion') or ''}",
            f"Disclosure Presented At: {consumer_consent.get('disclosurePresentedAt') or ''}",
            f"Consent Accepted At: {consumer_consent.get('consentAcceptedAt') or ''}",
            f"Access Demonstrated At: {consumer_consent.get('accessDemonstratedAt') or ''}",
            f"Access Method: {consumer_consent.get('accessDemonstrationMethod') or ''}",
            f"Consent Scope: {consumer_consent.get('consentScope') or ''}",
            f"Consent Withdrawn At: {consumer_consent.get('consentWithdrawnAt') or ''}",
            "",
        ]
        insert_at = lines.index("Detailed signer email, IP address, and user-agent evidence remain in the owner audit manifest.")
        lines[insert_at:insert_at] = consumer_lines
    for event in list(manifest.get("events") or []):
        event_type = event.get("eventType") or ""
        occurred_at = event.get("occurredAt") or ""
        lines.append(f"- {occurred_at} | {event_type}")
    return lines


def _wrap_receipt_fragment(
    text: str,
    *,
    font_name: str,
    font_size: float,
    max_width: float,
) -> List[str]:
    normalized = str(text or "")
    if normalized == "":
        return [""]
    if pdfmetrics.stringWidth(normalized, font_name, font_size) <= max_width:
        return [normalized]

    wrapped: List[str] = []
    remaining = normalized
    break_chars = "/:_-.?=&"
    while remaining:
        if pdfmetrics.stringWidth(remaining, font_name, font_size) <= max_width:
            wrapped.append(remaining)
            break

        break_index = None
        break_on_space = False
        for index, char in enumerate(remaining):
            candidate = remaining[: index + 1]
            if pdfmetrics.stringWidth(candidate, font_name, font_size) > max_width:
                break
            if char.isspace():
                break_index = index + 1
                break_on_space = True
            elif char in break_chars:
                break_index = index + 1
                break_on_space = False

        if break_index is None:
            break_index = 1
            while break_index < len(remaining):
                candidate = remaining[: break_index + 1]
                if pdfmetrics.stringWidth(candidate, font_name, font_size) > max_width:
                    break
                break_index += 1
            wrapped.append(remaining[:break_index])
            remaining = remaining[break_index:]
            continue

        wrapped.append(remaining[:break_index].rstrip())
        remaining = remaining[break_index:]
        if break_on_space:
            remaining = remaining.lstrip()

    return wrapped


def _wrap_receipt_line(
    text: str,
    *,
    font_name: str,
    font_size: float,
    max_width: float,
) -> List[_ReceiptWrappedLine]:
    normalized = str(text or "")
    if normalized == "":
        return [_ReceiptWrappedLine("")]

    separator = normalized.find(": ")
    if separator <= 0:
        return [
            _ReceiptWrappedLine(segment)
            for segment in _wrap_receipt_fragment(
                normalized,
                font_name=font_name,
                font_size=font_size,
                max_width=max_width,
            )
        ]

    label_prefix = normalized[: separator + 2]
    value = normalized[separator + 2 :]
    label_width = pdfmetrics.stringWidth(label_prefix, font_name, font_size)
    continuation_width = max_width - label_width
    if continuation_width <= max_width * 0.25:
        return [
            _ReceiptWrappedLine(segment)
            for segment in _wrap_receipt_fragment(
                normalized,
                font_name=font_name,
                font_size=font_size,
                max_width=max_width,
            )
        ]

    wrapped_value = _wrap_receipt_fragment(
        value,
        font_name=font_name,
        font_size=font_size,
        max_width=continuation_width,
    )
    if not wrapped_value:
        return [_ReceiptWrappedLine(label_prefix.rstrip())]

    wrapped_lines = [_ReceiptWrappedLine(f"{label_prefix}{wrapped_value[0]}")]
    wrapped_lines.extend(
        _ReceiptWrappedLine(segment, x_offset=label_width)
        for segment in wrapped_value[1:]
    )
    return wrapped_lines


def render_signing_audit_receipt_pdf(envelope_payload: Dict[str, Any]) -> bytes:
    from backend.services.signing_validation_service import build_signing_validation_url

    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter
    left_margin = 54
    right_margin = 54
    top_margin = 54
    bottom_margin = 54
    body_max_width = width - left_margin - right_margin
    y = height - 54
    line_height = 14
    lines = _receipt_lines(envelope_payload)
    for line in lines:
        is_title = line == "DullyPDF Signature Audit Receipt"
        font_name = "Helvetica-Bold" if is_title else "Helvetica"
        font_size = 14 if is_title else 10
        wrapped_lines = _wrap_receipt_line(
            str(line),
            font_name=font_name,
            font_size=font_size,
            max_width=body_max_width,
        )
        for wrapped_line in wrapped_lines:
            if y < bottom_margin:
                pdf.showPage()
                y = height - top_margin
            pdf.setFont(font_name, font_size)
            if wrapped_line.text:
                pdf.drawString(left_margin + wrapped_line.x_offset, y, wrapped_line.text)
            y -= line_height
    manifest = dict((envelope_payload or {}).get("manifest") or {})
    request = dict(manifest.get("request") or {})
    request_id = str(request.get("id") or "").strip()
    if request_id:
        validation_url = build_signing_validation_url(request_id)
        qr_header_font_name = "Helvetica-Bold"
        qr_header_font_size = 11
        qr_body_font_name = "Helvetica"
        qr_body_font_size = 10
        qr_url_lines = _wrap_receipt_line(
            validation_url,
            font_name=qr_body_font_name,
            font_size=qr_body_font_size,
            max_width=body_max_width,
        )
        qr_block_height = 18 + (len(qr_url_lines) * line_height) + 18 + 120
        if y < bottom_margin + qr_block_height:
            pdf.showPage()
            y = height - top_margin
        pdf.setFont(qr_header_font_name, qr_header_font_size)
        pdf.drawString(left_margin, y, "Scan to validate this DullyPDF signing record")
        y -= 18
        pdf.setFont(qr_body_font_name, qr_body_font_size)
        for wrapped_line in qr_url_lines:
            pdf.drawString(left_margin + wrapped_line.x_offset, y, wrapped_line.text)
            y -= line_height
        y -= 4
        qr_drawing = createBarcodeDrawing(
            "QR",
            value=validation_url,
            width=120,
            height=120,
            barLevel="M",
        )
        renderPDF.draw(qr_drawing, pdf, left_margin, max(y - 120, bottom_margin))
    pdf.save()
    return buffer.getvalue()
