"""Best-effort Cloud Run prewarm helpers for OpenAI worker services."""

from __future__ import annotations

from typing import List

import httpx

from backend.logging_config import get_logger
from backend.env_utils import env_truthy, int_env

from .tasks import (
    resolve_openai_remap_profile,
    resolve_openai_rename_profile,
    resolve_openai_task_config,
)


logger = get_logger(__name__)


def prewarm_openai_services(
    *,
    page_count: int,
    prewarm_rename: bool,
    prewarm_remap: bool,
) -> List[str]:
    """Trigger a lightweight /health request to warm relevant worker services."""
    if not env_truthy("OPENAI_PREWARM_ENABLED"):
        return []
    touched: List[str] = []
    timeout_seconds = max(1, int_env("OPENAI_PREWARM_TIMEOUT_SECONDS", 2))

    def _touch_url(url: str) -> None:
        if not url:
            return
        health_url = f"{url.rstrip('/')}/health"
        try:
            with httpx.Client(timeout=timeout_seconds) as client:
                response = client.get(health_url)
            if response.status_code < 500:
                touched.append(health_url)
            else:
                logger.debug("OpenAI prewarm returned %s for %s", response.status_code, health_url)
        except Exception as exc:
            logger.debug("OpenAI prewarm failed for %s: %s", health_url, exc)

    if prewarm_rename:
        try:
            rename_profile = resolve_openai_rename_profile(page_count)
            rename_config = resolve_openai_task_config("rename", rename_profile)
            _touch_url(rename_config.get("service_url") or "")
        except Exception as exc:
            logger.debug("OpenAI rename prewarm config unavailable: %s", exc)

    if prewarm_remap:
        try:
            remap_profile = resolve_openai_remap_profile(None)
            remap_config = resolve_openai_task_config("remap", remap_profile)
            _touch_url(remap_config.get("service_url") or "")
        except Exception as exc:
            logger.debug("OpenAI remap prewarm config unavailable: %s", exc)

    return touched

