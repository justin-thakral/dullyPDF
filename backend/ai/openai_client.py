"""Shared OpenAI client factory with bounded timeout/retry defaults."""

from __future__ import annotations

import os

from openai import OpenAI


def _parse_float_env(name: str, default: float, *, minimum: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default
    return value if value >= minimum else default


def _parse_int_env(name: str, default: int, *, minimum: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return value if value >= minimum else default


def resolve_openai_timeout_seconds() -> float:
    """Return request timeout in seconds for OpenAI SDK calls."""
    return _parse_float_env("OPENAI_REQUEST_TIMEOUT_SECONDS", 75.0, minimum=1.0)


def resolve_openai_max_retries() -> int:
    """Return max retry count for OpenAI SDK calls."""
    return _parse_int_env("OPENAI_MAX_RETRIES", 1, minimum=0)


def resolve_openai_worker_max_retries() -> int:
    """Return max retry count for worker-side OpenAI SDK calls."""
    return _parse_int_env("OPENAI_WORKER_MAX_RETRIES", 0, minimum=0)


def create_openai_client(
    *,
    api_key: str | None = None,
    max_retries_override: int | None = None,
) -> OpenAI:
    """Create an OpenAI client with explicit timeout/retry bounds."""
    if max_retries_override is None:
        max_retries = resolve_openai_max_retries()
    else:
        try:
            max_retries = int(max_retries_override)
        except (TypeError, ValueError):
            max_retries = resolve_openai_max_retries()
        if max_retries < 0:
            max_retries = 0
    params = {
        "timeout": resolve_openai_timeout_seconds(),
        "max_retries": max_retries,
    }
    if api_key:
        params["api_key"] = api_key
    return OpenAI(**params)


__all__ = [
    "create_openai_client",
    "resolve_openai_max_retries",
    "resolve_openai_timeout_seconds",
    "resolve_openai_worker_max_retries",
]
