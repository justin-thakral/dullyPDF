"""Gmail / email sending helpers."""

from __future__ import annotations

import base64
from email.utils import formataddr, getaddresses
import re
import threading
import time
from typing import Any, Dict, Optional

from fastapi import HTTPException
import httpx
from google.auth import default as google_auth_default
from google.auth.transport.requests import Request as GoogleAuthRequest

from backend.env_utils import env_value as _env_value
from backend.logging_config import get_logger
from backend.fieldDetecting.rename_pipeline.debug_flags import debug_enabled

from .app_config import is_prod

logger = get_logger(__name__)


def _log_external_http_failure(context: str, response: httpx.Response) -> None:
    """Log external HTTP failures without leaking response bodies in normal runs."""
    if debug_enabled():
        logger.error("%s failed (status=%s): %s", context, response.status_code, response.text)
    else:
        logger.error("%s failed (status=%s)", context, response.status_code)


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
