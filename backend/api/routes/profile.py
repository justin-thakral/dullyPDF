"""Authenticated profile endpoints."""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Header

from backend.ai.credit_pricing import resolve_credit_pricing_config
from backend.firebaseDB.user_database import (
    ROLE_GOD,
    get_user_billing_record,
    get_user_profile,
    normalize_role,
)
from backend.services.auth_service import require_user
from backend.services.billing_service import billing_enabled, resolve_checkout_catalog
from backend.services.limits_service import resolve_role_limits

router = APIRouter()


@router.get("/api/profile")
async def get_profile(authorization: Optional[str] = Header(default=None)) -> Dict[str, Any]:
    """Return the current user's profile details and limits."""
    user = require_user(authorization)
    profile = get_user_profile(user.app_user_id)
    role = normalize_role(profile.role if profile else user.role)
    credits_remaining: Optional[int] = None
    monthly_credits_remaining: Optional[int] = None
    refill_credits_remaining: Optional[int] = None
    available_credits: Optional[int] = None
    refill_credits_locked = False
    if profile:
        credits_remaining = profile.openai_credits_remaining
        monthly_credits_remaining = profile.openai_credits_monthly_remaining
        refill_credits_remaining = profile.openai_credits_refill_remaining
        available_credits = profile.openai_credits_available
        refill_credits_locked = bool(profile.refill_credits_locked)
    if role == ROLE_GOD:
        credits_remaining = None
        monthly_credits_remaining = None
        refill_credits_remaining = None
        available_credits = None
        refill_credits_locked = False
    billing_is_enabled = billing_enabled()
    billing_record = get_user_billing_record(user.app_user_id) if billing_is_enabled else None
    return {
        "email": user.email,
        "displayName": user.display_name,
        "role": role,
        "creditsRemaining": credits_remaining,
        "monthlyCreditsRemaining": monthly_credits_remaining,
        "refillCreditsRemaining": refill_credits_remaining,
        "availableCredits": available_credits,
        "refillCreditsLocked": refill_credits_locked,
        "creditPricing": resolve_credit_pricing_config(),
        "billing": {
            "enabled": billing_is_enabled,
            "plans": resolve_checkout_catalog() if billing_is_enabled else {},
            "hasSubscription": bool(billing_record and billing_record.subscription_id),
            "subscriptionStatus": billing_record.subscription_status if billing_record else None,
            "cancelAtPeriodEnd": billing_record.cancel_at_period_end if billing_record else None,
            "cancelAt": billing_record.cancel_at if billing_record else None,
            "currentPeriodEnd": billing_record.current_period_end if billing_record else None,
        },
        "limits": resolve_role_limits(role),
    }
