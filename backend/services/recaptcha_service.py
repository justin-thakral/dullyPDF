"""reCAPTCHA verification helpers."""

from __future__ import annotations

import math
from typing import Any, Dict, Optional

from fastapi import HTTPException, Request
import httpx

from backend.api.schemas import ContactRequest
from backend.env_utils import env_truthy as _env_truthy, env_value as _env_value
from backend.logging_config import get_logger
from backend.fieldDetecting.rename_pipeline.debug_flags import debug_enabled

from .contact_service import is_public_ip, resolve_client_ip
from .email_service import get_google_access_token

logger = get_logger(__name__)


def _is_prod() -> bool:
    return _env_value("ENV").strip().lower() in {"prod", "production"}


def recaptcha_required_for_contact() -> bool:
    raw = _env_value("CONTACT_REQUIRE_RECAPTCHA")
    if raw:
        return _env_truthy("CONTACT_REQUIRE_RECAPTCHA")
    return True


def recaptcha_required_for_signup() -> bool:
    raw = _env_value("SIGNUP_REQUIRE_RECAPTCHA")
    if raw:
        return _env_truthy("SIGNUP_REQUIRE_RECAPTCHA")
    return True


def recaptcha_required_for_fill_link() -> bool:
    raw = _env_value("FILL_LINK_REQUIRE_RECAPTCHA")
    if raw:
        return _env_truthy("FILL_LINK_REQUIRE_RECAPTCHA")
    return True


def recaptcha_required_any() -> bool:
    return (
        recaptcha_required_for_contact()
        or recaptcha_required_for_signup()
        or recaptcha_required_for_fill_link()
    )


def resolve_contact_recaptcha_action() -> str:
    return _env_value("RECAPTCHA_CONTACT_ACTION") or _env_value("RECAPTCHA_EXPECTED_ACTION") or "contact"


def resolve_signup_recaptcha_action() -> str:
    return _env_value("RECAPTCHA_SIGNUP_ACTION") or _env_value("RECAPTCHA_EXPECTED_ACTION") or "signup"


def resolve_fill_link_recaptcha_action() -> str:
    return _env_value("RECAPTCHA_FILL_LINK_ACTION") or _env_value("RECAPTCHA_EXPECTED_ACTION") or "fill_link_submit"


def resolve_recaptcha_project_id() -> str:
    return _env_value("RECAPTCHA_PROJECT_ID") or _env_value("FIREBASE_PROJECT_ID") or _env_value("GCP_PROJECT_ID")


def resolve_recaptcha_min_score() -> float:
    raw = _env_value("RECAPTCHA_MIN_SCORE")
    if not raw:
        return 0.5
    try:
        value = float(raw)
    except ValueError:
        return 0.5
    if not math.isfinite(value):
        return 0.5
    if value < 0.0 or value > 1.0:
        return 0.5
    return value


def resolve_recaptcha_allowed_hostnames() -> list[str]:
    raw = _env_value("RECAPTCHA_ALLOWED_HOSTNAMES")
    if not raw:
        return []
    return [host.strip().lower() for host in raw.split(",") if host.strip()]


def recaptcha_hostname_allowed(hostname: str, allowed: list[str]) -> bool:
    if not hostname:
        return False
    normalized = hostname.strip().lower()
    if not normalized:
        return False
    for entry in allowed:
        if normalized == entry:
            return True
        if entry.startswith("*."):
            suffix = entry[1:]
            if normalized.endswith(suffix) and normalized != suffix.lstrip("."):
                return True
    return False


async def verify_recaptcha_token(
    token: Optional[str],
    expected_action: Optional[str],
    request: Request,
    *,
    required: bool,
) -> None:
    if not token:
        if required:
            raise HTTPException(status_code=400, detail="Recaptcha token missing")
        return

    site_key = _env_value("RECAPTCHA_SITE_KEY")
    project_id = resolve_recaptcha_project_id()
    if not site_key or not project_id:
        if required:
            raise HTTPException(status_code=500, detail="Recaptcha is not configured")
        logger.warning("Recaptcha configuration missing; skipping verification.")
        return

    allowed_hostnames = resolve_recaptcha_allowed_hostnames()
    if _is_prod() and not allowed_hostnames:
        raise HTTPException(status_code=500, detail="Recaptcha allowed hostnames are not configured")

    expected_action = (expected_action or "").strip() or None
    event: Dict[str, Any] = {"token": token, "siteKey": site_key}
    if expected_action:
        event["expectedAction"] = expected_action
    user_agent = request.headers.get("user-agent")
    if user_agent:
        event["userAgent"] = user_agent
    client_ip = resolve_client_ip(request)
    if client_ip != "unknown" and is_public_ip(client_ip):
        event["userIpAddress"] = client_ip

    access_token = get_google_access_token()
    url = f"https://recaptchaenterprise.googleapis.com/v1/projects/{project_id}/assessments"
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(url, headers={"Authorization": f"Bearer {access_token}"}, json={"event": event})
    if response.status_code >= 400:
        if debug_enabled():
            logger.warning("Recaptcha verification failed (status=%s): %s", response.status_code, response.text)
        else:
            logger.warning("Recaptcha verification failed (status=%s)", response.status_code)
        raise HTTPException(status_code=502, detail="Recaptcha verification failed")

    data = response.json()
    token_props = data.get("tokenProperties", {}) if isinstance(data, dict) else {}
    if not token_props.get("valid"):
        reason = token_props.get("invalidReason") or "invalid-token"
        raise HTTPException(status_code=400, detail=f"Recaptcha invalid ({reason})")
    if expected_action:
        action = token_props.get("action")
        if action != expected_action:
            raise HTTPException(status_code=400, detail="Recaptcha action mismatch")

    if allowed_hostnames:
        hostname = str(token_props.get("hostname") or "").strip()
        if not recaptcha_hostname_allowed(hostname, allowed_hostnames):
            raise HTTPException(status_code=400, detail="Recaptcha hostname not allowed")

    min_score = resolve_recaptcha_min_score()
    risk = data.get("riskAnalysis", {}) if isinstance(data, dict) else {}
    try:
        score = float(risk.get("score", 0))
    except (TypeError, ValueError):
        score = 0.0
    if score < min_score:
        raise HTTPException(status_code=400, detail="Recaptcha score too low")


async def verify_contact_recaptcha(payload: ContactRequest, request: Request) -> None:
    await verify_recaptcha_token(
        payload.recaptchaToken,
        resolve_contact_recaptcha_action(),
        request,
        required=recaptcha_required_for_contact(),
    )
