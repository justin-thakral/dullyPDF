"""Contact form helpers: rate limits, IP resolution, subject/body formatting."""

from __future__ import annotations

import ipaddress
import re

from fastapi import Request

from backend.api.schemas import CONTACT_ISSUE_LABELS, ContactRequest
from backend.env_utils import env_truthy as _env_truthy, env_value as _env_value, int_env as _int_env


def resolve_contact_rate_limits() -> tuple[int, int, int]:
    window_seconds = _int_env("CONTACT_RATE_LIMIT_WINDOW_SECONDS", 600)
    per_ip = _int_env("CONTACT_RATE_LIMIT_PER_IP", 6)
    global_limit = _int_env("CONTACT_RATE_LIMIT_GLOBAL", 0)
    if window_seconds <= 0:
        window_seconds = 600
    if per_ip <= 0:
        per_ip = 6
    if global_limit < 0:
        global_limit = 0
    return window_seconds, per_ip, global_limit


def resolve_signup_rate_limits() -> tuple[int, int, int]:
    window_seconds = _int_env("SIGNUP_RATE_LIMIT_WINDOW_SECONDS", 600)
    per_ip = _int_env("SIGNUP_RATE_LIMIT_PER_IP", 8)
    global_limit = _int_env("SIGNUP_RATE_LIMIT_GLOBAL", 0)
    if window_seconds <= 0:
        window_seconds = 600
    if per_ip <= 0:
        per_ip = 8
    if global_limit < 0:
        global_limit = 0
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
