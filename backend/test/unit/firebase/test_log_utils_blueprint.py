"""Unit tests for `backend/firebaseDB/log_utils.py`."""

from datetime import datetime, timedelta, timezone

from backend.firebaseDB import log_utils


def test_log_ttl_seconds_parses_integer(monkeypatch) -> None:
    monkeypatch.setenv("SANDBOX_OPENAI_LOG_TTL_SECONDS", "120")
    assert log_utils.log_ttl_seconds() == 120


def test_log_ttl_seconds_invalid_value_falls_back_to_default(monkeypatch) -> None:
    monkeypatch.setenv("SANDBOX_OPENAI_LOG_TTL_SECONDS", "not-a-number")
    assert log_utils.log_ttl_seconds() == 2_592_000


def test_log_expires_at_returns_none_for_non_positive_ttl(mocker) -> None:
    mocker.patch("backend.firebaseDB.log_utils.log_ttl_seconds", return_value=0)
    assert log_utils.log_expires_at() is None


def test_log_expires_at_returns_now_plus_ttl(mocker) -> None:
    base_time = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)

    class _FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return base_time

    mocker.patch("backend.firebaseDB.log_utils.datetime", _FrozenDateTime)
    mocker.patch("backend.firebaseDB.log_utils.log_ttl_seconds", return_value=45)

    assert log_utils.log_expires_at() == base_time + timedelta(seconds=45)
