"""Audit-manifest and receipt helpers for completed signing requests.

The manifest builder is intentionally deterministic: it canonicalizes nested
data and signs the exact UTF-8 JSON bytes so the same request/event history
reproduces the same digest later. Receipt generation is linear in the number of
rendered lines, which in practice is O(event_count).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
from io import BytesIO
from typing import Any, Dict, Iterable, List

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

from backend.services.cloud_kms_service import (
    AuditSignatureEnvelope,
    sign_audit_manifest_bytes,
    verify_audit_manifest_signature,
)
from backend.services.signing_service import resolve_document_category_label, resolve_signing_retention_days


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


def _resolve_retention_until(completed_at: str | None) -> str:
    retention_days = resolve_signing_retention_days()
    raw_completed_at = str(completed_at or "").strip()
    try:
        dt = datetime.fromisoformat(raw_completed_at.replace("Z", "+00:00"))
    except ValueError:
        dt = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (dt + timedelta(days=retention_days)).isoformat()


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
    return {
        "schemaVersion": AUDIT_MANIFEST_SCHEMA_VERSION,
        "request": {
            "id": record.id,
            "title": record.title,
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
            "disclosureVersion": record.disclosure_version,
        },
        "signer": {
            "name": record.signer_name,
            "email": record.signer_email,
            "adoptedName": record.signature_adopted_name,
        },
        "ceremony": {
            "manualFallbackEnabled": bool(record.manual_fallback_enabled),
            "manualFallbackRequestedAt": record.manual_fallback_requested_at,
            "manualFallbackNote": record.manual_fallback_note,
            "openedAt": record.opened_at,
            "reviewedAt": record.reviewed_at,
            "consentedAt": record.consented_at,
            "signatureAdoptedAt": record.signature_adopted_at,
            "completedAt": record.completed_at,
            "completedSessionId": record.completed_session_id,
            "completedIpAddress": record.completed_ip_address,
            "completedUserAgent": record.completed_user_agent,
        },
        "documentEvidence": {
            "sourcePdfSha256": record.source_pdf_sha256,
            "signedPdfSha256": signed_pdf_sha256,
            "sourcePdfBucketPath": source_pdf_bucket_path,
            "signedPdfBucketPath": signed_pdf_bucket_path,
            "signedPdfPageCount": int(signed_pdf_page_count),
            "appliedAnchorCount": int(applied_anchor_count),
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
    retention_until = _resolve_retention_until(record.completed_at)
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


def _receipt_lines(envelope_payload: Dict[str, Any]) -> List[str]:
    manifest = dict((envelope_payload or {}).get("manifest") or {})
    request = dict(manifest.get("request") or {})
    signer = dict(manifest.get("signer") or {})
    ceremony = dict(manifest.get("ceremony") or {})
    document_evidence = dict(manifest.get("documentEvidence") or {})
    signature = dict((envelope_payload or {}).get("signature") or {})
    lines = [
        "DullyPDF Signature Audit Receipt",
        "",
        f"Request ID: {request.get('id') or ''}",
        f"Document: {request.get('sourceDocumentName') or ''}",
        f"Document Category: {request.get('documentCategoryLabel') or request.get('documentCategory') or ''}",
        f"Signer: {signer.get('name') or ''} <{signer.get('email') or ''}>",
        f"Adopted Signature: {signer.get('adoptedName') or ''}",
        f"Completed At: {ceremony.get('completedAt') or ''}",
        f"Completed IP: {ceremony.get('completedIpAddress') or ''}",
        f"Completed User Agent: {ceremony.get('completedUserAgent') or ''}",
        "",
        f"Source PDF SHA-256: {document_evidence.get('sourcePdfSha256') or ''}",
        f"Signed PDF SHA-256: {document_evidence.get('signedPdfSha256') or ''}",
        f"Manifest SHA-256: {envelope_payload.get('manifestSha256') or ''}",
        f"Retention Until: {document_evidence.get('retentionUntil') or ''}",
        "",
        f"Signature Method: {signature.get('method') or ''}",
        f"Signature Algorithm: {signature.get('algorithm') or ''}",
        f"KMS Key Version: {signature.get('keyVersionName') or ''}",
        "",
        "Event Timeline:",
    ]
    for event in list(manifest.get("events") or []):
        event_type = event.get("eventType") or ""
        occurred_at = event.get("occurredAt") or ""
        client_ip = event.get("clientIp") or ""
        lines.append(f"- {occurred_at} | {event_type} | {client_ip}")
    return lines


def render_signing_audit_receipt_pdf(envelope_payload: Dict[str, Any]) -> bytes:
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter
    y = height - 54
    line_height = 14
    for line in _receipt_lines(envelope_payload):
        if y < 54:
            pdf.showPage()
            y = height - 54
        pdf.setFont("Helvetica-Bold", 14 if line == "DullyPDF Signature Audit Receipt" else 10)
        if line and line != "DullyPDF Signature Audit Receipt":
            pdf.setFont("Helvetica", 10)
        pdf.drawString(54, y, str(line))
        y -= line_height
    pdf.save()
    return buffer.getvalue()
