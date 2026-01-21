"""Environment variable helpers."""

import os


def env_value(name: str) -> str:
    """Return a trimmed environment variable or empty string."""
    return (os.getenv(name) or "").strip()


def env_truthy(name: str) -> bool:
    """Return True for common truthy env values."""
    return env_value(name).lower() in {"1", "true", "yes"}


def int_env(name: str, default: int) -> int:
    """Parse an int from env with a fallback default."""
    raw = env_value(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default
