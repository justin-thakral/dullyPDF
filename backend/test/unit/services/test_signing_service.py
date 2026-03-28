"""Unit coverage for signing helpers."""

from __future__ import annotations

import pytest

from backend.services import signing_service


def test_signing_public_token_round_trip(mocker) -> None:
    mocker.patch.object(signing_service, "_resolve_signing_token_secret", return_value="x" * 48)

    token = signing_service.build_signing_public_token("request-123", 3)

    assert signing_service.parse_signing_public_token(token) == "request-123"
    assert signing_service.parse_signing_public_token_payload(token) == ("request-123", 3)


def test_signing_validation_token_round_trip(mocker) -> None:
    mocker.patch.object(signing_service, "_resolve_signing_token_secret", return_value="x" * 48)

    token = signing_service.build_signing_validation_token("request-123")

    assert signing_service.parse_signing_validation_token(token) == "request-123"
    assert signing_service.build_signing_validation_path("request-123").endswith(token)


def test_signing_public_token_accepts_legacy_version_one_tokens(mocker) -> None:
    mocker.patch.object(signing_service, "_resolve_signing_token_secret", return_value="x" * 48)

    legacy_token = ".".join(
        [
            "v1",
            signing_service._urlsafe_b64encode(b"request-123"),
            signing_service._legacy_signing_request_signature("request-123"),
        ]
    )

    assert signing_service.parse_signing_public_token_payload(legacy_token) == ("request-123", 1)


def test_signing_public_session_token_round_trip(mocker) -> None:
    mocker.patch.object(signing_service, "_resolve_signing_token_secret", return_value="x" * 48)
    mocker.patch.object(signing_service.time, "time", return_value=1000)

    token = signing_service.build_signing_public_session_token("request-123", "session-456", 1300)

    assert signing_service.parse_signing_public_session_token(token) == ("request-123", "session-456", 1300)


def test_signing_public_artifact_token_round_trip(mocker) -> None:
    mocker.patch.object(signing_service, "_resolve_signing_token_secret", return_value="x" * 48)
    mocker.patch.object(signing_service.time, "time", return_value=1000)

    token = signing_service.build_signing_public_artifact_token(
        "request-123",
        "session-456",
        "signed_pdf",
        1300,
    )

    assert signing_service.parse_signing_public_artifact_token(token) == (
        "request-123",
        "session-456",
        "signed_pdf",
        1300,
    )


def test_signing_public_artifact_token_rejects_expired_tokens(mocker) -> None:
    mocker.patch.object(signing_service, "_resolve_signing_token_secret", return_value="x" * 48)
    mocker.patch.object(signing_service.time, "time", return_value=2000)

    token = signing_service.build_signing_public_artifact_token(
        "request-123",
        "session-456",
        "audit_receipt",
        1300,
    )

    assert signing_service.parse_signing_public_artifact_token(token) is None


def test_validate_document_category_blocks_excluded_categories() -> None:
    with pytest.raises(ValueError):
        signing_service.validate_document_category("court_document")
    with pytest.raises(ValueError):
        signing_service.validate_document_category("ucc_governed_record")
    with pytest.raises(ValueError):
        signing_service.validate_document_category("product_recall_or_material_failure")


def test_resolve_signing_disclosure_version_distinguishes_consumer_mode() -> None:
    assert signing_service.resolve_signing_disclosure_version("business") == "us-esign-business-v1"
    assert signing_service.resolve_signing_disclosure_version("consumer") == "us-esign-consumer-v1"


def test_resolve_signing_signer_transport_defaults_to_email_and_email_otp() -> None:
    transport = signing_service.resolve_signing_signer_transport("workspace")

    assert transport.signer_contact_method == "email"
    assert transport.signer_auth_method == "email_otp"
    assert transport.invite_method == "email"
    assert transport.verification_required is True
    assert transport.verification_method == "email_otp"


def test_build_signing_source_version_includes_source_handle_and_hash_prefix() -> None:
    version = signing_service.build_signing_source_version(
        source_type="workspace",
        source_id="form-alpha",
        source_template_id="form-alpha",
        source_pdf_sha256="a" * 64,
    )

    assert version == "workspace:form-alpha:aaaaaaaaaaaa"


def test_build_signing_source_version_prefers_fill_link_response_id_over_template_id() -> None:
    version = signing_service.build_signing_source_version(
        source_type="fill_link_response",
        source_id="resp-42",
        source_template_id="form-alpha",
        source_pdf_sha256="b" * 64,
    )

    assert version == "fill_link_response:resp-42:bbbbbbbbbbbb"


def test_validate_signing_source_type_blocks_fill_and_sign_uploaded_pdf() -> None:
    with pytest.raises(ValueError):
        signing_service.validate_signing_source_type(
            mode="fill_and_sign",
            source_type="uploaded_pdf",
            source_id=None,
        )


def test_validate_signer_email_rejects_multiple_recipients_and_display_names() -> None:
    with pytest.raises(ValueError):
        signing_service.validate_signer_email("alex@example.com, pat@example.com")
    with pytest.raises(ValueError):
        signing_service.validate_signer_email("Alex Signer <alex@example.com>")


def test_build_signing_source_pdf_object_path_uses_expected_directory_layout() -> None:
    path = signing_service.build_signing_source_pdf_object_path(
        user_id="user-1",
        request_id="req-1",
        source_document_name="Bravo Packet.pdf",
        timestamp_ms=1234567890,
    )

    assert path == "users/user-1/signing/req-1/source/1234567890-Bravo_Packet.pdf"


def test_build_signing_artifact_paths_use_expected_directory_layouts() -> None:
    signed_pdf_path = signing_service.build_signing_signed_pdf_object_path(
        user_id="user-1",
        request_id="req-1",
        source_document_name="Bravo Packet.pdf",
        timestamp_ms=111,
    )
    manifest_path = signing_service.build_signing_audit_manifest_object_path(
        user_id="user-1",
        request_id="req-1",
        source_document_name="Bravo Packet.pdf",
        timestamp_ms=222,
    )
    receipt_path = signing_service.build_signing_audit_receipt_object_path(
        user_id="user-1",
        request_id="req-1",
        source_document_name="Bravo Packet.pdf",
        timestamp_ms=333,
    )

    assert signed_pdf_path == "users/user-1/signing/req-1/artifacts/signed_pdf/111-Bravo_Packet-signed_pdf.pdf"
    assert manifest_path == "users/user-1/signing/req-1/artifacts/audit_manifest/222-Bravo_Packet-audit_manifest.json"
    assert receipt_path == "users/user-1/signing/req-1/artifacts/audit_receipt/333-Bravo_Packet-audit_receipt.pdf"


def test_normalize_signing_artifact_key_rejects_unknown_values() -> None:
    assert signing_service.normalize_signing_artifact_key("source_pdf") == "source_pdf"
    assert signing_service.normalize_signing_artifact_key("signed_pdf") == "signed_pdf"
    with pytest.raises(ValueError):
        signing_service.normalize_signing_artifact_key("unknown")


def test_resolve_signing_public_status_message_handles_completed_and_invalidated() -> None:
    assert signing_service.resolve_signing_public_status_message("completed", None) == "This signing request has already been completed."
    assert signing_service.resolve_signing_public_status_message("invalidated", "Source changed") == "Source changed"


def test_resolve_signing_public_status_message_marks_expired_sent_requests() -> None:
    message = signing_service.resolve_signing_public_status_message(
        "sent",
        None,
        expires_at="2000-01-01T00:00:00+00:00",
    )

    assert "expired" in message.lower()


def test_validate_signing_sendable_record_requires_owner_review_for_fill_and_sign() -> None:
    record = type(
        "SigningRecord",
        (),
        {
            "status": signing_service.SIGNING_STATUS_DRAFT,
            "mode": signing_service.SIGNING_MODE_FILL_AND_SIGN,
            "document_category": "ordinary_business_form",
            "source_pdf_sha256": "a" * 64,
            "esign_eligibility_confirmed_at": "2026-03-28T00:00:00+00:00",
            "anchors": [{"kind": "signature", "page": 1, "rect": {"x": 1, "y": 1, "width": 10, "height": 10}}],
            "owner_review_confirmed_at": None,
            "invalidation_reason": None,
        },
    )()

    with pytest.raises(ValueError):
        signing_service.validate_signing_sendable_record(record, owner_review_confirmed=False)

    signing_service.validate_signing_sendable_record(record, owner_review_confirmed=True)


def test_validate_signing_sendable_record_blocks_legacy_consumer_drafts_without_specific_disclosures() -> None:
    record = type(
        "SigningRecord",
        (),
        {
            "status": signing_service.SIGNING_STATUS_DRAFT,
            "mode": signing_service.SIGNING_MODE_SIGN,
            "signature_mode": signing_service.SIGNATURE_MODE_CONSUMER,
            "document_category": "authorization_consent_form",
            "source_pdf_sha256": "a" * 64,
            "esign_eligibility_confirmed_at": "2026-03-28T00:00:00+00:00",
            "sender_display_name": "Owner Example",
            "sender_email": "owner@example.com",
            "sender_contact_email": "owner@example.com",
            "consumer_paper_copy_procedure": None,
            "consumer_paper_copy_fee_description": None,
            "consumer_withdrawal_procedure": None,
            "consumer_withdrawal_consequences": None,
            "consumer_contact_update_procedure": None,
            "consumer_consent_scope_override": None,
            "anchors": [{"kind": "signature", "page": 1, "rect": {"x": 1, "y": 1, "width": 10, "height": 10}}],
            "owner_review_confirmed_at": None,
            "invalidation_reason": None,
        },
    )()

    with pytest.raises(ValueError, match="predates the current disclosure requirements"):
        signing_service.validate_signing_sendable_record(record, owner_review_confirmed=False)


def test_validate_esign_eligibility_confirmation_requires_explicit_true() -> None:
    with pytest.raises(ValueError):
        signing_service.validate_esign_eligibility_confirmation(False)

    assert signing_service.validate_esign_eligibility_confirmation(True) is True


def test_resolve_signing_consumer_disclosure_fields_requires_request_specific_procedures() -> None:
    with pytest.raises(ValueError, match="paper-copy procedure"):
        signing_service.resolve_signing_consumer_disclosure_fields(
            signature_mode="consumer",
            sender_email="owner@example.com",
            require_complete=True,
        )


def test_resolve_signing_disclosure_payload_uses_sender_specific_consumer_details() -> None:
    payload = signing_service.resolve_signing_disclosure_payload(
        "us-esign-consumer-v1",
        request_id="req-1",
        sender_display_name="Owner Example",
        sender_email="owner@example.com",
        manual_fallback_enabled=False,
        paper_copy_procedure="Email owner@example.com to request a paper copy for this request.",
        paper_copy_fee_description="No paper-copy fee is charged.",
        withdrawal_procedure="Use withdraw-consent before completion or email owner@example.com.",
        withdrawal_consequences="Withdrawing consent ends the electronic process for this request.",
        contact_update_procedure="Email owner@example.com if your contact information changes.",
    )

    assert payload["sender"]["displayName"] == "Owner Example"
    assert payload["sender"]["contactEmail"] == "owner@example.com"
    assert payload["paperCopy"] == "Email owner@example.com to request a paper copy for this request."
    assert payload["paperOption"] is None
    assert payload["withdrawal"]["instructions"].startswith("Use withdraw-consent")
    assert payload["summaryLines"][-1] == "Paper-copy fees and charges: No paper-copy fee is charged."


def test_validate_signing_sendable_record_revalidates_document_category() -> None:
    record = type(
        "SigningRecord",
        (),
        {
            "status": signing_service.SIGNING_STATUS_DRAFT,
            "mode": signing_service.SIGNING_MODE_SIGN,
            "document_category": "court_document",
            "source_pdf_sha256": "a" * 64,
            "esign_eligibility_confirmed_at": "2026-03-28T00:00:00+00:00",
            "anchors": [{"kind": "signature", "page": 1, "rect": {"x": 1, "y": 1, "width": 10, "height": 10}}],
            "owner_review_confirmed_at": None,
            "invalidation_reason": None,
        },
    )()

    with pytest.raises(ValueError, match="blocked"):
        signing_service.validate_signing_sendable_record(record, owner_review_confirmed=False)


def test_validate_signing_reissuable_record_revalidates_document_category() -> None:
    record = type(
        "SigningRecord",
        (),
        {
            "status": signing_service.SIGNING_STATUS_SENT,
            "document_category": "court_document",
            "source_pdf_bucket_path": "gs://bucket/source.pdf",
            "esign_eligibility_confirmed_at": "2026-03-28T00:00:00+00:00",
            "public_link_revoked_at": None,
            "expires_at": None,
            "invalidation_reason": None,
        },
    )()

    with pytest.raises(ValueError, match="blocked"):
        signing_service.validate_signing_reissuable_record(record)


def test_resolve_signing_retention_days_defaults_to_seven_years() -> None:
    assert signing_service.resolve_signing_retention_days() == 2555


def test_signing_request_is_expired_uses_request_expiry_timestamp() -> None:
    record = type("SigningRecord", (), {"expires_at": "2000-01-01T00:00:00+00:00"})()

    assert signing_service.signing_request_is_expired(record) is True


def test_signing_session_bindings_normalize_public_inputs() -> None:
    assert signing_service.build_signing_session_ip_scope("8.8.8.8") == "8.8.8.0/24"
    assert signing_service.build_signing_session_ip_scope("127.0.0.1") is None
    assert signing_service.build_signing_user_agent_fingerprint("Browser/1.0") is not None


def test_resolve_signing_token_secret_reuses_fill_link_secret_in_dev(monkeypatch) -> None:
    monkeypatch.delenv("SIGNING_LINK_TOKEN_SECRET", raising=False)
    monkeypatch.setenv("FILL_LINK_TOKEN_SECRET", "stable-local-fill-link-secret")
    monkeypatch.setenv("ENV", "dev")
    monkeypatch.setattr(signing_service, "_WARNED_DEV_SIGNING_TOKEN_SECRET", False)

    assert signing_service._resolve_signing_token_secret() == "stable-local-fill-link-secret"


def test_resolve_signing_verification_policy_defaults_to_all_email_signing_sources(monkeypatch) -> None:
    monkeypatch.delenv("SIGNING_VERIFICATION_SOURCE_TYPES", raising=False)

    assert signing_service.resolve_signing_verification_policy("workspace") == (True, "email_otp")
    assert signing_service.resolve_signing_verification_policy("fill_link_response") == (True, "email_otp")
    assert signing_service.resolve_signing_verification_policy("uploaded_pdf") == (True, "email_otp")


def test_resolve_signing_verification_policy_supports_source_type_subset_and_none(monkeypatch) -> None:
    monkeypatch.setenv("SIGNING_VERIFICATION_SOURCE_TYPES", "fill_link_response")
    assert signing_service.resolve_signing_verification_policy("workspace") == (False, None)
    assert signing_service.resolve_signing_verification_policy("fill_link_response") == (True, "email_otp")

    monkeypatch.setenv("SIGNING_VERIFICATION_SOURCE_TYPES", "none")
    assert signing_service.resolve_signing_verification_policy("workspace") == (False, None)
