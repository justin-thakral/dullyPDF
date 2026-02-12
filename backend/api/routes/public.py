"""Public unauthenticated endpoints."""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request

from backend.api.schemas import ContactRequest, RecaptchaAssessmentRequest
from backend.security.rate_limit import check_rate_limit
from backend.services.contact_service import (
    resolve_client_ip,
    resolve_contact_body,
    resolve_contact_rate_limits,
    resolve_contact_subject,
    resolve_signup_rate_limits,
)
from backend.services.email_service import send_contact_email
from backend.services.recaptcha_service import (
    recaptcha_required_for_signup,
    resolve_signup_recaptcha_action,
    verify_contact_recaptcha,
    verify_recaptcha_token,
)

router = APIRouter()


@router.post("/api/contact")
async def submit_contact(payload: ContactRequest, request: Request) -> Dict[str, Any]:
    """Accept a homepage contact form submission."""
    window_seconds, per_ip, global_limit = resolve_contact_rate_limits()
    if global_limit > 0:
        rate_key = "contact:global"
        allowed = check_rate_limit(rate_key, limit=global_limit, window_seconds=window_seconds)
    else:
        client_ip = resolve_client_ip(request)
        rate_key = f"contact:{client_ip}"
        allowed = check_rate_limit(rate_key, limit=per_ip, window_seconds=window_seconds)

    if not allowed:
        raise HTTPException(status_code=429, detail="Too many contact requests. Please wait and try again.")

    await verify_contact_recaptcha(payload, request)

    subject = resolve_contact_subject(payload)
    body = resolve_contact_body(payload, request)
    reply_to = None
    if payload.contactEmail:
        reply_to = {"email": payload.contactEmail, "name": payload.contactName or payload.contactEmail}
    await send_contact_email(subject, body, reply_to)
    return {"success": True}


@router.post("/api/recaptcha/assess")
async def assess_recaptcha(payload: RecaptchaAssessmentRequest, request: Request) -> Dict[str, Any]:
    """Verify a reCAPTCHA token for sensitive public flows."""
    window_seconds, per_ip, global_limit = resolve_signup_rate_limits()
    action = resolve_signup_recaptcha_action()
    if global_limit > 0:
        rate_key = f"recaptcha:{action}:global"
        allowed = check_rate_limit(rate_key, limit=global_limit, window_seconds=window_seconds)
    else:
        client_ip = resolve_client_ip(request)
        rate_key = f"recaptcha:{action}:{client_ip}"
        allowed = check_rate_limit(rate_key, limit=per_ip, window_seconds=window_seconds)

    if not allowed:
        raise HTTPException(status_code=429, detail="Too many verification attempts. Please wait and try again.")

    await verify_recaptcha_token(payload.token, action, request, required=recaptcha_required_for_signup())
    return {"success": True}
