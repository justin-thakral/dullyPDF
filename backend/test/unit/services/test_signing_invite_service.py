"""Unit coverage for signing invite delivery helpers."""

from __future__ import annotations

import pytest

from backend.services import signing_invite_service


def test_build_signing_invite_url_prefers_explicit_origin(monkeypatch) -> None:
    monkeypatch.setenv("SIGNING_APP_ORIGIN", "https://sign.example.com/")

    assert signing_invite_service.build_signing_invite_url("/sign/token-1") == "https://sign.example.com/sign/token-1"


def test_build_signing_invite_url_prefers_request_origin_outside_prod(monkeypatch) -> None:
    monkeypatch.setenv("SIGNING_APP_ORIGIN", "http://localhost:5177")
    monkeypatch.setattr(signing_invite_service, "is_prod", lambda: False)

    assert (
        signing_invite_service.build_signing_invite_url(
            "/sign/token-1",
            request_origin="http://localhost:5173/respond/token-abc",
        )
        == "http://localhost:5173/sign/token-1"
    )


def test_build_signing_invite_url_ignores_unallowlisted_request_origin_outside_prod(monkeypatch) -> None:
    monkeypatch.setenv("SIGNING_APP_ORIGIN", "http://localhost:5177")
    monkeypatch.setattr(signing_invite_service, "is_prod", lambda: False)

    assert (
        signing_invite_service.build_signing_invite_url(
            "/sign/token-1",
            request_origin="https://evil.example/respond/token-abc",
        )
        == "http://localhost:5177/sign/token-1"
    )


def test_resolve_signing_invite_origin_rejects_non_canonical_prod_origin(monkeypatch) -> None:
    monkeypatch.setenv("SIGNING_APP_ORIGIN", "https://sign.example.com")
    monkeypatch.setattr(signing_invite_service, "is_prod", lambda: True)

    with pytest.raises(RuntimeError):
        signing_invite_service.resolve_signing_invite_origin()


def test_resolve_signing_invite_event_type_maps_delivery_statuses() -> None:
    assert (
        signing_invite_service.resolve_signing_invite_event_type(signing_invite_service.SIGNING_INVITE_DELIVERY_SENT)
        == signing_invite_service.SIGNING_EVENT_INVITE_SENT
    )
    assert (
        signing_invite_service.resolve_signing_invite_event_type(signing_invite_service.SIGNING_INVITE_DELIVERY_FAILED)
        == signing_invite_service.SIGNING_EVENT_INVITE_FAILED
    )
    assert (
        signing_invite_service.resolve_signing_invite_event_type(signing_invite_service.SIGNING_INVITE_DELIVERY_SKIPPED)
        == signing_invite_service.SIGNING_EVENT_INVITE_SKIPPED
    )
    assert signing_invite_service.resolve_signing_invite_event_type("pending") is None


@pytest.mark.anyio
async def test_send_signing_invite_email_skips_when_sender_not_configured(monkeypatch) -> None:
    monkeypatch.delenv("SIGNING_FROM_EMAIL", raising=False)
    monkeypatch.delenv("CONTACT_FROM_EMAIL", raising=False)
    monkeypatch.delenv("CONTACT_TO_EMAIL", raising=False)

    result = await signing_invite_service.send_signing_invite_email(
        signer_email="ada@example.com",
        signer_name="Ada Lovelace",
        document_name="Bravo Packet",
        public_path="/sign/token-1",
    )

    assert result.delivery_status == signing_invite_service.SIGNING_INVITE_DELIVERY_SKIPPED
    assert result.error_message == "Signing invite email routing is not configured."


@pytest.mark.anyio
async def test_send_signing_invite_email_succeeds_when_gmail_is_configured(monkeypatch) -> None:
    monkeypatch.setenv("SIGNING_FROM_EMAIL", "noreply@example.com")
    monkeypatch.setenv("SIGNING_APP_ORIGIN", "https://sign.example.com")

    async def _fake_get_gmail_access_token():
        return "access-token"

    monkeypatch.setattr(signing_invite_service, "get_gmail_access_token", _fake_get_gmail_access_token)

    captured = {}

    async def _fake_send_gmail_message(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(signing_invite_service, "send_gmail_message", _fake_send_gmail_message)

    result = await signing_invite_service.send_signing_invite_email(
        signer_email="ada@example.com",
        signer_name="Ada Lovelace",
        document_name="Bravo Packet",
        public_path="/sign/token-1",
        sender_email="owner@example.com",
    )

    assert result.delivery_status == signing_invite_service.SIGNING_INVITE_DELIVERY_SENT
    assert result.sent_at is not None
    assert captured["to_email"] == "ada@example.com"
    assert captured["from_email"] == "noreply@example.com"
    assert captured["subject"] == "Signature request: Bravo Packet"
    assert "https://sign.example.com/sign/token-1" in captured["body"]
    assert captured["reply_to"] == {"email": "owner@example.com", "name": "owner@example.com"}


@pytest.mark.anyio
async def test_send_signing_invite_email_returns_failed_when_gmail_send_raises(monkeypatch) -> None:
    monkeypatch.setenv("SIGNING_FROM_EMAIL", "noreply@example.com")
    monkeypatch.setenv("SIGNING_APP_ORIGIN", "https://sign.example.com")

    async def _fake_get_gmail_access_token():
        return "access-token"

    async def _fake_send_gmail_message(**_kwargs):
        raise RuntimeError("gmail send boom")

    monkeypatch.setattr(signing_invite_service, "get_gmail_access_token", _fake_get_gmail_access_token)
    monkeypatch.setattr(signing_invite_service, "send_gmail_message", _fake_send_gmail_message)

    result = await signing_invite_service.send_signing_invite_email(
        signer_email="ada@example.com",
        signer_name="Ada Lovelace",
        document_name="Bravo Packet",
        public_path="/sign/token-1",
        sender_email="owner@example.com",
    )

    assert result.delivery_status == signing_invite_service.SIGNING_INVITE_DELIVERY_FAILED
    assert result.provider == signing_invite_service.SIGNING_INVITE_PROVIDER_GMAIL_API
    assert result.error_code == "gmail_send_failed"
    assert result.error_message == "Failed to deliver the signing invite email."


@pytest.mark.anyio
async def test_deliver_signing_invite_for_request_rejects_unsupported_signer_contact_method(monkeypatch) -> None:
    record = type(
        "SigningRecord",
        (),
        {
            "id": "req-1",
            "signer_contact_method": "sms",
            "invite_method": "sms",
        },
    )()
    monkeypatch.setattr(
        signing_invite_service,
        "mark_signing_request_invite_delivery",
        lambda *args, **kwargs: None,
    )

    result = await signing_invite_service.deliver_signing_invite_for_request(
        record=record,
        user_id="user-1",
    )

    assert result.record is record
    assert result.delivery.delivery_status == signing_invite_service.SIGNING_INVITE_DELIVERY_FAILED
    assert result.delivery.error_code == "unsupported_signer_contact_method"
