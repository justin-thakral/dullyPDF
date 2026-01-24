"""
FastAPI service for PDF field detection and form management.

Primary pipeline:
- CommonForms ML detection
- OpenAI schema mapping is isolated to schema-only endpoints (no row data).
- OpenAI rename is handled via explicit endpoints with overlay prompts.

Legacy note:
- The OpenCV sandbox pipeline is archived in `legacy/fieldDetecting/` and is not used here.

Data structures:
- Session entries cached in L1 with Firestore/GCS fallback for multi-instance access.
"""

import hashlib
import importlib.util
import io
import json
import os
import re
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import BackgroundTasks, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from firebase_admin import auth as firebase_auth
from pydantic import BaseModel, Field, field_validator
import fitz

from .detection_status import (
    DETECTION_STATUS_COMPLETE,
    DETECTION_STATUS_FAILED,
    DETECTION_STATUS_QUEUED,
    DETECTION_STATUS_RUNNING,
)
from .detection_tasks import enqueue_detection_task, resolve_detector_profile, resolve_task_config
from .fieldDetecting.rename_pipeline.combinedSrc.config import get_logger
from .fieldDetecting.rename_pipeline.combinedSrc.form_filler import inject_fields
from .fieldDetecting.rename_pipeline.debug_flags import debug_enabled, get_debug_password
from .ai.rename_pipeline import run_openai_rename_on_pdf
from .ai.schema_mapping import (
    build_allowlist_payload,
    call_openai_schema_mapping_chunked,
    validate_payload_size,
)
from .env_utils import env_truthy as _env_truthy, env_value as _env_value, int_env as _int_env
from .firebaseDB.app_database import (
    consume_openai_credits,
    create_template,
    delete_template,
    ensure_user,
    get_user_profile,
    get_template,
    list_templates,
    normalize_role,
    refund_openai_credits,
    ROLE_GOD,
)
from .firebaseDB.detection_database import record_detection_request, update_detection_request
from .firebaseDB.schema_database import (
    create_schema,
    get_schema,
    list_schemas,
    record_openai_request,
    record_openai_rename_request,
)
from .firebaseDB.firebase_service import RequestUser, verify_id_token
from .firebaseDB.session_database import get_session_metadata
from .firebaseDB.storage_service import (
    delete_pdf,
    download_pdf_bytes,
    download_session_json,
    is_gcs_path,
    stream_pdf,
    upload_form_pdf,
    upload_template_pdf,
)
from .pdf_validation import PdfValidationError, PdfValidationResult, preflight_pdf_bytes
from .security.rate_limit import check_rate_limit
from .sessions.session_store import (
    get_session_entry as _get_session_entry,
    get_session_entry_if_present as _get_session_entry_if_present,
    store_session_entry as _store_session_entry,
    touch_session_entry as _touch_session_entry,
    update_session_entry as _update_session_entry,
)
from .time_utils import now_iso

logger = get_logger(__name__)


def _is_prod() -> bool:
    return _env_value("ENV").lower() in {"prod", "production"}


def _require_prod_env() -> None:
    """
    Fail fast when prod environment variables are missing.
    """
    if not _is_prod():
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
    detector_mode = _resolve_detection_mode()
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


def _docs_enabled() -> bool:
    """
    Decide whether OpenAPI/Docs routes should be exposed.
    """
    if _is_prod():
        return False
    return True


def _legacy_endpoints_enabled() -> bool:
    if _is_prod():
        return False
    raw = _env_value("SANDBOX_ENABLE_LEGACY_ENDPOINTS")
    if not raw:
        return True
    return _env_truthy("SANDBOX_ENABLE_LEGACY_ENDPOINTS")


def _require_legacy_enabled() -> None:
    if not _legacy_endpoints_enabled():
        raise HTTPException(status_code=404, detail="Not found")


def _commonforms_available() -> bool:
    try:
        return importlib.util.find_spec("commonforms") is not None
    except Exception:
        return False


def _resolve_detection_mode() -> str:
    raw = _env_value("DETECTOR_MODE").lower()
    if raw:
        if raw == "local" and not _commonforms_available() and _env_value("DETECTOR_TASKS_QUEUE"):
            logger.warning("DETECTOR_MODE=local but CommonForms is missing; falling back to tasks.")
            return "tasks"
        return raw
    if _env_value("DETECTOR_TASKS_QUEUE"):
        return "tasks"
    return "local"


def _run_local_detection(pdf_bytes: bytes) -> Dict[str, Any]:
    fd, temp_name = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)
    temp_path = Path(temp_name)
    try:
        temp_path.write_bytes(pdf_bytes)
        try:
            from .fieldDetecting.commonforms.commonForm import detect_commonforms_fields
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail="CommonForms dependencies are missing; set DETECTOR_MODE=tasks or install detector deps.",
            ) from exc
        resolved = detect_commonforms_fields(Path(temp_path))
    finally:
        temp_path.unlink(missing_ok=True)
    resolved["pipeline"] = "commonforms"
    return resolved


def _enqueue_detection_job(
    pdf_bytes: bytes,
    source_pdf: str,
    user: Optional[RequestUser],
    *,
    page_count: Optional[int] = None,
) -> Dict[str, Any]:
    session_id = str(uuid.uuid4())
    resolved_page_count = page_count if page_count is not None else _get_pdf_page_count(pdf_bytes)
    detector_profile = resolve_detector_profile(resolved_page_count)
    task_config = resolve_task_config(detector_profile)
    entry: Dict[str, Any] = {
        "pdf_bytes": pdf_bytes,
        "fields": [],
        "source_pdf": source_pdf,
        "result": {},
        "page_count": resolved_page_count,
        "user_id": user.app_user_id if user else None,
        "detection_status": DETECTION_STATUS_QUEUED,
        "detection_queued_at": now_iso(),
        "detection_error": "",
        "detection_profile": task_config["profile"],
        "detection_queue": task_config["queue"],
        "detection_service_url": task_config["service_url"],
    }
    _store_session_entry(session_id, entry, persist_l1=False)
    pdf_path = entry.get("pdf_path")
    if not pdf_path:
        raise HTTPException(status_code=500, detail="Session PDF storage failed")

    payload = {
        "sessionId": session_id,
        "pdfPath": pdf_path,
        "pipeline": "commonforms",
    }
    record_detection_request(
        request_id=session_id,
        session_id=session_id,
        user_id=user.app_user_id if user else None,
        status=DETECTION_STATUS_QUEUED,
        page_count=resolved_page_count,
    )
    try:
        task_name = enqueue_detection_task(payload, profile=task_config["profile"])
    except Exception as exc:
        entry["detection_status"] = DETECTION_STATUS_FAILED
        entry["detection_completed_at"] = now_iso()
        entry["detection_error"] = str(exc)
        _update_session_entry(session_id, entry)
        update_detection_request(
            request_id=session_id,
            status=DETECTION_STATUS_FAILED,
            error=str(exc),
        )
        raise HTTPException(status_code=500, detail="Failed to enqueue detection job") from exc

    entry["detection_task_name"] = task_name
    _update_session_entry(session_id, entry)
    return {
        "sessionId": session_id,
        "status": DETECTION_STATUS_QUEUED,
        "pipeline": "commonforms",
    }


class SchemaField(BaseModel):
    """Schema field metadata (name + type) for AI mapping.
    """

    name: str = Field(..., min_length=1)
    type: Optional[str] = "string"


class SchemaCreateRequest(BaseModel):
    """Schema creation payload containing only metadata (no rows).
    """

    name: Optional[str] = None
    fields: List[SchemaField]
    source: Optional[str] = None
    sampleCount: Optional[int] = None


def _coerce_rect_float(value: Any, label: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"rect {label} must be a number") from exc


def _rect_from_xywh(x: Any, y: Any, width: Any, height: Any) -> Dict[str, float]:
    x_val = _coerce_rect_float(x, "x")
    y_val = _coerce_rect_float(y, "y")
    width_val = _coerce_rect_float(width, "width")
    height_val = _coerce_rect_float(height, "height")
    if width_val <= 0 or height_val <= 0:
        raise ValueError("rect width/height must be positive")
    return {"x": x_val, "y": y_val, "width": width_val, "height": height_val}


def _rect_from_corners(x1: Any, y1: Any, x2: Any, y2: Any) -> Dict[str, float]:
    x1_val = _coerce_rect_float(x1, "x1")
    y1_val = _coerce_rect_float(y1, "y1")
    x2_val = _coerce_rect_float(x2, "x2")
    y2_val = _coerce_rect_float(y2, "y2")
    width_val = x2_val - x1_val
    height_val = y2_val - y1_val
    if width_val <= 0 or height_val <= 0:
        raise ValueError("rect corner coordinates must produce positive width/height")
    return {"x": x1_val, "y": y1_val, "width": width_val, "height": height_val}


class TemplateOverlayField(BaseModel):
    """Template overlay field payload with no row data or values.
    """

    name: str = Field(..., min_length=1)
    type: Optional[str] = "text"
    page: Optional[int] = None
    rect: Optional[Dict[str, float]] = None
    groupKey: Optional[str] = None
    optionKey: Optional[str] = None
    optionLabel: Optional[str] = None
    groupLabel: Optional[str] = None

    model_config = {"extra": "ignore"}

    @field_validator("rect", mode="before")
    @classmethod
    def _normalize_rect(cls, value: Any) -> Optional[Dict[str, float]]:
        if value is None:
            return None
        if isinstance(value, dict):
            if not value:
                return None
            if {"x", "y", "width", "height"}.issubset(value):
                return _rect_from_xywh(value.get("x"), value.get("y"), value.get("width"), value.get("height"))
            if {"x1", "y1", "x2", "y2"}.issubset(value):
                return _rect_from_corners(value.get("x1"), value.get("y1"), value.get("x2"), value.get("y2"))
            raise ValueError("rect dict must include x/y/width/height or x1/y1/x2/y2")
        if isinstance(value, (list, tuple)):
            if len(value) != 4:
                raise ValueError("rect list must have 4 numbers")
            return _rect_from_corners(value[0], value[1], value[2], value[3])
        raise ValueError("rect must be a dict or 4-item list")


class SchemaMappingRequest(BaseModel):
    """OpenAI mapping request using schema metadata + template overlay tags.
    """

    schemaId: str = Field(..., min_length=1)
    templateId: Optional[str] = None
    templateFields: List[TemplateOverlayField]
    sessionId: Optional[str] = None


class RenameFieldsRequest(BaseModel):
    """OpenAI rename request using cached PDF bytes and optional schema headers.
    """

    sessionId: str = Field(..., min_length=1)
    schemaId: Optional[str] = None
    templateFields: Optional[List[TemplateOverlayField]] = None


class SavedFormSessionRequest(BaseModel):
    """Create a detection session from a saved form + extracted fields."""

    fields: List[Dict[str, Any]] = Field(default_factory=list)
    pageCount: Optional[int] = None


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


def _resolve_cors_origins() -> list[str]:
    """
    Resolve CORS origins from environment with a debug-only wildcard option.
    """
    raw = os.getenv("SANDBOX_CORS_ORIGINS", "").strip()
    if raw == "*":
        if debug_enabled():
            return ["*"]
        raw = ""
    origins = [origin.strip() for origin in raw.split(",") if origin.strip()] if raw else []
    if not _is_prod():
        origins.extend(_DEFAULT_CORS_ORIGINS)
    if not origins:
        return list(_DEFAULT_CORS_ORIGINS)
    seen: set[str] = set()
    return [origin for origin in origins if not (origin in seen or seen.add(origin))]


def _resolve_stream_cors_headers(origin: Optional[str]) -> Dict[str, str]:
    """
    Add explicit CORS headers for streaming responses when the origin is allowlisted.
    """
    if not origin:
        return {}
    allowed = _resolve_cors_origins()
    if "*" in allowed:
        return {"Access-Control-Allow-Origin": "*"}
    if origin in allowed:
        return {"Access-Control-Allow-Origin": origin, "Vary": "Origin"}
    return {}


def _is_password_sign_in(decoded: Dict[str, Any]) -> bool:
    """
    Return True when the token originated from email/password sign-in.
    """
    firebase_claims = decoded.get("firebase") if isinstance(decoded, dict) else {}
    if not isinstance(firebase_claims, dict):
        return False
    provider = str(firebase_claims.get("sign_in_provider") or "").strip().lower()
    return provider in {"password", "emaillink", "email_link"}


def _enforce_email_verification(decoded: Dict[str, Any]) -> None:
    """
    Reject password users until their email is verified.
    """
    if not _is_password_sign_in(decoded):
        return
    if decoded.get("email_verified") is True:
        return
    raise HTTPException(status_code=403, detail="Email verification required")


def _verify_token(authorization: Optional[str]) -> Dict[str, Any]:
    """
    Validate Firebase auth headers and return the decoded token.
    """
    try:
        decoded = verify_id_token(authorization)
        _enforce_email_verification(decoded)
        return decoded
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Missing Authorization token") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail="Firebase authentication is not configured") from exc
    except firebase_auth.RevokedIdTokenError as exc:
        raise HTTPException(status_code=401, detail="Authorization token revoked") from exc
    except Exception as exc:
        logger.warning("Firebase token verification failed: %s", exc)
        raise HTTPException(status_code=401, detail="Invalid Authorization token") from exc


def _require_user(authorization: Optional[str]) -> RequestUser:
    """
    Resolve the current request user from Firebase token and upsert into Firestore.

    We return a RequestUser so storage + template lookups remain keyed by UID.
    """
    decoded = _verify_token(authorization)
    try:
        return ensure_user(decoded)
    except Exception as exc:
        logger.error("Failed to sync Firebase user profile: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to synchronize user profile") from exc


def _has_admin_override(authorization: Optional[str], x_admin_token: Optional[str]) -> bool:
    """
    Return True when the request includes a valid admin override token.
    """
    if _is_prod():
        return False
    allow_override = os.getenv("SANDBOX_ALLOW_ADMIN_OVERRIDE", "").strip().lower()
    if allow_override and allow_override not in {"1", "true", "yes"}:
        return False
    token = os.getenv("ADMIN_TOKEN")
    if not token and debug_enabled():
        token = get_debug_password()
    if not token:
        return False
    bearer = None
    if authorization and authorization.lower().startswith("bearer "):
        bearer = authorization.split(" ", 1)[1].strip()
    return bool(bearer == token or (x_admin_token and x_admin_token == token))


def _sanitize_basename_segment(value: str, fallback: str) -> str:
    """
    Sanitize a filename segment to prevent header injection or path traversal.
    """
    raw = (value or fallback or "file").strip()
    base = os.path.basename(raw)
    cleaned = re.sub(r"[\r\n]", "", base)
    cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "_", cleaned)
    cleaned = re.sub(r"^\.+", "", cleaned)
    return cleaned or fallback


def _safe_pdf_download_filename(name: str, fallback: str = "document") -> str:
    """
    Normalize filenames so browsers receive a safe, short, PDF-only value.

    This mirrors the Node implementation used in the legacy backend.
    """
    safe_base = _sanitize_basename_segment(name, fallback)
    if not safe_base.lower().endswith(".pdf"):
        safe_base = f"{safe_base}.pdf"
    if len(safe_base) > 180:
        trimmed = safe_base[:180]
        if not trimmed.lower().endswith(".pdf"):
            trimmed = f"{trimmed[:176]}.pdf"
        return trimmed
    return safe_base


def _log_pdf_label(name: str) -> str:
    """
    Return a stable, non-sensitive identifier for PDF logging.
    """
    safe = _sanitize_basename_segment(name, "document")
    digest = hashlib.sha256(safe.encode("utf-8")).hexdigest()[:10]
    suffix = ".pdf" if safe.lower().endswith(".pdf") else ""
    return f"pdf{suffix}#{digest}"


def _cleanup_paths(paths: List[Path]) -> None:
    """
    Best-effort cleanup for temp files.
    """
    for path in paths:
        try:
            path.unlink(missing_ok=True)
        except Exception as exc:
            logger.debug("Failed to delete temp file %s: %s", path, exc)


def _rect_list_from_xywh(x: Any, y: Any, width: Any, height: Any) -> Optional[List[float]]:
    """
    Convert x/y/width/height into [x1, y1, x2, y2] or return None on invalid inputs.
    """
    try:
        x1 = float(x)
        y1 = float(y)
        w = float(width)
        h = float(height)
    except (TypeError, ValueError):
        return None
    return [x1, y1, x1 + w, y1 + h]


def _rect_list_from_corners(x1: Any, y1: Any, x2: Any, y2: Any) -> Optional[List[float]]:
    """
    Convert corner coordinates into [x1, y1, x2, y2] or return None on invalid inputs.
    """
    try:
        return [float(x1), float(y1), float(x2), float(y2)]
    except (TypeError, ValueError):
        return None


def _coerce_field_payloads(raw_fields: List[Any]) -> List[Dict[str, Any]]:
    """
    Normalize incoming field payloads to the expected dict shape.
    """
    cleaned: List[Dict[str, Any]] = []
    for entry in raw_fields:
        if not isinstance(entry, dict):
            continue
        payload = dict(entry)
        rect_list: Optional[List[float]] = None
        rect = payload.get("rect")
        if isinstance(rect, dict):
            if {"x", "y", "width", "height"}.issubset(rect):
                rect_list = _rect_list_from_xywh(rect.get("x"), rect.get("y"), rect.get("width"), rect.get("height"))
                for key in ("x", "y", "width", "height"):
                    if key not in payload and key in rect:
                        payload[key] = rect[key]
            elif {"x1", "y1", "x2", "y2"}.issubset(rect):
                rect_list = _rect_list_from_corners(rect.get("x1"), rect.get("y1"), rect.get("x2"), rect.get("y2"))
        elif isinstance(rect, (list, tuple)) and len(rect) == 4:
            rect_list = _rect_list_from_corners(rect[0], rect[1], rect[2], rect[3])

        if rect_list is None:
            rect_list = _rect_list_from_xywh(
                payload.get("x"),
                payload.get("y"),
                payload.get("width"),
                payload.get("height"),
            )

        if rect_list is not None:
            payload["rect"] = rect_list
            x1, y1, x2, y2 = rect_list
            payload.setdefault("x", x1)
            payload.setdefault("y", y1)
            payload.setdefault("width", x2 - x1)
            payload.setdefault("height", y2 - y1)
        elif isinstance(rect, dict):
            payload["rect"] = None
        cleaned.append(payload)
    return cleaned


def _get_pdf_page_count(pdf_bytes: bytes) -> int:
    """
    Return the number of pages in a PDF byte stream.
    """
    if not pdf_bytes:
        return 0
    with fitz.open(stream=io.BytesIO(pdf_bytes), filetype="pdf") as doc:
        return max(1, int(doc.page_count))


def _resolve_detect_max_pages(role: Optional[str]) -> int:
    """
    Resolve detection page limits for the caller role.
    """
    normalized = normalize_role(role)
    if normalized == ROLE_GOD:
        return max(1, _int_env("SANDBOX_DETECT_MAX_PAGES_GOD", 100))
    return max(1, _int_env("SANDBOX_DETECT_MAX_PAGES_BASE", 5))


def _resolve_fillable_max_pages(role: Optional[str]) -> int:
    """
    Resolve fillable PDF page limits for the caller role.
    """
    normalized = normalize_role(role)
    if normalized == ROLE_GOD:
        return max(1, _int_env("SANDBOX_FILLABLE_MAX_PAGES_GOD", 1000))
    return max(1, _int_env("SANDBOX_FILLABLE_MAX_PAGES_BASE", 50))


def _resolve_saved_forms_limit(role: Optional[str]) -> int:
    """
    Resolve saved form limits for the caller role.
    """
    normalized = normalize_role(role)
    if normalized == ROLE_GOD:
        return max(1, _int_env("SANDBOX_SAVED_FORMS_MAX_GOD", 20))
    return max(1, _int_env("SANDBOX_SAVED_FORMS_MAX_BASE", 3))


def _resolve_role_limits(role: Optional[str]) -> Dict[str, int]:
    """
    Build a limit summary for profile responses.
    """
    return {
        "detectMaxPages": _resolve_detect_max_pages(role),
        "fillableMaxPages": _resolve_fillable_max_pages(role),
        "savedFormsMax": _resolve_saved_forms_limit(role),
    }


def _validate_pdf_for_detection(pdf_bytes: bytes) -> PdfValidationResult:
    try:
        return preflight_pdf_bytes(pdf_bytes)
    except PdfValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _estimate_template_page_count(template_fields: List[Dict[str, Any]]) -> int:
    """
    Estimate page count by taking the max page index from template fields.
    """
    max_page = 0
    for field in template_fields:
        page = field.get("page")
        try:
            page_value = int(page)
        except (TypeError, ValueError):
            page_value = 1
        if page_value > max_page:
            max_page = page_value
    return max(1, max_page)


def _sanitize_pdf_field_name_candidate(raw_name: str, fallback_base: str = "field") -> str:
    """
    Sanitize a PDF field name for rename suggestions.

    Steps:
    - Collapse whitespace and illegal characters into underscores.
    - Strip leading/trailing underscores and enforce lowercase.
    - Cap length to avoid oversized names in UI/state payloads.
    """
    max_len = 96

    def _coerce(value: str, fallback: str) -> str:
        return (
            str(value or fallback or "field")
            .strip()
            .replace(" ", "_")
            .replace("\t", "_")
            .replace("\n", "_")
            .replace("\r", "_")
            .replace("\u00a0", "_")
            .replace("\u2007", "_")
            .replace("\u202f", "_")
        )

    base = _coerce(raw_name, fallback_base)
    base = re.sub(r"\s+", "_", base)
    base = re.sub(r"[^a-zA-Z0-9_.-]", "_", base)
    base = re.sub(r"_{2,}", "_", base)
    base = base.strip("_").lower()
    base = base[:max_len]
    if base:
        return base
    fallback = _coerce(fallback_base, "field")
    fallback = re.sub(r"\s+", "_", fallback)
    fallback = re.sub(r"[^a-zA-Z0-9_.-]", "_", fallback)
    fallback = re.sub(r"_{2,}", "_", fallback)
    fallback = fallback.strip("_").lower()
    fallback = fallback[:max_len]
    return fallback or "field"


def _normalize_data_key(value: str) -> str:
    """
    Normalize schema/template keys to a stable lowercase underscore form.
    """
    normalized = str(value or "").strip().lower()
    if not normalized:
        return ""
    normalized = re.sub(r"[\s-]+", "_", normalized)
    normalized = re.sub(r"[^a-z0-9_]", "", normalized)
    return normalized


def _template_fields_to_rename_fields(fields: List[TemplateOverlayField]) -> List[Dict[str, Any]]:
    """
    Convert template overlay fields into rename-friendly payloads.
    Skips fields without numeric rectangles and normalizes geometry to [x1, y1, x2, y2].
    """
    rename_fields: List[Dict[str, Any]] = []
    for field in fields:
        rect = field.rect or {}
        x = rect.get("x")
        y = rect.get("y")
        width = rect.get("width")
        height = rect.get("height")
        if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
            continue
        if not isinstance(width, (int, float)) or not isinstance(height, (int, float)):
            continue
        rename_fields.append(
            {
                "name": field.name,
                "type": field.type or "text",
                "page": int(field.page or 1),
                "rect": [float(x), float(y), float(x) + float(width), float(y) + float(height)],
                "groupKey": field.groupKey,
                "optionKey": field.optionKey,
                "optionLabel": field.optionLabel,
                "groupLabel": field.groupLabel,
            }
        )
    return rename_fields


def _build_schema_mapping_payload(
    schema_fields: List[Dict[str, Any]],
    template_tags: List[Dict[str, Any]],
    ai_response: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Build a JSON-friendly mapping response for schema-to-template results.

    We strictly filter AI output to known schema/template values so hallucinated
    mappings cannot leak into the response.
    """
    allowed_schema = [str(field.get("name") or "").strip() for field in schema_fields]
    allowed_schema = [field for field in allowed_schema if field]
    allowed_template = [str(tag.get("tag") or "").strip() for tag in template_tags]
    allowed_template = [tag for tag in allowed_template if tag]

    allowed_schema_set = set(allowed_schema)
    allowed_schema_map: Dict[str, str] = {}
    for field in allowed_schema:
        normalized = _normalize_data_key(field)
        if normalized and normalized not in allowed_schema_map:
            allowed_schema_map[normalized] = field
    allowed_template_set = set(allowed_template)
    allowed_group_key_map: Dict[str, str] = {}
    for tag in template_tags:
        raw_group_key = str(tag.get("groupKey") or "").strip()
        if not raw_group_key:
            continue
        normalized_group_key = _normalize_data_key(raw_group_key)
        if not normalized_group_key:
            continue
        if normalized_group_key not in allowed_group_key_map:
            allowed_group_key_map[normalized_group_key] = raw_group_key

    sanitized_mappings = []
    mapped_schema = set()
    mapped_template = set()
    raw_mappings = ai_response.get("mappings") or []
    for entry in raw_mappings if isinstance(raw_mappings, list) else []:
        if not isinstance(entry, dict):
            continue
        schema_field = (
            entry.get("schemaField")
            or entry.get("databaseField")
            or entry.get("source")
            or ""
        )
        template_tag = (
            entry.get("templateTag")
            or entry.get("pdfField")
            or entry.get("targetField")
            or ""
        )
        schema_field = str(schema_field).strip()
        template_tag = str(template_tag).strip()
        if not schema_field or not template_tag:
            continue
        if schema_field not in allowed_schema_set or template_tag not in allowed_template_set:
            continue

        try:
            confidence_value = float(entry.get("confidence", 0.6))
        except (TypeError, ValueError):
            confidence_value = 0.6
        confidence_value = min(max(confidence_value, 0.0), 1.0)

        desired_name = _sanitize_pdf_field_name_candidate(schema_field, schema_field)
        sanitized_mappings.append(
            {
                "databaseField": schema_field,
                "pdfField": desired_name,
                "originalPdfField": template_tag,
                "confidence": confidence_value,
                "reasoning": entry.get("reasoning", "AI suggested mapping"),
                "id": re.sub(r"[^a-zA-Z0-9_]", "_", f"{schema_field}_to_{template_tag}"),
            }
        )
        mapped_schema.add(schema_field)
        mapped_template.add(template_tag)

    raw_templates = (
        ai_response.get("templateRules")
        or ai_response.get("template_rules")
        or ai_response.get("derivedMappings")
        or []
    )
    template_rules = []
    if isinstance(raw_templates, list):
        for raw in raw_templates:
            if not isinstance(raw, dict):
                continue
            target = (
                raw.get("targetField")
                or raw.get("pdfField")
                or raw.get("target")
                or raw.get("name")
            )
            target = str(target or "").strip()
            if target not in allowed_template_set:
                continue
            sources = raw.get("sources")
            if isinstance(sources, list):
                filtered = [src for src in sources if str(src).strip() in allowed_schema_set]
                if not filtered:
                    continue
                raw = dict(raw)
                raw["sources"] = filtered
            template_rules.append(raw)

    raw_checkbox = ai_response.get("checkboxRules") or ai_response.get("checkbox_rules") or []
    checkbox_rules = []
    if isinstance(raw_checkbox, list):
        for raw in raw_checkbox:
            if not isinstance(raw, dict):
                continue
            schema_field_raw = str(raw.get("databaseField") or "").strip()
            if not schema_field_raw:
                continue
            schema_field = (
                schema_field_raw
                if schema_field_raw in allowed_schema_set
                else allowed_schema_map.get(_normalize_data_key(schema_field_raw))
            )
            if not schema_field:
                continue
            raw_group_key = str(raw.get("groupKey") or "").strip()
            normalized_group_key = _normalize_data_key(raw_group_key)
            normalized_schema_key = _normalize_data_key(schema_field)
            resolved_group_key = None
            if normalized_group_key:
                resolved_group_key = allowed_group_key_map.get(normalized_group_key)
            if not resolved_group_key and normalized_schema_key:
                resolved_group_key = allowed_group_key_map.get(normalized_schema_key)
            if allowed_group_key_map and not resolved_group_key:
                continue
            group_key = resolved_group_key or normalized_group_key or normalized_schema_key
            if not group_key:
                continue
            normalized_rule = dict(raw)
            normalized_rule["databaseField"] = schema_field
            normalized_rule["groupKey"] = group_key
            checkbox_rules.append(normalized_rule)

    identifier_key = str(
        ai_response.get("identifierKey")
        or ai_response.get("patientIdentifierField")
        or ""
    ).strip()
    if identifier_key not in allowed_schema_set:
        identifier_key = None

    confidence_values = [entry.get("confidence", 0.0) for entry in sanitized_mappings]
    try:
        overall_confidence = (
            sum(float(val) for val in confidence_values) / len(confidence_values)
            if confidence_values
            else 0.0
        )
    except (TypeError, ValueError):
        overall_confidence = 0.0

    return {
        "success": True,
        "mappings": sanitized_mappings,
        "templateRules": template_rules,
        "checkboxRules": checkbox_rules,
        "identifierKey": identifier_key,
        "notes": ai_response.get("notes") or "",
        "unmappedDatabaseFields": [field for field in allowed_schema if field not in mapped_schema],
        "unmappedPdfFields": [tag for tag in allowed_template if tag not in mapped_template],
        "confidence": overall_confidence,
        "totalMappings": len(sanitized_mappings),
    }


def _resolve_upload_limit() -> tuple[int, int]:
    """
    Resolve the max upload size for PDFs.

    We parse the env once and return (max_mb, max_bytes) so callers can enforce
    size limits without duplicating the conversion logic.
    """
    try:
        max_mb = int(os.getenv("SANDBOX_MAX_UPLOAD_MB", "50"))
    except ValueError:
        max_mb = 50
    if max_mb < 1:
        max_mb = 1
    return max_mb, max_mb * 1024 * 1024


async def _read_upload_bytes(upload: UploadFile, *, max_bytes: int, limit_message: str) -> bytes:
    """
    Read an UploadFile into memory with a hard size cap.

    Implementation detail:
    - Use a bytearray as a mutable buffer to avoid repeated reallocations.
    - Read fixed-size chunks so we can stop as soon as the cap is exceeded.
    """
    chunk_size = 1024 * 1024
    buffer = bytearray()
    total = 0
    while True:
        chunk = await upload.read(chunk_size)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(status_code=413, detail=limit_message)
        buffer.extend(chunk)
    return bytes(buffer)


def _write_upload_to_temp(upload: UploadFile, *, max_bytes: int, limit_message: str) -> Path:
    """
    Write UploadFile to a temp PDF so we can stream it to storage buckets.

    We stream fixed-size chunks from the upload to avoid holding the full PDF in memory
    while still enforcing an upper bound on the total bytes written.
    """
    suffix = ".pdf" if (upload.filename or "").lower().endswith(".pdf") else ""
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        total = 0
        while True:
            chunk = upload.file.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                tmp.flush()
                tmp.close()
                Path(tmp.name).unlink(missing_ok=True)
                raise HTTPException(status_code=413, detail=limit_message)
            tmp.write(chunk)
        return Path(tmp.name)


_require_prod_env()

_DOCS_ENABLED = _docs_enabled()
app = FastAPI(
    title="Sandbox PDF Field Detector",
    docs_url="/docs" if _DOCS_ENABLED else None,
    redoc_url="/redoc" if _DOCS_ENABLED else None,
    openapi_url="/openapi.json" if _DOCS_ENABLED else None,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_resolve_cors_origins(),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def enforce_security_guards(request: Request, call_next):
    """
    Enforce auth before body parsing and hide legacy endpoints when disabled.
    """
    origin = request.headers.get("origin")
    cors_headers = _resolve_stream_cors_headers(origin)
    if request.method == "OPTIONS":
        return await call_next(request)

    path = request.url.path
    if not _legacy_endpoints_enabled() and (
        path in {"/api/process-pdf", "/api/register-fillable", "/api/detected-fields"}
        or path.startswith("/download/")
    ):
        return JSONResponse(status_code=404, content={"detail": "Not found"}, headers=cors_headers)

    if path == "/detect-fields" or path.startswith("/detect-fields/"):
        authorization = request.headers.get("authorization")
        x_admin_token = request.headers.get("x-admin-token")
        if _has_admin_override(authorization, x_admin_token):
            request.state.detect_admin_override = True
            return await call_next(request)
        try:
            request.state.detect_auth_payload = _verify_token(authorization)
        except HTTPException as exc:
            return JSONResponse(
                status_code=exc.status_code,
                content={"detail": exc.detail},
                headers=cors_headers,
            )
        return await call_next(request)

    if path.startswith("/api/") and path != "/api/health":
        authorization = request.headers.get("authorization")
        try:
            request.state.preverified_auth_payload = _verify_token(authorization)
        except HTTPException as exc:
            return JSONResponse(
                status_code=exc.status_code,
                content={"detail": exc.detail},
                headers=cors_headers,
            )
        return await call_next(request)

    if path.startswith("/download/"):
        authorization = request.headers.get("authorization")
        try:
            request.state.preverified_auth_payload = _verify_token(authorization)
        except HTTPException as exc:
            return JSONResponse(
                status_code=exc.status_code,
                content={"detail": exc.detail},
                headers=cors_headers,
            )
        return await call_next(request)

    return await call_next(request)


@app.get("/health")
async def health() -> Dict[str, str]:
    """
    Liveness probe.
    """
    return {"status": "ok"}


@app.get("/api/health")
async def api_health() -> Dict[str, str]:
    """
    API health probe for clients.
    """
    return {"status": "ok"}


@app.get("/api/profile")
async def get_profile(authorization: Optional[str] = Header(default=None)) -> Dict[str, Any]:
    """
    Return the current user's profile details and limits.
    """
    user = _require_user(authorization)
    profile = get_user_profile(user.app_user_id)
    role = normalize_role(user.role)
    credits_remaining: Optional[int] = None
    if profile:
        credits_remaining = profile.openai_credits_remaining
    if role == ROLE_GOD:
        credits_remaining = None
    return {
        "email": user.email,
        "displayName": user.display_name,
        "role": role,
        "creditsRemaining": credits_remaining,
        "limits": _resolve_role_limits(role),
    }


@app.post("/api/process-pdf")
async def process_pdf(
    pdf: UploadFile = File(...),
    pipeline: Optional[str] = None,
    pipeline_form: Optional[str] = Form(None, alias="pipeline"),
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    """
    CommonForms-only detection endpoint for the upload UI.
    """
    _require_legacy_enabled()
    user = _require_user(authorization)
    if not pdf:
        raise HTTPException(status_code=400, detail="Missing PDF upload")

    source_pdf = pdf.filename or "upload.pdf"
    content_type = (pdf.content_type or "").lower()
    if not source_pdf.lower().endswith(".pdf") and content_type not in {"application/pdf", "application/octet-stream"}:
        raise HTTPException(status_code=400, detail="Only PDF uploads are supported")

    max_mb, max_bytes = _resolve_upload_limit()
    pdf_bytes = await _read_upload_bytes(
        pdf,
        max_bytes=max_bytes,
        limit_message=f"PDF exceeds {max_mb}MB upload limit",
    )
    if not pdf_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")
    validation = _validate_pdf_for_detection(pdf_bytes)
    pdf_bytes = validation.pdf_bytes
    page_count = validation.page_count
    if validation.was_decrypted:
        logger.info("Detection PDF decrypted with empty password.")
    max_pages = _resolve_detect_max_pages(user.role)
    if page_count > max_pages:
        raise HTTPException(
            status_code=403,
            detail=f"Detection limited to {max_pages} pages for your tier (got {page_count}).",
        )

    pipeline_choice = (pipeline or pipeline_form or "commonforms").strip().lower()
    if pipeline_choice != "commonforms":
        raise HTTPException(status_code=400, detail="Unsupported pipeline selection")
    detection_mode = _resolve_detection_mode()
    if detection_mode == "local":
        session_id = str(uuid.uuid4())
        record_detection_request(
            request_id=session_id,
            session_id=session_id,
            user_id=user.app_user_id,
            status=DETECTION_STATUS_RUNNING,
            page_count=page_count,
        )
        try:
            resolved = _run_local_detection(pdf_bytes)
            fields = resolved.get("fields", [])
            _store_session_entry(
                session_id,
                {
                    "pdf_bytes": pdf_bytes,
                    "fields": fields,
                    "source_pdf": source_pdf,
                    "result": resolved,
                    "page_count": page_count,
                    "user_id": user.app_user_id,
                    "detection_status": DETECTION_STATUS_COMPLETE,
                    "detection_completed_at": now_iso(),
                },
            )
            update_detection_request(
                request_id=session_id,
                status=DETECTION_STATUS_COMPLETE,
                page_count=page_count,
            )
            return {
                "success": True,
                "sessionId": session_id,
                "originalFilename": source_pdf,
                "pipeline": resolved.get("pipeline", pipeline_choice),
                "fieldCount": len(fields),
                "fields": fields,
                "result": resolved,
                "status": DETECTION_STATUS_COMPLETE,
            }
        except Exception as exc:
            update_detection_request(
                request_id=session_id,
                status=DETECTION_STATUS_FAILED,
                error=str(exc),
                page_count=page_count,
            )
            raise
    if detection_mode == "tasks":
        response = _enqueue_detection_job(pdf_bytes, source_pdf, user, page_count=page_count)
        return {
            "success": True,
            "originalFilename": source_pdf,
            **response,
        }
    raise HTTPException(status_code=500, detail=f"Unsupported detection mode: {detection_mode}")


@app.post("/api/register-fillable")
async def register_fillable_pdf(
    pdf: UploadFile = File(...),
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    """
    Register a PDF for later field upload/merge flows without running detection.
    """
    _require_legacy_enabled()
    user = _require_user(authorization)
    if not pdf:
        raise HTTPException(status_code=400, detail="Missing PDF upload")

    source_pdf = pdf.filename or "upload.pdf"
    content_type = (pdf.content_type or "").lower()
    if not source_pdf.lower().endswith(".pdf") and content_type not in {"application/pdf", "application/octet-stream"}:
        raise HTTPException(status_code=400, detail="Only PDF uploads are supported")

    session_id = str(uuid.uuid4())
    max_mb, max_bytes = _resolve_upload_limit()
    pdf_bytes = await _read_upload_bytes(
        pdf,
        max_bytes=max_bytes,
        limit_message=f"PDF exceeds {max_mb}MB upload limit",
    )
    if not pdf_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    page_count = _get_pdf_page_count(pdf_bytes)
    max_pages = _resolve_fillable_max_pages(user.role)
    if page_count > max_pages:
        raise HTTPException(
            status_code=403,
            detail=f"Fillable upload limited to {max_pages} pages for your tier (got {page_count}).",
        )
    _store_session_entry(
        session_id,
        {
            "pdf_bytes": pdf_bytes,
            "fields": [],
            "source_pdf": source_pdf,
            "result": {},
            "page_count": page_count,
            "user_id": user.app_user_id,
        },
    )
    return {
        "success": True,
        "sessionId": session_id,
        "originalFilename": source_pdf,
    }


@app.get("/api/detected-fields")
async def get_detected_fields(
    sessionId: str,
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    """
    Return cached fields for a prior session.
    """
    _require_legacy_enabled()
    user = _require_user(authorization)
    entry = _get_session_entry(
        sessionId,
        user,
        include_pdf_bytes=False,
        include_result=False,
        include_renames=False,
        include_checkbox_rules=False,
        force_l2=True,
    )
    fields = entry.get("fields", [])
    return {
        "success": True,
        "sessionId": sessionId,
        "items": fields,
        "total": len(fields),
        "status": entry.get("detection_status") or DETECTION_STATUS_COMPLETE,
    }


@app.post("/api/sessions/{session_id}/touch")
async def touch_session(
    session_id: str,
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    """
    Refresh the session TTL so long-lived editor sessions are not cleaned up.
    """
    user = _require_user(authorization)
    _touch_session_entry(session_id, user)
    return {"success": True, "sessionId": session_id}


@app.get("/download/{session_id}")
async def download_session_pdf(
    session_id: str,
    authorization: Optional[str] = Header(default=None),
):
    """
    Stream the original PDF bytes for a session.
    """
    _require_legacy_enabled()
    user = _require_user(authorization)
    entry = _get_session_entry(
        session_id,
        user,
        include_pdf_bytes=False,
        include_fields=False,
        include_result=False,
        include_renames=False,
        include_checkbox_rules=False,
    )
    filename = _safe_pdf_download_filename(entry.get("source_pdf") or "document")
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    pdf_bytes = entry.get("pdf_bytes")
    if pdf_bytes:
        stream = io.BytesIO(pdf_bytes)
    else:
        pdf_path = entry.get("pdf_path")
        if not pdf_path:
            raise HTTPException(status_code=404, detail="Session PDF not found")
        stream = stream_pdf(pdf_path)
    return StreamingResponse(stream, media_type="application/pdf", headers=headers)


@app.post("/detect-fields")
async def detect_fields(
    request: Request,
    file: UploadFile = File(...),
    pipeline: Optional[str] = None,
    pipeline_form: Optional[str] = Form(None, alias="pipeline"),
    authorization: Optional[str] = Header(default=None),
    x_admin_token: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    """
    Main detection endpoint: CommonForms field detection only.
    """
    auth_payload: Optional[Dict[str, Any]] = getattr(request.state, "detect_auth_payload", None)
    user: Optional[RequestUser] = None
    admin_override = getattr(request.state, "detect_admin_override", False)
    if not admin_override:
        admin_override = _has_admin_override(authorization, x_admin_token)
    if not admin_override:
        if auth_payload is None:
            auth_payload = _verify_token(authorization)
        try:
            user = ensure_user(auth_payload or {})
        except Exception as exc:
            logger.error("Failed to sync Firebase user profile: %s", exc)
            raise HTTPException(status_code=500, detail="Failed to synchronize user profile") from exc
    if not file:
        raise HTTPException(status_code=400, detail="Missing PDF upload")

    if not admin_override and user:
        try:
            window_seconds = int(os.getenv("SANDBOX_DETECT_RATE_LIMIT_WINDOW_SECONDS", "30"))
        except ValueError:
            window_seconds = 30
        try:
            user_rate = int(os.getenv("SANDBOX_DETECT_RATE_LIMIT_PER_USER", "6"))
        except ValueError:
            user_rate = 6
        if not check_rate_limit(
            f"detect:user:{user.app_user_id}",
            limit=user_rate,
            window_seconds=window_seconds,
        ):
            raise HTTPException(status_code=429, detail="Rate limit exceeded for user")

    source_pdf = file.filename or "upload.pdf"
    content_type = (file.content_type or "").lower()
    if not source_pdf.lower().endswith(".pdf") and content_type not in {"application/pdf", "application/octet-stream"}:
        raise HTTPException(status_code=400, detail="Only PDF uploads are supported")

    max_mb, max_bytes = _resolve_upload_limit()
    pdf_bytes = await _read_upload_bytes(
        file,
        max_bytes=max_bytes,
        limit_message=f"PDF exceeds {max_mb}MB upload limit",
    )
    if not pdf_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")
    validation = _validate_pdf_for_detection(pdf_bytes)
    pdf_bytes = validation.pdf_bytes
    page_count = validation.page_count
    if validation.was_decrypted:
        logger.info("Detection PDF decrypted with empty password.")
    if not admin_override and user:
        max_pages = _resolve_detect_max_pages(user.role)
        if page_count > max_pages:
            raise HTTPException(
                status_code=403,
                detail=f"Detection limited to {max_pages} pages for your tier (got {page_count}).",
            )
    if auth_payload and auth_payload.get("uid"):
        logger.info("Detection request by %s", auth_payload["uid"])
    elif admin_override:
        logger.info("Detection request by admin override")
    logger.info("Starting detection for %s", _log_pdf_label(source_pdf))

    pipeline_choice = (pipeline or pipeline_form or "commonforms").strip().lower()
    if pipeline_choice != "commonforms":
        raise HTTPException(status_code=400, detail="Unsupported pipeline selection")

    detection_mode = _resolve_detection_mode()
    if detection_mode == "local":
        session_id = str(uuid.uuid4())
        record_detection_request(
            request_id=session_id,
            session_id=session_id,
            user_id=user.app_user_id if user else None,
            status=DETECTION_STATUS_RUNNING,
            page_count=page_count,
        )
        try:
            resolved = _run_local_detection(pdf_bytes)
            fields = resolved.get("fields", [])
            _store_session_entry(
                session_id,
                {
                    "pdf_bytes": pdf_bytes,
                    "fields": fields,
                    "source_pdf": source_pdf,
                    "result": resolved,
                    "page_count": page_count,
                    "user_id": user.app_user_id if user else None,
                    "detection_status": DETECTION_STATUS_COMPLETE,
                    "detection_completed_at": now_iso(),
                },
            )
            update_detection_request(
                request_id=session_id,
                status=DETECTION_STATUS_COMPLETE,
                page_count=page_count,
            )
            logger.info(
                "Session %s -> %s final fields produced (commonforms pipeline)",
                session_id,
                len(fields),
            )
            return {
                **resolved,
                "sessionId": session_id,
                "status": DETECTION_STATUS_COMPLETE,
            }
        except Exception as exc:
            update_detection_request(
                request_id=session_id,
                status=DETECTION_STATUS_FAILED,
                error=str(exc),
                page_count=page_count,
            )
            raise

    if detection_mode == "tasks":
        response = _enqueue_detection_job(pdf_bytes, source_pdf, user, page_count=page_count)
        logger.info("Session %s -> queued detection job", response.get("sessionId"))
        return response

    raise HTTPException(status_code=500, detail=f"Unsupported detection mode: {detection_mode}")


@app.get("/detect-fields/{session_id}")
async def get_detection_status(
    request: Request,
    session_id: str,
    authorization: Optional[str] = Header(default=None),
    x_admin_token: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    """
    Return detector job status and results when available.
    """
    user: Optional[RequestUser] = None
    admin_override = getattr(request.state, "detect_admin_override", False)
    if not admin_override:
        admin_override = _has_admin_override(authorization, x_admin_token)
    if not admin_override:
        auth_payload = getattr(request.state, "detect_auth_payload", None)
        if auth_payload is None:
            auth_payload = _verify_token(authorization)
        try:
            user = ensure_user(auth_payload)
        except Exception as exc:
            logger.error("Failed to sync Firebase user profile: %s", exc)
            raise HTTPException(status_code=500, detail="Failed to synchronize user profile") from exc

    metadata = get_session_metadata(session_id)
    if not metadata:
        raise HTTPException(status_code=404, detail="Session not found")
    owner_id = metadata.get("user_id")
    if not admin_override:
        if not owner_id:
            raise HTTPException(status_code=403, detail="Session access denied")
        if owner_id != user.app_user_id:
            raise HTTPException(status_code=403, detail="Session access denied")

    status = metadata.get("detection_status")
    if not status:
        status = DETECTION_STATUS_COMPLETE if metadata.get("fields_path") else DETECTION_STATUS_FAILED

    response: Dict[str, Any] = {
        "sessionId": session_id,
        "status": status,
        "pipeline": "commonforms",
        "sourcePdf": metadata.get("source_pdf"),
        "pageCount": metadata.get("page_count"),
        "detectionQueuedAt": metadata.get("detection_queued_at"),
        "detectionStartedAt": metadata.get("detection_started_at"),
        "detectionDurationSeconds": metadata.get("detection_duration_seconds"),
        "detectionProfile": metadata.get("detection_profile"),
        "detectionQueue": metadata.get("detection_queue"),
        "detectionServiceUrl": metadata.get("detection_service_url"),
    }

    if status == DETECTION_STATUS_FAILED:
        response["error"] = metadata.get("detection_error") or "Detection failed"
        return response

    if status != DETECTION_STATUS_COMPLETE:
        return response

    fields_path = metadata.get("fields_path")
    result_path = metadata.get("result_path")
    fields = download_session_json(fields_path) if fields_path else []
    response["fields"] = fields
    response["fieldCount"] = len(fields)
    if result_path:
        response["result"] = download_session_json(result_path) or {}
    return response


@app.post("/api/schemas")
async def create_schema_endpoint(
    payload: SchemaCreateRequest,
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    """
    Create a schema record containing only headers and inferred types.
    """
    user = _require_user(authorization)
    raw_fields = [field.model_dump() for field in payload.fields]
    allowlist = build_allowlist_payload(raw_fields, [])
    schema_fields = allowlist.get("schemaFields") or []
    if not schema_fields:
        raise HTTPException(status_code=400, detail="Schema fields are required")
    try:
        validate_payload_size(allowlist)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    record = create_schema(
        user_id=user.app_user_id,
        fields=schema_fields,
        name=payload.name,
        source=payload.source,
        sample_count=payload.sampleCount,
    )
    logger.info("Schema stored: %s (fields=%s)", record.id, len(schema_fields))
    return {
        "success": True,
        "schemaId": record.id,
        "name": record.name,
        "fieldCount": len(record.fields),
        "fields": record.fields,
        "createdAt": record.created_at,
    }


@app.get("/api/schemas")
async def list_schemas_endpoint(authorization: Optional[str] = Header(default=None)) -> Dict[str, Any]:
    """
    List schemas owned by the caller.
    """
    user = _require_user(authorization)
    records = list_schemas(user.app_user_id)
    return {
        "schemas": [
            {
                "id": record.id,
                "name": record.name,
                "fieldCount": len(record.fields),
                "fields": record.fields,
                "createdAt": record.created_at,
            }
            for record in records
        ]
    }


@app.post("/api/renames/ai")
async def rename_fields_ai(
    request: Request,
    payload: RenameFieldsRequest,
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    """
    Run OpenAI rename using cached PDF bytes and overlay tags.

    parsing R response lines (excluding OpenAI latency).
    """
    auth_payload = getattr(request.state, "preverified_auth_payload", None)
    if auth_payload is None:
        user = _require_user(authorization)
    else:
        try:
            user = ensure_user(auth_payload)
        except Exception as exc:
            logger.error("Failed to sync Firebase user profile: %s", exc)
            raise HTTPException(status_code=500, detail="Failed to synchronize user profile") from exc

    entry = _get_session_entry(
        payload.sessionId,
        user,
        include_result=False,
        include_renames=False,
        include_checkbox_rules=False,
        force_l2=True,
    )
    pdf_bytes = entry.get("pdf_bytes")
    if not pdf_bytes:
        raise HTTPException(status_code=404, detail="Session PDF not found")

    rename_fields: List[Dict[str, Any]]
    if payload.templateFields:
        rename_fields = _template_fields_to_rename_fields(payload.templateFields)
    else:
        rename_fields = list(entry.get("fields") or [])
    if not rename_fields:
        raise HTTPException(status_code=400, detail="No fields available for rename")

    database_fields: Optional[List[str]] = None
    schema_id: Optional[str] = None
    if payload.schemaId:
        schema = get_schema(payload.schemaId, user.app_user_id)
        if not schema:
            raise HTTPException(status_code=404, detail="Schema not found")
        allowlist = build_allowlist_payload(schema.fields, [])
        schema_fields = allowlist.get("schemaFields") or []
        if not schema_fields:
            raise HTTPException(status_code=400, detail="Schema fields are required for rename")
        try:
            validate_payload_size(allowlist)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        database_fields = [field.get("name") for field in schema_fields if field.get("name")]
        schema_id = schema.id

    try:
        window_seconds = int(os.getenv("OPENAI_RENAME_RATE_LIMIT_WINDOW_SECONDS", "60"))
    except ValueError:
        window_seconds = 60
    try:
        user_rate = int(os.getenv("OPENAI_RENAME_RATE_LIMIT_PER_USER", "6"))
    except ValueError:
        user_rate = 6

    if not check_rate_limit(f"rename:user:{user.app_user_id}", limit=user_rate, window_seconds=window_seconds):
        raise HTTPException(status_code=429, detail="Rate limit exceeded for user")

    page_count = entry.get("page_count") or _get_pdf_page_count(pdf_bytes)
    remaining, allowed = consume_openai_credits(
        user.app_user_id,
        pages=page_count,
        role=user.role,
    )
    if not allowed:
        raise HTTPException(
            status_code=402,
            detail=f"OpenAI credits exhausted (remaining={remaining}, required={page_count})",
        )
    credits_charged = normalize_role(user.role) != ROLE_GOD

    request_id = uuid.uuid4().hex
    record_openai_rename_request(
        request_id=request_id,
        user_id=user.app_user_id,
        session_id=payload.sessionId,
        schema_id=schema_id,
    )

    logger.info(
        "OpenAI rename request %s (session=%s fields=%s)",
        request_id,
        payload.sessionId,
        len(rename_fields),
    )
    try:
        rename_report, renamed_fields = run_openai_rename_on_pdf(
            pdf_bytes=pdf_bytes,
            pdf_name=entry.get("source_pdf") or "document.pdf",
            fields=rename_fields,
            database_fields=database_fields,
        )
    except Exception as exc:
        if credits_charged:
            try:
                refund_openai_credits(
                    user.app_user_id,
                    pages=page_count,
                    role=user.role,
                )
            except Exception as refund_exc:
                logger.warning("Failed to refund OpenAI credits for rename: %s", refund_exc)
        status_code = getattr(exc, "status_code", None) or 500
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc

    checkbox_rules = rename_report.get("checkboxRules") or []
    entry["fields"] = renamed_fields
    entry["renames"] = rename_report
    entry["checkboxRules"] = checkbox_rules
    entry["openai_credit_consumed"] = True
    entry["openai_credit_pages"] = page_count
    entry["openai_credit_mapping_used"] = False
    entry["page_count"] = page_count
    _update_session_entry(
        payload.sessionId,
        entry,
        persist_fields=True,
        persist_renames=True,
        persist_checkbox_rules=True,
    )

    return {
        "success": True,
        "requestId": request_id,
        "sessionId": payload.sessionId,
        "schemaId": schema_id,
        "renames": rename_report,
        "fields": renamed_fields,
        "checkboxRules": checkbox_rules,
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
    }


@app.post("/api/schema-mappings/ai")
async def map_schema_ai(
    request: Request,
    payload: SchemaMappingRequest,
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    """
    Run OpenAI mapping using schema metadata + template overlay tags.
    """
    auth_payload = getattr(request.state, "preverified_auth_payload", None)
    if auth_payload is None:
        user = _require_user(authorization)
    else:
        try:
            user = ensure_user(auth_payload)
        except Exception as exc:
            logger.error("Failed to sync Firebase user profile: %s", exc)
            raise HTTPException(status_code=500, detail="Failed to synchronize user profile") from exc
    schema = get_schema(payload.schemaId, user.app_user_id)
    if not schema:
        raise HTTPException(status_code=404, detail="Schema not found")

    template = None
    if payload.templateId:
        template = get_template(payload.templateId, user.app_user_id)
        if not template:
            raise HTTPException(status_code=403, detail="Template access denied")
    if not payload.sessionId and not template:
        raise HTTPException(status_code=400, detail="sessionId or templateId is required")

    template_fields = [field.model_dump() for field in payload.templateFields]
    if not template_fields:
        raise HTTPException(status_code=400, detail="templateFields is required")

    allowlist_payload = build_allowlist_payload(schema.fields, template_fields)
    template_tags = allowlist_payload.get("templateTags") or []
    if not template_tags:
        raise HTTPException(status_code=400, detail="No valid template tags provided")
    schema_fields = allowlist_payload.get("schemaFields") or []
    try:
        window_seconds = int(os.getenv("OPENAI_SCHEMA_RATE_LIMIT_WINDOW_SECONDS", "60"))
    except ValueError:
        window_seconds = 60
    try:
        user_rate = int(os.getenv("OPENAI_SCHEMA_RATE_LIMIT_PER_USER", "10"))
    except ValueError:
        user_rate = 10

    if not check_rate_limit(f"user:{user.app_user_id}", limit=user_rate, window_seconds=window_seconds):
        raise HTTPException(status_code=429, detail="Rate limit exceeded for user")

    session_entry = None
    if payload.sessionId:
        session_entry = _get_session_entry(
            payload.sessionId,
            user,
            include_pdf_bytes=False,
            include_fields=False,
            include_result=False,
            include_renames=False,
            include_checkbox_rules=False,
        )
    skip_credit = False
    if session_entry and session_entry.get("openai_credit_consumed"):
        if not session_entry.get("openai_credit_mapping_used"):
            skip_credit = True

    credits_charged = False
    charged_pages = 0
    if not skip_credit:
        page_count = None
        if session_entry:
            page_count = session_entry.get("openai_credit_pages") or session_entry.get("page_count")
            if not page_count and session_entry.get("pdf_bytes"):
                page_count = _get_pdf_page_count(session_entry["pdf_bytes"])
        elif template and template.pdf_bucket_path and is_gcs_path(template.pdf_bucket_path):
            try:
                pdf_bytes = download_pdf_bytes(template.pdf_bucket_path)
            except Exception as exc:
                logger.exception("Failed to load template PDF for mapping credits")
                raise HTTPException(status_code=500, detail="Failed to load template PDF") from exc
            page_count = _get_pdf_page_count(pdf_bytes)
        if not page_count:
            page_count = _estimate_template_page_count(template_fields)
        remaining, allowed = consume_openai_credits(
            user.app_user_id,
            pages=page_count,
            role=user.role,
        )
        if not allowed:
            raise HTTPException(
                status_code=402,
                detail=f"OpenAI credits exhausted (remaining={remaining}, required={page_count})",
            )
        credits_charged = normalize_role(user.role) != ROLE_GOD
        charged_pages = page_count

    request_id = uuid.uuid4().hex
    record_openai_request(
        request_id=request_id,
        user_id=user.app_user_id,
        schema_id=schema.id,
        template_id=payload.templateId,
    )

    logger.info(
        "OpenAI schema mapping request %s (schema=%s tags=%s)",
        request_id,
        schema.id,
        len(template_tags),
    )
    try:
        ai_response = call_openai_schema_mapping_chunked(allowlist_payload)
    except ValueError as exc:
        if credits_charged:
            try:
                refund_openai_credits(
                    user.app_user_id,
                    pages=charged_pages,
                    role=user.role,
                )
            except Exception as refund_exc:
                logger.warning("Failed to refund OpenAI credits for mapping: %s", refund_exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        if credits_charged:
            try:
                refund_openai_credits(
                    user.app_user_id,
                    pages=charged_pages,
                    role=user.role,
                )
            except Exception as refund_exc:
                logger.warning("Failed to refund OpenAI credits for mapping: %s", refund_exc)
        status_code = getattr(exc, "status_code", None) or 500
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc

    mapping_results = _build_schema_mapping_payload(
        allowlist_payload.get("schemaFields") or [],
        allowlist_payload.get("templateTags") or [],
        ai_response,
    )
    if skip_credit and session_entry and payload.sessionId:
        session_entry["openai_credit_mapping_used"] = True
        _update_session_entry(payload.sessionId, session_entry)
    return {
        "success": True,
        "requestId": request_id,
        "schemaId": schema.id,
        "mappingResults": mapping_results,
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
    }


@app.post("/api/forms/materialize")
async def materialize_form(
    background_tasks: BackgroundTasks,
    request: Request,
    pdf: UploadFile = File(...),
    fields: str = Form(...),
    authorization: Optional[str] = Header(default=None),
):
    """
    Inject fields into a PDF and return a fillable PDF download.
    """
    _verify_token(authorization)
    if not pdf:
        raise HTTPException(status_code=400, detail="No PDF file uploaded")

    filename = pdf.filename or "form.pdf"
    content_type = (pdf.content_type or "").lower()
    if not filename.lower().endswith(".pdf") and content_type not in {"application/pdf", "application/octet-stream"}:
        raise HTTPException(status_code=400, detail="Only PDF uploads are supported")

    try:
        raw_payload = json.loads(fields)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid fields payload") from exc

    if isinstance(raw_payload, dict):
        template = dict(raw_payload)
        raw_fields = list(template.get("fields") or [])
    elif isinstance(raw_payload, list):
        template = {}
        raw_fields = list(raw_payload)
    else:
        raise HTTPException(status_code=400, detail="Invalid fields payload")

    max_mb, max_bytes = _resolve_upload_limit()
    temp_path = _write_upload_to_temp(
        pdf,
        max_bytes=max_bytes,
        limit_message=f"PDF exceeds {max_mb}MB upload limit",
    )

    if not raw_fields:
        background_tasks.add_task(_cleanup_paths, [temp_path])
        output_name = _safe_pdf_download_filename(filename, "form")
        response = FileResponse(
            str(temp_path),
            media_type="application/pdf",
            filename=output_name,
            background=background_tasks,
        )
        response.headers.update(_resolve_stream_cors_headers(request.headers.get("origin")))
        return response

    template.setdefault("coordinateSystem", "originTop")
    template["fields"] = _coerce_field_payloads(raw_fields)

    template_fd, template_name = tempfile.mkstemp(suffix=".json")
    os.close(template_fd)
    template_path = Path(template_name)
    template_path.write_text(json.dumps(template), encoding="utf-8")
    output_fd, output_name = tempfile.mkstemp(suffix=".pdf")
    os.close(output_fd)
    output_path = Path(output_name)

    try:
        inject_fields(temp_path, template_path, output_path)
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Failed to generate fillable PDF") from exc
    finally:
        background_tasks.add_task(_cleanup_paths, [temp_path, template_path, output_path])

    stem = os.path.splitext(filename)[0] or "form"
    output_name = _safe_pdf_download_filename(f"{stem}-fillable", "form")
    response = FileResponse(
        str(output_path),
        media_type="application/pdf",
        filename=output_name,
        background=background_tasks,
    )
    response.headers.update(_resolve_stream_cors_headers(request.headers.get("origin")))
    return response


@app.get("/api/saved-forms")
async def list_saved_forms(authorization: Optional[str] = Header(default=None)) -> Dict[str, Any]:
    """
    List saved form metadata for the current user.
    """
    user = _require_user(authorization)
    templates = list_templates(user.app_user_id)
    forms = [
        {
            "id": tpl.id,
            "name": tpl.name or tpl.pdf_bucket_path or "Saved form",
            "createdAt": tpl.created_at,
        }
        for tpl in templates
    ]
    return {"forms": forms}


@app.get("/api/saved-forms/{form_id}")
async def get_saved_form(form_id: str, authorization: Optional[str] = Header(default=None)) -> Dict[str, Any]:
    """
    Return metadata for a saved form.
    """
    user = _require_user(authorization)
    if not form_id:
        raise HTTPException(status_code=400, detail="Missing form id")
    template = get_template(form_id, user.app_user_id)
    if not template:
        raise HTTPException(status_code=404, detail="Form not found")
    return {
        "url": f"/api/saved-forms/{form_id}/download",
        "name": template.name or template.pdf_bucket_path or "Saved form",
        "sessionId": template.id,
    }


@app.get("/api/saved-forms/{form_id}/download")
async def download_saved_form(
    form_id: str,
    request: Request,
    authorization: Optional[str] = Header(default=None),
):
    """
    Stream a saved form PDF from storage.
    """
    user = _require_user(authorization)
    if not form_id:
        raise HTTPException(status_code=400, detail="Missing form id")
    template = get_template(form_id, user.app_user_id)
    if not template:
        raise HTTPException(status_code=404, detail="Form not found")
    if not template.pdf_bucket_path or not is_gcs_path(template.pdf_bucket_path):
        raise HTTPException(status_code=404, detail="Form PDF not found in storage")

    logger.debug("Streaming form from storage", {"pdf_bucket_path": template.pdf_bucket_path})
    stream = stream_pdf(template.pdf_bucket_path)
    filename = _safe_pdf_download_filename(template.name or template.pdf_bucket_path or "form", "form")
    headers = {"Content-Disposition": f'inline; filename="{filename}"'}
    headers.update(_resolve_stream_cors_headers(request.headers.get("origin")))
    return StreamingResponse(stream, media_type="application/pdf", headers=headers)


@app.post("/api/saved-forms/{form_id}/session")
async def create_saved_form_session(
    form_id: str,
    payload: SavedFormSessionRequest,
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    """
    Create a detection session for a saved form using extracted fields.
    """
    user = _require_user(authorization)
    if not form_id:
        raise HTTPException(status_code=400, detail="Missing form id")
    template = get_template(form_id, user.app_user_id)
    if not template:
        raise HTTPException(status_code=404, detail="Form not found")
    if not template.pdf_bucket_path or not is_gcs_path(template.pdf_bucket_path):
        raise HTTPException(status_code=404, detail="Form PDF not found in storage")

    fields = _coerce_field_payloads(payload.fields)
    if not fields:
        raise HTTPException(status_code=400, detail="No fields provided for saved form session")

    try:
        pdf_bytes = download_pdf_bytes(template.pdf_bucket_path)
    except Exception as exc:
        logger.exception("Failed to load saved form PDF for session %s", form_id)
        raise HTTPException(status_code=500, detail="Failed to load saved form PDF") from exc
    page_count = _get_pdf_page_count(pdf_bytes)

    session_id = str(uuid.uuid4())
    entry: Dict[str, Any] = {
        "user_id": user.app_user_id,
        "source_pdf": template.name or template.pdf_bucket_path or "saved-form.pdf",
        "pdf_path": template.pdf_bucket_path,
        "fields": fields,
        "page_count": page_count,
        "detection_status": DETECTION_STATUS_COMPLETE,
        "detection_completed_at": now_iso(),
    }
    _store_session_entry(
        session_id,
        entry,
        persist_pdf=False,
        persist_fields=True,
        persist_result=False,
    )
    return {"success": True, "sessionId": session_id, "fieldCount": len(fields)}


@app.post("/api/templates/session")
async def create_template_session(
    pdf: UploadFile = File(...),
    fields: str = Form(...),
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    """
    Create a session for a fillable template upload so OpenAI rename/mapping can run.
    """
    user = _require_user(authorization)
    if not pdf:
        raise HTTPException(status_code=400, detail="Missing PDF upload")

    source_pdf = pdf.filename or "upload.pdf"
    content_type = (pdf.content_type or "").lower()
    if not source_pdf.lower().endswith(".pdf") and content_type not in {"application/pdf", "application/octet-stream"}:
        raise HTTPException(status_code=400, detail="Only PDF uploads are supported")

    try:
        raw_payload = json.loads(fields)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid fields payload") from exc

    if isinstance(raw_payload, dict):
        raw_fields = list(raw_payload.get("fields") or [])
    elif isinstance(raw_payload, list):
        raw_fields = list(raw_payload)
    else:
        raise HTTPException(status_code=400, detail="Invalid fields payload")

    template_fields = _coerce_field_payloads(raw_fields)
    if not template_fields:
        raise HTTPException(status_code=400, detail="No fields provided for template session")

    max_mb, max_bytes = _resolve_upload_limit()
    pdf_bytes = await _read_upload_bytes(
        pdf,
        max_bytes=max_bytes,
        limit_message=f"PDF exceeds {max_mb}MB upload limit",
    )
    if not pdf_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    validation = _validate_pdf_for_detection(pdf_bytes)
    max_pages = _resolve_fillable_max_pages(user.role)
    if validation.page_count > max_pages:
        raise HTTPException(
            status_code=403,
            detail=f"Fillable upload limited to {max_pages} pages for your tier (got {validation.page_count}).",
        )
    session_id = str(uuid.uuid4())
    entry: Dict[str, Any] = {
        "user_id": user.app_user_id,
        "source_pdf": source_pdf,
        "pdf_bytes": validation.pdf_bytes,
        "fields": template_fields,
        "page_count": validation.page_count,
        "detection_status": DETECTION_STATUS_COMPLETE,
        "detection_completed_at": now_iso(),
    }
    _store_session_entry(
        session_id,
        entry,
        persist_pdf=True,
        persist_fields=True,
        persist_result=False,
    )
    return {
        "success": True,
        "sessionId": session_id,
        "fieldCount": len(template_fields),
        "pageCount": validation.page_count,
    }


@app.post("/api/saved-forms")
async def save_form(
    pdf: UploadFile = File(...),
    name: str = Form("Saved form"),
    sessionId: Optional[str] = Form(default=None),
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    """
    Upload a PDF and persist it as a saved form + template for the user.
    """
    user = _require_user(authorization)
    if not pdf:
        raise HTTPException(status_code=400, detail="No PDF file uploaded")

    filename = pdf.filename or "upload.pdf"
    content_type = (pdf.content_type or "").lower()
    if not filename.lower().endswith(".pdf") and content_type not in {"application/pdf", "application/octet-stream"}:
        raise HTTPException(status_code=400, detail="Only PDF uploads are supported")

    max_saved_forms = _resolve_saved_forms_limit(user.role)
    existing_templates = list_templates(user.app_user_id)
    if len(existing_templates) >= max_saved_forms:
        raise HTTPException(
            status_code=403,
            detail=f"Saved form limit reached ({max_saved_forms} max).",
        )

    temp_path = None
    uploaded_paths: List[str] = []
    try:
        max_mb, max_bytes = _resolve_upload_limit()
        temp_path = _write_upload_to_temp(
            pdf,
            max_bytes=max_bytes,
            limit_message=f"PDF exceeds {max_mb}MB upload limit",
        )
        try:
            pdf_bytes = temp_path.read_bytes()
        except Exception as exc:
            logger.exception("Failed to read uploaded PDF for validation")
            raise HTTPException(status_code=400, detail="Invalid PDF upload") from exc
        validation = _validate_pdf_for_detection(pdf_bytes)
        max_pages = _resolve_fillable_max_pages(user.role)
        if validation.page_count > max_pages:
            raise HTTPException(
                status_code=403,
                detail=f"Fillable upload limited to {max_pages} pages for your tier (got {validation.page_count}).",
            )

        form_id = uuid.uuid4().hex
        timestamp = int(datetime.now(tz=timezone.utc).timestamp() * 1000)
        forms_object = f"users/{user.app_user_id}/forms/{timestamp}-{form_id}.pdf"
        templates_object = f"users/{user.app_user_id}/templates/{timestamp}-{form_id}.pdf"

        logger.debug("Uploading form to storage", {"formsObject": forms_object})
        pdf_bucket_path = upload_form_pdf(str(temp_path), forms_object)
        uploaded_paths.append(pdf_bucket_path)
        template_bucket_path = upload_template_pdf(str(temp_path), templates_object)
        uploaded_paths.append(template_bucket_path)

        metadata = {"name": name}
        if sessionId and sessionId.strip():
            metadata["originalSessionId"] = sessionId.strip()

        try:
            template = create_template(
                user_id=user.app_user_id,
                pdf_path=pdf_bucket_path,
                template_path=template_bucket_path,
                metadata=metadata,
            )
        except Exception as exc:
            logger.error("Failed to persist template metadata; cleaning up storage: %s", exc)
            for path in uploaded_paths:
                try:
                    delete_pdf(path)
                except Exception as cleanup_exc:
                    logger.error("Failed to delete storage object during cleanup: %s", cleanup_exc)
            raise

        return {
            "success": True,
            "id": template.id,
            "name": template.name or name,
        }
    finally:
        if temp_path and temp_path.exists():
            try:
                temp_path.unlink()
            except Exception as exc:
                logger.debug("Failed to clean temp upload: %s", exc)


@app.delete("/api/saved-forms/{form_id}")
async def delete_saved_form(form_id: str, authorization: Optional[str] = Header(default=None)) -> Dict[str, Any]:
    """
    Delete a saved form and its storage objects.
    """
    user = _require_user(authorization)
    if not form_id:
        raise HTTPException(status_code=400, detail="Missing form id")
    template = get_template(form_id, user.app_user_id)
    if not template:
        raise HTTPException(status_code=404, detail="Form not found")

    deletion_tasks = []
    if template.pdf_bucket_path and is_gcs_path(template.pdf_bucket_path):
        deletion_tasks.append(template.pdf_bucket_path)
    if template.template_bucket_path and template.template_bucket_path != template.pdf_bucket_path:
        if is_gcs_path(template.template_bucket_path):
            deletion_tasks.append(template.template_bucket_path)

    for bucket_path in deletion_tasks:
        try:
            delete_pdf(bucket_path)
        except Exception as exc:
            logger.error("Failed to delete storage object: %s", exc)
            raise HTTPException(status_code=500, detail="Failed to delete saved form") from exc

    removed = delete_template(form_id, user.app_user_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Form not found")

    return {"success": True}


def run():
    """
    Convenience entrypoint for `python -m backend.main`.
    """
    import uvicorn

    uvicorn.run(
        "backend.main:app",
        host="0.0.0.0",
        port=int(8000),
        reload=False,
    )


if __name__ == "__main__":
    run()
