"""Runtime configuration helpers for API bootstrap and middleware."""

from __future__ import annotations

import importlib.util
import os
from typing import Dict, Optional

from fastapi import HTTPException

from backend.env_utils import env_truthy as _env_truthy, env_value as _env_value
from backend.logging_config import get_logger
from backend.fieldDetecting.rename_pipeline.debug_flags import debug_enabled

_DEFAULT_CORS_ORIGINS = [
    "http://localhost:5173",
    "http://localhost:5174",
    "http://localhost:5175",
    "http://localhost:5176",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:5174",
    "http://127.0.0.1:5175",
    "http://127.0.0.1:5176",
]

logger = get_logger(__name__)


def is_prod() -> bool:
    return _env_value("ENV").lower() in {"prod", "production"}


def docs_enabled() -> bool:
    if is_prod():
        return False
    return True


def legacy_endpoints_enabled() -> bool:
    if is_prod():
        return False
    raw = _env_value("SANDBOX_ENABLE_LEGACY_ENDPOINTS")
    if not raw:
        return True
    return _env_truthy("SANDBOX_ENABLE_LEGACY_ENDPOINTS")


def require_legacy_enabled() -> None:
    if not legacy_endpoints_enabled():
        raise HTTPException(status_code=404, detail="Not found")


def commonforms_available() -> bool:
    try:
        return importlib.util.find_spec("commonforms") is not None
    except Exception:
        return False


def resolve_detection_mode() -> str:
    tasks_configured = bool(
        _env_value("DETECTOR_TASKS_QUEUE") or _env_value("DETECTOR_TASKS_QUEUE_LIGHT")
    )
    raw = _env_value("DETECTOR_MODE").lower()
    if raw:
        if raw == "local" and not commonforms_available() and tasks_configured:
            logger.warning("DETECTOR_MODE=local but CommonForms is missing; falling back to tasks.")
            return "tasks"
        return raw
    if tasks_configured:
        return "tasks"
    return "local"


def _recaptcha_required_for_contact() -> bool:
    from backend.services.recaptcha_service import recaptcha_required_for_contact
    return recaptcha_required_for_contact()


def _recaptcha_required_for_signup() -> bool:
    from backend.services.recaptcha_service import recaptcha_required_for_signup
    return recaptcha_required_for_signup()


def _recaptcha_required_any() -> bool:
    from backend.services.recaptcha_service import recaptcha_required_any
    return recaptcha_required_any()


def require_prod_env() -> None:
    """Fail fast when production environment variables are missing."""
    if not is_prod():
        return
    missing = []
    if not _env_value("SANDBOX_CORS_ORIGINS"):
        missing.append("SANDBOX_CORS_ORIGINS")
    if _env_value("SANDBOX_CORS_ORIGINS") == "*":
        missing.append("SANDBOX_CORS_ORIGINS (cannot be '*')")
    if not _env_value("FIREBASE_PROJECT_ID"):
        missing.append("FIREBASE_PROJECT_ID")
    if not (
        _env_value("FIREBASE_CREDENTIALS")
        or _env_value("GOOGLE_APPLICATION_CREDENTIALS")
        or _env_truthy("FIREBASE_USE_ADC")
    ):
        missing.append("FIREBASE_CREDENTIALS, GOOGLE_APPLICATION_CREDENTIALS, or FIREBASE_USE_ADC=true")
    if not _env_value("FORMS_BUCKET"):
        missing.append("FORMS_BUCKET")
    if not _env_value("TEMPLATES_BUCKET"):
        missing.append("TEMPLATES_BUCKET")
    if not _env_value("CONTACT_TO_EMAIL"):
        missing.append("CONTACT_TO_EMAIL")
    if not _env_value("CONTACT_FROM_EMAIL"):
        missing.append("CONTACT_FROM_EMAIL")
    if not _env_value("GMAIL_CLIENT_ID"):
        missing.append("GMAIL_CLIENT_ID")
    if not _env_value("GMAIL_CLIENT_SECRET"):
        missing.append("GMAIL_CLIENT_SECRET")
    if not _env_value("GMAIL_REFRESH_TOKEN"):
        missing.append("GMAIL_REFRESH_TOKEN")
    if _recaptcha_required_any():
        if not _env_value("RECAPTCHA_SITE_KEY"):
            missing.append("RECAPTCHA_SITE_KEY")
        if not (_env_value("RECAPTCHA_PROJECT_ID") or _env_value("FIREBASE_PROJECT_ID") or _env_value("GCP_PROJECT_ID")):
            missing.append("RECAPTCHA_PROJECT_ID (or FIREBASE_PROJECT_ID/GCP_PROJECT_ID)")

    detector_mode = resolve_detection_mode()
    if detector_mode != "tasks":
        missing.append("DETECTOR_MODE=tasks")
    if detector_mode == "tasks":
        if not (_env_value("DETECTOR_TASKS_PROJECT") or _env_value("GCP_PROJECT_ID")):
            missing.append("DETECTOR_TASKS_PROJECT (or GCP_PROJECT_ID)")
        if not _env_value("DETECTOR_TASKS_LOCATION"):
            missing.append("DETECTOR_TASKS_LOCATION")
        if not (_env_value("DETECTOR_TASKS_QUEUE") or _env_value("DETECTOR_TASKS_QUEUE_LIGHT")):
            missing.append("DETECTOR_TASKS_QUEUE (or DETECTOR_TASKS_QUEUE_LIGHT)")
        if not (_env_value("DETECTOR_SERVICE_URL") or _env_value("DETECTOR_SERVICE_URL_LIGHT")):
            missing.append("DETECTOR_SERVICE_URL (or DETECTOR_SERVICE_URL_LIGHT)")
        if _env_value("DETECTOR_TASKS_QUEUE_HEAVY") and not _env_value("DETECTOR_SERVICE_URL_HEAVY"):
            missing.append("DETECTOR_SERVICE_URL_HEAVY (required with DETECTOR_TASKS_QUEUE_HEAVY)")
        if _env_value("DETECTOR_SERVICE_URL_HEAVY") and not _env_value("DETECTOR_TASKS_QUEUE_HEAVY"):
            missing.append("DETECTOR_TASKS_QUEUE_HEAVY (required with DETECTOR_SERVICE_URL_HEAVY)")
        if not _env_value("DETECTOR_TASKS_SERVICE_ACCOUNT"):
            missing.append("DETECTOR_TASKS_SERVICE_ACCOUNT")
    if missing:
        raise RuntimeError("Missing required prod env vars: " + ", ".join(missing))


def resolve_cors_origins() -> list[str]:
    """Resolve CORS origins from env with a debug-only wildcard option."""
    raw = os.getenv("SANDBOX_CORS_ORIGINS", "").strip()
    if raw == "*":
        if debug_enabled():
            return ["*"]
        raw = ""
    origins = [origin.strip() for origin in raw.split(",") if origin.strip()] if raw else []
    if not is_prod():
        origins.extend(_DEFAULT_CORS_ORIGINS)
    if not origins:
        return list(_DEFAULT_CORS_ORIGINS)
    seen: set[str] = set()
    return [origin for origin in origins if not (origin in seen or seen.add(origin))]


def resolve_stream_cors_headers(origin: Optional[str]) -> Dict[str, str]:
    """Add explicit CORS headers for streaming responses when origin is allowlisted."""
    if not origin:
        return {}
    allowed = resolve_cors_origins()
    if "*" in allowed:
        return {"Access-Control-Allow-Origin": "*"}
    if origin in allowed:
        return {"Access-Control-Allow-Origin": origin, "Vary": "Origin"}
    return {}
