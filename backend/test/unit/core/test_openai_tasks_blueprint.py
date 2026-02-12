"""Unit tests for backend.ai.tasks."""

from __future__ import annotations

import json
import sys
import types

import pytest

from backend.ai import tasks as openai_tasks


@pytest.fixture(autouse=True)
def _clear_openai_task_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in [
        "GCP_PROJECT_ID",
        "OPENAI_RENAME_TASKS_PROJECT",
        "OPENAI_RENAME_TASKS_LOCATION",
        "OPENAI_RENAME_TASKS_SERVICE_ACCOUNT",
        "OPENAI_RENAME_TASKS_QUEUE",
        "OPENAI_RENAME_TASKS_QUEUE_LIGHT",
        "OPENAI_RENAME_TASKS_QUEUE_HEAVY",
        "OPENAI_RENAME_SERVICE_URL",
        "OPENAI_RENAME_SERVICE_URL_LIGHT",
        "OPENAI_RENAME_SERVICE_URL_HEAVY",
        "OPENAI_RENAME_TASKS_AUDIENCE",
        "OPENAI_RENAME_TASKS_AUDIENCE_LIGHT",
        "OPENAI_RENAME_TASKS_AUDIENCE_HEAVY",
        "OPENAI_RENAME_TASKS_HEAVY_PAGE_THRESHOLD",
        "OPENAI_RENAME_TASKS_DISPATCH_DEADLINE_SECONDS",
        "OPENAI_RENAME_TASKS_DISPATCH_DEADLINE_SECONDS_LIGHT",
        "OPENAI_RENAME_TASKS_DISPATCH_DEADLINE_SECONDS_HEAVY",
        "OPENAI_RENAME_TASKS_FORCE_IMMEDIATE",
        "OPENAI_REMAP_TASKS_PROJECT",
        "OPENAI_REMAP_TASKS_LOCATION",
        "OPENAI_REMAP_TASKS_SERVICE_ACCOUNT",
        "OPENAI_REMAP_TASKS_QUEUE",
        "OPENAI_REMAP_TASKS_QUEUE_LIGHT",
        "OPENAI_REMAP_TASKS_QUEUE_HEAVY",
        "OPENAI_REMAP_SERVICE_URL",
        "OPENAI_REMAP_SERVICE_URL_LIGHT",
        "OPENAI_REMAP_SERVICE_URL_HEAVY",
        "OPENAI_REMAP_TASKS_AUDIENCE",
        "OPENAI_REMAP_TASKS_AUDIENCE_LIGHT",
        "OPENAI_REMAP_TASKS_AUDIENCE_HEAVY",
        "OPENAI_REMAP_TASKS_HEAVY_TAG_THRESHOLD",
        "OPENAI_REMAP_TASKS_DISPATCH_DEADLINE_SECONDS",
        "OPENAI_REMAP_TASKS_DISPATCH_DEADLINE_SECONDS_LIGHT",
        "OPENAI_REMAP_TASKS_DISPATCH_DEADLINE_SECONDS_HEAVY",
        "OPENAI_REMAP_TASKS_FORCE_IMMEDIATE",
        "OPENAI_TASKS_FORCE_IMMEDIATE",
    ]:
        monkeypatch.delenv(key, raising=False)


def _install_fake_tasks_v2(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    created_requests: list[dict] = []

    class FakeCloudTasksClient:
        def queue_path(self, project: str, location: str, queue: str) -> str:
            return f"projects/{project}/locations/{location}/queues/{queue}"

        def create_task(self, request: dict):
            created_requests.append(request)
            return types.SimpleNamespace(name="tasks/fake-openai-task")

    tasks_v2_module = types.ModuleType("google.cloud.tasks_v2")
    tasks_v2_module.CloudTasksClient = FakeCloudTasksClient
    tasks_v2_module.HttpMethod = types.SimpleNamespace(POST="POST")

    google_module = sys.modules.get("google")
    if google_module is None:
        google_module = types.ModuleType("google")
        monkeypatch.setitem(sys.modules, "google", google_module)

    cloud_module = types.ModuleType("google.cloud")
    cloud_module.tasks_v2 = tasks_v2_module
    setattr(google_module, "cloud", cloud_module)

    monkeypatch.setitem(sys.modules, "google.cloud", cloud_module)
    monkeypatch.setitem(sys.modules, "google.cloud.tasks_v2", tasks_v2_module)

    return created_requests


def test_resolve_openai_profiles_require_heavy_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_RENAME_TASKS_HEAVY_PAGE_THRESHOLD", "5")
    monkeypatch.setenv("OPENAI_RENAME_TASKS_QUEUE_HEAVY", "rename-heavy")
    assert openai_tasks.resolve_openai_rename_profile(5) == openai_tasks.OPENAI_TASK_PROFILE_HEAVY
    assert openai_tasks.resolve_openai_rename_profile(4) == openai_tasks.OPENAI_TASK_PROFILE_LIGHT

    monkeypatch.delenv("OPENAI_RENAME_TASKS_QUEUE_HEAVY", raising=False)
    assert openai_tasks.resolve_openai_rename_profile(100) == openai_tasks.OPENAI_TASK_PROFILE_LIGHT

    monkeypatch.setenv("OPENAI_REMAP_TASKS_HEAVY_TAG_THRESHOLD", "2")
    monkeypatch.setenv("OPENAI_REMAP_SERVICE_URL_HEAVY", "https://remap-heavy")
    assert openai_tasks.resolve_openai_remap_profile(2) == openai_tasks.OPENAI_TASK_PROFILE_HEAVY


def test_resolve_openai_task_config_raises_for_missing_matrix() -> None:
    with pytest.raises(RuntimeError, match="Missing OpenAI task config:") as excinfo:
        openai_tasks.resolve_openai_task_config("rename", "light")
    message = str(excinfo.value)
    assert "OPENAI_RENAME_TASKS_PROJECT" in message
    assert "OPENAI_RENAME_TASKS_LOCATION" in message


def test_enqueue_openai_rename_task_builds_expected_request(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_RENAME_TASKS_PROJECT", "project-a")
    monkeypatch.setenv("OPENAI_RENAME_TASKS_LOCATION", "us-central1")
    monkeypatch.setenv("OPENAI_RENAME_TASKS_SERVICE_ACCOUNT", "svc@example.com")
    monkeypatch.setenv("OPENAI_RENAME_TASKS_QUEUE_LIGHT", "openai-rename-light")
    monkeypatch.setenv("OPENAI_RENAME_SERVICE_URL_LIGHT", "https://rename.example.com/")
    monkeypatch.setenv("OPENAI_RENAME_TASKS_AUDIENCE_LIGHT", "rename-audience")
    monkeypatch.setenv("OPENAI_RENAME_TASKS_DISPATCH_DEADLINE_SECONDS_LIGHT", "25")
    monkeypatch.setenv("OPENAI_RENAME_TASKS_FORCE_IMMEDIATE", "true")

    created_requests = _install_fake_tasks_v2(monkeypatch)
    payload = {"jobId": "job-1", "sessionId": "sess-1"}

    task_name = openai_tasks.enqueue_openai_rename_task(payload, profile="light")

    assert task_name == "tasks/fake-openai-task"
    request = created_requests[0]
    assert request["parent"] == "projects/project-a/locations/us-central1/queues/openai-rename-light"
    task = request["task"]
    http_request = task["http_request"]
    assert http_request["url"] == "https://rename.example.com/internal/rename"
    assert http_request["body"] == json.dumps(payload, ensure_ascii=True).encode("utf-8")
    assert http_request["oidc_token"] == {
        "service_account_email": "svc@example.com",
        "audience": "rename-audience",
    }
    assert task["dispatch_deadline"].seconds == 25
    assert task["schedule_time"].seconds == 0


def test_enqueue_openai_remap_task_uses_profile_specific_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_REMAP_TASKS_PROJECT", "project-a")
    monkeypatch.setenv("OPENAI_REMAP_TASKS_LOCATION", "us-central1")
    monkeypatch.setenv("OPENAI_REMAP_TASKS_SERVICE_ACCOUNT", "svc@example.com")
    monkeypatch.setenv("OPENAI_REMAP_TASKS_QUEUE_HEAVY", "openai-remap-heavy")
    monkeypatch.setenv("OPENAI_REMAP_SERVICE_URL_HEAVY", "https://remap.example.com///")

    created_requests = _install_fake_tasks_v2(monkeypatch)

    openai_tasks.enqueue_openai_remap_task({"jobId": "job-2"}, profile="heavy")

    request = created_requests[0]
    task = request["task"]
    assert request["parent"] == "projects/project-a/locations/us-central1/queues/openai-remap-heavy"
    assert task["http_request"]["url"] == "https://remap.example.com/internal/remap"
    # With no explicit audience env var, it falls back to service URL.
    assert task["http_request"]["oidc_token"]["audience"] == "https://remap.example.com"
