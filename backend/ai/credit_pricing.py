"""Credit pricing helpers for OpenAI rename/remap endpoints."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, Literal


OPENAI_CREDIT_OPERATION_RENAME = "rename"
OPENAI_CREDIT_OPERATION_REMAP = "remap"
OPENAI_CREDIT_OPERATION_RENAME_REMAP = "rename_remap"

CreditOperation = Literal[
    OPENAI_CREDIT_OPERATION_RENAME,
    OPENAI_CREDIT_OPERATION_REMAP,
    OPENAI_CREDIT_OPERATION_RENAME_REMAP,
]

_DEFAULT_PAGE_BUCKET_SIZE = 5
_DEFAULT_RENAME_BASE_COST = 1
_DEFAULT_REMAP_BASE_COST = 1
_DEFAULT_RENAME_REMAP_BASE_COST = 2


def _safe_positive_int_env(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _coerce_positive_int(value: Any) -> int:
    try:
        resolved = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("page_count must be a positive integer") from exc
    if resolved <= 0:
        raise ValueError("page_count must be a positive integer")
    return resolved


def _resolve_base_cost(operation: CreditOperation) -> int:
    if operation == OPENAI_CREDIT_OPERATION_RENAME:
        return _safe_positive_int_env(
            "OPENAI_CREDITS_RENAME_BASE_COST",
            _DEFAULT_RENAME_BASE_COST,
        )
    if operation == OPENAI_CREDIT_OPERATION_REMAP:
        return _safe_positive_int_env(
            "OPENAI_CREDITS_REMAP_BASE_COST",
            _DEFAULT_REMAP_BASE_COST,
        )
    if operation == OPENAI_CREDIT_OPERATION_RENAME_REMAP:
        return _safe_positive_int_env(
            "OPENAI_CREDITS_RENAME_REMAP_BASE_COST",
            _DEFAULT_RENAME_REMAP_BASE_COST,
        )
    raise ValueError(f"Unsupported credit pricing operation: {operation}")


def resolve_credit_pricing_config() -> Dict[str, int]:
    """Expose server-side credit pricing settings for client-side UX checks."""
    return {
        "pageBucketSize": _safe_positive_int_env(
            "OPENAI_CREDITS_PAGE_BUCKET_SIZE",
            _DEFAULT_PAGE_BUCKET_SIZE,
        ),
        "renameBaseCost": _resolve_base_cost(OPENAI_CREDIT_OPERATION_RENAME),
        "remapBaseCost": _resolve_base_cost(OPENAI_CREDIT_OPERATION_REMAP),
        "renameRemapBaseCost": _resolve_base_cost(OPENAI_CREDIT_OPERATION_RENAME_REMAP),
    }


@dataclass(frozen=True)
class CreditPricing:
    operation: CreditOperation
    page_count: int
    bucket_size: int
    bucket_count: int
    base_cost: int
    total_credits: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "operation": self.operation,
            "pageCount": self.page_count,
            "bucketSize": self.bucket_size,
            "bucketCount": self.bucket_count,
            "baseCost": self.base_cost,
            "totalCredits": self.total_credits,
        }


def compute_credit_pricing(operation: CreditOperation, *, page_count: Any) -> CreditPricing:
    """Return credit pricing using bucketed pages and operation base cost."""
    normalized_page_count = _coerce_positive_int(page_count)
    bucket_size = _safe_positive_int_env(
        "OPENAI_CREDITS_PAGE_BUCKET_SIZE",
        _DEFAULT_PAGE_BUCKET_SIZE,
    )
    base_cost = _resolve_base_cost(operation)
    bucket_count = (normalized_page_count + bucket_size - 1) // bucket_size
    total_credits = base_cost * bucket_count
    return CreditPricing(
        operation=operation,
        page_count=normalized_page_count,
        bucket_size=bucket_size,
        bucket_count=bucket_count,
        base_cost=base_cost,
        total_credits=total_credits,
    )
