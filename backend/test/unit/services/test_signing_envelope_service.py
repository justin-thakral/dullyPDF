"""Unit coverage for signing envelope orchestration (turn advancement)."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from backend.services import signing_envelope_service as envelope_service


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _envelope(**overrides):
    defaults = {
        "id": "env-1",
        "user_id": "user-1",
        "title": "Multi-Signer Packet",
        "mode": "sign",
        "signature_mode": "business",
        "signing_mode": "parallel",
        "signer_count": 3,
        "completed_signer_count": 0,
        "status": "sent",
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _request(**overrides):
    defaults = {
        "id": "req-1",
        "envelope_id": "env-1",
        "signer_order": 1,
        "signer_email": "alice@example.com",
        "status": "sent",
        "turn_activated_at": None,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_advance_noop_when_no_envelope_id(mocker) -> None:
    """A request without an envelope_id should not touch any DB functions."""
    increment_mock = mocker.patch.object(envelope_service, "increment_envelope_completed_count")
    get_mock = mocker.patch.object(envelope_service, "get_signing_envelope")

    envelope_service.advance_envelope_after_signer_completion(_request(envelope_id=None))

    increment_mock.assert_not_called()
    get_mock.assert_not_called()


def test_advance_noop_when_envelope_id_is_empty_string(mocker) -> None:
    """An empty-string envelope_id should also short-circuit."""
    increment_mock = mocker.patch.object(envelope_service, "increment_envelope_completed_count")

    envelope_service.advance_envelope_after_signer_completion(_request(envelope_id=""))

    increment_mock.assert_not_called()


def test_advance_parallel_not_all_done(mocker) -> None:
    """2 of 3 signers done in parallel mode -> status becomes partial."""
    mocker.patch.object(envelope_service, "increment_envelope_completed_count", return_value=2)
    mocker.patch.object(
        envelope_service,
        "get_signing_envelope",
        return_value=_envelope(signing_mode="parallel", signer_count=3, status="sent"),
    )
    update_mock = mocker.patch.object(envelope_service, "update_signing_envelope")

    envelope_service.advance_envelope_after_signer_completion(_request(signer_order=2))

    update_mock.assert_called_once_with("env-1", {"status": "partial"})


def test_advance_parallel_all_done(mocker) -> None:
    """3 of 3 signers done -> envelope marked completed."""
    mocker.patch.object(envelope_service, "increment_envelope_completed_count", return_value=3)
    mocker.patch.object(
        envelope_service,
        "get_signing_envelope",
        return_value=_envelope(signing_mode="parallel", signer_count=3),
    )
    mocker.patch.object(envelope_service, "update_signing_envelope")
    mocker.patch.object(envelope_service, "now_iso", return_value="2026-04-01T00:00:00+00:00")
    complete_mock = mocker.patch.object(envelope_service, "_complete_envelope", new=mocker.AsyncMock())

    envelope_service.advance_envelope_after_signer_completion(_request(signer_order=3))

    complete_mock.assert_called_once()


def test_advance_sequential_activates_next_signer(mocker) -> None:
    """In sequential mode, after signer 1 completes, the next signer should be activated."""
    mocker.patch.object(envelope_service, "increment_envelope_completed_count", return_value=1)
    envelope = _envelope(signing_mode="sequential", signer_count=3)
    mocker.patch.object(
        envelope_service,
        "get_signing_envelope",
        return_value=envelope,
    )
    next_req = _request(id="req-2", signer_order=2, signer_email="bob@example.com", status="sent")
    mocker.patch.object(
        envelope_service,
        "list_signing_requests_for_envelope",
        return_value=[
            _request(id="req-1", signer_order=1, turn_activated_at="2026-03-28T12:00:00+00:00"),
            next_req,
            _request(id="req-3", signer_order=3, signer_email="carol@example.com", status="sent"),
        ],
    )
    mocker.patch.object(envelope_service, "now_iso", return_value="2026-04-01T10:00:00+00:00")
    activated_req = _request(
        id="req-2",
        signer_order=2,
        signer_email="bob@example.com",
        status="sent",
        turn_activated_at="2026-04-01T10:00:00+00:00",
    )
    update_req_mock = mocker.patch.object(
        envelope_service,
        "_update_public_signing_request",
        return_value=activated_req,
    )
    update_env_mock = mocker.patch.object(envelope_service, "update_signing_envelope")

    # Mock the private helper that performs the inline import + invite delivery
    deliver_mock = mocker.patch.object(
        envelope_service,
        "_deliver_next_signer_invite",
        new=mocker.AsyncMock(),
    )

    envelope_service.advance_envelope_after_signer_completion(_request(signer_order=1))

    # Next signer's turn should be activated
    update_req_mock.assert_called_once_with(
        "req-2",
        allowed_statuses={"draft", "sent"},
        updates={"turn_activated_at": "2026-04-01T10:00:00+00:00"},
    )

    # Invite should be delivered because next signer has status "sent"
    deliver_mock.assert_awaited_once_with(envelope, activated_req)

    # Envelope should be set to partial since not all signers done
    update_env_mock.assert_called_once_with("env-1", {"status": "partial"})


def test_advance_sequential_all_done(mocker) -> None:
    """Last sequential signer completes -> envelope is completed."""
    mocker.patch.object(envelope_service, "increment_envelope_completed_count", return_value=2)
    mocker.patch.object(
        envelope_service,
        "get_signing_envelope",
        return_value=_envelope(signing_mode="sequential", signer_count=2),
    )
    mocker.patch.object(envelope_service, "update_signing_envelope")
    mocker.patch.object(envelope_service, "now_iso", return_value="2026-04-01T12:00:00+00:00")
    complete_mock = mocker.patch.object(envelope_service, "_complete_envelope", new=mocker.AsyncMock())

    envelope_service.advance_envelope_after_signer_completion(_request(signer_order=2))

    complete_mock.assert_called_once()


def test_advance_envelope_not_found(mocker) -> None:
    """If the envelope no longer exists in DB, log a warning and return."""
    mocker.patch.object(envelope_service, "increment_envelope_completed_count", return_value=1)
    mocker.patch.object(envelope_service, "get_signing_envelope", return_value=None)
    logger_mock = mocker.patch.object(envelope_service, "logger")
    update_mock = mocker.patch.object(envelope_service, "update_signing_envelope")

    envelope_service.advance_envelope_after_signer_completion(_request())

    logger_mock.warning.assert_called_once()
    assert "not found" in logger_mock.warning.call_args[0][0]
    update_mock.assert_not_called()


def test_complete_envelope_artifact_failure_leaves_envelope_partial(mocker) -> None:
    envelope = _envelope(signing_mode="parallel", signer_count=2, status="partial")
    mocker.patch.object(
        envelope_service,
        "list_signing_requests_for_envelope",
        return_value=[
            _request(id="req-1", signer_order=1, status="completed"),
            _request(id="req-2", signer_order=2, status="completed"),
        ],
    )
    mocker.patch.object(envelope_service, "now_iso", return_value="2026-04-01T12:00:00+00:00")
    mocker.patch.object(
        envelope_service,
        "_generate_envelope_artifacts",
        new=mocker.AsyncMock(side_effect=RuntimeError("boom")),
    )
    update_mock = mocker.patch.object(envelope_service, "update_signing_envelope")

    asyncio.run(envelope_service._complete_envelope(envelope))

    update_mock.assert_called_once_with(
        "env-1",
        {
            "status": "partial",
            "completed_at": None,
            "signed_pdf_bucket_path": None,
            "signed_pdf_sha256": None,
            "audit_manifest_bucket_path": None,
            "audit_manifest_sha256": None,
            "audit_receipt_bucket_path": None,
            "audit_receipt_sha256": None,
        },
    )


def test_activate_next_signer_delivers_invite(mocker) -> None:
    """When the next signer already has status 'sent', their invite should be delivered."""
    mocker.patch.object(envelope_service, "increment_envelope_completed_count", return_value=1)
    envelope = _envelope(signing_mode="sequential", signer_count=2)
    mocker.patch.object(
        envelope_service,
        "get_signing_envelope",
        return_value=envelope,
    )
    next_req = _request(id="req-2", signer_order=2, signer_email="bob@example.com", status="sent")
    mocker.patch.object(
        envelope_service,
        "list_signing_requests_for_envelope",
        return_value=[
            _request(id="req-1", signer_order=1, turn_activated_at="2026-03-28T12:00:00+00:00"),
            next_req,
        ],
    )
    mocker.patch.object(envelope_service, "now_iso", return_value="2026-04-01T10:00:00+00:00")
    activated_req = _request(
        id="req-2",
        signer_order=2,
        signer_email="bob@example.com",
        status="sent",
        turn_activated_at="2026-04-01T10:00:00+00:00",
    )
    mocker.patch.object(
        envelope_service,
        "_update_public_signing_request",
        return_value=activated_req,
    )
    mocker.patch.object(envelope_service, "update_signing_envelope")

    deliver_mock = mocker.patch.object(
        envelope_service,
        "_deliver_next_signer_invite",
        new=mocker.AsyncMock(),
    )

    envelope_service.advance_envelope_after_signer_completion(_request(signer_order=1))

    deliver_mock.assert_awaited_once_with(envelope, activated_req)


def test_activate_next_signer_skips_draft(mocker) -> None:
    """When the next signer is still in 'draft' status, log info but don't deliver invite."""
    mocker.patch.object(envelope_service, "increment_envelope_completed_count", return_value=1)
    mocker.patch.object(
        envelope_service,
        "get_signing_envelope",
        return_value=_envelope(signing_mode="sequential", signer_count=2),
    )
    draft_req = _request(id="req-2", signer_order=2, signer_email="bob@example.com", status="draft")
    mocker.patch.object(
        envelope_service,
        "list_signing_requests_for_envelope",
        return_value=[
            _request(id="req-1", signer_order=1, turn_activated_at="2026-03-28T12:00:00+00:00"),
            draft_req,
        ],
    )
    mocker.patch.object(envelope_service, "now_iso", return_value="2026-04-01T10:00:00+00:00")
    activated_draft_req = _request(
        id="req-2",
        signer_order=2,
        signer_email="bob@example.com",
        status="draft",
        turn_activated_at="2026-04-01T10:00:00+00:00",
    )
    mocker.patch.object(
        envelope_service,
        "_update_public_signing_request",
        return_value=activated_draft_req,
    )
    mocker.patch.object(envelope_service, "update_signing_envelope")
    logger_mock = mocker.patch.object(envelope_service, "logger")

    deliver_mock = mocker.patch.object(
        envelope_service,
        "_deliver_next_signer_invite",
        new=mocker.AsyncMock(),
    )

    envelope_service.advance_envelope_after_signer_completion(_request(signer_order=1))

    deliver_mock.assert_not_awaited()
    logger_mock.info.assert_called()
    # Verify the log message mentions "draft"
    info_messages = [call[0][0] for call in logger_mock.info.call_args_list]
    assert any("draft" in msg for msg in info_messages)
