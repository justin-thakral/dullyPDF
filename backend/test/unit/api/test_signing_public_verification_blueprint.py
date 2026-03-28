from __future__ import annotations

from types import SimpleNamespace

from backend.services.signing_verification_service import SigningVerificationDeliveryResult


def _record(**overrides):
    payload = {
        "id": "req-1",
        "signer_email": "alex@example.com",
        "signer_name": "Alex Signer",
        "source_document_name": "Bravo Packet",
        "sender_email": "owner@example.com",
    }
    payload.update(overrides)
    return SimpleNamespace(**payload)


def _session(**overrides):
    payload = {
        "id": "session-1",
        "link_token_id": "link-token-1",
        "verification_sent_at": None,
        "verification_code_hash": "stored-hash",
        "verification_expires_at": "2026-03-24T12:13:00+00:00",
        "verification_attempt_count": 0,
        "verification_completed_at": None,
        "consumer_access_attempt_count": 0,
    }
    payload.update(overrides)
    return SimpleNamespace(**payload)


def test_public_signing_verification_send_issues_email_otp_challenge(client, app_main, mocker) -> None:
    record = _record()
    session = _session(verification_code_hash=None, verification_expires_at=None)
    updated_session = _session()
    delivery = SigningVerificationDeliveryResult(
        delivery_status="sent",
        attempted_at="2026-03-24T12:03:00+00:00",
        sent_at="2026-03-24T12:03:05+00:00",
        message_id="gmail-message-1",
    )

    mocker.patch.object(app_main, "_check_public_rate_limits", return_value=True)
    mocker.patch.object(
        app_main,
        "_require_public_signing_session",
        return_value=(record, session, "203.0.113.5", "browser/1.0"),
    )
    mocker.patch.object(app_main, "signing_record_requires_verification", return_value=True)
    mocker.patch.object(app_main, "session_has_public_signing_email_verification", return_value=False)
    mocker.patch.object(app_main, "generate_signing_email_otp_code", return_value="123456")
    send_mock = mocker.patch.object(
        app_main,
        "send_signing_verification_email",
        mocker.AsyncMock(return_value=delivery),
    )
    hash_mock = mocker.patch.object(app_main, "build_signing_email_otp_hash", return_value="otp-hash-1")
    challenge_mock = mocker.patch.object(
        app_main,
        "set_signing_session_verification_challenge",
        return_value=updated_session,
    )
    event_mock = mocker.patch.object(app_main, "record_signing_event")
    mocker.patch.object(app_main, "_serialize_public_request", return_value={"id": "req-1"})
    mocker.patch.object(
        app_main,
        "serialize_public_signing_session",
        side_effect=lambda current_session, *, session_token: {
            "id": current_session.id,
            "token": session_token,
        },
    )

    response = client.post(
        "/api/signing/public/token-1/verification/send",
        headers={"X-Signing-Session": "session-token-1"},
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    send_mock.assert_awaited_once()
    assert send_mock.await_args.kwargs["sender_email"] == "owner@example.com"
    hash_mock.assert_called_once_with("session-1", "123456")
    challenge_mock.assert_called_once()
    assert challenge_mock.call_args.kwargs["code_hash"] == "otp-hash-1"
    assert challenge_mock.call_args.kwargs["verification_message_id"] == "gmail-message-1"
    assert event_mock.call_args.kwargs["event_type"] == app_main.SIGNING_EVENT_VERIFICATION_STARTED


def test_public_signing_verification_verify_rejects_expired_code(client, app_main, mocker) -> None:
    record = _record()
    session = _session(verification_expires_at="2000-01-01T00:00:00+00:00")

    mocker.patch.object(app_main, "_check_public_rate_limits", return_value=True)
    mocker.patch.object(
        app_main,
        "_require_public_signing_session",
        return_value=(record, session, "203.0.113.5", "browser/1.0"),
    )
    mocker.patch.object(app_main, "signing_record_requires_verification", return_value=True)

    response = client.post(
        "/api/signing/public/token-1/verification/verify",
        headers={"X-Signing-Session": "session-token-1"},
        json={"code": "123456"},
    )

    assert response.status_code == 409
    assert "request a new verification code" in response.json()["detail"].lower()


def test_public_signing_verification_verify_throttles_after_max_failed_attempts(client, app_main, mocker) -> None:
    record = _record()
    session = _session(verification_attempt_count=5)

    mocker.patch.object(app_main, "_check_public_rate_limits", return_value=True)
    mocker.patch.object(
        app_main,
        "_require_public_signing_session",
        return_value=(record, session, "203.0.113.5", "browser/1.0"),
    )
    mocker.patch.object(app_main, "signing_record_requires_verification", return_value=True)
    mocker.patch.object(app_main, "resolve_signing_verification_max_attempts", return_value=5)

    response = client.post(
        "/api/signing/public/token-1/verification/verify",
        headers={"X-Signing-Session": "session-token-1"},
        json={"code": "123456"},
    )

    assert response.status_code == 429
    assert "too many failed verification attempts" in response.json()["detail"].lower()


def test_public_signing_verification_verify_records_failed_attempt_and_remaining_budget(client, app_main, mocker) -> None:
    record = _record()
    session = _session(verification_attempt_count=1, verification_expires_at="2099-01-01T00:00:00+00:00")
    updated_session = _session(verification_attempt_count=2, verification_expires_at="2099-01-01T00:00:00+00:00")

    mocker.patch.object(app_main, "_check_public_rate_limits", return_value=True)
    mocker.patch.object(
        app_main,
        "_require_public_signing_session",
        return_value=(record, session, "203.0.113.5", "browser/1.0"),
    )
    mocker.patch.object(app_main, "signing_record_requires_verification", return_value=True)
    mocker.patch.object(app_main, "resolve_signing_verification_max_attempts", return_value=5)
    mocker.patch.object(app_main, "build_signing_email_otp_hash", return_value="wrong-hash")
    increment_mock = mocker.patch.object(
        app_main,
        "increment_signing_session_verification_attempt",
        return_value=updated_session,
    )
    event_mock = mocker.patch.object(app_main, "record_signing_event")

    response = client.post(
        "/api/signing/public/token-1/verification/verify",
        headers={"X-Signing-Session": "session-token-1"},
        json={"code": "123456"},
    )

    assert response.status_code == 400
    assert "invalid" in response.json()["detail"].lower()
    increment_mock.assert_called_once_with("session-1", "req-1")
    assert event_mock.call_args.kwargs["event_type"] == app_main.SIGNING_EVENT_VERIFICATION_FAILED
    assert event_mock.call_args.kwargs["details"]["attemptCount"] == 2
    assert event_mock.call_args.kwargs["details"]["attemptsRemaining"] == 3


def test_public_signing_consumer_consent_records_failed_access_code_attempt_and_remaining_budget(client, app_main, mocker) -> None:
    record = _record(signature_mode="consumer")
    session = _session(consumer_access_attempt_count=1)
    updated_session = _session(consumer_access_attempt_count=2)

    rate_limit_mock = mocker.patch.object(app_main, "_check_public_rate_limits", return_value=True)
    mocker.patch.object(
        app_main,
        "_require_public_signing_session",
        return_value=(record, session, "203.0.113.5", "browser/1.0"),
    )
    mocker.patch.object(app_main, "_require_public_signing_session_verified", return_value=None)
    mocker.patch.object(app_main, "resolve_signing_consumer_access_max_attempts", return_value=5)
    mocker.patch.object(app_main, "build_signing_consumer_access_code", return_value="ABC123")
    increment_mock = mocker.patch.object(
        app_main,
        "increment_signing_session_consumer_access_attempt",
        return_value=updated_session,
    )
    event_mock = mocker.patch.object(app_main, "record_signing_event")

    response = client.post(
        "/api/signing/public/token-1/consent",
        headers={"X-Signing-Session": "session-token-1"},
        json={"accepted": True, "accessCode": "WRONG1"},
    )

    assert response.status_code == 400
    assert "enter the 6-character access code" in response.json()["detail"].lower()
    assert rate_limit_mock.call_args.kwargs["scope"] == "signing_consumer_access_verify"
    increment_mock.assert_called_once_with("session-1", "req-1")
    assert event_mock.call_args.kwargs["event_type"] == app_main.SIGNING_EVENT_CONSUMER_ACCESS_FAILED
    assert event_mock.call_args.kwargs["details"]["attemptCount"] == 2
    assert event_mock.call_args.kwargs["details"]["attemptsRemaining"] == 3


def test_public_signing_consumer_consent_throttles_after_max_failed_access_code_attempts(client, app_main, mocker) -> None:
    record = _record(signature_mode="consumer")
    session = _session(consumer_access_attempt_count=5)

    mocker.patch.object(app_main, "_check_public_rate_limits", return_value=True)
    mocker.patch.object(
        app_main,
        "_require_public_signing_session",
        return_value=(record, session, "203.0.113.5", "browser/1.0"),
    )
    mocker.patch.object(app_main, "_require_public_signing_session_verified", return_value=None)
    mocker.patch.object(app_main, "resolve_signing_consumer_access_max_attempts", return_value=5)

    response = client.post(
        "/api/signing/public/token-1/consent",
        headers={"X-Signing-Session": "session-token-1"},
        json={"accepted": True, "accessCode": "ABC123"},
    )

    assert response.status_code == 429
    assert "failed consumer access code attempts" in response.json()["detail"].lower()
