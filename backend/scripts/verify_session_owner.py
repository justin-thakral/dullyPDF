"""Verify session ownership enforcement for sessions without user_id."""

from __future__ import annotations

import sys
from typing import Callable, Tuple

from fastapi import HTTPException

from backend.firebaseDB.firebase_service import RequestUser
from backend.sessions.session_store import _require_owner


def _expect_forbidden(label: str, func: Callable[[], None]) -> Tuple[bool, str]:
    try:
        func()
    except HTTPException as exc:
        if exc.status_code != 403:
            return False, f"{label}: expected 403, got {exc.status_code}"
        return True, f"{label}: blocked as expected"
    except Exception as exc:  # pragma: no cover - sanity guard for unexpected errors
        return False, f"{label}: unexpected exception {exc.__class__.__name__}"
    return False, f"{label}: expected 403, but no exception was raised"


def _expect_allowed(label: str, func: Callable[[], None]) -> Tuple[bool, str]:
    try:
        func()
    except Exception as exc:  # pragma: no cover - should not raise
        return False, f"{label}: unexpected exception {exc.__class__.__name__}"
    return True, f"{label}: allowed as expected"


def main() -> int:
    user = RequestUser(uid="uid-1", app_user_id="user-1", email="user-1@example.com")
    other_user = RequestUser(uid="uid-2", app_user_id="user-2", email="user-2@example.com")

    checks = [
        _expect_forbidden(
            "missing user_id",
            lambda: _require_owner({"user_id": ""}, user),
        ),
        _expect_forbidden(
            "legacy session with no user_id",
            lambda: _require_owner({}, user),
        ),
        _expect_forbidden(
            "wrong owner",
            lambda: _require_owner({"user_id": other_user.app_user_id}, user),
        ),
        _expect_allowed(
            "matching owner",
            lambda: _require_owner({"user_id": user.app_user_id}, user),
        ),
    ]

    ok = True
    for passed, message in checks:
        print(message)
        ok = ok and passed

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
