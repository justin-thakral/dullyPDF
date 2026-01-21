"""Cloud Tasks helper for enqueuing detector jobs."""

import json
from typing import Any, Dict, Optional

from google.protobuf import duration_pb2, timestamp_pb2

from .env_utils import env_truthy, env_value, int_env


DETECTOR_TASK_HANDLER = "/internal/detect"
DETECTOR_PROFILE_HEAVY = "heavy"
DETECTOR_PROFILE_LIGHT = "light"


def resolve_detector_profile(page_count: Optional[int]) -> str:
    threshold = int_env("DETECTOR_TASKS_HEAVY_PAGE_THRESHOLD", 10)
    heavy_enabled = bool(
        env_value("DETECTOR_TASKS_QUEUE_HEAVY") or env_value("DETECTOR_SERVICE_URL_HEAVY")
    )
    if heavy_enabled and page_count is not None and page_count >= threshold:
        return DETECTOR_PROFILE_HEAVY
    return DETECTOR_PROFILE_LIGHT


def _profile_env(key: str, profile: str) -> str:
    return env_value(f"{key}_{profile.upper()}")


def resolve_task_config(profile: Optional[str]) -> Dict[str, str]:
    project = env_value("DETECTOR_TASKS_PROJECT") or env_value("GCP_PROJECT_ID")
    location = env_value("DETECTOR_TASKS_LOCATION")
    service_account = env_value("DETECTOR_TASKS_SERVICE_ACCOUNT")
    normalized_profile = profile or DETECTOR_PROFILE_LIGHT
    queue = _profile_env("DETECTOR_TASKS_QUEUE", normalized_profile) or env_value("DETECTOR_TASKS_QUEUE")
    service_url = (
        _profile_env("DETECTOR_SERVICE_URL", normalized_profile) or env_value("DETECTOR_SERVICE_URL")
    ).rstrip("/")
    audience = (
        _profile_env("DETECTOR_TASKS_AUDIENCE", normalized_profile)
        or env_value("DETECTOR_TASKS_AUDIENCE")
        or service_url
    )
    missing = []
    if not project:
        missing.append("DETECTOR_TASKS_PROJECT")
    if not location:
        missing.append("DETECTOR_TASKS_LOCATION")
    if not queue:
        missing.append(f"DETECTOR_TASKS_QUEUE_{normalized_profile.upper()} or DETECTOR_TASKS_QUEUE")
    if not service_url:
        missing.append(f"DETECTOR_SERVICE_URL_{normalized_profile.upper()} or DETECTOR_SERVICE_URL")
    if not service_account:
        missing.append("DETECTOR_TASKS_SERVICE_ACCOUNT")
    if missing:
        raise RuntimeError("Missing detector task config: " + ", ".join(missing))
    return {
        "project": project,
        "location": location,
        "queue": queue,
        "service_url": service_url,
        "service_account": service_account,
        "audience": audience,
        "profile": normalized_profile,
    }


def enqueue_detection_task(payload: Dict[str, Any], *, profile: Optional[str] = None) -> str:
    try:
        from google.cloud import tasks_v2
    except ImportError as exc:
        raise RuntimeError(
            "google-cloud-tasks is required for DETECTOR_MODE=tasks. "
            "Install backend/requirements.txt to enable Cloud Tasks."
        ) from exc
    config = resolve_task_config(profile)
    client = tasks_v2.CloudTasksClient()
    parent = client.queue_path(config["project"], config["location"], config["queue"])
    body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
    task = {
        "http_request": {
            "http_method": tasks_v2.HttpMethod.POST,
            "url": f"{config['service_url']}{DETECTOR_TASK_HANDLER}",
            "headers": {"Content-Type": "application/json"},
            "body": body,
            "oidc_token": {
                "service_account_email": config["service_account"],
                "audience": config["audience"],
            },
        }
    }
    deadline_raw = _profile_env(
        "DETECTOR_TASKS_DISPATCH_DEADLINE_SECONDS",
        config["profile"],
    ) or env_value("DETECTOR_TASKS_DISPATCH_DEADLINE_SECONDS")
    if deadline_raw:
        try:
            deadline_seconds = int(deadline_raw)
        except ValueError:
            deadline_seconds = 0
        if deadline_seconds > 0:
            task["dispatch_deadline"] = duration_pb2.Duration(seconds=deadline_seconds)
    if env_truthy("DETECTOR_TASKS_FORCE_IMMEDIATE"):
        # Schedule tasks in the past to dispatch immediately even if host clock skew exists.
        task["schedule_time"] = timestamp_pb2.Timestamp(seconds=0)
    response = client.create_task(request={"parent": parent, "task": task})
    return response.name
