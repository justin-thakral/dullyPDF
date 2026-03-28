"""Unit tests for backend.detection_tasks."""

import builtins
import json
import sys
import types

import pytest

from backend.detection import tasks as detection_tasks


@pytest.fixture(autouse=True)
def _clear_detector_task_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in [
        "GCP_PROJECT_ID",
        "DETECTOR_TASKS_PROJECT",
        "DETECTOR_TASKS_LOCATION",
        "DETECTOR_TASKS_SERVICE_ACCOUNT",
        "DETECTOR_TASKS_QUEUE",
        "DETECTOR_TASKS_QUEUE_CPU",
        "DETECTOR_TASKS_QUEUE_GPU",
        "DETECTOR_TASKS_QUEUE_LIGHT",
        "DETECTOR_TASKS_QUEUE_HEAVY",
        "DETECTOR_TASKS_QUEUE_LIGHT_CPU",
        "DETECTOR_TASKS_QUEUE_HEAVY_CPU",
        "DETECTOR_TASKS_QUEUE_LIGHT_GPU",
        "DETECTOR_TASKS_QUEUE_HEAVY_GPU",
        "DETECTOR_SERVICE_URL",
        "DETECTOR_SERVICE_URL_CPU",
        "DETECTOR_SERVICE_URL_GPU",
        "DETECTOR_SERVICE_URL_LIGHT",
        "DETECTOR_SERVICE_URL_HEAVY",
        "DETECTOR_SERVICE_URL_LIGHT_CPU",
        "DETECTOR_SERVICE_URL_HEAVY_CPU",
        "DETECTOR_SERVICE_URL_LIGHT_GPU",
        "DETECTOR_SERVICE_URL_HEAVY_GPU",
        "DETECTOR_TASKS_AUDIENCE",
        "DETECTOR_TASKS_AUDIENCE_CPU",
        "DETECTOR_TASKS_AUDIENCE_GPU",
        "DETECTOR_TASKS_AUDIENCE_LIGHT",
        "DETECTOR_TASKS_AUDIENCE_HEAVY",
        "DETECTOR_TASKS_AUDIENCE_LIGHT_CPU",
        "DETECTOR_TASKS_AUDIENCE_HEAVY_CPU",
        "DETECTOR_TASKS_AUDIENCE_LIGHT_GPU",
        "DETECTOR_TASKS_AUDIENCE_HEAVY_GPU",
        "DETECTOR_TASKS_HEAVY_PAGE_THRESHOLD",
        "DETECTOR_TASKS_DISPATCH_DEADLINE_SECONDS",
        "DETECTOR_TASKS_DISPATCH_DEADLINE_SECONDS_LIGHT",
        "DETECTOR_TASKS_DISPATCH_DEADLINE_SECONDS_HEAVY",
        "DETECTOR_TASKS_FORCE_IMMEDIATE",
        "DETECTOR_ROUTING_MODE",
        "DETECTOR_SERIALIZE_GPU_TASKS",
        "DETECTOR_GPU_BUSY_FALLBACK_TO_CPU",
        "DETECTOR_GPU_BUSY_FALLBACK_PAGE_THRESHOLD",
        "DETECTOR_GPU_BUSY_ACTIVE_WINDOW_SECONDS",
    ]:
        monkeypatch.delenv(key, raising=False)


def _install_fake_tasks_v2(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    created_requests: list[dict] = []

    class FakeCloudTasksClient:
        def queue_path(self, project: str, location: str, queue: str) -> str:
            return f"projects/{project}/locations/{location}/queues/{queue}"

        def create_task(self, request: dict):
            created_requests.append(request)
            return types.SimpleNamespace(name="tasks/fake-task-id")

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


def test_resolve_detector_profile_requires_heavy_config_and_threshold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DETECTOR_TASKS_HEAVY_PAGE_THRESHOLD", "5")
    monkeypatch.setenv("DETECTOR_TASKS_QUEUE_HEAVY", "heavy-queue")

    assert detection_tasks.resolve_detector_profile(page_count=5) == detection_tasks.DETECTOR_PROFILE_HEAVY
    assert detection_tasks.resolve_detector_profile(page_count=4) == detection_tasks.DETECTOR_PROFILE_LIGHT

    monkeypatch.delenv("DETECTOR_TASKS_QUEUE_HEAVY", raising=False)
    assert detection_tasks.resolve_detector_profile(page_count=10) == detection_tasks.DETECTOR_PROFILE_LIGHT


def test_resolve_task_config_applies_profile_overrides_and_trims_service_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DETECTOR_TASKS_PROJECT", "project-a")
    monkeypatch.setenv("DETECTOR_TASKS_LOCATION", "us-central1")
    monkeypatch.setenv("DETECTOR_TASKS_SERVICE_ACCOUNT", "svc@example.com")
    monkeypatch.setenv("DETECTOR_TASKS_QUEUE", "default-queue")
    monkeypatch.setenv("DETECTOR_SERVICE_URL", "https://default.example.com/")
    monkeypatch.setenv("DETECTOR_TASKS_AUDIENCE", "default-audience")
    monkeypatch.setenv("DETECTOR_TASKS_QUEUE_HEAVY", "heavy-queue")
    monkeypatch.setenv("DETECTOR_SERVICE_URL_HEAVY", "https://heavy.example.com///")
    monkeypatch.setenv("DETECTOR_TASKS_AUDIENCE_HEAVY", "heavy-audience")

    config = detection_tasks.resolve_task_config(detection_tasks.DETECTOR_PROFILE_HEAVY)

    assert config["project"] == "project-a"
    assert config["location"] == "us-central1"
    assert config["service_account"] == "svc@example.com"
    assert config["queue"] == "heavy-queue"
    assert config["service_url"] == "https://heavy.example.com"
    assert config["audience"] == "heavy-audience"
    assert config["profile"] == detection_tasks.DETECTOR_PROFILE_HEAVY


def test_resolve_task_config_serializes_gpu_tasks_onto_shared_queue_and_shared_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DETECTOR_ROUTING_MODE", "gpu")
    monkeypatch.setenv("DETECTOR_SERIALIZE_GPU_TASKS", "true")
    monkeypatch.setenv("DETECTOR_TASKS_PROJECT", "project-a")
    monkeypatch.setenv("DETECTOR_TASKS_LOCATION", "us-central1")
    monkeypatch.setenv("DETECTOR_TASKS_SERVICE_ACCOUNT", "svc@example.com")
    monkeypatch.setenv("DETECTOR_TASKS_QUEUE", "shared-queue")
    monkeypatch.setenv("DETECTOR_TASKS_QUEUE_HEAVY", "heavy-queue")
    monkeypatch.setenv("DETECTOR_SERVICE_URL", "https://default.example.com/")
    monkeypatch.setenv("DETECTOR_SERVICE_URL_HEAVY", "https://heavy.example.com/")

    config = detection_tasks.resolve_task_config(detection_tasks.DETECTOR_PROFILE_HEAVY)

    assert config["queue"] == "shared-queue"
    assert config["service_url"] == "https://default.example.com"
    assert config["profile"] == detection_tasks.DETECTOR_PROFILE_HEAVY


def test_resolve_task_config_serialized_single_gpu_mode_reuses_light_gpu_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DETECTOR_ROUTING_MODE", "gpu")
    monkeypatch.setenv("DETECTOR_SERIALIZE_GPU_TASKS", "true")
    monkeypatch.setenv("DETECTOR_TASKS_PROJECT", "project-a")
    monkeypatch.setenv("DETECTOR_TASKS_LOCATION", "us-central1")
    monkeypatch.setenv("DETECTOR_TASKS_SERVICE_ACCOUNT", "svc@example.com")
    monkeypatch.setenv("DETECTOR_TASKS_QUEUE", "shared-queue")
    monkeypatch.setenv("DETECTOR_SERVICE_URL_LIGHT_GPU", "https://gpu-light.example.com/")
    monkeypatch.setenv("DETECTOR_SERVICE_URL_HEAVY_GPU", "https://gpu-heavy.example.com/")
    monkeypatch.setenv("DETECTOR_TASKS_AUDIENCE_LIGHT_GPU", "gpu-light-audience")
    monkeypatch.setenv("DETECTOR_TASKS_AUDIENCE_HEAVY_GPU", "gpu-heavy-audience")

    config = detection_tasks.resolve_task_config(detection_tasks.DETECTOR_PROFILE_HEAVY)

    assert config["queue"] == "shared-queue"
    assert config["service_url"] == "https://gpu-light.example.com"
    assert config["audience"] == "gpu-light-audience"
    assert config["profile"] == detection_tasks.DETECTOR_PROFILE_HEAVY


def test_resolve_detector_target_uses_cpu_fallback_for_small_pdfs_when_gpu_lane_is_busy(
    monkeypatch: pytest.MonkeyPatch,
    mocker,
) -> None:
    monkeypatch.setenv("DETECTOR_ROUTING_MODE", "gpu")
    monkeypatch.setenv("DETECTOR_GPU_BUSY_FALLBACK_TO_CPU", "true")
    monkeypatch.setenv("DETECTOR_GPU_BUSY_FALLBACK_PAGE_THRESHOLD", "5")
    monkeypatch.setenv("DETECTOR_TASKS_QUEUE_LIGHT_CPU", "cpu-light")
    monkeypatch.setenv("DETECTOR_SERVICE_URL_LIGHT_CPU", "https://cpu.example.com")
    lane_busy_mock = mocker.patch.object(detection_tasks, "detection_lane_busy", return_value=True)

    target = detection_tasks.resolve_detector_target(detection_tasks.DETECTOR_PROFILE_LIGHT, page_count=4)

    assert target == detection_tasks.DETECTOR_TARGET_CPU
    lane_busy_mock.assert_called_once_with(detection_tasks.DETECTOR_TARGET_GPU, active_window_seconds=1800)


def test_resolve_detector_target_keeps_gpu_for_five_page_pdf_even_when_gpu_lane_is_busy(
    monkeypatch: pytest.MonkeyPatch,
    mocker,
) -> None:
    monkeypatch.setenv("DETECTOR_ROUTING_MODE", "gpu")
    monkeypatch.setenv("DETECTOR_GPU_BUSY_FALLBACK_TO_CPU", "true")
    monkeypatch.setenv("DETECTOR_GPU_BUSY_FALLBACK_PAGE_THRESHOLD", "5")
    monkeypatch.setenv("DETECTOR_TASKS_QUEUE_LIGHT_CPU", "cpu-light")
    monkeypatch.setenv("DETECTOR_SERVICE_URL_LIGHT_CPU", "https://cpu.example.com")
    lane_busy_mock = mocker.patch.object(detection_tasks, "detection_lane_busy", return_value=True)

    target = detection_tasks.resolve_detector_target(detection_tasks.DETECTOR_PROFILE_LIGHT, page_count=5)

    assert target == detection_tasks.DETECTOR_TARGET_GPU
    lane_busy_mock.assert_not_called()


def test_resolve_detector_target_defaults_to_gpu_when_lane_probe_fails(
    monkeypatch: pytest.MonkeyPatch,
    mocker,
) -> None:
    monkeypatch.setenv("DETECTOR_ROUTING_MODE", "gpu")
    monkeypatch.setenv("DETECTOR_GPU_BUSY_FALLBACK_TO_CPU", "true")
    monkeypatch.setenv("DETECTOR_TASKS_QUEUE_LIGHT_CPU", "cpu-light")
    monkeypatch.setenv("DETECTOR_SERVICE_URL_LIGHT_CPU", "https://cpu.example.com")
    mocker.patch.object(detection_tasks, "detection_lane_busy", side_effect=RuntimeError("firestore down"))

    target = detection_tasks.resolve_detector_target(detection_tasks.DETECTOR_PROFILE_LIGHT, page_count=2)

    assert target == detection_tasks.DETECTOR_TARGET_GPU


def test_resolve_task_config_uses_explicit_cpu_target_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DETECTOR_ROUTING_MODE", "gpu")
    monkeypatch.setenv("DETECTOR_TASKS_PROJECT", "project-a")
    monkeypatch.setenv("DETECTOR_TASKS_LOCATION", "us-central1")
    monkeypatch.setenv("DETECTOR_TASKS_SERVICE_ACCOUNT", "svc@example.com")
    monkeypatch.setenv("DETECTOR_TASKS_QUEUE_LIGHT", "gpu-light")
    monkeypatch.setenv("DETECTOR_SERVICE_URL_LIGHT", "https://gpu.example.com")
    monkeypatch.setenv("DETECTOR_TASKS_QUEUE_LIGHT_CPU", "cpu-light")
    monkeypatch.setenv("DETECTOR_SERVICE_URL_LIGHT_CPU", "https://cpu.example.com/")
    monkeypatch.setenv("DETECTOR_TASKS_AUDIENCE_LIGHT_CPU", "cpu-aud")

    config = detection_tasks.resolve_task_config(
        detection_tasks.DETECTOR_PROFILE_LIGHT,
        target=detection_tasks.DETECTOR_TARGET_CPU,
    )

    assert config["queue"] == "cpu-light"
    assert config["service_url"] == "https://cpu.example.com"
    assert config["audience"] == "cpu-aud"
    assert config["target"] == detection_tasks.DETECTOR_TARGET_CPU


def test_resolve_task_config_raises_with_missing_required_values() -> None:
    with pytest.raises(RuntimeError, match="Missing detector task config:") as excinfo:
        detection_tasks.resolve_task_config(None)
    message = str(excinfo.value)

    assert "DETECTOR_TASKS_PROJECT" in message
    assert "DETECTOR_TASKS_LOCATION" in message
    assert "DETECTOR_TASKS_SERVICE_ACCOUNT" in message
    assert "DETECTOR_TASKS_QUEUE_LIGHT_CPU or DETECTOR_TASKS_QUEUE_CPU or DETECTOR_TASKS_QUEUE_LIGHT or DETECTOR_TASKS_QUEUE" in message
    assert "DETECTOR_SERVICE_URL_LIGHT_CPU or DETECTOR_SERVICE_URL_CPU or DETECTOR_SERVICE_URL_LIGHT or DETECTOR_SERVICE_URL" in message


def test_enqueue_detection_task_builds_expected_cloud_tasks_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DETECTOR_TASKS_PROJECT", "project-a")
    monkeypatch.setenv("DETECTOR_TASKS_LOCATION", "us-central1")
    monkeypatch.setenv("DETECTOR_TASKS_SERVICE_ACCOUNT", "svc@example.com")
    monkeypatch.setenv("DETECTOR_TASKS_QUEUE", "detector-light")
    monkeypatch.setenv("DETECTOR_SERVICE_URL", "https://detector.example.com/")
    monkeypatch.setenv("DETECTOR_TASKS_AUDIENCE", "detector-audience")
    monkeypatch.setenv("DETECTOR_TASKS_DISPATCH_DEADLINE_SECONDS", "30")
    monkeypatch.setenv("DETECTOR_TASKS_FORCE_IMMEDIATE", "true")

    created_requests = _install_fake_tasks_v2(monkeypatch)
    payload = {"jobId": "job-1", "sessionId": "session-1"}

    task_name = detection_tasks.enqueue_detection_task(payload)

    assert task_name == "tasks/fake-task-id"
    assert len(created_requests) == 1
    request = created_requests[0]
    assert request["parent"] == "projects/project-a/locations/us-central1/queues/detector-light"
    task = request["task"]
    http_request = task["http_request"]
    assert http_request["http_method"] == "POST"
    assert http_request["url"] == "https://detector.example.com/internal/detect"
    assert http_request["headers"] == {"Content-Type": "application/json"}
    assert http_request["body"] == json.dumps(payload, ensure_ascii=True).encode("utf-8")
    assert http_request["oidc_token"] == {
        "service_account_email": "svc@example.com",
        "audience": "detector-audience",
    }
    assert task["dispatch_deadline"].seconds == 30
    assert task["schedule_time"].seconds == 0


def test_enqueue_detection_task_ignores_invalid_dispatch_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DETECTOR_TASKS_PROJECT", "project-a")
    monkeypatch.setenv("DETECTOR_TASKS_LOCATION", "us-central1")
    monkeypatch.setenv("DETECTOR_TASKS_SERVICE_ACCOUNT", "svc@example.com")
    monkeypatch.setenv("DETECTOR_TASKS_QUEUE", "detector-light")
    monkeypatch.setenv("DETECTOR_SERVICE_URL", "https://detector.example.com")
    monkeypatch.setenv("DETECTOR_TASKS_DISPATCH_DEADLINE_SECONDS", "not-an-int")

    created_requests = _install_fake_tasks_v2(monkeypatch)

    detection_tasks.enqueue_detection_task({"jobId": "job-1"})

    request = created_requests[0]
    assert "dispatch_deadline" not in request["task"]


def test_enqueue_detection_task_raises_when_cloud_tasks_dependency_missing(
    mocker,
) -> None:
    real_import = builtins.__import__

    def _import_with_missing_tasks(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "google.cloud" and "tasks_v2" in fromlist:
            raise ImportError("missing google.cloud.tasks_v2")
        return real_import(name, globals, locals, fromlist, level)

    mocker.patch("builtins.__import__", side_effect=_import_with_missing_tasks)

    with pytest.raises(
        RuntimeError,
        match="google-cloud-tasks is required for DETECTOR_MODE=tasks",
    ):
        detection_tasks.enqueue_detection_task({"jobId": "job-1"})


# --- Edge case tests ---


def test_resolve_detector_profile_returns_light_when_page_count_is_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """page_count=None should always return LIGHT even when heavy is fully
    configured, because the source explicitly checks `page_count is not None`."""
    monkeypatch.setenv("DETECTOR_TASKS_HEAVY_PAGE_THRESHOLD", "1")
    monkeypatch.setenv("DETECTOR_TASKS_QUEUE_HEAVY", "heavy-queue")
    monkeypatch.setenv("DETECTOR_SERVICE_URL_HEAVY", "https://heavy.example.com")
    assert detection_tasks.resolve_detector_profile(page_count=None) == detection_tasks.DETECTOR_PROFILE_LIGHT


def test_resolve_detector_profile_enables_heavy_via_service_url_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Heavy should be enabled when DETECTOR_SERVICE_URL_HEAVY is set even if
    DETECTOR_TASKS_QUEUE_HEAVY is not (the or check on line 18-19)."""
    monkeypatch.setenv("DETECTOR_TASKS_HEAVY_PAGE_THRESHOLD", "3")
    monkeypatch.setenv("DETECTOR_SERVICE_URL_HEAVY", "https://heavy.example.com")
    assert detection_tasks.resolve_detector_profile(page_count=5) == detection_tasks.DETECTOR_PROFILE_HEAVY


def test_resolve_task_config_falls_back_to_gcp_project_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When DETECTOR_TASKS_PROJECT is unset, GCP_PROJECT_ID should be used."""
    monkeypatch.setenv("GCP_PROJECT_ID", "fallback-project")
    monkeypatch.setenv("DETECTOR_TASKS_LOCATION", "us-central1")
    monkeypatch.setenv("DETECTOR_TASKS_SERVICE_ACCOUNT", "svc@example.com")
    monkeypatch.setenv("DETECTOR_TASKS_QUEUE", "q")
    monkeypatch.setenv("DETECTOR_SERVICE_URL", "https://detector.example.com")

    config = detection_tasks.resolve_task_config(None)
    assert config["project"] == "fallback-project"


def test_resolve_task_config_audience_falls_back_to_service_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When neither profile-specific nor generic audience env vars are set,
    audience should fall back to service_url (line 42)."""
    monkeypatch.setenv("DETECTOR_TASKS_PROJECT", "p")
    monkeypatch.setenv("DETECTOR_TASKS_LOCATION", "loc")
    monkeypatch.setenv("DETECTOR_TASKS_SERVICE_ACCOUNT", "svc@example.com")
    monkeypatch.setenv("DETECTOR_TASKS_QUEUE", "q")
    monkeypatch.setenv("DETECTOR_SERVICE_URL", "https://detector.example.com/")

    config = detection_tasks.resolve_task_config(None)
    assert config["audience"] == "https://detector.example.com"


def test_resolve_task_config_uses_light_profile_env_vars(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify light-profile-specific env vars are resolved correctly."""
    monkeypatch.setenv("DETECTOR_TASKS_PROJECT", "p")
    monkeypatch.setenv("DETECTOR_TASKS_LOCATION", "loc")
    monkeypatch.setenv("DETECTOR_TASKS_SERVICE_ACCOUNT", "svc@example.com")
    monkeypatch.setenv("DETECTOR_TASKS_QUEUE_LIGHT", "light-queue")
    monkeypatch.setenv("DETECTOR_SERVICE_URL_LIGHT", "https://light.example.com")
    monkeypatch.setenv("DETECTOR_TASKS_AUDIENCE_LIGHT", "light-aud")

    config = detection_tasks.resolve_task_config(detection_tasks.DETECTOR_PROFILE_LIGHT)
    assert config["queue"] == "light-queue"
    assert config["service_url"] == "https://light.example.com"
    assert config["audience"] == "light-aud"
    assert config["profile"] == detection_tasks.DETECTOR_PROFILE_LIGHT


def test_enqueue_detection_task_with_explicit_profile_kwarg(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Passing an explicit profile kwarg should override the default None."""
    monkeypatch.setenv("DETECTOR_TASKS_PROJECT", "p")
    monkeypatch.setenv("DETECTOR_TASKS_LOCATION", "loc")
    monkeypatch.setenv("DETECTOR_TASKS_SERVICE_ACCOUNT", "svc@example.com")
    monkeypatch.setenv("DETECTOR_TASKS_QUEUE_HEAVY", "heavy-q")
    monkeypatch.setenv("DETECTOR_SERVICE_URL_HEAVY", "https://heavy.example.com")

    created_requests = _install_fake_tasks_v2(monkeypatch)
    detection_tasks.enqueue_detection_task(
        {"jobId": "j1"}, profile=detection_tasks.DETECTOR_PROFILE_HEAVY
    )
    request = created_requests[0]
    assert "heavy-q" in request["parent"]
