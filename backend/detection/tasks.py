"""Cloud Tasks helpers for async detector jobs."""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

from google.protobuf import duration_pb2, timestamp_pb2

from ..env_utils import env_truthy, env_value
from ..firebaseDB.detection_database import detection_lane_busy
from ..logging_config import get_logger

DETECTOR_PROFILE_LIGHT = "light"
DETECTOR_PROFILE_HEAVY = "heavy"

DETECTOR_TARGET_CPU = "cpu"
DETECTOR_TARGET_GPU = "gpu"

DETECTOR_TASK_HANDLER = "/internal/detect"
_GPU_LANE_ACTIVE_WINDOW_SECONDS = 1800

logger = get_logger(__name__)


def _profile_env(base_key: str, profile: str) -> str:
    return env_value(f"{base_key}_{profile.upper()}")


def _gpu_profile_env(base_key: str, profile: str) -> str:
    return env_value(f"{base_key}_{profile.upper()}_GPU")


def _target_profile_env(base_key: str, profile: str, target: str) -> str:
    return env_value(f"{base_key}_{profile.upper()}_{target.upper()}")


def _target_env(base_key: str, target: str) -> str:
    return env_value(f"{base_key}_{target.upper()}")


def _safe_positive_int(value: str, default: int) -> int:
    raw = (value or "").strip()
    if not raw:
        return default
    try:
        parsed = int(raw)
    except ValueError:
        return default
    return parsed if parsed > 0 else default


def resolve_detector_profile(page_count: Optional[int]) -> str:
    threshold = _safe_positive_int(env_value("DETECTOR_TASKS_HEAVY_PAGE_THRESHOLD"), 10)
    heavy_enabled = bool(
        env_value("DETECTOR_TASKS_QUEUE_HEAVY")
        or env_value("DETECTOR_SERVICE_URL_HEAVY")
    )
    if heavy_enabled and page_count is not None and page_count >= threshold:
        return DETECTOR_PROFILE_HEAVY
    return DETECTOR_PROFILE_LIGHT


def _resolve_detector_runtime(profile: str) -> str:
    routing_mode = env_value("DETECTOR_ROUTING_MODE").lower()
    if routing_mode == "gpu":
        return DETECTOR_TARGET_GPU
    if routing_mode == "split" and profile == DETECTOR_PROFILE_HEAVY:
        return DETECTOR_TARGET_GPU
    return DETECTOR_TARGET_CPU


def _share_single_gpu_service() -> bool:
    return (
        env_value("DETECTOR_ROUTING_MODE").lower() == "gpu"
        and env_truthy("DETECTOR_SERIALIZE_GPU_TASKS")
    )


def _resolve_detector_queue_candidates(profile: str, target: str) -> list[str]:
    if (
        target == DETECTOR_TARGET_GPU
        and profile == DETECTOR_PROFILE_HEAVY
        and env_value("DETECTOR_ROUTING_MODE").lower() == "gpu"
        and env_truthy("DETECTOR_SERIALIZE_GPU_TASKS")
    ):
        return [env_value("DETECTOR_TASKS_QUEUE"), env_value("DETECTOR_TASKS_QUEUE_LIGHT")]
    return [
        _target_profile_env("DETECTOR_TASKS_QUEUE", profile, target),
        _target_env("DETECTOR_TASKS_QUEUE", target),
        _profile_env("DETECTOR_TASKS_QUEUE", profile),
        env_value("DETECTOR_TASKS_QUEUE"),
    ]


def _resolve_detector_service_url_candidates(profile: str, target: str) -> list[str]:
    effective_profile = profile
    if target == DETECTOR_TARGET_GPU and profile == DETECTOR_PROFILE_HEAVY and _share_single_gpu_service():
        effective_profile = DETECTOR_PROFILE_LIGHT
    candidates = [
        _target_profile_env("DETECTOR_SERVICE_URL", effective_profile, target),
        _target_env("DETECTOR_SERVICE_URL", target),
    ]
    if target == DETECTOR_TARGET_GPU:
        candidates.append(_gpu_profile_env("DETECTOR_SERVICE_URL", effective_profile))
    candidates.extend([
        _profile_env("DETECTOR_SERVICE_URL", effective_profile),
        env_value("DETECTOR_SERVICE_URL"),
    ])
    return candidates


def _resolve_detector_audience_candidates(profile: str, target: str) -> list[str]:
    effective_profile = profile
    if target == DETECTOR_TARGET_GPU and profile == DETECTOR_PROFILE_HEAVY and _share_single_gpu_service():
        effective_profile = DETECTOR_PROFILE_LIGHT
    candidates = [
        _target_profile_env("DETECTOR_TASKS_AUDIENCE", effective_profile, target),
        _target_env("DETECTOR_TASKS_AUDIENCE", target),
    ]
    if target == DETECTOR_TARGET_GPU:
        candidates.append(_gpu_profile_env("DETECTOR_TASKS_AUDIENCE", effective_profile))
    candidates.extend([
        _profile_env("DETECTOR_TASKS_AUDIENCE", effective_profile),
        env_value("DETECTOR_TASKS_AUDIENCE"),
    ])
    return candidates


def _first_non_empty(candidates: list[str]) -> str:
    for candidate in candidates:
        if candidate:
            return candidate.rstrip("/")
    return ""


def resolve_detector_target(profile: str, *, page_count: Optional[int]) -> str:
    target = _resolve_detector_runtime(profile)
    if target != DETECTOR_TARGET_GPU:
        return target
    if not env_truthy("DETECTOR_GPU_BUSY_FALLBACK_TO_CPU"):
        return target
    if not (_resolve_detector_queue_candidates(profile, DETECTOR_TARGET_CPU) and _resolve_detector_service_url_candidates(profile, DETECTOR_TARGET_CPU)):
        return target

    threshold = _safe_positive_int(env_value("DETECTOR_GPU_BUSY_FALLBACK_PAGE_THRESHOLD"), 0)
    if threshold > 0 and page_count is not None and page_count >= threshold:
        return target
    if threshold > 0 and page_count is None:
        return target

    try:
        if detection_lane_busy(DETECTOR_TARGET_GPU, active_window_seconds=_GPU_LANE_ACTIVE_WINDOW_SECONDS):
            return DETECTOR_TARGET_CPU
    except Exception as exc:
        logger.warning("Detector lane probe failed; keeping GPU target: %s", exc)
    return target


def resolve_task_config(profile: Optional[str], *, target: Optional[str] = None) -> Dict[str, str]:
    normalized_profile = (profile or DETECTOR_PROFILE_LIGHT).strip().lower()
    if normalized_profile not in {DETECTOR_PROFILE_LIGHT, DETECTOR_PROFILE_HEAVY}:
        normalized_profile = DETECTOR_PROFILE_LIGHT

    resolved_target = (target or _resolve_detector_runtime(normalized_profile)).strip().lower()
    if resolved_target not in {DETECTOR_TARGET_CPU, DETECTOR_TARGET_GPU}:
        resolved_target = DETECTOR_TARGET_CPU

    project = env_value("DETECTOR_TASKS_PROJECT") or env_value("GCP_PROJECT_ID")
    location = env_value("DETECTOR_TASKS_LOCATION")
    queue_candidates = _resolve_detector_queue_candidates(normalized_profile, resolved_target)
    service_url_candidates = _resolve_detector_service_url_candidates(normalized_profile, resolved_target)
    audience_candidates = _resolve_detector_audience_candidates(normalized_profile, resolved_target)
    queue = _first_non_empty(queue_candidates)
    service_url = _first_non_empty(service_url_candidates)
    service_account = env_value("DETECTOR_TASKS_SERVICE_ACCOUNT")
    audience = _first_non_empty(audience_candidates) or service_url

    missing = []
    if not project:
        missing.append("DETECTOR_TASKS_PROJECT (or GCP_PROJECT_ID)")
    if not location:
        missing.append("DETECTOR_TASKS_LOCATION")
    if not queue:
        missing.append(
            " or ".join(
                [
                    f"DETECTOR_TASKS_QUEUE_{normalized_profile.upper()}_{resolved_target.upper()}",
                    f"DETECTOR_TASKS_QUEUE_{resolved_target.upper()}",
                    f"DETECTOR_TASKS_QUEUE_{normalized_profile.upper()}",
                    "DETECTOR_TASKS_QUEUE",
                ]
            )
        )
    if not service_url:
        missing.append(
            " or ".join(
                [
                    f"DETECTOR_SERVICE_URL_{normalized_profile.upper()}_{resolved_target.upper()}",
                    f"DETECTOR_SERVICE_URL_{resolved_target.upper()}",
                    f"DETECTOR_SERVICE_URL_{normalized_profile.upper()}",
                    "DETECTOR_SERVICE_URL",
                ]
            )
        )
    if not service_account:
        missing.append("DETECTOR_TASKS_SERVICE_ACCOUNT")
    if missing:
        raise RuntimeError("Missing detector task config: " + ", ".join(missing))

    return {
        "profile": normalized_profile,
        "runtime": resolved_target,
        "target": resolved_target,
        "project": project,
        "location": location,
        "queue": queue,
        "service_url": service_url,
        "service_account": service_account,
        "audience": audience,
    }


def enqueue_detection_task(payload: Dict[str, Any], *, profile: Optional[str] = None) -> str:
    try:
        from google.cloud import tasks_v2
    except ImportError as exc:
        raise RuntimeError(
            "google-cloud-tasks is required for DETECTOR_MODE=tasks. "
            "Install backend/requirements.txt to enable Cloud Tasks."
        ) from exc

    resolved_profile = (profile or DETECTOR_PROFILE_LIGHT).strip().lower()
    config = resolve_task_config(
        resolved_profile,
        target=resolve_detector_target(resolved_profile, page_count=None),
    )
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

    deadline_raw = (
        _profile_env("DETECTOR_TASKS_DISPATCH_DEADLINE_SECONDS", config["profile"])
        or env_value("DETECTOR_TASKS_DISPATCH_DEADLINE_SECONDS")
    )
    if deadline_raw:
        deadline_seconds = _safe_positive_int(deadline_raw, 0)
        if deadline_seconds > 0:
            task["dispatch_deadline"] = duration_pb2.Duration(seconds=deadline_seconds)

    if env_truthy("DETECTOR_TASKS_FORCE_IMMEDIATE"):
        # Schedule in the past so Cloud Tasks dispatches immediately even if clocks drift.
        task["schedule_time"] = timestamp_pb2.Timestamp(seconds=0)

    response = client.create_task(request={"parent": parent, "task": task})
    return response.name
