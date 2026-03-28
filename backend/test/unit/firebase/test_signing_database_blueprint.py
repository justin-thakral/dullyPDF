from __future__ import annotations

from backend.firebaseDB import signing_database
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


def test_count_signing_request_limit_usage_for_source_version_counts_reserved_slots_only() -> None:
    firestore_client = FakeFirestoreClient()
    collection = firestore_client.collection(signing_database.SIGNING_REQUESTS_COLLECTION)
    collection.document("draft-1").set(
        {
            "user_id": "user-1",
            "mode": "sign",
            "signature_mode": "business",
            "source_type": "workspace",
            "source_document_name": "Bravo Packet",
            "source_version": "workspace:form-alpha:hash-one",
            "document_category": "ordinary_business_form",
            "manual_fallback_enabled": True,
            "signer_name": "Alex Signer",
            "signer_email": "alex@example.com",
            "status": signing_database.SIGNING_STATUS_DRAFT,
            "sent_at": None,
            "anchors": [],
            "disclosure_version": "us-esign-business-v1",
            "created_at": "2026-03-24T12:00:00+00:00",
            "updated_at": "2026-03-24T12:00:00+00:00",
        }
    )
    collection.document("sent-1").set(
        {
            "user_id": "user-1",
            "mode": "sign",
            "signature_mode": "business",
            "source_type": "workspace",
            "source_document_name": "Bravo Packet",
            "source_version": "workspace:form-alpha:hash-one",
            "document_category": "ordinary_business_form",
            "manual_fallback_enabled": True,
            "signer_name": "Alex Signer",
            "signer_email": "alex@example.com",
            "status": signing_database.SIGNING_STATUS_INVALIDATED,
            "sent_at": "2026-03-24T12:10:00+00:00",
            "anchors": [],
            "disclosure_version": "us-esign-business-v1",
            "created_at": "2026-03-24T12:09:00+00:00",
            "updated_at": "2026-03-24T12:11:00+00:00",
        }
    )
    collection.document("invalid-draft").set(
        {
            "user_id": "user-1",
            "mode": "sign",
            "signature_mode": "business",
            "source_type": "workspace",
            "source_document_name": "Bravo Packet",
            "source_version": "workspace:form-alpha:hash-one",
            "document_category": "ordinary_business_form",
            "manual_fallback_enabled": True,
            "signer_name": "Alex Signer",
            "signer_email": "alex@example.com",
            "status": signing_database.SIGNING_STATUS_INVALIDATED,
            "sent_at": None,
            "anchors": [],
            "disclosure_version": "us-esign-business-v1",
            "created_at": "2026-03-24T12:12:00+00:00",
            "updated_at": "2026-03-24T12:12:00+00:00",
        }
    )
    collection.document("other-source").set(
        {
            "user_id": "user-1",
            "mode": "sign",
            "signature_mode": "business",
            "source_type": "workspace",
            "source_document_name": "Other Packet",
            "source_version": "workspace:form-beta:hash-two",
            "document_category": "ordinary_business_form",
            "manual_fallback_enabled": True,
            "signer_name": "Alex Signer",
            "signer_email": "alex@example.com",
            "status": signing_database.SIGNING_STATUS_SENT,
            "sent_at": "2026-03-24T12:15:00+00:00",
            "anchors": [],
            "disclosure_version": "us-esign-business-v1",
            "created_at": "2026-03-24T12:14:00+00:00",
            "updated_at": "2026-03-24T12:15:00+00:00",
        }
    )
    collection.document("other-user").set(
        {
            "user_id": "user-2",
            "mode": "sign",
            "signature_mode": "business",
            "source_type": "workspace",
            "source_document_name": "Bravo Packet",
            "source_version": "workspace:form-alpha:hash-one",
            "document_category": "ordinary_business_form",
            "manual_fallback_enabled": True,
            "signer_name": "Alex Signer",
            "signer_email": "alex@example.com",
            "status": signing_database.SIGNING_STATUS_SENT,
            "sent_at": "2026-03-24T12:20:00+00:00",
            "anchors": [],
            "disclosure_version": "us-esign-business-v1",
            "created_at": "2026-03-24T12:19:00+00:00",
            "updated_at": "2026-03-24T12:20:00+00:00",
        }
    )

    assert signing_database.count_signing_request_limit_usage_for_source_version(
        "user-1",
        "workspace:form-alpha:hash-one",
        client=firestore_client,
    ) == 2


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
