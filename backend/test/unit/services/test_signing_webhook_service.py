from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.services import signing_webhook_service


def _record(**overrides):
    payload = {
        "id": "req-1",
        "title": "Bravo Packet Signature Request",
        "status": "completed",
        "mode": "sign",
        "signature_mode": "business",
        "source_type": "workspace",
        "source_id": "form-alpha",
        "source_link_id": None,
        "source_record_label": None,
        "source_document_name": "Bravo Packet",
        "source_version": "workspace:form-alpha:abc123",
        "document_category": "ordinary_business_form",
        "user_id": "user-1",
        "signer_name": "Alex Signer",
        "signer_email": "alex@example.com",
        "signer_contact_method": "email",
        "signer_auth_method": "email_otp",
        "verification_required": True,
        "verification_method": "email_otp",
        "invite_method": "email",
        "invite_delivery_status": "sent",
        "manual_fallback_enabled": True,
        "created_at": "2026-03-28T12:00:00+00:00",
        "sent_at": "2026-03-28T12:01:00+00:00",
        "completed_at": "2026-03-28T12:05:00+00:00",
        "invalidated_at": None,
        "invalidation_reason": None,
        "public_link_version": 2,
        "source_pdf_bucket_path": "gs://signing/source.pdf",
        "signed_pdf_bucket_path": "gs://signing/signed.pdf",
        "audit_manifest_bucket_path": "gs://signing/manifest.json",
        "audit_receipt_bucket_path": "gs://signing/receipt.pdf",
    }
    payload.update(overrides)
    return SimpleNamespace(**payload)


def test_build_signing_webhook_payload_includes_validation_path() -> None:
    payload = signing_webhook_service.build_signing_webhook_payload(
        _record(),
        event_type="completed",
        details={"statusAfter": "completed"},
        occurred_at="2026-03-28T12:05:00+00:00",
    )

    assert payload["type"] == "completed"
    assert payload["request"]["signerContactMethod"] == "email"
    assert payload["request"]["signerAuthMethod"] == "email_otp"
    assert payload["request"]["validationPath"].startswith("/verify-signing/")
    assert payload["artifacts"]["auditReceiptAvailable"] is True


@pytest.mark.anyio
async def test_emit_signing_webhook_event_posts_signed_payload(monkeypatch) -> None:
    monkeypatch.setenv("SIGNING_WEBHOOK_URLS", "https://example.com/signing-webhooks")
    monkeypatch.setenv("SIGNING_WEBHOOK_SECRET", "webhook-secret-123")

    captured = {}

    class _FakeResponse:
        status_code = 200

    class _FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            captured["timeout"] = kwargs.get("timeout")

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, *, content, headers):
            captured["url"] = url
            captured["content"] = content.decode("utf-8")
            captured["headers"] = dict(headers)
            return _FakeResponse()

    monkeypatch.setattr(signing_webhook_service.httpx, "AsyncClient", _FakeAsyncClient)

    await signing_webhook_service.emit_signing_webhook_event(
        _record(),
        event_type="completed",
        details={"statusAfter": "completed"},
        occurred_at="2026-03-28T12:05:00+00:00",
    )

    assert captured["url"] == "https://example.com/signing-webhooks"
    assert '"type":"completed"' in captured["content"]
    assert '"validationPath":"/verify-signing/' in captured["content"]
    assert captured["headers"]["X-Dully-Signature"].startswith("t=2026-03-28T12:05:00+00:00,v1=")
