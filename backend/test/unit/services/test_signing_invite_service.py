"""Unit coverage for signing invite delivery helpers."""

from __future__ import annotations

import pytest

from backend.services import signing_invite_service


def test_build_signing_invite_url_prefers_explicit_origin(monkeypatch) -> None:
    monkeypatch.setenv("SIGNING_APP_ORIGIN", "https://sign.example.com/")

    assert signing_invite_service.build_signing_invite_url("/sign/token-1") == "https://sign.example.com/sign/token-1"


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
