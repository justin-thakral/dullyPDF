"""Public contact and reCAPTCHA helpers."""

from __future__ import annotations

import base64
from email.utils import formataddr, getaddresses
import ipaddress
import re
import threading
import time
from typing import Any, Dict, Optional

from fastapi import HTTPException, Request
import httpx
from google.auth import default as google_auth_default
from google.auth.transport.requests import Request as GoogleAuthRequest

from backend.api.schemas import CONTACT_ISSUE_LABELS, ContactRequest
from backend.env_utils import env_truthy as _env_truthy, env_value as _env_value, int_env as _int_env
from backend.fieldDetecting.rename_pipeline.combinedSrc.config import get_logger
from backend.fieldDetecting.rename_pipeline.debug_flags import debug_enabled

from .app_config import is_prod

logger = get_logger(__name__)


def _log_external_http_failure(context: str, response: httpx.Response) -> None:
    """Log external HTTP failures without leaking response bodies in normal runs."""
    if debug_enabled():
        logger.error("%s failed (status=%s): %s", context, response.status_code, response.text)
    else:
        logger.error("%s failed (status=%s)", context, response.status_code)


def resolve_contact_rate_limits() -> tuple[int, int, int]:
    window_seconds = _int_env("CONTACT_RATE_LIMIT_WINDOW_SECONDS", 600)
    per_ip = _int_env("CONTACT_RATE_LIMIT_PER_IP", 6)
    global_limit = _int_env("CONTACT_RATE_LIMIT_GLOBAL", 0)
    return window_seconds, per_ip, global_limit


def resolve_signup_rate_limits() -> tuple[int, int, int]:
    window_seconds = _int_env("SIGNUP_RATE_LIMIT_WINDOW_SECONDS", 600)
    per_ip = _int_env("SIGNUP_RATE_LIMIT_PER_IP", 8)
    global_limit = _int_env("SIGNUP_RATE_LIMIT_GLOBAL", 0)
    return window_seconds, per_ip, global_limit


def trust_proxy_headers() -> bool:
    raw = _env_value("SANDBOX_TRUST_PROXY_HEADERS")
    if raw:
        return _env_truthy("SANDBOX_TRUST_PROXY_HEADERS")
    return False


def resolve_client_ip(request: Request) -> str:
    forwarded_for = request.headers.get("x-forwarded-for") or ""
    if forwarded_for and trust_proxy_headers():
        first = forwarded_for.split(",")[0].strip()
        if first:
            return first
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def is_public_ip(value: str) -> bool:
    """Return True when the IP is a public, routable address."""
    try:
        addr = ipaddress.ip_address(str(value or "").strip())
    except ValueError:
        return False
    return not (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_multicast
        or addr.is_reserved
        or getattr(addr, "is_unspecified", False)
    )


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


def recaptcha_required_any() -> bool:
    return recaptcha_required_for_contact() or recaptcha_required_for_signup()


def resolve_contact_recaptcha_action() -> str:
    return _env_value("RECAPTCHA_CONTACT_ACTION") or _env_value("RECAPTCHA_EXPECTED_ACTION") or "contact"


def resolve_signup_recaptcha_action() -> str:
    return _env_value("RECAPTCHA_SIGNUP_ACTION") or _env_value("RECAPTCHA_EXPECTED_ACTION") or "signup"


def resolve_recaptcha_project_id() -> str:
    return _env_value("RECAPTCHA_PROJECT_ID") or _env_value("FIREBASE_PROJECT_ID") or _env_value("GCP_PROJECT_ID")


def resolve_recaptcha_min_score() -> float:
    raw = _env_value("RECAPTCHA_MIN_SCORE")
    if not raw:
        return 0.5
    try:
        return float(raw)
    except ValueError:
        return 0.5


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


_GMAIL_TOKEN_CACHE: Dict[str, Any] = {"access_token": None, "expires_at": 0.0}


def resolve_gmail_user_id() -> str:
    return _env_value("GMAIL_USER_ID") or "me"


async def get_gmail_access_token() -> str:
    cached_token = _GMAIL_TOKEN_CACHE.get("access_token")
    expires_at = float(_GMAIL_TOKEN_CACHE.get("expires_at") or 0.0)
    now = time.time()
    if cached_token and now < (expires_at - 60):
        return str(cached_token)

    client_id = _env_value("GMAIL_CLIENT_ID")
    client_secret = _env_value("GMAIL_CLIENT_SECRET")
    refresh_token = _env_value("GMAIL_REFRESH_TOKEN")
    if not client_id or not client_secret or not refresh_token:
        raise RuntimeError("Gmail API credentials are missing")

    payload = {
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post("https://oauth2.googleapis.com/token", data=payload)
    if response.status_code >= 400:
        _log_external_http_failure("Gmail token refresh", response)
        raise RuntimeError("Failed to refresh Gmail access token")

    data = response.json()
    access_token = data.get("access_token")
    expires_in = data.get("expires_in")
    if not access_token:
        raise RuntimeError("Gmail token response missing access_token")
    try:
        expires_in_val = float(expires_in)
    except (TypeError, ValueError):
        expires_in_val = 3600.0

    _GMAIL_TOKEN_CACHE["access_token"] = access_token
    _GMAIL_TOKEN_CACHE["expires_at"] = now + expires_in_val
    return str(access_token)


_GOOGLE_ACCESS_TOKEN_SCOPES = ("https://www.googleapis.com/auth/cloud-platform",)
_GOOGLE_CREDENTIALS = None
_GOOGLE_CREDENTIALS_LOCK = threading.Lock()


def get_google_access_token() -> str:
    """Return cached Google access token for calling Google APIs."""
    global _GOOGLE_CREDENTIALS
    with _GOOGLE_CREDENTIALS_LOCK:
        credentials = _GOOGLE_CREDENTIALS
        if credentials is None:
            credentials, _ = google_auth_default(scopes=list(_GOOGLE_ACCESS_TOKEN_SCOPES))
            if getattr(credentials, "requires_scopes", False):
                credentials = credentials.with_scopes(list(_GOOGLE_ACCESS_TOKEN_SCOPES))
            _GOOGLE_CREDENTIALS = credentials

        if not credentials.valid:
            credentials.refresh(GoogleAuthRequest())
        token = credentials.token
    if not token:
        raise RuntimeError("Failed to acquire Google auth token")
    return token


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

    allowed_hostnames = resolve_recaptcha_allowed_hostnames()
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


def resolve_contact_subject(payload: ContactRequest) -> str:
    issue_label = CONTACT_ISSUE_LABELS.get(payload.issueType, payload.issueType)
    summary = payload.summary.strip()
    subject = f"[DullyPDF][{issue_label}] {summary}".strip()
    subject = re.sub(r"\s+", " ", subject)
    if payload.includeContactInSubject:
        contact_token = payload.contactEmail or payload.contactPhone or payload.contactName
        if contact_token:
            subject = f"{subject} | Contact: {contact_token}"
    subject = re.sub(r"[\r\n]+", " ", subject).strip()
    return subject[:200]


def resolve_contact_body(payload: ContactRequest, request: Request) -> str:
    issue_label = CONTACT_ISSUE_LABELS.get(payload.issueType, payload.issueType)
    lines = [
        f"Issue type: {issue_label}",
        f"Summary: {payload.summary.strip()}",
        "",
        "Message:",
        payload.message.strip(),
        "",
        "Contact details:",
        f"Name: {payload.contactName or '-'}",
        f"Company: {payload.contactCompany or '-'}",
        f"Email: {payload.contactEmail or '-'}",
        f"Phone: {payload.contactPhone or '-'}",
        f"Preferred contact: {payload.preferredContact or '-'}",
    ]
    if payload.pageUrl:
        lines.append(f"Page: {payload.pageUrl}")
    user_agent = request.headers.get("user-agent")
    if user_agent:
        lines.append(f"User-Agent: {user_agent}")
    return "\n".join(lines).strip()


def sanitize_email_header_value(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    cleaned = re.sub(r"[\r\n]+", " ", str(value)).strip()
    return cleaned or None


def format_reply_to_header(reply_to: Optional[Dict[str, str]]) -> Optional[str]:
    if not reply_to:
        return None
    reply_email = sanitize_email_header_value(reply_to.get("email"))
    if not reply_email:
        return None
    reply_name = sanitize_email_header_value(reply_to.get("name"))
    parsed = getaddresses([reply_email])
    addr = parsed[0][1] if parsed else reply_email
    addr = sanitize_email_header_value(addr)
    if not addr:
        return None
    if reply_name:
        return formataddr((reply_name, addr))
    return addr


async def send_contact_email(subject: str, body: str, reply_to: Optional[Dict[str, str]]) -> None:
    to_email = _env_value("CONTACT_TO_EMAIL")
    from_email = _env_value("CONTACT_FROM_EMAIL") or to_email
    if not to_email or not from_email:
        raise HTTPException(status_code=500, detail="Contact email routing is not configured")

    try:
        access_token = await get_gmail_access_token()
    except Exception as exc:
        if is_prod():
            raise HTTPException(status_code=500, detail="Gmail API is not configured") from exc
        logger.warning("Gmail API not configured; skipping contact email.")
        return

    headers = [
        f"From: {from_email}",
        f"To: {to_email}",
        f"Subject: {subject}",
        'Content-Type: text/plain; charset="UTF-8"',
        "Content-Transfer-Encoding: 7bit",
    ]
    if reply_to:
        reply_label = format_reply_to_header(reply_to)
        if reply_label:
            headers.append(f"Reply-To: {reply_label}")

    raw_message = "\r\n".join(headers) + "\r\n\r\n" + body
    encoded_message = base64.urlsafe_b64encode(raw_message.encode("utf-8")).decode("utf-8")

    gmail_payload = {"raw": encoded_message}
    user_id = resolve_gmail_user_id()
    url = f"https://gmail.googleapis.com/gmail/v1/users/{user_id}/messages/send"
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(url, headers={"Authorization": f"Bearer {access_token}"}, json=gmail_payload)
    if response.status_code >= 400:
        _log_external_http_failure("Gmail API contact email send", response)
        raise HTTPException(status_code=502, detail="Failed to send contact email")
