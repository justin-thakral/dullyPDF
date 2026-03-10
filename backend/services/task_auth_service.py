"""Shared Cloud Tasks OIDC audience helpers."""

from __future__ import annotations

from typing import Any, Dict, Iterable, Sequence

from fastapi import HTTPException
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

from backend.env_utils import env_value


def _unique_nonempty(values: Iterable[str], *, strip_trailing_slash: bool = False) -> list[str]:
    seen: set[str] = set()
    resolved: list[str] = []
    for raw in values:
        value = (raw or "").strip()
        if strip_trailing_slash:
            value = value.rstrip("/")
        if not value or value in seen:
            continue
        seen.add(value)
        resolved.append(value)
    return resolved


def resolve_task_audiences(
    *,
    audience_envs: Sequence[str],
    service_url_envs: Sequence[str],
) -> list[str]:
    """Return all configured OIDC audiences that a worker should trust.

    Cloud Tasks can mint profile-specific OIDC audiences (light/heavy/GPU) while
    the worker endpoint stays fixed. We accept any configured audience for the
    service, but caller identity is still enforced separately by the worker.
    """

    audiences = _unique_nonempty(env_value(name) for name in audience_envs)
    service_urls = _unique_nonempty(
        (env_value(name) for name in service_url_envs),
        strip_trailing_slash=True,
    )
    return _unique_nonempty([*audiences, *service_urls])


def verify_internal_oidc_token(
    token: str,
    *,
    audiences: Sequence[str],
    missing_audience_detail: str,
    invalid_token_detail: str,
) -> Dict[str, Any]:
    """Validate a Cloud Tasks OIDC token against any configured audience."""

    if not audiences:
        raise HTTPException(status_code=500, detail=missing_audience_detail)

    verifier_request = google_requests.Request()
    last_error: Exception | None = None
    for audience in audiences:
        try:
            return id_token.verify_oauth2_token(token, verifier_request, audience=audience)
        except Exception as exc:  # pragma: no cover - exercised via caller-facing tests
            last_error = exc

    raise HTTPException(status_code=401, detail=invalid_token_detail) from last_error
