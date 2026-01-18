"""Sandbox debug flag parsing and gating helpers."""

import os
import sys

from .env_loader import bootstrap_env

bootstrap_env()

_DEBUG_FLAG_PRESENT = False
_DEBUG_ARG_INDEXES: list[int] = []

for idx, arg in enumerate(list(sys.argv)):
    if arg == "--debug" or arg.startswith("--debug="):
        _DEBUG_FLAG_PRESENT = True
        _DEBUG_ARG_INDEXES.append(idx)

for idx in sorted(_DEBUG_ARG_INDEXES, reverse=True):
    try:
        sys.argv.pop(idx)
    except IndexError:
        continue


def debug_flag_present() -> bool:
    """
    Return True when the --debug flag was provided for this process.
    """
    return _DEBUG_FLAG_PRESENT


def _resolve_debug_password() -> str:
    """
    Resolve the debug password from environment variables.

    We accept SANDBOX_DEBUG_PASSWORD first, then fall back to debugPassword for
    legacy compatibility with existing .env files.
    """
    return (os.getenv("SANDBOX_DEBUG_PASSWORD") or os.getenv("debugPassword") or "").strip()


def debug_password_valid() -> bool:
    """
    Validate the debug password from .env.

    We require a non-empty value so debug-only behavior is opt-in.
    """
    value = _resolve_debug_password()
    return bool(value)


def get_debug_password() -> str | None:
    """
    Return the debug password, if configured.
    """
    value = _resolve_debug_password()
    return value or None


def debug_enabled() -> bool:
    """
    Return True only when the debug flag is present and a password is configured.
    """
    if os.getenv("SANDBOX_DEBUG_FORCE", "").strip().lower() in {"1", "true", "yes"}:
        return debug_password_valid()
    return debug_flag_present() and debug_password_valid()
