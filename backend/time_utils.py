"""Shared timestamp helpers."""

from datetime import datetime, timezone


def now_iso() -> str:
    """Return an ISO-8601 timestamp in UTC."""
    return datetime.now(timezone.utc).isoformat()
