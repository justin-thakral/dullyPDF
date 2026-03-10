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
    raw = _env_value("SANDBOX_ENABLE_DOCS")
    if not raw:
        return True
    return _env_truthy("SANDBOX_ENABLE_DOCS")


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


def _resolve_openai_mode(prefix: str) -> str:
    tasks_configured = bool(
        _env_value(f"{prefix}_TASKS_QUEUE")
        or _env_value(f"{prefix}_TASKS_QUEUE_LIGHT")
    )
    raw = _env_value(f"{prefix}_MODE").lower()
    if raw:
        return raw
    if tasks_configured:
        return "tasks"
    return "local"


def resolve_openai_rename_mode() -> str:
    return _resolve_openai_mode("OPENAI_RENAME")


def resolve_openai_remap_mode() -> str:
    return _resolve_openai_mode("OPENAI_REMAP")


def _recaptcha_required_for_contact() -> bool:
    from backend.services.recaptcha_service import recaptcha_required_for_contact
    return recaptcha_required_for_contact()


def _recaptcha_required_for_signup() -> bool:
    from backend.services.recaptcha_service import recaptcha_required_for_signup
    return recaptcha_required_for_signup()


def _recaptcha_required_any() -> bool:
    from backend.services.recaptcha_service import recaptcha_required_any
    return recaptcha_required_any()


def _fill_link_token_secret_is_placeholder(value: str) -> bool:
    from backend.services.fill_links_service import fill_link_token_secret_is_weak
    return fill_link_token_secret_is_weak(value)


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
    if not _env_truthy("FIREBASE_USE_ADC"):
        missing.append("FIREBASE_USE_ADC=true")
    if _env_value("FIREBASE_CREDENTIALS"):
        missing.append("FIREBASE_CREDENTIALS (must be unset in prod; use ADC only)")
    if _env_value("GOOGLE_APPLICATION_CREDENTIALS"):
        missing.append("GOOGLE_APPLICATION_CREDENTIALS (must be unset in prod; use ADC only)")
    if not _env_value("FORMS_BUCKET"):
        missing.append("FORMS_BUCKET")
    if not _env_value("TEMPLATES_BUCKET"):
        missing.append("TEMPLATES_BUCKET")
    fill_link_token_secret = _env_value("FILL_LINK_TOKEN_SECRET")
    if not fill_link_token_secret:
        missing.append("FILL_LINK_TOKEN_SECRET")
    elif _fill_link_token_secret_is_placeholder(fill_link_token_secret):
        missing.append("FILL_LINK_TOKEN_SECRET (must be unique and at least 32 characters)")
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
    stripe_secret_key = _env_value("STRIPE_SECRET_KEY")
    if not stripe_secret_key:
        missing.append("STRIPE_SECRET_KEY")
    stripe_webhook_secret = _env_value("STRIPE_WEBHOOK_SECRET")
    if not stripe_webhook_secret:
        missing.append("STRIPE_WEBHOOK_SECRET")
    if not _env_value("STRIPE_PRICE_PRO_MONTHLY"):
        missing.append("STRIPE_PRICE_PRO_MONTHLY")
    if not _env_value("STRIPE_PRICE_PRO_YEARLY"):
        missing.append("STRIPE_PRICE_PRO_YEARLY")
    if not _env_value("STRIPE_PRICE_REFILL_500"):
        missing.append("STRIPE_PRICE_REFILL_500")
    checkout_success_url = _env_value("STRIPE_CHECKOUT_SUCCESS_URL")
    if not checkout_success_url:
        missing.append("STRIPE_CHECKOUT_SUCCESS_URL")
    elif not checkout_success_url.lower().startswith("https://"):
        missing.append("STRIPE_CHECKOUT_SUCCESS_URL (must use https)")
    checkout_cancel_url = _env_value("STRIPE_CHECKOUT_CANCEL_URL")
    if not checkout_cancel_url:
        missing.append("STRIPE_CHECKOUT_CANCEL_URL")
    elif not checkout_cancel_url.lower().startswith("https://"):
        missing.append("STRIPE_CHECKOUT_CANCEL_URL (must use https)")
    stripe_processed_cap_raw = _env_value("STRIPE_MAX_PROCESSED_EVENTS").strip()
    if not stripe_processed_cap_raw:
        missing.append("STRIPE_MAX_PROCESSED_EVENTS (must be a positive integer in prod)")
    else:
        try:
            stripe_processed_cap = int(stripe_processed_cap_raw)
        except ValueError:
            missing.append("STRIPE_MAX_PROCESSED_EVENTS (must be a positive integer in prod)")
        else:
            if stripe_processed_cap <= 0:
                missing.append("STRIPE_MAX_PROCESSED_EVENTS (must be a positive integer in prod)")
    if (_env_value("CONTACT_REQUIRE_RECAPTCHA") or "true").strip().lower() != "true":
        missing.append("CONTACT_REQUIRE_RECAPTCHA (must be true in prod)")
    if (_env_value("SIGNUP_REQUIRE_RECAPTCHA") or "true").strip().lower() != "true":
        missing.append("SIGNUP_REQUIRE_RECAPTCHA (must be true in prod)")
    if (_env_value("FILL_LINK_REQUIRE_RECAPTCHA") or "true").strip().lower() != "true":
        missing.append("FILL_LINK_REQUIRE_RECAPTCHA (must be true in prod)")
    if _recaptcha_required_any():
        if not _env_value("RECAPTCHA_SITE_KEY"):
            missing.append("RECAPTCHA_SITE_KEY")
        if not (_env_value("RECAPTCHA_PROJECT_ID") or _env_value("FIREBASE_PROJECT_ID") or _env_value("GCP_PROJECT_ID")):
            missing.append("RECAPTCHA_PROJECT_ID (or FIREBASE_PROJECT_ID/GCP_PROJECT_ID)")
        if not _env_value("RECAPTCHA_ALLOWED_HOSTNAMES"):
            missing.append("RECAPTCHA_ALLOWED_HOSTNAMES (required in prod when reCAPTCHA is enabled)")

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

    rename_mode = resolve_openai_rename_mode()
    if rename_mode == "tasks":
        if not (_env_value("OPENAI_RENAME_TASKS_PROJECT") or _env_value("GCP_PROJECT_ID")):
            missing.append("OPENAI_RENAME_TASKS_PROJECT (or GCP_PROJECT_ID)")
        if not _env_value("OPENAI_RENAME_TASKS_LOCATION"):
            missing.append("OPENAI_RENAME_TASKS_LOCATION")
        if not (_env_value("OPENAI_RENAME_TASKS_QUEUE") or _env_value("OPENAI_RENAME_TASKS_QUEUE_LIGHT")):
            missing.append("OPENAI_RENAME_TASKS_QUEUE (or OPENAI_RENAME_TASKS_QUEUE_LIGHT)")
        if not (_env_value("OPENAI_RENAME_SERVICE_URL") or _env_value("OPENAI_RENAME_SERVICE_URL_LIGHT")):
            missing.append("OPENAI_RENAME_SERVICE_URL (or OPENAI_RENAME_SERVICE_URL_LIGHT)")
        if _env_value("OPENAI_RENAME_TASKS_QUEUE_HEAVY") and not _env_value("OPENAI_RENAME_SERVICE_URL_HEAVY"):
            missing.append("OPENAI_RENAME_SERVICE_URL_HEAVY (required with OPENAI_RENAME_TASKS_QUEUE_HEAVY)")
        if _env_value("OPENAI_RENAME_SERVICE_URL_HEAVY") and not _env_value("OPENAI_RENAME_TASKS_QUEUE_HEAVY"):
            missing.append("OPENAI_RENAME_TASKS_QUEUE_HEAVY (required with OPENAI_RENAME_SERVICE_URL_HEAVY)")
        if not _env_value("OPENAI_RENAME_TASKS_SERVICE_ACCOUNT"):
            missing.append("OPENAI_RENAME_TASKS_SERVICE_ACCOUNT")

    remap_mode = resolve_openai_remap_mode()
    if remap_mode == "tasks":
        if not (_env_value("OPENAI_REMAP_TASKS_PROJECT") or _env_value("GCP_PROJECT_ID")):
            missing.append("OPENAI_REMAP_TASKS_PROJECT (or GCP_PROJECT_ID)")
        if not _env_value("OPENAI_REMAP_TASKS_LOCATION"):
            missing.append("OPENAI_REMAP_TASKS_LOCATION")
        if not (_env_value("OPENAI_REMAP_TASKS_QUEUE") or _env_value("OPENAI_REMAP_TASKS_QUEUE_LIGHT")):
            missing.append("OPENAI_REMAP_TASKS_QUEUE (or OPENAI_REMAP_TASKS_QUEUE_LIGHT)")
        if not (_env_value("OPENAI_REMAP_SERVICE_URL") or _env_value("OPENAI_REMAP_SERVICE_URL_LIGHT")):
            missing.append("OPENAI_REMAP_SERVICE_URL (or OPENAI_REMAP_SERVICE_URL_LIGHT)")
        if _env_value("OPENAI_REMAP_TASKS_QUEUE_HEAVY") and not _env_value("OPENAI_REMAP_SERVICE_URL_HEAVY"):
            missing.append("OPENAI_REMAP_SERVICE_URL_HEAVY (required with OPENAI_REMAP_TASKS_QUEUE_HEAVY)")
        if _env_value("OPENAI_REMAP_SERVICE_URL_HEAVY") and not _env_value("OPENAI_REMAP_TASKS_QUEUE_HEAVY"):
            missing.append("OPENAI_REMAP_TASKS_QUEUE_HEAVY (required with OPENAI_REMAP_SERVICE_URL_HEAVY)")
        if not _env_value("OPENAI_REMAP_TASKS_SERVICE_ACCOUNT"):
            missing.append("OPENAI_REMAP_TASKS_SERVICE_ACCOUNT")
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
