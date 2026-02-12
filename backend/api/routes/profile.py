"""Authenticated profile endpoints."""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Header

from backend.firebaseDB.user_database import ROLE_GOD, get_user_profile, normalize_role
from backend.services.auth_service import require_user
from backend.services.limits_service import resolve_role_limits

router = APIRouter()


@router.get("/api/profile")
async def get_profile(authorization: Optional[str] = Header(default=None)) -> Dict[str, Any]:
    """Return the current user's profile details and limits."""
    user = require_user(authorization)
    profile = get_user_profile(user.app_user_id)
    role = normalize_role(user.role)
    credits_remaining: Optional[int] = None
    if profile:
        credits_remaining = profile.openai_credits_remaining
    if role == ROLE_GOD:
        credits_remaining = None
    return {
        "email": user.email,
        "displayName": user.display_name,
        "role": role,
        "creditsRemaining": credits_remaining,
        "limits": resolve_role_limits(role),
    }
