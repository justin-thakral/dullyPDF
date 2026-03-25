"""Unit coverage for audit manifest and receipt generation."""

from __future__ import annotations

from io import BytesIO
from types import SimpleNamespace

from pypdf import PdfReader

from backend.services.signing_audit_service import (
    build_signing_audit_bundle,
    verify_signing_audit_envelope,
)


def _record(**overrides):
    payload = {
        "id": "req-1",
        "title": "Bravo Packet Signature Request",
        "mode": "sign",
        "signature_mode": "business",
        "status": "completed",
        "source_type": "workspace",
        "source_id": "form-alpha",
        "source_template_id": "form-alpha",
        "source_template_name": "Bravo Packet",
        "source_document_name": "Bravo Packet",
        "source_version": "workspace:form-alpha:abc123",
        "document_category": "ordinary_business_form",
        "disclosure_version": "us-esign-business-v1",
        "signer_name": "Alex Signer",
        "signer_email": "alex@example.com",
        "signature_adopted_name": "Alex Signer",
        "manual_fallback_enabled": True,
        "manual_fallback_requested_at": None,
        "manual_fallback_note": None,
        "opened_at": "2026-03-24T12:02:00+00:00",
        "reviewed_at": "2026-03-24T12:03:00+00:00",
        "consented_at": None,
        "signature_adopted_at": "2026-03-24T12:04:00+00:00",
        "completed_at": "2026-03-24T12:05:00+00:00",
        "completed_session_id": "session-1",
        "completed_ip_address": "203.0.113.7",
        "completed_user_agent": "integration-browser/1.0",
        "source_pdf_sha256": "a" * 64,
        "anchors": [
            {"kind": "signature", "page": 1, "rect": {"x": 10, "y": 10, "width": 100, "height": 30}},
        ],
    }
    payload.update(overrides)
    return SimpleNamespace(**payload)


def test_build_signing_audit_bundle_is_reproducible_and_verifiable(monkeypatch) -> None:
    monkeypatch.setenv("SIGNING_AUDIT_DEV_SECRET", "dev-audit-secret-1234567890")

    bundle = build_signing_audit_bundle(
        record=_record(),
        events=[
            {
                "eventType": "opened",
                "sessionId": "session-1",
                "linkTokenId": "token-1",
                "clientIp": "203.0.113.7",
                "userAgent": "integration-browser/1.0",
                "occurredAt": "2026-03-24T12:02:00+00:00",
                "details": {"sourcePdfSha256": "a" * 64},
            },
            {
                "eventType": "completed",
                "sessionId": "session-1",
                "linkTokenId": "token-1",
                "clientIp": "203.0.113.7",
                "userAgent": "integration-browser/1.0",
                "occurredAt": "2026-03-24T12:05:00+00:00",
                "details": {"signedPdfSha256": "b" * 64},
            },
        ],
        signed_pdf_sha256="b" * 64,
        signed_pdf_bucket_path="gs://signing-bucket/users/user-1/signing/req-1/artifacts/signed_pdf/final.pdf",
        source_pdf_bucket_path="gs://signing-bucket/users/user-1/signing/req-1/source/source.pdf",
        signed_pdf_page_count=1,
        applied_anchor_count=1,
    )

    assert bundle.manifest_payload["documentEvidence"]["retentionUntil"] == bundle.retention_until
    assert bundle.signature["method"] == "dev_hmac_sha256"
    assert verify_signing_audit_envelope(bundle.envelope_payload) is True

    receipt_reader = PdfReader(BytesIO(bundle.receipt_pdf_bytes))
    receipt_text = "\n".join(page.extract_text() or "" for page in receipt_reader.pages)
    assert "DullyPDF Signature Audit Receipt" in receipt_text
    assert "Request ID: req-1" in receipt_text
    assert "Signed PDF SHA-256" in receipt_text
