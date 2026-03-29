from __future__ import annotations

import pytest

from backend.firebaseDB import signing_database
from backend.services.signing_quota_service import SigningRequestMonthlyLimitError
from backend.test.unit.firebase._fakes import FakeFirestoreClient


def _create_session(firestore_client: FakeFirestoreClient):
    return signing_database.create_signing_session(
        "req-1",
        link_token_id="link-token-1",
        client_ip="203.0.113.5",
        user_agent="browser/1.0",
        binding_ip_scope="203.0.113.0/24",
        binding_user_agent_hash="ua-hash-1",
        expires_at="2026-03-24T13:00:00+00:00",
        client=firestore_client,
    )


def test_set_signing_session_verification_challenge_stores_ephemeral_otp_state() -> None:
    firestore_client = FakeFirestoreClient()
    session = _create_session(firestore_client)

    updated_session = signing_database.set_signing_session_verification_challenge(
        session.id,
        "req-1",
        code_hash="otp-hash-1",
        sent_at="2026-03-24T12:03:00+00:00",
        expires_at="2026-03-24T12:13:00+00:00",
        verification_message_id="gmail-message-1",
        client=firestore_client,
    )

    assert updated_session is not None
    assert updated_session.verification_code_hash == "otp-hash-1"
    assert updated_session.verification_sent_at == "2026-03-24T12:03:00+00:00"
    assert updated_session.verification_expires_at == "2026-03-24T12:13:00+00:00"
    assert updated_session.verification_attempt_count == 0
    assert updated_session.verification_resend_count == 1
    assert updated_session.verification_completed_at is None
    assert updated_session.verification_message_id == "gmail-message-1"
    assert updated_session.consumer_access_attempt_count == 0


def test_increment_signing_session_verification_attempt_counts_failed_codes() -> None:
    firestore_client = FakeFirestoreClient()
    session = _create_session(firestore_client)
    signing_database.set_signing_session_verification_challenge(
        session.id,
        "req-1",
        code_hash="otp-hash-1",
        sent_at="2026-03-24T12:03:00+00:00",
        expires_at="2026-03-24T12:13:00+00:00",
        client=firestore_client,
    )

    once = signing_database.increment_signing_session_verification_attempt(session.id, "req-1", client=firestore_client)
    twice = signing_database.increment_signing_session_verification_attempt(session.id, "req-1", client=firestore_client)

    assert once is not None
    assert twice is not None
    assert once.verification_attempt_count == 1
    assert twice.verification_attempt_count == 2

def test_mark_signing_request_sent_consumes_monthly_quota_and_rollback_restores_it(mocker) -> None:
    firestore_client = FakeFirestoreClient()
    request = signing_database.create_signing_request(
        user_id="user-1",
        title="Bravo Packet Signature Request",
        mode="sign",
        signature_mode="business",
        source_type="workspace",
        source_id="form-alpha",
        source_link_id=None,
        source_record_label=None,
        source_document_name="Bravo Packet",
        source_template_id="form-alpha",
        source_template_name="Bravo Packet",
        source_pdf_sha256="a" * 64,
        source_version="workspace:form-alpha:hash-one",
        document_category="ordinary_business_form",
        company_binding_enabled=False,
        authority_attestation_version=None,
        authority_attestation_text=None,
        authority_attestation_sha256=None,
        manual_fallback_enabled=True,
        signer_name="Alex Signer",
        signer_email="alex@example.com",
        anchors=[],
        disclosure_version="us-esign-business-v1",
        client=firestore_client,
    )
    mocker.patch.object(signing_database, "now_iso", return_value="2026-03-24T12:00:00+00:00")
    mocker.patch.object(signing_database, "_current_month_key", return_value="2026-03")

    sent = signing_database.mark_signing_request_sent(
        request.id,
        "user-1",
        source_pdf_bucket_path="gs://signing-bucket/requests/source.pdf",
        source_pdf_sha256="b" * 64,
        source_version="workspace:form-alpha:hash-two",
        monthly_limit=25,
        client=firestore_client,
    )

    assert sent is not None
    assert sent.status == signing_database.SIGNING_STATUS_SENT
    assert sent.quota_consumed_at == "2026-03-24T12:00:00+00:00"
    assert sent.quota_month_key == "2026-03"
    usage = signing_database.get_signing_monthly_usage("user-1", month_key="2026-03", client=firestore_client)
    assert usage is not None
    assert usage.request_count == 1

    rolled_back = signing_database.rollback_signing_request_sent(
        request.id,
        "user-1",
        expected_source_pdf_bucket_path="gs://signing-bucket/requests/source.pdf",
        expected_source_pdf_sha256="b" * 64,
        client=firestore_client,
    )

    assert rolled_back is not None
    assert rolled_back.status == signing_database.SIGNING_STATUS_DRAFT
    assert rolled_back.sent_at is None
    assert rolled_back.quota_consumed_at is None
    assert rolled_back.quota_month_key is None
    usage_after_rollback = signing_database.get_signing_monthly_usage("user-1", month_key="2026-03", client=firestore_client)
    assert usage_after_rollback is not None
    assert usage_after_rollback.request_count == 0


def test_mark_signing_request_sent_blocks_when_monthly_quota_is_exhausted(mocker) -> None:
    firestore_client = FakeFirestoreClient()
    request = signing_database.create_signing_request(
        user_id="user-1",
        title="Bravo Packet Signature Request",
        mode="sign",
        signature_mode="business",
        source_type="workspace",
        source_id="form-alpha",
        source_link_id=None,
        source_record_label=None,
        source_document_name="Bravo Packet",
        source_template_id="form-alpha",
        source_template_name="Bravo Packet",
        source_pdf_sha256="a" * 64,
        source_version="workspace:form-alpha:hash-one",
        document_category="ordinary_business_form",
        company_binding_enabled=False,
        authority_attestation_version=None,
        authority_attestation_text=None,
        authority_attestation_sha256=None,
        manual_fallback_enabled=True,
        signer_name="Alex Signer",
        signer_email="alex@example.com",
        anchors=[],
        disclosure_version="us-esign-business-v1",
        client=firestore_client,
    )
    firestore_client.collection(signing_database.SIGNING_USAGE_COUNTERS_COLLECTION).document("user-1__2026-03").set(
        {
            "user_id": "user-1",
            "month_key": "2026-03",
            "request_count": 25,
            "created_at": "2026-03-01T00:00:00+00:00",
            "updated_at": "2026-03-24T11:59:00+00:00",
        }
    )
    mocker.patch.object(signing_database, "_current_month_key", return_value="2026-03")

    with pytest.raises(SigningRequestMonthlyLimitError, match="25 sent signing request limit"):
        signing_database.mark_signing_request_sent(
            request.id,
            "user-1",
            source_pdf_bucket_path="gs://signing-bucket/requests/source.pdf",
            source_pdf_sha256="b" * 64,
            source_version="workspace:form-alpha:hash-two",
            monthly_limit=25,
            client=firestore_client,
        )


def test_mark_signing_request_sent_is_idempotent_for_existing_sent_request(mocker) -> None:
    firestore_client = FakeFirestoreClient()
    request = signing_database.create_signing_request(
        user_id="user-1",
        title="Bravo Packet Signature Request",
        mode="sign",
        signature_mode="business",
        source_type="workspace",
        source_id="form-alpha",
        source_link_id=None,
        source_record_label=None,
        source_document_name="Bravo Packet",
        source_template_id="form-alpha",
        source_template_name="Bravo Packet",
        source_pdf_sha256="a" * 64,
        source_version="workspace:form-alpha:hash-one",
        document_category="ordinary_business_form",
        company_binding_enabled=False,
        authority_attestation_version=None,
        authority_attestation_text=None,
        authority_attestation_sha256=None,
        manual_fallback_enabled=True,
        signer_name="Alex Signer",
        signer_email="alex@example.com",
        anchors=[],
        disclosure_version="us-esign-business-v1",
        client=firestore_client,
    )
    mocker.patch.object(signing_database, "now_iso", return_value="2026-03-24T12:00:00+00:00")
    mocker.patch.object(signing_database, "_current_month_key", return_value="2026-03")

    first = signing_database.mark_signing_request_sent(
        request.id,
        "user-1",
        source_pdf_bucket_path="gs://signing-bucket/requests/source.pdf",
        source_pdf_sha256="b" * 64,
        source_version="workspace:form-alpha:hash-two",
        monthly_limit=25,
        client=firestore_client,
    )
    second = signing_database.mark_signing_request_sent(
        request.id,
        "user-1",
        source_pdf_bucket_path="gs://signing-bucket/requests/source.pdf",
        source_pdf_sha256="b" * 64,
        source_version="workspace:form-alpha:hash-two",
        monthly_limit=25,
        client=firestore_client,
    )

    assert first is not None
    assert second is not None
    assert first.status == signing_database.SIGNING_STATUS_SENT
    assert second.status == signing_database.SIGNING_STATUS_SENT
    usage = signing_database.get_signing_monthly_usage("user-1", month_key="2026-03", client=firestore_client)
    assert usage is not None
    assert usage.request_count == 1


def test_consumer_access_attempt_counter_tracks_failed_codes_and_can_reset() -> None:
    firestore_client = FakeFirestoreClient()
    session = _create_session(firestore_client)

    once = signing_database.increment_signing_session_consumer_access_attempt(
        session.id,
        "req-1",
        client=firestore_client,
    )
    twice = signing_database.increment_signing_session_consumer_access_attempt(
        session.id,
        "req-1",
        client=firestore_client,
    )
    reset = signing_database.reset_signing_session_consumer_access_attempts(
        session.id,
        "req-1",
        client=firestore_client,
    )

    assert once is not None
    assert twice is not None
    assert reset is not None
    assert once.consumer_access_attempt_count == 1
    assert twice.consumer_access_attempt_count == 2
    assert reset.consumer_access_attempt_count == 0


def test_mark_signing_session_verified_clears_ephemeral_otp_fields_and_updates_request() -> None:
    firestore_client = FakeFirestoreClient()
    firestore_client.collection(signing_database.SIGNING_REQUESTS_COLLECTION).document("req-1").set(
        {
            "user_id": "user-1",
            "mode": "sign",
            "signature_mode": "business",
            "source_type": "workspace",
            "source_document_name": "Bravo Packet",
            "document_category": "ordinary_business_form",
            "manual_fallback_enabled": True,
            "signer_name": "Alex Signer",
            "signer_email": "alex@example.com",
            "status": signing_database.SIGNING_STATUS_SENT,
            "anchors": [],
            "disclosure_version": "us-esign-business-v1",
            "verification_required": True,
            "verification_method": "email_otp",
            "verification_completed_at": None,
            "created_at": "2026-03-24T12:00:00+00:00",
            "updated_at": "2026-03-24T12:00:00+00:00",
        }
    )
    session = _create_session(firestore_client)
    signing_database.set_signing_session_verification_challenge(
        session.id,
        "req-1",
        code_hash="otp-hash-1",
        sent_at="2026-03-24T12:03:00+00:00",
        expires_at="2026-03-24T12:13:00+00:00",
        verification_message_id="gmail-message-1",
        client=firestore_client,
    )
    signing_database.increment_signing_session_verification_attempt(session.id, "req-1", client=firestore_client)

    verified_session = signing_database.mark_signing_session_verified(
        session.id,
        "req-1",
        verification_method="email_otp",
        verified_at="2026-03-24T12:04:30+00:00",
        client=firestore_client,
    )

    assert verified_session is not None
    assert verified_session.verification_code_hash is None
    assert verified_session.verification_sent_at is None
    assert verified_session.verification_expires_at is None
    assert verified_session.verification_attempt_count == 0
    assert verified_session.verification_resend_count == 0
    assert verified_session.verification_completed_at == "2026-03-24T12:04:30+00:00"
    assert verified_session.verification_message_id is None

    request_record = signing_database.get_signing_request("req-1", client=firestore_client)
    assert request_record is not None
    assert request_record.verification_method == "email_otp"
    assert request_record.verification_completed_at == "2026-03-24T12:04:30+00:00"
