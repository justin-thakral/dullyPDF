"""OpenAI usage normalization, cost estimation, and retryable error helpers."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from backend.env_utils import env_value


_TOKEN_KEYS = (
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "cached_input_tokens",
    "reasoning_output_tokens",
)


def _to_int(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 0
    return parsed if parsed >= 0 else 0


def _to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _as_dict(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    if value is None:
        return {}
    try:
        data = vars(value)
    except TypeError:
        return {}
    if isinstance(data, dict):
        return data
    return {}


def _obj_get(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        return value.get(key)
    return getattr(value, key, None)


def normalize_responses_usage(response_or_usage: Any) -> Dict[str, int]:
    """Normalize Responses API usage payloads into stable token keys."""
    usage = _obj_get(response_or_usage, "usage") or response_or_usage
    input_tokens = _to_int(_obj_get(usage, "input_tokens"))
    output_tokens = _to_int(_obj_get(usage, "output_tokens"))
    total_tokens = _to_int(_obj_get(usage, "total_tokens"))

    input_details = _obj_get(usage, "input_tokens_details")
    output_details = _obj_get(usage, "output_tokens_details")
    cached_input_tokens = _to_int(_obj_get(input_details, "cached_tokens"))
    reasoning_output_tokens = _to_int(_obj_get(output_details, "reasoning_tokens"))

    if total_tokens <= 0:
        total_tokens = input_tokens + output_tokens

    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "cached_input_tokens": cached_input_tokens,
        "reasoning_output_tokens": reasoning_output_tokens,
    }


def normalize_chat_usage(response_or_usage: Any) -> Dict[str, int]:
    """Normalize Chat Completions usage payloads into stable token keys."""
    usage = _obj_get(response_or_usage, "usage") or response_or_usage
    input_tokens = _to_int(_obj_get(usage, "prompt_tokens"))
    output_tokens = _to_int(_obj_get(usage, "completion_tokens"))
    total_tokens = _to_int(_obj_get(usage, "total_tokens"))

    prompt_details = _obj_get(usage, "prompt_tokens_details")
    completion_details = _obj_get(usage, "completion_tokens_details")
    cached_input_tokens = _to_int(_obj_get(prompt_details, "cached_tokens"))
    reasoning_output_tokens = _to_int(_obj_get(completion_details, "reasoning_tokens"))

    if total_tokens <= 0:
        total_tokens = input_tokens + output_tokens

    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "cached_input_tokens": cached_input_tokens,
        "reasoning_output_tokens": reasoning_output_tokens,
    }


def aggregate_openai_usage(events: Iterable[Dict[str, Any]]) -> Dict[str, int]:
    """Sum normalized usage events into one token summary."""
    totals = {key: 0 for key in _TOKEN_KEYS}
    for event in events:
        if not isinstance(event, dict):
            continue
        for key in _TOKEN_KEYS:
            totals[key] += _to_int(event.get(key))
    if totals["total_tokens"] <= 0:
        totals["total_tokens"] = totals["input_tokens"] + totals["output_tokens"]
    return totals


def coerce_usage_events(raw_events: Any) -> List[Dict[str, Any]]:
    """Return only dict usage events from arbitrary input."""
    if not isinstance(raw_events, list):
        return []
    return [event for event in raw_events if isinstance(event, dict)]


def merge_usage_events(
    existing_events: List[Dict[str, Any]],
    new_events: List[Dict[str, Any]],
    *,
    attempt: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Append new usage events, annotating attempt number when provided."""
    merged: List[Dict[str, Any]] = [dict(event) for event in coerce_usage_events(existing_events)]
    for raw_event in coerce_usage_events(new_events):
        event = dict(raw_event)
        if attempt is not None:
            event["attempt"] = int(attempt)
        merged.append(event)
    return merged


def _estimate_cost_usd(usage_totals: Dict[str, int]) -> Optional[float]:
    """Estimate USD from usage totals when token price env vars are configured."""
    input_rate = _to_float(env_value("OPENAI_PRICE_INPUT_PER_1M_USD"))
    output_rate = _to_float(env_value("OPENAI_PRICE_OUTPUT_PER_1M_USD"))
    if input_rate is None or output_rate is None:
        return None

    cached_input_rate = _to_float(env_value("OPENAI_PRICE_CACHED_INPUT_PER_1M_USD"))
    reasoning_output_rate = _to_float(env_value("OPENAI_PRICE_REASONING_OUTPUT_PER_1M_USD"))
    if cached_input_rate is None:
        cached_input_rate = input_rate
    if reasoning_output_rate is None:
        reasoning_output_rate = output_rate

    input_tokens = _to_int(usage_totals.get("input_tokens"))
    output_tokens = _to_int(usage_totals.get("output_tokens"))
    cached_input_tokens = _to_int(usage_totals.get("cached_input_tokens"))
    reasoning_output_tokens = _to_int(usage_totals.get("reasoning_output_tokens"))

    non_cached_input_tokens = max(input_tokens - cached_input_tokens, 0)
    non_reasoning_output_tokens = max(output_tokens - reasoning_output_tokens, 0)

    total_usd = (
        (non_cached_input_tokens * input_rate)
        + (cached_input_tokens * cached_input_rate)
        + (non_reasoning_output_tokens * output_rate)
        + (reasoning_output_tokens * reasoning_output_rate)
    ) / 1_000_000.0
    return round(total_usd, 8)


def build_openai_usage_summary(
    events: List[Dict[str, Any]],
    *,
    model: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a per-job usage summary with optional USD estimate."""
    usage_events = coerce_usage_events(events)
    totals = aggregate_openai_usage(usage_events)
    summary: Dict[str, Any] = {
        "model": (model or "").strip() or None,
        "calls": len(usage_events),
        **totals,
    }
    estimated_cost = _estimate_cost_usd(totals)
    if estimated_cost is not None:
        summary["estimated_cost_usd"] = estimated_cost
    return summary


def _extract_error_code(exc: Exception) -> str:
    for attr in ("code", "error_code"):
        value = getattr(exc, attr, None)
        if value:
            return str(value).strip().lower()

    body = getattr(exc, "body", None)
    body_dict = _as_dict(body)
    if body_dict:
        nested = _as_dict(body_dict.get("error"))
        code = nested.get("code") or body_dict.get("code")
        if code:
            return str(code).strip().lower()

    error = getattr(exc, "error", None)
    error_dict = _as_dict(error)
    if error_dict:
        code = error_dict.get("code")
        if code:
            return str(code).strip().lower()

    response = getattr(exc, "response", None)
    json_loader = getattr(response, "json", None)
    if callable(json_loader):
        try:
            payload = json_loader()
        except Exception:
            payload = None
        payload_dict = _as_dict(payload)
        if payload_dict:
            nested = _as_dict(payload_dict.get("error"))
            code = nested.get("code") or payload_dict.get("code")
            if code:
                return str(code).strip().lower()

    message = str(exc).strip().lower()
    if "insufficient_quota" in message:
        return "insufficient_quota"
    return ""


def is_insufficient_quota_error(exc: Exception) -> bool:
    """Return True when an OpenAI error indicates exhausted account quota."""
    return _extract_error_code(exc) == "insufficient_quota"


__all__ = [
    "aggregate_openai_usage",
    "build_openai_usage_summary",
    "coerce_usage_events",
    "is_insufficient_quota_error",
    "merge_usage_events",
    "normalize_chat_usage",
    "normalize_responses_usage",
]
