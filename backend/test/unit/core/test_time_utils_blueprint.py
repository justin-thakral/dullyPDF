"""Unit tests for backend.time_utils."""

from datetime import datetime, timedelta

from backend.time_utils import now_iso


def test_now_iso_returns_parseable_utc_timestamp() -> None:
    value = now_iso()
    parsed = datetime.fromisoformat(value)

    assert isinstance(value, str)
    assert parsed.tzinfo is not None
    assert parsed.utcoffset() == timedelta(0)
