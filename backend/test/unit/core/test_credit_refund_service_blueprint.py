"""Unit tests for backend.services.credit_refund_service."""

from __future__ import annotations

import backend.services.credit_refund_service as credit_refund_service


def test_attempt_credit_refund_success_path_calls_user_refund_once(monkeypatch, mocker) -> None:
    monkeypatch.setenv("OPENAI_CREDIT_REFUND_MAX_ATTEMPTS", "3")
    monkeypatch.setenv("OPENAI_CREDIT_REFUND_RETRY_BACKOFF_MS", "1")
    refund_mock = mocker.patch.object(credit_refund_service, "refund_openai_credits", return_value=12)
    record_mock = mocker.patch.object(credit_refund_service, "record_credit_refund_failure", return_value="rec-1")

    success = credit_refund_service.attempt_credit_refund(
        user_id="user-1",
        role="base",
        credits=2,
        source="rename.sync_openai",
        request_id="req-1",
    )

    assert success is True
    refund_mock.assert_called_once_with("user-1", credits=2, role="base")
    record_mock.assert_not_called()


def test_attempt_credit_refund_retries_then_succeeds(monkeypatch, mocker) -> None:
    monkeypatch.setenv("OPENAI_CREDIT_REFUND_MAX_ATTEMPTS", "3")
    monkeypatch.setenv("OPENAI_CREDIT_REFUND_RETRY_BACKOFF_MS", "0")
    sleep_mock = mocker.patch.object(credit_refund_service.time, "sleep", return_value=None)
    refund_mock = mocker.patch.object(
        credit_refund_service,
        "refund_openai_credits",
        side_effect=[RuntimeError("transient"), 10],
    )
    record_mock = mocker.patch.object(credit_refund_service, "record_credit_refund_failure", return_value="rec-1")

    success = credit_refund_service.attempt_credit_refund(
        user_id="user-1",
        role="base",
        credits=1,
        source="rename.sync_openai",
        request_id="req-1",
    )

    assert success is True
    assert refund_mock.call_count == 2
    sleep_mock.assert_not_called()
    record_mock.assert_not_called()


def test_attempt_credit_refund_records_reconciliation_after_exhausting_retries(monkeypatch, mocker) -> None:
    monkeypatch.setenv("OPENAI_CREDIT_REFUND_MAX_ATTEMPTS", "3")
    monkeypatch.setenv("OPENAI_CREDIT_REFUND_RETRY_BACKOFF_MS", "1")
    sleep_mock = mocker.patch.object(credit_refund_service.time, "sleep", return_value=None)
    refund_mock = mocker.patch.object(
        credit_refund_service,
        "refund_openai_credits",
        side_effect=RuntimeError("firestore down"),
    )
    record_mock = mocker.patch.object(credit_refund_service, "record_credit_refund_failure", return_value="rec-1")

    success = credit_refund_service.attempt_credit_refund(
        user_id="user-1",
        role="base",
        credits=3,
        source="remap.sync_openai",
        request_id="req-2",
        job_id="job-2",
    )

    assert success is False
    assert refund_mock.call_count == 3
    assert sleep_mock.call_count == 2
    record_mock.assert_called_once()
    record_kwargs = record_mock.call_args.kwargs
    assert record_kwargs["user_id"] == "user-1"
    assert record_kwargs["credits"] == 3
    assert record_kwargs["source"] == "remap.sync_openai"
    assert record_kwargs["request_id"] == "req-2"
    assert record_kwargs["job_id"] == "job-2"
    assert record_kwargs["attempts"] == 3


def test_attempt_credit_refund_passes_breakdown_for_pro_users(monkeypatch, mocker) -> None:
    monkeypatch.setenv("OPENAI_CREDIT_REFUND_MAX_ATTEMPTS", "1")
    monkeypatch.setenv("OPENAI_CREDIT_REFUND_RETRY_BACKOFF_MS", "1")
    refund_mock = mocker.patch.object(credit_refund_service, "refund_openai_credits", return_value=50)
    mocker.patch.object(credit_refund_service, "record_credit_refund_failure", return_value="rec-1")

    success = credit_refund_service.attempt_credit_refund(
        user_id="user-1",
        role="pro",
        credits=4,
        source="rename.worker",
        credit_breakdown={"monthly": 2, "refill": 2},
    )

    assert success is True
    refund_mock.assert_called_once_with(
        "user-1",
        credits=4,
        role="pro",
        credit_breakdown={"base": 0, "monthly": 2, "refill": 2},
    )
