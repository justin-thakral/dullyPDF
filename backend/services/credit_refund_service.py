"""Shared retry/reconciliation flow for OpenAI credit refunds."""

from __future__ import annotations

import time
from typing import Any, Dict, Optional

from backend.env_utils import int_env
from backend.firebaseDB.credit_refund_database import record_credit_refund_failure
from backend.firebaseDB.user_database import refund_openai_credits
from backend.logging_config import get_logger


logger = get_logger(__name__)


def _normalize_credit_breakdown(raw: Optional[Dict[str, Any]]) -> Dict[str, int]:
    payload = raw if isinstance(raw, dict) else {}
    normalized: Dict[str, int] = {}
    for key in ("base", "monthly", "refill"):
        try:
            value = int(payload.get(key, 0))
        except (TypeError, ValueError):
            value = 0
        normalized[key] = value if value > 0 else 0
    return normalized


def _positive_env_int(name: str, default: int) -> int:
    value = int_env(name, default)
    return value if value > 0 else default


def _attempt_refund(
    *,
    user_id: str,
    role: Optional[str],
    credits: int,
    credit_breakdown: Optional[Dict[str, Any]] = None,
) -> None:
    breakdown = _normalize_credit_breakdown(credit_breakdown)
    kwargs: Dict[str, Any] = {}
    if breakdown["base"] > 0 or breakdown["monthly"] > 0 or breakdown["refill"] > 0:
        kwargs["credit_breakdown"] = breakdown
    refund_openai_credits(
        user_id,
        credits=credits,
        role=role,
        **kwargs,
    )


def attempt_credit_refund(
    *,
    user_id: str,
    role: Optional[str],
    credits: int,
    source: str,
    credit_breakdown: Optional[Dict[str, Any]] = None,
    request_id: Optional[str] = None,
    job_id: Optional[str] = None,
) -> bool:
    """Try to refund credits with retries; record failures for reconciliation."""
    normalized_user_id = (user_id or "").strip()
    if not normalized_user_id:
        logger.error("Credit refund skipped: missing user_id (source=%s).", source or "unknown")
        return False
    try:
        credits_to_refund = int(credits)
    except (TypeError, ValueError):
        credits_to_refund = 0
    if credits_to_refund <= 0:
        return True

    normalized_source = (source or "").strip() or "unknown"
    max_attempts = _positive_env_int("OPENAI_CREDIT_REFUND_MAX_ATTEMPTS", 3)
    backoff_ms = int_env("OPENAI_CREDIT_REFUND_RETRY_BACKOFF_MS", 150)
    if backoff_ms < 0:
        backoff_ms = 150
    last_error: Optional[Exception] = None

    for attempt in range(1, max_attempts + 1):
        try:
            _attempt_refund(
                user_id=normalized_user_id,
                role=role,
                credits=credits_to_refund,
                credit_breakdown=credit_breakdown,
            )
            if attempt > 1:
                logger.warning(
                    "Credit refund succeeded after retry (source=%s, user_id=%s, attempt=%s/%s).",
                    normalized_source,
                    normalized_user_id,
                    attempt,
                    max_attempts,
                )
            return True
        except Exception as exc:
            last_error = exc
            if attempt < max_attempts:
                logger.warning(
                    "Credit refund attempt failed (source=%s, user_id=%s, attempt=%s/%s): %s",
                    normalized_source,
                    normalized_user_id,
                    attempt,
                    max_attempts,
                    exc,
                )
                delay_seconds = (backoff_ms * attempt) / 1000.0
                if delay_seconds > 0:
                    time.sleep(delay_seconds)

    failure_record_id: Optional[str] = None
    last_error_message = str(last_error) if last_error else "Unknown refund failure"
    try:
        failure_record_id = record_credit_refund_failure(
            user_id=normalized_user_id,
            credits=credits_to_refund,
            role=role,
            source=normalized_source,
            error_message=last_error_message,
            attempts=max_attempts,
            credit_breakdown=credit_breakdown,
            request_id=request_id,
            job_id=job_id,
        )
    except Exception as record_exc:
        logger.error(
            "Failed to persist credit refund reconciliation record (source=%s, user_id=%s): %s",
            normalized_source,
            normalized_user_id,
            record_exc,
            exc_info=True,
        )

    logger.error(
        "Credit refund failed after retries (source=%s, user_id=%s, credits=%s, record_id=%s): %s",
        normalized_source,
        normalized_user_id,
        credits_to_refund,
        failure_record_id or "unavailable",
        last_error_message,
        exc_info=(type(last_error), last_error, last_error.__traceback__) if last_error else False,
    )
    return False
