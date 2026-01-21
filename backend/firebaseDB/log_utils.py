"""Shared helpers for log retention timestamps."""

from datetime import datetime, timedelta, timezone
import os
from typing import Optional

from ..time_utils import now_iso


def log_ttl_seconds() -> int:
    raw = os.getenv("SANDBOX_OPENAI_LOG_TTL_SECONDS", "2592000").strip()
    try:
        return int(raw)
    except ValueError:
        return 2592000


def log_expires_at() -> Optional[datetime]:
    ttl_seconds = log_ttl_seconds()
    if ttl_seconds <= 0:
        return None
    return datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)


__all__ = ["log_ttl_seconds", "log_expires_at", "now_iso"]
