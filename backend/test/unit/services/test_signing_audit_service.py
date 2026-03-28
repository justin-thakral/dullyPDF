"""Unit coverage for audit manifest and receipt generation."""

from __future__ import annotations

from io import BytesIO
from types import SimpleNamespace

from pypdf import PdfReader
from reportlab.pdfbase import pdfmetrics

from backend.services.signing_audit_service import (
    _wrap_receipt_line,
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
        "user_id": "user-1",
        "sender_email": "owner@example.com",
        "invite_method": "email",
        "invite_provider": "gmail_api",
        "invite_delivery_status": "sent",
        "invite_last_attempt_at": "2026-03-24T12:01:10+00:00",
        "invite_sent_at": "2026-03-24T12:01:12+00:00",
        "invite_delivery_error": None,
        "invite_delivery_error_code": None,
        "invite_message_id": "gmail-message-1",
        "manual_link_shared_at": None,
        "public_link_version": 2,
        "public_link_revoked_at": None,
        "public_link_last_reissued_at": "2026-03-24T12:01:30+00:00",
        "verification_required": False,
        "verification_method": None,
        "verification_completed_at": None,
        "signer_name": "Alex Signer",
        "signer_email": "alex@example.com",
        "signer_contact_method": "email",
        "signer_auth_method": "email_otp",
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
        "signed_pdf_digital_signature_method": "pkcs12",
        "signed_pdf_digital_signature_algorithm": "sha256_rsa",
        "signed_pdf_digital_signature_field_name": "DullyPDFDigitalSignature",
        "signed_pdf_digital_signature_subfilter": "/ETSI.CAdES.detached",
        "signed_pdf_digital_signature_timestamped": True,
        "signed_pdf_digital_certificate_subject": "CN=DullyPDF Test Signer",
        "signed_pdf_digital_certificate_issuer": "CN=DullyPDF Test Issuer",
        "signed_pdf_digital_certificate_serial_number": "01",
        "signed_pdf_digital_certificate_fingerprint_sha256": "f" * 64,
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
    assert bundle.manifest_payload["request"]["publicLinkVersion"] == 2
    assert bundle.manifest_payload["request"]["signerContactMethod"] == "email"
    assert bundle.manifest_payload["request"]["signerAuthMethod"] == "email_otp"
    assert bundle.manifest_payload["sender"]["ownerUserId"] == "user-1"
    assert bundle.manifest_payload["sender"]["senderEmail"] == "owner@example.com"
    assert bundle.manifest_payload["sender"]["inviteProviderMessageId"] == "gmail-message-1"
    assert bundle.signature["method"] == "dev_hmac_sha256"
    assert verify_signing_audit_envelope(bundle.envelope_payload) is True

    receipt_reader = PdfReader(BytesIO(bundle.receipt_pdf_bytes))
    receipt_text = "\n".join(page.extract_text() or "" for page in receipt_reader.pages)
    assert "DullyPDF Signature Audit Receipt" in receipt_text
    assert "Request ID: req-1" in receipt_text
    assert "Sender: owner@example.com" in receipt_text
    assert "Delivery Method: email" in receipt_text
    assert "Validation URL: http://localhost:5173/verify-signing/" in receipt_text
    assert "Signed PDF SHA-256" in receipt_text
    assert "PDF Signature Method: pkcs12" in receipt_text
    assert "PDF Timestamped: yes" in receipt_text
    assert "Signer: Alex Signer" in receipt_text
    assert "alex@example.com" not in receipt_text
    assert "203.0.113.7" not in receipt_text
    assert "integration-browser/1.0" not in receipt_text


def test_build_signing_audit_bundle_includes_consumer_consent_evidence(monkeypatch) -> None:
    monkeypatch.setenv("SIGNING_AUDIT_DEV_SECRET", "dev-audit-secret-1234567890")

    consumer_payload = {
        "version": "us-esign-consumer-v1",
        "summaryLines": ["Consumer disclosure summary."],
        "scope": "This consent applies only to this request.",
        "accessCheck": {
            "required": True,
            "format": "pdf",
            "instructions": "Open the access PDF and enter the code.",
            "accessPath": "/api/signing/public/token-1/consumer-access-pdf",
            "codeLength": 6,
        },
    }

    bundle = build_signing_audit_bundle(
        record=_record(
            signature_mode="consumer",
            disclosure_version="us-esign-consumer-v1",
            consumer_disclosure_version="us-esign-consumer-v1",
            consumer_disclosure_payload=consumer_payload,
            consumer_disclosure_sha256="c" * 64,
            consumer_disclosure_presented_at="2026-03-24T12:02:05+00:00",
            consumer_consent_scope="This consent applies only to this request.",
            consented_at="2026-03-24T12:02:30+00:00",
            consumer_access_demonstrated_at="2026-03-24T12:02:30+00:00",
            consumer_access_demonstration_method="consumer_access_pdf_code",
            consent_withdrawn_at=None,
        ),
        events=[
            {
                "eventType": "consent_accepted",
                "sessionId": "session-1",
                "linkTokenId": "token-1",
                "clientIp": "203.0.113.7",
                "userAgent": "integration-browser/1.0",
                "occurredAt": "2026-03-24T12:02:30+00:00",
                "details": {"disclosureSha256": "c" * 64},
            },
        ],
        signed_pdf_sha256="b" * 64,
        signed_pdf_bucket_path="gs://signing-bucket/users/user-1/signing/req-1/artifacts/signed_pdf/final.pdf",
        source_pdf_bucket_path="gs://signing-bucket/users/user-1/signing/req-1/source/source.pdf",
        signed_pdf_page_count=1,
        applied_anchor_count=1,
    )

    consumer_consent = bundle.manifest_payload["consumerConsent"]
    assert consumer_consent["disclosureVersion"] == "us-esign-consumer-v1"
    assert consumer_consent["disclosurePayload"] == consumer_payload
    assert consumer_consent["disclosureSha256"] == "c" * 64
    assert consumer_consent["disclosurePresentedAt"] == "2026-03-24T12:02:05+00:00"
    assert consumer_consent["consentAcceptedAt"] == "2026-03-24T12:02:30+00:00"
    assert consumer_consent["accessDemonstratedAt"] == "2026-03-24T12:02:30+00:00"
    assert consumer_consent["accessDemonstrationMethod"] == "consumer_access_pdf_code"
    assert bundle.manifest_payload["disclosure"]["payload"] == consumer_payload
    assert bundle.manifest_payload["disclosure"]["payloadSha256"] == "c" * 64

    receipt_reader = PdfReader(BytesIO(bundle.receipt_pdf_bytes))
    receipt_text = "\n".join(page.extract_text() or "" for page in receipt_reader.pages)
    assert "Consumer Disclosure Version: us-esign-consumer-v1" in receipt_text
    assert "Access Method: consumer_access_pdf_code" in receipt_text


def test_wrap_receipt_line_keeps_long_values_inside_printable_width() -> None:
    max_width = 612 - 54 - 54
    long_lines = [
        (
            "Validation URL: "
            "http://localhost:5173/verify-signing/"
            "sv1.NDUwZTU1Yjc2NzE0NGMzYmI0OGZkNDk1NGUwNjQ4OGM."
            "teSKkEvpWr93N6sFVwFLSdfiZqRmnuHhFNoM0yr4QmQ"
        ),
        (
            "PDF Signature Subject: Common Name: DullyPDF Dev PDF Signing, Organization: "
            "DullyPDF Development, Locality: New York, State/Province: New York, Country: US"
        ),
    ]

    for raw_line in long_lines:
        wrapped = _wrap_receipt_line(raw_line, font_name="Helvetica", font_size=10, max_width=max_width)
        assert len(wrapped) > 1
        assert "".join(segment.text.strip() for segment in wrapped)
        assert wrapped[0].x_offset == 0
        assert any(segment.x_offset > 0 for segment in wrapped[1:])
        for segment in wrapped:
            rendered_width = segment.x_offset + pdfmetrics.stringWidth(segment.text, "Helvetica", 10)
            assert rendered_width <= max_width
