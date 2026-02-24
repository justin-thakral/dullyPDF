"""
Payload profiling and budget fallback helpers for OpenAI rename image inputs.
"""

from __future__ import annotations

import math
from typing import Any, Callable, Dict


def normalize_image_format(value: str, *, default: str) -> str:
    normalized = (value or "").strip().lower()
    if normalized == "jpeg":
        normalized = "jpg"
    if normalized in {"png", "jpg", "webp"}:
        return normalized
    return default


def normalize_image_detail(value: str, *, default: str) -> str:
    normalized = (value or "").strip().lower()
    if normalized in {"low", "high", "auto"}:
        return normalized
    return default


def estimate_data_url_bytes(data_url: str | None) -> int:
    if not data_url:
        return 0
    _, sep, payload = data_url.partition(",")
    if not sep or not payload:
        return 0
    # Base64 payload chars are 4/3 of decoded bytes.
    return int(math.ceil(len(payload) * 0.75))


def estimate_page_payload(
    *,
    system_message: str,
    user_message: str,
    clean_page_url: str | None,
    overlay_url: str | None,
    prev_page_url: str | None,
) -> Dict[str, int]:
    clean_bytes = estimate_data_url_bytes(clean_page_url)
    overlay_bytes = estimate_data_url_bytes(overlay_url)
    prev_bytes = estimate_data_url_bytes(prev_page_url)
    return {
        "prompt_chars": len(system_message or "") + len(user_message or ""),
        "clean_bytes": clean_bytes,
        "overlay_bytes": overlay_bytes,
        "prev_bytes": prev_bytes,
        "image_bytes": clean_bytes + overlay_bytes + prev_bytes,
    }


def budget_page_payload(
    *,
    page_idx: int,
    page_image: Any,
    overlay_image: Any,
    prev_crop_image: Any | None,
    system_message: str,
    user_message: str,
    clean_profile: Dict[str, Any],
    overlay_profile: Dict[str, Any],
    prev_detail: str,
    page_prompt_char_budget: int,
    page_image_byte_budget: int,
    overlay_min_dim: int,
    budget_clean_profile: Dict[str, Any],
    encode_model_image: Callable[..., str],
    logger: Any | None = None,
) -> Dict[str, Any]:
    """
    Encode page/overlay images and apply fallback reductions until within budget.
    """
    page_clean_max_dim = int(clean_profile["max_dim"])
    page_clean_quality = int(clean_profile["quality"])
    page_clean_format = str(clean_profile["format"])
    page_clean_detail = str(clean_profile["detail"])

    page_overlay_max_dim = int(overlay_profile["max_dim"])
    page_overlay_quality = int(overlay_profile["quality"])
    page_overlay_format = str(overlay_profile["format"])
    page_overlay_detail = str(overlay_profile["detail"])

    page_prev_detail = str(prev_detail)

    clean_page_url = encode_model_image(
        page_image,
        max_dim=page_clean_max_dim,
        format=page_clean_format,
        quality=page_clean_quality,
    )
    overlay_url = encode_model_image(
        overlay_image,
        max_dim=page_overlay_max_dim,
        format=page_overlay_format,
        quality=page_overlay_quality,
    )
    prev_page_url = None
    if prev_crop_image is not None:
        prev_page_url = encode_model_image(
            prev_crop_image,
            max_dim=page_clean_max_dim,
            format=page_clean_format,
            quality=page_clean_quality,
        )

    payload_metrics = estimate_page_payload(
        system_message=system_message,
        user_message=user_message,
        clean_page_url=clean_page_url,
        overlay_url=overlay_url,
        prev_page_url=prev_page_url,
    )

    if payload_metrics["image_bytes"] > page_image_byte_budget:
        page_clean_detail = "low"
        page_prev_detail = "low"
        tightened_clean_max_dim = min(page_clean_max_dim, int(budget_clean_profile["max_dim"]))
        tightened_clean_quality = min(page_clean_quality, int(budget_clean_profile["quality"]))
        tightened_clean_format = str(budget_clean_profile["format"])
        if (
            tightened_clean_max_dim != page_clean_max_dim
            or tightened_clean_quality != page_clean_quality
            or tightened_clean_format != page_clean_format
        ):
            page_clean_max_dim = tightened_clean_max_dim
            page_clean_quality = tightened_clean_quality
            page_clean_format = tightened_clean_format
            clean_page_url = encode_model_image(
                page_image,
                max_dim=page_clean_max_dim,
                format=page_clean_format,
                quality=page_clean_quality,
            )
            if prev_crop_image is not None:
                prev_page_url = encode_model_image(
                    prev_crop_image,
                    max_dim=page_clean_max_dim,
                    format=page_clean_format,
                    quality=page_clean_quality,
                )
            payload_metrics = estimate_page_payload(
                system_message=system_message,
                user_message=user_message,
                clean_page_url=clean_page_url,
                overlay_url=overlay_url,
                prev_page_url=prev_page_url,
            )

    if payload_metrics["image_bytes"] > page_image_byte_budget and prev_page_url:
        prev_page_url = None
        payload_metrics = estimate_page_payload(
            system_message=system_message,
            user_message=user_message,
            clean_page_url=clean_page_url,
            overlay_url=overlay_url,
            prev_page_url=prev_page_url,
        )

    min_overlay_dim_for_budget = max(256, min(page_overlay_max_dim, int(overlay_min_dim)))
    while payload_metrics["image_bytes"] > page_image_byte_budget and page_overlay_max_dim > min_overlay_dim_for_budget:
        next_dim = max(min_overlay_dim_for_budget, int(page_overlay_max_dim * 0.85))
        if next_dim >= page_overlay_max_dim:
            break
        page_overlay_max_dim = next_dim
        overlay_url = encode_model_image(
            overlay_image,
            max_dim=page_overlay_max_dim,
            format=page_overlay_format,
            quality=page_overlay_quality,
        )
        payload_metrics = estimate_page_payload(
            system_message=system_message,
            user_message=user_message,
            clean_page_url=clean_page_url,
            overlay_url=overlay_url,
            prev_page_url=prev_page_url,
        )

    if (
        payload_metrics["prompt_chars"] > page_prompt_char_budget
        or payload_metrics["image_bytes"] > page_image_byte_budget
    ) and logger:
        logger.warning(
            "Rename payload page %s still above budget (prompt=%s/%s, images=%s/%s).",
            page_idx,
            payload_metrics["prompt_chars"],
            page_prompt_char_budget,
            payload_metrics["image_bytes"],
            page_image_byte_budget,
        )

    return {
        "clean_page_url": clean_page_url,
        "clean_detail": page_clean_detail,
        "overlay_url": overlay_url,
        "overlay_detail": page_overlay_detail,
        "prev_page_url": prev_page_url,
        "prev_detail": page_prev_detail,
        "payload_metrics": payload_metrics,
    }
