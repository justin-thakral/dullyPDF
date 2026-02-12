"""Unit tests for backend.ai.openai_usage."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.ai import openai_usage


def test_normalize_responses_usage_handles_nested_details() -> None:
    response = SimpleNamespace(
        usage=SimpleNamespace(
            input_tokens=120,
            output_tokens=40,
            total_tokens=160,
            input_tokens_details=SimpleNamespace(cached_tokens=20),
            output_tokens_details=SimpleNamespace(reasoning_tokens=10),
        )
    )

    assert openai_usage.normalize_responses_usage(response) == {
        "input_tokens": 120,
        "output_tokens": 40,
        "total_tokens": 160,
        "cached_input_tokens": 20,
        "reasoning_output_tokens": 10,
    }


def test_normalize_chat_usage_handles_dict_payload() -> None:
    response = {
        "usage": {
            "prompt_tokens": 90,
            "completion_tokens": 30,
            "prompt_tokens_details": {"cached_tokens": 12},
            "completion_tokens_details": {"reasoning_tokens": 8},
        }
    }

    assert openai_usage.normalize_chat_usage(response) == {
        "input_tokens": 90,
        "output_tokens": 30,
        "total_tokens": 120,
        "cached_input_tokens": 12,
        "reasoning_output_tokens": 8,
    }


def test_build_openai_usage_summary_computes_estimated_cost_when_rates_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_PRICE_INPUT_PER_1M_USD", "2")
    monkeypatch.setenv("OPENAI_PRICE_OUTPUT_PER_1M_USD", "8")
    monkeypatch.setenv("OPENAI_PRICE_CACHED_INPUT_PER_1M_USD", "1")
    monkeypatch.setenv("OPENAI_PRICE_REASONING_OUTPUT_PER_1M_USD", "10")

    summary = openai_usage.build_openai_usage_summary(
        [
            {
                "input_tokens": 1000,
                "output_tokens": 200,
                "total_tokens": 1200,
                "cached_input_tokens": 200,
                "reasoning_output_tokens": 50,
            }
        ],
        model="gpt-5-mini",
    )

    # (800 * 2 + 200 * 1 + 150 * 8 + 50 * 10) / 1_000_000 = 0.0035
    assert summary["model"] == "gpt-5-mini"
    assert summary["calls"] == 1
    assert summary["estimated_cost_usd"] == pytest.approx(0.0035)


def test_is_insufficient_quota_error_detects_code_and_message() -> None:
    err_with_code = Exception("quota")
    setattr(err_with_code, "code", "insufficient_quota")
    assert openai_usage.is_insufficient_quota_error(err_with_code) is True

    err_with_message = Exception("Error code: 429 ... insufficient_quota ...")
    assert openai_usage.is_insufficient_quota_error(err_with_message) is True

    other = Exception("some other error")
    assert openai_usage.is_insufficient_quota_error(other) is False


def test_merge_usage_events_appends_attempt_metadata() -> None:
    existing = [{"input_tokens": 10, "output_tokens": 2, "total_tokens": 12}]
    merged = openai_usage.merge_usage_events(
        existing,
        [{"input_tokens": 20, "output_tokens": 4, "total_tokens": 24}],
        attempt=2,
    )

    assert len(merged) == 2
    assert merged[0]["total_tokens"] == 12
    assert merged[1]["total_tokens"] == 24
    assert merged[1]["attempt"] == 2
