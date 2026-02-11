"""Role and tier-based limits."""

from __future__ import annotations

from typing import Dict, Optional

from backend.env_utils import int_env as _int_env
from backend.firebaseDB.app_database import ROLE_GOD, normalize_role


def resolve_detect_max_pages(role: Optional[str]) -> int:
    normalized = normalize_role(role)
    if normalized == ROLE_GOD:
        return max(1, _int_env("SANDBOX_DETECT_MAX_PAGES_GOD", 100))
    return max(1, _int_env("SANDBOX_DETECT_MAX_PAGES_BASE", 5))


def resolve_fillable_max_pages(role: Optional[str]) -> int:
    normalized = normalize_role(role)
    if normalized == ROLE_GOD:
        return max(1, _int_env("SANDBOX_FILLABLE_MAX_PAGES_GOD", 1000))
    return max(1, _int_env("SANDBOX_FILLABLE_MAX_PAGES_BASE", 50))


def resolve_saved_forms_limit(role: Optional[str]) -> int:
    normalized = normalize_role(role)
    if normalized == ROLE_GOD:
        return max(1, _int_env("SANDBOX_SAVED_FORMS_MAX_GOD", 20))
    return max(1, _int_env("SANDBOX_SAVED_FORMS_MAX_BASE", 3))


def resolve_role_limits(role: Optional[str]) -> Dict[str, int]:
    return {
        "detectMaxPages": resolve_detect_max_pages(role),
        "fillableMaxPages": resolve_fillable_max_pages(role),
        "savedFormsMax": resolve_saved_forms_limit(role),
    }
