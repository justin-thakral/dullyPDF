from __future__ import annotations

import pytest

from backend.ai.credit_pricing import (
    OPENAI_CREDIT_OPERATION_REMAP,
    OPENAI_CREDIT_OPERATION_RENAME,
    OPENAI_CREDIT_OPERATION_RENAME_REMAP,
    compute_credit_pricing,
)


@pytest.mark.parametrize(
    ("operation", "page_count", "expected_credits"),
    [
        (OPENAI_CREDIT_OPERATION_RENAME, 1, 1),
        (OPENAI_CREDIT_OPERATION_RENAME, 5, 1),
        (OPENAI_CREDIT_OPERATION_RENAME, 6, 2),
        (OPENAI_CREDIT_OPERATION_RENAME, 12, 3),
        (OPENAI_CREDIT_OPERATION_REMAP, 10, 2),
        (OPENAI_CREDIT_OPERATION_REMAP, 12, 3),
        (OPENAI_CREDIT_OPERATION_RENAME_REMAP, 10, 4),
        (OPENAI_CREDIT_OPERATION_RENAME_REMAP, 11, 6),
        (OPENAI_CREDIT_OPERATION_RENAME_REMAP, 12, 6),
    ],
)
def test_compute_credit_pricing_uses_page_buckets(operation: str, page_count: int, expected_credits: int) -> None:
    pricing = compute_credit_pricing(operation, page_count=page_count)
    assert pricing.total_credits == expected_credits


@pytest.mark.parametrize("bad_page_count", [0, -1, "bad", None])
def test_compute_credit_pricing_rejects_invalid_page_count(bad_page_count) -> None:
    with pytest.raises(ValueError):
        compute_credit_pricing(OPENAI_CREDIT_OPERATION_RENAME, page_count=bad_page_count)


def test_compute_credit_pricing_respects_env_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_CREDITS_PAGE_BUCKET_SIZE", "4")
    monkeypatch.setenv("OPENAI_CREDITS_RENAME_REMAP_BASE_COST", "3")
    pricing = compute_credit_pricing(OPENAI_CREDIT_OPERATION_RENAME_REMAP, page_count=10)
    assert pricing.bucket_size == 4
    assert pricing.bucket_count == 3
    assert pricing.base_cost == 3
    assert pricing.total_credits == 9


def test_compute_credit_pricing_to_dict_contains_expected_fields() -> None:
    pricing = compute_credit_pricing(OPENAI_CREDIT_OPERATION_REMAP, page_count=12)
    assert pricing.to_dict() == {
        "operation": OPENAI_CREDIT_OPERATION_REMAP,
        "pageCount": 12,
        "bucketSize": 5,
        "bucketCount": 3,
        "baseCost": 1,
        "totalCredits": 3,
    }
