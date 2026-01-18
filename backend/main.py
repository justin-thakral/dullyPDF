"""
FastAPI service for PDF field detection and form management.

Primary pipeline:
- CommonForms ML detection
- OpenAI schema mapping is isolated to schema-only endpoints (no row data).
- OpenAI rename is handled via explicit endpoints with overlay prompts.

Legacy note:
- The OpenCV sandbox pipeline is archived in `legacy/fieldDetecting/` and is not used here.

Data structures:
- _API_SESSION_CACHE: in-memory LRU cache keyed by session_id storing PDF bytes + fields.
"""

import hashlib
import io
import json
import os
import re
import tempfile
import threading
import time
import uuid
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import BackgroundTasks, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from firebase_admin import auth as firebase_auth
from pydantic import BaseModel, Field
import fitz

from .fieldDetecting.commonforms.commonForm import detect_commonforms_fields
from .fieldDetecting.rename_pipeline.combinedSrc.config import get_logger
from .fieldDetecting.rename_pipeline.combinedSrc.form_filler import inject_fields
from .fieldDetecting.rename_pipeline.debug_flags import debug_enabled, get_debug_password
from .ai.rename_pipeline import run_openai_rename_on_pdf
from .ai.schema_mapping import (
    build_allowlist_payload,
    call_openai_schema_mapping_chunked,
    validate_payload_size,
)
from .firebaseDB.app_database import (
    consume_openai_credits,
    create_template,
    delete_template,
    ensure_user,
    get_template,
    list_templates,
)
from .firebaseDB.schema_database import (
    create_mapping,
    create_schema,
    get_schema,
    list_schemas,
    record_openai_request,
    record_openai_rename_request,
)
from .firebaseDB.firebase_service import RequestUser, verify_id_token
from .firebaseDB.storage_service import (
    delete_pdf,
    is_gcs_path,
    stream_pdf,
    upload_form_pdf,
    upload_template_pdf,
)
from .security.rate_limit import check_rate_limit

logger = get_logger(__name__)
# OrderedDict preserves LRU order for O(1) eviction; TTL sweeps are O(n) in cache size.
_API_SESSION_CACHE: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
_SESSION_CACHE_LOCK = threading.Lock()


def _env_value(name: str) -> str:
    return (os.getenv(name) or "").strip()


def _env_truthy(name: str) -> bool:
    return _env_value(name).lower() in {"1", "true", "yes"}


def _int_env(name: str, default: int) -> int:
    raw = _env_value(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


_SESSION_TTL_SECONDS = _int_env("SANDBOX_SESSION_TTL_SECONDS", 3600)
_SESSION_SWEEP_INTERVAL_SECONDS = _int_env("SANDBOX_SESSION_SWEEP_INTERVAL_SECONDS", 300)
_SESSION_MAX_ENTRIES = max(0, _int_env("SANDBOX_SESSION_MAX_ENTRIES", 200))
_LAST_SESSION_SWEEP = 0.0


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
    if not (_env_value("FIREBASE_CREDENTIALS") or _env_value("GOOGLE_APPLICATION_CREDENTIALS")):
        missing.append("FIREBASE_CREDENTIALS or GOOGLE_APPLICATION_CREDENTIALS")
    if not _env_value("FORMS_BUCKET"):
        missing.append("FORMS_BUCKET")
    if not _env_value("TEMPLATES_BUCKET"):
        missing.append("TEMPLATES_BUCKET")
    if missing:
        raise RuntimeError("Missing required prod env vars: " + ", ".join(missing))


def _session_now() -> float:
    return time.monotonic()


def _session_last_access(entry: Dict[str, Any]) -> float:
    raw = entry.get("last_access") or entry.get("created_at") or 0.0
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 0.0


def _prune_session_cache(now: float) -> None:
    """Expire cached sessions after a TTL. Complexity: O(n) over session count."""
    global _LAST_SESSION_SWEEP
    if _SESSION_TTL_SECONDS <= 0:
        return
    if _SESSION_SWEEP_INTERVAL_SECONDS > 0 and (now - _LAST_SESSION_SWEEP) < _SESSION_SWEEP_INTERVAL_SECONDS:
        return
    cutoff = now - _SESSION_TTL_SECONDS
    expired_ids = [
        session_id
        for session_id, entry in _API_SESSION_CACHE.items()
        if _session_last_access(entry) < cutoff
    ]
    for session_id in expired_ids:
        _API_SESSION_CACHE.pop(session_id, None)
    _LAST_SESSION_SWEEP = now


def _trim_session_cache_size() -> None:
    """Evict least-recently-used sessions to enforce size caps. Complexity: O(k) evictions."""
    if _SESSION_MAX_ENTRIES <= 0:
        return
    while len(_API_SESSION_CACHE) > _SESSION_MAX_ENTRIES:
        _API_SESSION_CACHE.popitem(last=False)


def _store_session_entry(session_id: str, entry: Dict[str, Any]) -> None:
    now = _session_now()
    entry["created_at"] = now
    entry["last_access"] = now
    with _SESSION_CACHE_LOCK:
        _prune_session_cache(now)
        _API_SESSION_CACHE[session_id] = entry
        _API_SESSION_CACHE.move_to_end(session_id)
        _trim_session_cache_size()


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


class SchemaMappingRequest(BaseModel):
    """OpenAI mapping request using schema metadata + template overlay tags.
    """

    schemaId: str = Field(..., min_length=1)
    templateId: Optional[str] = None
    templateFields: List[TemplateOverlayField]
    sessionId: Optional[str] = None


class MappingCreateRequest(BaseModel):
    """Persist a schema mapping payload after approval.
    """

    schemaId: str = Field(..., min_length=1)
    templateId: Optional[str] = None
    mappingResults: Dict[str, Any]


class RenameFieldsRequest(BaseModel):
    """OpenAI rename request using cached PDF bytes and optional schema headers.
    """

    sessionId: str = Field(..., min_length=1)
    schemaId: Optional[str] = None
    templateFields: Optional[List[TemplateOverlayField]] = None


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


def _verify_token(authorization: Optional[str]) -> Dict[str, Any]:
    """
    Validate Firebase auth headers and return the decoded token.
    """
    try:
        return verify_id_token(authorization)
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


def _get_session_entry(session_id: str, user: RequestUser) -> Dict[str, Any]:
    """
    Fetch a cached session entry and enforce ownership.
    """
    now = _session_now()
    with _SESSION_CACHE_LOCK:
        _prune_session_cache(now)
        entry = _API_SESSION_CACHE.get(session_id)
        if not entry:
            raise HTTPException(status_code=404, detail="Session not found")
        owner_id = entry.get("user_id")
        if owner_id and owner_id != user.app_user_id:
            raise HTTPException(status_code=403, detail="Session access denied")
        entry["last_access"] = now
        _API_SESSION_CACHE.move_to_end(session_id)
        return entry


def _get_session_entry_if_present(session_id: Optional[str], user: RequestUser) -> Optional[Dict[str, Any]]:
    """
    Return a cached session entry when available and owned by the user.
    """
    if not session_id:
        return None
    now = _session_now()
    with _SESSION_CACHE_LOCK:
        _prune_session_cache(now)
        entry = _API_SESSION_CACHE.get(session_id)
        if not entry:
            return None
        owner_id = entry.get("user_id")
        if owner_id and owner_id != user.app_user_id:
            raise HTTPException(status_code=403, detail="Session access denied")
        entry["last_access"] = now
        _API_SESSION_CACHE.move_to_end(session_id)
        return entry


def _has_admin_override(authorization: Optional[str], x_admin_token: Optional[str]) -> bool:
    """
    Return True when the request includes a valid admin override token.
    """
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


def _coerce_field_payloads(raw_fields: List[Any]) -> List[Dict[str, Any]]:
    """
    Normalize incoming field payloads to the expected dict shape.
    """
    cleaned: List[Dict[str, Any]] = []
    for entry in raw_fields:
        if not isinstance(entry, dict):
            continue
        payload = dict(entry)
        rect = payload.get("rect")
        if isinstance(rect, dict):
            for key in ("x", "y", "width", "height"):
                if key not in payload and key in rect:
                    payload[key] = rect[key]
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
    allowed_template_set = set(allowed_template)
    allowed_group_keys = {
        str(tag.get("groupKey") or "").strip()
        for tag in template_tags
        if str(tag.get("groupKey") or "").strip()
    }

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
            schema_field = str(raw.get("databaseField") or "").strip()
            group_key = str(raw.get("groupKey") or "").strip()
            if schema_field not in allowed_schema_set:
                continue
            if allowed_group_keys and group_key not in allowed_group_keys:
                continue
            checkbox_rules.append(raw)

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

app = FastAPI(title="Sandbox PDF Field Detector")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_resolve_cors_origins(),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


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

    session_id = str(uuid.uuid4())
    max_mb, max_bytes = _resolve_upload_limit()
    pdf_bytes = await _read_upload_bytes(
        pdf,
        max_bytes=max_bytes,
        limit_message=f"PDF exceeds {max_mb}MB upload limit",
    )
    if not pdf_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    pipeline_choice = "commonforms"
    fd, temp_name = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)
    temp_path = Path(temp_name)
    try:
        temp_path.write_bytes(pdf_bytes)
        resolved = detect_commonforms_fields(Path(temp_path))
    finally:
        temp_path.unlink(missing_ok=True)
    resolved["pipeline"] = "commonforms"

    fields = resolved.get("fields", [])
    _store_session_entry(
        session_id,
        {
            "pdf_bytes": pdf_bytes,
            "fields": fields,
            "source_pdf": source_pdf,
            "result": resolved,
            "user_id": user.app_user_id,
        },
    )
    return {
        "success": True,
        "sessionId": session_id,
        "originalFilename": source_pdf,
        "pipeline": resolved.get("pipeline", pipeline_choice),
        "fieldCount": len(fields),
        "fields": fields,
        "result": resolved,
    }


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

    _store_session_entry(
        session_id,
        {
            "pdf_bytes": pdf_bytes,
            "fields": [],
            "source_pdf": source_pdf,
            "result": {},
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
    entry = _get_session_entry(sessionId, user)
    fields = entry.get("fields", [])
    return {
        "success": True,
        "sessionId": sessionId,
        "items": fields,
        "total": len(fields),
    }


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
    entry = _get_session_entry(session_id, user)
    filename = _safe_pdf_download_filename(entry.get("source_pdf") or "document")
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return StreamingResponse(io.BytesIO(entry["pdf_bytes"]), media_type="application/pdf", headers=headers)


@app.post("/detect-fields")
async def detect_fields(
    file: UploadFile = File(...),
    pipeline: Optional[str] = None,
    pipeline_form: Optional[str] = Form(None, alias="pipeline"),
    authorization: Optional[str] = Header(default=None),
    x_admin_token: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    """
    Main detection endpoint: CommonForms field detection only.
    """
    auth_payload: Dict[str, Any] = {}
    user: Optional[RequestUser] = None
    admin_override = _has_admin_override(authorization, x_admin_token)
    if not admin_override:
        auth_payload = _verify_token(authorization)
        try:
            user = ensure_user(auth_payload)
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

    session_id = str(uuid.uuid4())
    max_mb, max_bytes = _resolve_upload_limit()
    pdf_bytes = await _read_upload_bytes(
        file,
        max_bytes=max_bytes,
        limit_message=f"PDF exceeds {max_mb}MB upload limit",
    )
    if not pdf_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")
    if auth_payload.get("uid"):
        logger.info("Session %s -> request by %s", session_id, auth_payload["uid"])
    elif admin_override:
        logger.info("Session %s -> request by admin override", session_id)
    logger.info("Session %s -> starting detection for %s", session_id, _log_pdf_label(source_pdf))

    pipeline_choice = "commonforms"
    if pipeline_choice == "commonforms":
        fd, temp_name = tempfile.mkstemp(suffix=".pdf")
        os.close(fd)
        temp_path = Path(temp_name)
        try:
            temp_path.write_bytes(pdf_bytes)
            resolved = detect_commonforms_fields(Path(temp_path))
        finally:
            temp_path.unlink(missing_ok=True)
        resolved["pipeline"] = "commonforms"
        logger.info(
            "Session %s -> %s final fields produced (commonforms pipeline)",
            session_id,
            len(resolved.get("fields", [])),
        )
        fields = resolved.get("fields", [])
        _store_session_entry(
            session_id,
            {
                "pdf_bytes": pdf_bytes,
                "fields": fields,
                "source_pdf": source_pdf,
                "result": resolved,
                "user_id": user.app_user_id if user else None,
            },
        )
        return {
            **resolved,
            "sessionId": session_id,
        }

    raise HTTPException(status_code=400, detail="Unsupported pipeline selection")


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
    payload: RenameFieldsRequest,
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    """
    Run OpenAI rename using cached PDF bytes and overlay tags.

    parsing R response lines (excluding OpenAI latency).
    """
    user = _require_user(authorization)

    entry = _get_session_entry(payload.sessionId, user)
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

    page_count = _get_pdf_page_count(pdf_bytes)
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
        status_code = getattr(exc, "status_code", None) or 500
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc

    checkbox_rules = rename_report.get("checkboxRules") or []
    entry["fields"] = renamed_fields
    entry["renames"] = rename_report
    entry["checkboxRules"] = checkbox_rules
    entry["openai_credit_consumed"] = True
    entry["openai_credit_pages"] = page_count
    entry["openai_credit_mapping_used"] = False

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
    payload: SchemaMappingRequest,
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    """
    Run OpenAI mapping using schema metadata + template overlay tags.
    """
    user = _require_user(authorization)
    schema = get_schema(payload.schemaId, user.app_user_id)
    if not schema:
        raise HTTPException(status_code=404, detail="Schema not found")

    if payload.templateId:
        template = get_template(payload.templateId, user.app_user_id)
        if not template:
            raise HTTPException(status_code=403, detail="Template access denied")

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

    session_entry = _get_session_entry_if_present(payload.sessionId, user)
    skip_credit = False
    if session_entry and session_entry.get("openai_credit_consumed"):
        if not session_entry.get("openai_credit_mapping_used"):
            session_entry["openai_credit_mapping_used"] = True
            skip_credit = True

    if not skip_credit:
        if session_entry and session_entry.get("pdf_bytes"):
            page_count = _get_pdf_page_count(session_entry["pdf_bytes"])
        else:
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
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        status_code = getattr(exc, "status_code", None) or 500
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc

    mapping_results = _build_schema_mapping_payload(
        allowlist_payload.get("schemaFields") or [],
        allowlist_payload.get("templateTags") or [],
        ai_response,
    )
    mapping_record = create_mapping(
        user_id=user.app_user_id,
        schema_id=schema.id,
        template_id=payload.templateId,
        payload=mapping_results,
    )

    return {
        "success": True,
        "requestId": request_id,
        "mappingId": mapping_record.id,
        "schemaId": schema.id,
        "mappingResults": mapping_results,
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
    }


@app.post("/api/schema-mappings")
async def create_schema_mapping(
    payload: MappingCreateRequest,
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    """
    Persist a schema mapping payload after client approval.
    """
    user = _require_user(authorization)
    schema = get_schema(payload.schemaId, user.app_user_id)
    if not schema:
        raise HTTPException(status_code=404, detail="Schema not found")
    if payload.templateId:
        template = get_template(payload.templateId, user.app_user_id)
        if not template:
            raise HTTPException(status_code=403, detail="Template access denied")

    mapping_payload = payload.mappingResults or {}
    if not isinstance(mapping_payload, dict):
        raise HTTPException(status_code=400, detail="mappingResults must be an object")

    record = create_mapping(
        user_id=user.app_user_id,
        schema_id=schema.id,
        template_id=payload.templateId,
        payload=mapping_payload,
    )
    return {
        "success": True,
        "mappingId": record.id,
        "schemaId": schema.id,
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

    temp_path = None
    uploaded_paths: List[str] = []
    try:
        max_mb, max_bytes = _resolve_upload_limit()
        temp_path = _write_upload_to_temp(
            pdf,
            max_bytes=max_bytes,
            limit_message=f"PDF exceeds {max_mb}MB upload limit",
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
