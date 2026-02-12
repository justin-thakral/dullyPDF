"""Unit tests for backend.ai.openai_client."""

from __future__ import annotations

import pytest

from backend.ai import openai_client


@pytest.fixture(autouse=True)
def _clear_openai_client_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_REQUEST_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("OPENAI_MAX_RETRIES", raising=False)
    monkeypatch.delenv("OPENAI_WORKER_MAX_RETRIES", raising=False)


def test_resolve_openai_timeout_seconds_defaults_and_guards(monkeypatch: pytest.MonkeyPatch) -> None:
    assert openai_client.resolve_openai_timeout_seconds() == 75.0

    monkeypatch.setenv("OPENAI_REQUEST_TIMEOUT_SECONDS", "45")
    assert openai_client.resolve_openai_timeout_seconds() == 45.0

    monkeypatch.setenv("OPENAI_REQUEST_TIMEOUT_SECONDS", "0")
    assert openai_client.resolve_openai_timeout_seconds() == 75.0

    monkeypatch.setenv("OPENAI_REQUEST_TIMEOUT_SECONDS", "invalid")
    assert openai_client.resolve_openai_timeout_seconds() == 75.0


def test_resolve_openai_max_retries_defaults_and_guards(monkeypatch: pytest.MonkeyPatch) -> None:
    assert openai_client.resolve_openai_max_retries() == 1

    monkeypatch.setenv("OPENAI_MAX_RETRIES", "2")
    assert openai_client.resolve_openai_max_retries() == 2

    monkeypatch.setenv("OPENAI_MAX_RETRIES", "-1")
    assert openai_client.resolve_openai_max_retries() == 1

    monkeypatch.setenv("OPENAI_MAX_RETRIES", "invalid")
    assert openai_client.resolve_openai_max_retries() == 1


def test_create_openai_client_passes_resolved_config(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    class FakeOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(openai_client, "OpenAI", FakeOpenAI)
    monkeypatch.setenv("OPENAI_REQUEST_TIMEOUT_SECONDS", "33")
    monkeypatch.setenv("OPENAI_MAX_RETRIES", "0")

    created = openai_client.create_openai_client(api_key="test-key")

    assert isinstance(created, FakeOpenAI)
    assert captured == {
        "api_key": "test-key",
        "timeout": 33.0,
        "max_retries": 0,
    }


def test_create_openai_client_uses_override_for_max_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    class FakeOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(openai_client, "OpenAI", FakeOpenAI)
    monkeypatch.setenv("OPENAI_MAX_RETRIES", "7")

    created = openai_client.create_openai_client(max_retries_override=0)

    assert isinstance(created, FakeOpenAI)
    assert captured["max_retries"] == 0


def test_resolve_openai_worker_max_retries_defaults_and_guards(monkeypatch: pytest.MonkeyPatch) -> None:
    assert openai_client.resolve_openai_worker_max_retries() == 0

    monkeypatch.setenv("OPENAI_WORKER_MAX_RETRIES", "3")
    assert openai_client.resolve_openai_worker_max_retries() == 3

    monkeypatch.setenv("OPENAI_WORKER_MAX_RETRIES", "-2")
    assert openai_client.resolve_openai_worker_max_retries() == 0
