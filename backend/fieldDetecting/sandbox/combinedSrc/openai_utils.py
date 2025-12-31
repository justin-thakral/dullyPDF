from __future__ import annotations

from typing import Any, Dict, Optional

from openai import OpenAI, OpenAIError

from .config import get_logger

logger = get_logger(__name__)


def _error_text(exc: Exception) -> str:
    """
    Best-effort extraction of a human-readable error message from OpenAI SDK exceptions.

    The OpenAI Python SDK error types can vary across versions; we keep this resilient by
    checking common attributes before falling back to `str(exc)`.
    """
    for attr in ("message", "error", "body", "response"):
        val = getattr(exc, attr, None)
        if val is None:
            continue
        try:
            return str(val)
        except Exception:
            continue
    return str(exc)


def _is_temperature_unsupported(exc: Exception) -> bool:
    """
    Some models reject `temperature` entirely. The SDK surfaces this as a 400 with an error
    message similar to: `"temperature" is not supported with this model`.
    """
    msg = _error_text(exc).lower()
    return "temperature" in msg and ("not supported" in msg or "unsupported" in msg)


def responses_create_with_temperature_fallback(
    client: OpenAI,
    *,
    model: str,
    input: Any,
    text: Dict[str, Any],
    max_output_tokens: int,
    temperature: Optional[float] = 0,
    **kwargs: Any,
):
    """
    Call `client.responses.create` with a compatibility retry.

    Why this exists:
    - Some newer models reject the `temperature` parameter entirely.
    - We want deterministic behavior (temperature=0) when supported, but we must remain
      robust when it is not.

    Strategy:
    - Try with `temperature` when provided.
    - If the model rejects it, retry once without `temperature`.
    """
    params: Dict[str, Any] = {
        "model": model,
        "input": input,
        "text": text,
        "max_output_tokens": int(max_output_tokens),
    }
    params.update(kwargs)
    if temperature is not None:
        params["temperature"] = temperature

    try:
        return client.responses.create(**params)
    except OpenAIError as exc:
        if temperature is None or not _is_temperature_unsupported(exc):
            raise
        logger.warning(
            "Model %s rejected temperature; retrying without it (%s)",
            model,
            _error_text(exc),
        )
        params.pop("temperature", None)
        return client.responses.create(**params)


def extract_response_text(response: Any) -> str:
    """
    Extract text from a Responses API response.

    The SDK can return content across multiple output items; we join all text parts
    to avoid truncating the payload.
    """
    content = getattr(response, "output_text", None)
    if content:
        return content

    parts = []
    for output_item in getattr(response, "output", []) or []:
        for part in getattr(output_item, "content", []) or []:
            text = getattr(part, "text", None)
            if text:
                parts.append(text)
    return "".join(parts)


__all__ = ["responses_create_with_temperature_fallback", "extract_response_text"]
