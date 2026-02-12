"""Cloud Tasks helpers for async OpenAI rename/remap jobs."""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

from google.protobuf import duration_pb2, timestamp_pb2

from ..env_utils import env_truthy, env_value

OPENAI_TASK_PROFILE_LIGHT = "light"
OPENAI_TASK_PROFILE_HEAVY = "heavy"

OPENAI_RENAME_TASK_HANDLER = "/internal/rename"
OPENAI_REMAP_TASK_HANDLER = "/internal/remap"

_SUPPORTED_KINDS = {"rename", "remap"}


def _kind_prefix(kind: str) -> str:
    normalized = (kind or "").strip().lower()
    if normalized not in _SUPPORTED_KINDS:
        raise ValueError(f"Unsupported OpenAI task kind: {kind}")
    return "OPENAI_RENAME" if normalized == "rename" else "OPENAI_REMAP"


def _profile_env(base_key: str, profile: str) -> str:
    return env_value(f"{base_key}_{profile.upper()}")


def _safe_positive_int(value: str, default: int) -> int:
    raw = (value or "").strip()
    if not raw:
        return default
    try:
        parsed = int(raw)
    except ValueError:
        return default
    return parsed if parsed > 0 else default


def resolve_openai_rename_profile(page_count: Optional[int]) -> str:
    threshold = _safe_positive_int(env_value("OPENAI_RENAME_TASKS_HEAVY_PAGE_THRESHOLD"), 10)
    heavy_enabled = bool(
        env_value("OPENAI_RENAME_TASKS_QUEUE_HEAVY")
        or env_value("OPENAI_RENAME_SERVICE_URL_HEAVY")
    )
    if heavy_enabled and page_count is not None and page_count >= threshold:
        return OPENAI_TASK_PROFILE_HEAVY
    return OPENAI_TASK_PROFILE_LIGHT


def resolve_openai_remap_profile(template_field_count: Optional[int]) -> str:
    threshold = _safe_positive_int(env_value("OPENAI_REMAP_TASKS_HEAVY_TAG_THRESHOLD"), 120)
    heavy_enabled = bool(
        env_value("OPENAI_REMAP_TASKS_QUEUE_HEAVY")
        or env_value("OPENAI_REMAP_SERVICE_URL_HEAVY")
    )
    if heavy_enabled and template_field_count is not None and template_field_count >= threshold:
        return OPENAI_TASK_PROFILE_HEAVY
    return OPENAI_TASK_PROFILE_LIGHT


def resolve_openai_task_config(kind: str, profile: Optional[str]) -> Dict[str, str]:
    prefix = _kind_prefix(kind)
    normalized_profile = (profile or OPENAI_TASK_PROFILE_LIGHT).strip().lower()
    if normalized_profile not in {OPENAI_TASK_PROFILE_LIGHT, OPENAI_TASK_PROFILE_HEAVY}:
        normalized_profile = OPENAI_TASK_PROFILE_LIGHT

    project = env_value(f"{prefix}_TASKS_PROJECT") or env_value("GCP_PROJECT_ID")
    location = env_value(f"{prefix}_TASKS_LOCATION")
    queue = _profile_env(f"{prefix}_TASKS_QUEUE", normalized_profile) or env_value(
        f"{prefix}_TASKS_QUEUE"
    )
    service_url = (
        _profile_env(f"{prefix}_SERVICE_URL", normalized_profile)
        or env_value(f"{prefix}_SERVICE_URL")
    ).rstrip("/")
    service_account = env_value(f"{prefix}_TASKS_SERVICE_ACCOUNT")
    audience = (
        _profile_env(f"{prefix}_TASKS_AUDIENCE", normalized_profile)
        or env_value(f"{prefix}_TASKS_AUDIENCE")
        or service_url
    )

    missing = []
    if not project:
        missing.append(f"{prefix}_TASKS_PROJECT (or GCP_PROJECT_ID)")
    if not location:
        missing.append(f"{prefix}_TASKS_LOCATION")
    if not queue:
        missing.append(f"{prefix}_TASKS_QUEUE_{normalized_profile.upper()} or {prefix}_TASKS_QUEUE")
    if not service_url:
        missing.append(f"{prefix}_SERVICE_URL_{normalized_profile.upper()} or {prefix}_SERVICE_URL")
    if not service_account:
        missing.append(f"{prefix}_TASKS_SERVICE_ACCOUNT")
    if missing:
        raise RuntimeError("Missing OpenAI task config: " + ", ".join(missing))

    return {
        "kind": kind,
        "profile": normalized_profile,
        "project": project,
        "location": location,
        "queue": queue,
        "service_url": service_url,
        "service_account": service_account,
        "audience": audience,
        "prefix": prefix,
    }


def _task_handler_for_kind(kind: str) -> str:
    normalized = (kind or "").strip().lower()
    if normalized == "rename":
        return OPENAI_RENAME_TASK_HANDLER
    if normalized == "remap":
        return OPENAI_REMAP_TASK_HANDLER
    raise ValueError(f"Unsupported OpenAI task kind: {kind}")


def _enqueue_openai_task(kind: str, payload: Dict[str, Any], *, profile: Optional[str]) -> str:
    try:
        from google.cloud import tasks_v2
    except ImportError as exc:
        raise RuntimeError(
            "google-cloud-tasks is required for OPENAI_*_MODE=tasks. "
            "Install backend/requirements.txt to enable Cloud Tasks."
        ) from exc

    config = resolve_openai_task_config(kind, profile)
    client = tasks_v2.CloudTasksClient()
    parent = client.queue_path(config["project"], config["location"], config["queue"])
    body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
    task = {
        "http_request": {
            "http_method": tasks_v2.HttpMethod.POST,
            "url": f"{config['service_url']}{_task_handler_for_kind(kind)}",
            "headers": {"Content-Type": "application/json"},
            "body": body,
            "oidc_token": {
                "service_account_email": config["service_account"],
                "audience": config["audience"],
            },
        }
    }

    prefix = config["prefix"]
    deadline_raw = _profile_env(
        f"{prefix}_TASKS_DISPATCH_DEADLINE_SECONDS",
        config["profile"],
    ) or env_value(f"{prefix}_TASKS_DISPATCH_DEADLINE_SECONDS")
    if deadline_raw:
        deadline_seconds = _safe_positive_int(deadline_raw, 0)
        if deadline_seconds > 0:
            task["dispatch_deadline"] = duration_pb2.Duration(seconds=deadline_seconds)

    if env_truthy(f"{prefix}_TASKS_FORCE_IMMEDIATE") or env_truthy("OPENAI_TASKS_FORCE_IMMEDIATE"):
        # Schedule in the past so Cloud Tasks dispatches right away even when clocks drift.
        task["schedule_time"] = timestamp_pb2.Timestamp(seconds=0)

    response = client.create_task(request={"parent": parent, "task": task})
    return response.name


def enqueue_openai_rename_task(payload: Dict[str, Any], *, profile: Optional[str] = None) -> str:
    return _enqueue_openai_task("rename", payload, profile=profile)


def enqueue_openai_remap_task(payload: Dict[str, Any], *, profile: Optional[str] = None) -> str:
    return _enqueue_openai_task("remap", payload, profile=profile)

