"""Role and tier-based limits."""

from __future__ import annotations

from typing import Dict, Optional

from backend.env_utils import int_env as _int_env
from backend.firebaseDB.user_database import ROLE_GOD, ROLE_PRO, normalize_role


def resolve_detect_max_pages(role: Optional[str]) -> int:
    normalized = normalize_role(role)
    if normalized == ROLE_GOD:
        return max(1, _int_env("SANDBOX_DETECT_MAX_PAGES_GOD", 100))
    if normalized == ROLE_PRO:
        return max(1, _int_env("SANDBOX_DETECT_MAX_PAGES_PRO", 100))
    return max(1, _int_env("SANDBOX_DETECT_MAX_PAGES_BASE", 5))


def resolve_fillable_max_pages(role: Optional[str]) -> int:
    normalized = normalize_role(role)
    if normalized == ROLE_GOD:
        return max(1, _int_env("SANDBOX_FILLABLE_MAX_PAGES_GOD", 1000))
    if normalized == ROLE_PRO:
        return max(1, _int_env("SANDBOX_FILLABLE_MAX_PAGES_PRO", 1000))
    return max(1, _int_env("SANDBOX_FILLABLE_MAX_PAGES_BASE", 50))


def resolve_saved_forms_limit(role: Optional[str]) -> int:
    normalized = normalize_role(role)
    if normalized == ROLE_GOD:
        return max(1, _int_env("SANDBOX_SAVED_FORMS_MAX_GOD", 20))
    if normalized == ROLE_PRO:
        return max(1, _int_env("SANDBOX_SAVED_FORMS_MAX_PRO", 20))
    return max(1, _int_env("SANDBOX_SAVED_FORMS_MAX_BASE", 3))


def resolve_fill_links_active_limit(role: Optional[str]) -> int:
    normalized = normalize_role(role)
    if normalized == ROLE_GOD:
        return max(1, _int_env("SANDBOX_FILL_LINKS_ACTIVE_MAX_GOD", 100))
    if normalized == ROLE_PRO:
        return max(1, _int_env("SANDBOX_FILL_LINKS_ACTIVE_MAX_PRO", 20))
    return max(1, _int_env("SANDBOX_FILL_LINKS_ACTIVE_MAX_BASE", 1))


def resolve_fill_link_response_limit(role: Optional[str]) -> int:
    normalized = normalize_role(role)
    if normalized == ROLE_GOD:
        return max(1, _int_env("SANDBOX_FILL_LINK_RESPONSES_MAX_GOD", 10000))
    if normalized == ROLE_PRO:
        return max(1, _int_env("SANDBOX_FILL_LINK_RESPONSES_MAX_PRO", 10000))
    return max(1, _int_env("SANDBOX_FILL_LINK_RESPONSES_MAX_BASE", 5))


def resolve_role_limits(role: Optional[str]) -> Dict[str, int]:
    return {
        "detectMaxPages": resolve_detect_max_pages(role),
        "fillableMaxPages": resolve_fillable_max_pages(role),
        "savedFormsMax": resolve_saved_forms_limit(role),
        "fillLinksActiveMax": resolve_fill_links_active_limit(role),
        "fillLinkResponsesMax": resolve_fill_link_response_limit(role),
    }
