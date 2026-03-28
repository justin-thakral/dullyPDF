"""Unit coverage for consumer disclosure artifact helpers."""

from __future__ import annotations

from types import SimpleNamespace

from backend.services.signing_consumer_consent_service import (
    build_consumer_disclosure_artifact,
    persist_consumer_disclosure_artifact,
    resolve_consumer_disclosure_artifact,
)
from backend.services.signing_service import build_signing_public_token


def _record(**overrides):
    payload = {
        "id": "req-consumer-1",
        "signature_mode": "consumer",
        "disclosure_version": "us-esign-consumer-v1",
        "sender_display_name": "Owner Example",
        "sender_email": "owner@example.com",
        "sender_contact_email": "owner@example.com",
        "manual_fallback_enabled": True,
        "consumer_paper_copy_procedure": "Email owner@example.com to request a paper copy for this request.",
        "consumer_paper_copy_fee_description": "No paper-copy fee is charged.",
        "consumer_withdrawal_procedure": "Use the withdraw option or email owner@example.com before completion.",
        "consumer_withdrawal_consequences": "Withdrawing consent ends the electronic process for this request.",
        "consumer_contact_update_procedure": "Email owner@example.com if your contact details change before completion.",
        "consumer_consent_scope_override": None,
        "consumer_disclosure_version": None,
        "consumer_disclosure_payload": None,
        "consumer_disclosure_sha256": None,
        "consumer_consent_scope": None,
        "public_link_version": 3,
    }
    payload.update(overrides)
    return SimpleNamespace(**payload)


def test_build_consumer_disclosure_artifact_is_versioned_and_hashed(monkeypatch) -> None:
    monkeypatch.setenv("SIGNING_LINK_TOKEN_SECRET", "unit-test-signing-token-secret-1234567890")

    record = _record()
    artifact = build_consumer_disclosure_artifact(record)
    expected_token = build_signing_public_token(record.id, record.public_link_version)

    assert artifact["version"] == "us-esign-consumer-v1"
    assert artifact["sha256"]
    assert len(artifact["sha256"]) == 64
    assert artifact["scope"] == artifact["payload"]["scope"]
    assert artifact["payload"]["sender"]["displayName"] == "Owner Example"
    assert artifact["payload"]["sender"]["contactEmail"] == "owner@example.com"
    assert artifact["payload"]["accessCheck"]["accessPath"] == (
        f"/api/signing/public/{expected_token}/consumer-access-pdf"
    )
    assert artifact["payload"]["accessCheck"]["codeLength"] == 6


def test_resolve_consumer_disclosure_artifact_prefers_persisted_payload() -> None:
    stored_payload = {
        "version": "us-esign-consumer-v1",
        "summaryLines": ["Stored disclosure line."],
        "scope": "Stored consumer scope.",
        "accessCheck": {"required": True, "format": "pdf"},
    }
    record = _record(
        consumer_disclosure_version="us-esign-consumer-v1",
        consumer_disclosure_payload=stored_payload,
        consumer_disclosure_sha256="f" * 64,
        consumer_consent_scope="Stored consumer scope.",
    )

    artifact = resolve_consumer_disclosure_artifact(record)

    assert artifact["version"] == "us-esign-consumer-v1"
    assert artifact["payload"] == stored_payload
    assert artifact["sha256"] == "f" * 64
    assert artifact["scope"] == "Stored consumer scope."


def test_persist_consumer_disclosure_artifact_stores_generated_payload_when_missing(monkeypatch) -> None:
    monkeypatch.setenv("SIGNING_LINK_TOKEN_SECRET", "unit-test-signing-token-secret-1234567890")
    persisted = {}

    def _fake_store(
        request_id,
        *,
        disclosure_version,
        disclosure_payload,
        disclosure_sha256,
        consent_scope,
        reset_ceremony_progress=False,
        client=None,
    ):
        persisted.update(
            {
                "request_id": request_id,
                "disclosure_version": disclosure_version,
                "disclosure_payload": disclosure_payload,
                "disclosure_sha256": disclosure_sha256,
                "consent_scope": consent_scope,
                "reset_ceremony_progress": reset_ceremony_progress,
                "client": client,
            }
        )
        return SimpleNamespace(id=request_id, consumer_disclosure_payload=disclosure_payload)

    monkeypatch.setattr(
        "backend.services.signing_consumer_consent_service.store_signing_request_consumer_disclosure",
        _fake_store,
    )

    result = persist_consumer_disclosure_artifact(_record())

    assert persisted["request_id"] == "req-consumer-1"
    assert persisted["disclosure_version"] == "us-esign-consumer-v1"
    assert persisted["disclosure_payload"]["paperOption"]["fees"]
    assert persisted["disclosure_payload"]["withdrawal"]["instructions"]
    assert persisted["disclosure_payload"]["contactUpdates"]
    assert persisted["disclosure_payload"]["sender"]["contactEmail"] == "owner@example.com"
    assert persisted["disclosure_payload"]["hardwareSoftware"]
    assert len(persisted["disclosure_sha256"]) == 64
    assert persisted["consent_scope"] == persisted["disclosure_payload"]["scope"]
    assert persisted["reset_ceremony_progress"] is False
    assert result.consumer_disclosure_payload == persisted["disclosure_payload"]


def test_persist_consumer_disclosure_artifact_resets_ceremony_progress_when_payload_changes(monkeypatch) -> None:
    persisted = {}

    monkeypatch.setattr(
        "backend.services.signing_consumer_consent_service.build_consumer_disclosure_artifact",
        lambda record: {
            "version": "us-esign-consumer-v2",
            "payload": {
                "version": "us-esign-consumer-v2",
                "summaryLines": ["Updated disclosure line."],
                "scope": "Updated scope.",
            },
            "sha256": "a" * 64,
            "scope": "Updated scope.",
        },
    )

    def _fake_store(
        request_id,
        *,
        disclosure_version,
        disclosure_payload,
        disclosure_sha256,
        consent_scope,
        reset_ceremony_progress=False,
        client=None,
    ):
        persisted.update(
            {
                "request_id": request_id,
                "disclosure_version": disclosure_version,
                "disclosure_payload": disclosure_payload,
                "disclosure_sha256": disclosure_sha256,
                "consent_scope": consent_scope,
                "reset_ceremony_progress": reset_ceremony_progress,
                "client": client,
            }
        )
        return SimpleNamespace(id=request_id, consumer_disclosure_payload=disclosure_payload)

    monkeypatch.setattr(
        "backend.services.signing_consumer_consent_service.store_signing_request_consumer_disclosure",
        _fake_store,
    )

    persist_consumer_disclosure_artifact(
        _record(
            consumer_disclosure_version="us-esign-consumer-v1",
            consumer_disclosure_payload={"version": "us-esign-consumer-v1", "summaryLines": ["Old disclosure line."]},
            consumer_disclosure_sha256="b" * 64,
            consumer_consent_scope="Old scope.",
        )
    )

    assert persisted["request_id"] == "req-consumer-1"
    assert persisted["reset_ceremony_progress"] is True
    assert persisted["disclosure_version"] == "us-esign-consumer-v2"


def test_persist_consumer_disclosure_artifact_keeps_completed_records_immutable(monkeypatch) -> None:
    store_called = {"value": False}

    def _fake_store(*args, **kwargs):
        store_called["value"] = True
        return None

    monkeypatch.setattr(
        "backend.services.signing_consumer_consent_service.store_signing_request_consumer_disclosure",
        _fake_store,
    )

    record = _record(
        status="completed",
        consumer_disclosure_version="us-esign-consumer-v1",
        consumer_disclosure_payload={"version": "us-esign-consumer-v1"},
        consumer_disclosure_sha256="f" * 64,
        consumer_consent_scope="Stored scope.",
    )

    result = persist_consumer_disclosure_artifact(record)

    assert result is record
    assert store_called["value"] is False
