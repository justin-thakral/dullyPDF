"""Unit coverage for signing helpers."""

from __future__ import annotations

import pytest

from backend.services import signing_service


def test_signing_public_token_round_trip(mocker) -> None:
    mocker.patch.object(signing_service, "_resolve_signing_token_secret", return_value="x" * 48)

    token = signing_service.build_signing_public_token("request-123")

    assert signing_service.parse_signing_public_token(token) == "request-123"


def test_signing_public_session_token_round_trip(mocker) -> None:
    mocker.patch.object(signing_service, "_resolve_signing_token_secret", return_value="x" * 48)
    mocker.patch.object(signing_service.time, "time", return_value=1000)

    token = signing_service.build_signing_public_session_token("request-123", "session-456", 1300)

    assert signing_service.parse_signing_public_session_token(token) == ("request-123", "session-456", 1300)


def test_validate_document_category_blocks_excluded_categories() -> None:
    with pytest.raises(ValueError):
        signing_service.validate_document_category("court_document")


def test_resolve_signing_disclosure_version_distinguishes_consumer_mode() -> None:
    assert signing_service.resolve_signing_disclosure_version("business") == "us-esign-business-v1"
    assert signing_service.resolve_signing_disclosure_version("consumer") == "us-esign-consumer-v1"


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


def test_validate_signing_sendable_record_requires_owner_review_for_fill_and_sign() -> None:
    record = type(
        "SigningRecord",
        (),
        {
            "status": signing_service.SIGNING_STATUS_DRAFT,
            "mode": signing_service.SIGNING_MODE_FILL_AND_SIGN,
            "source_pdf_sha256": "a" * 64,
            "anchors": [{"kind": "signature", "page": 1, "rect": {"x": 1, "y": 1, "width": 10, "height": 10}}],
            "owner_review_confirmed_at": None,
            "invalidation_reason": None,
        },
    )()

    with pytest.raises(ValueError):
        signing_service.validate_signing_sendable_record(record, owner_review_confirmed=False)

    signing_service.validate_signing_sendable_record(record, owner_review_confirmed=True)


def test_resolve_signing_retention_days_defaults_to_seven_years() -> None:
    assert signing_service.resolve_signing_retention_days() == 2555
