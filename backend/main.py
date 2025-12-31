import io
import json
import os
import re
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import BackgroundTasks, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from .fieldDetecting.commonforms.commonForm import detect_commonforms_fields
from .fieldDetecting.sandbox.combinedSrc.config import get_logger
from .fieldDetecting.sandbox.combinedSrc.form_filler import inject_fields
from .fieldDetecting.sandbox.combinedSrc.output_layout import ensure_output_layout, temp_prefix_from_pdf
from .fieldDetecting.sandbox.combinedSrc.extract_labels import extract_labels
from .fieldDetecting.sandbox.combinedSrc.pipeline_router import run_pipeline
from .fieldDetecting.sandbox.combinedSrc.render_pdf import render_pdf_to_images
from .fieldDetecting.sandbox.combinedSrc.rename_resolver import run_openai_rename_pipeline
from .fieldDetecting.sandbox.debug_flags import debug_enabled, get_debug_password
from .fieldDetecting.sandbox.field_mapper import FieldMappingService
from .firebaseDB.app_database import create_template, delete_template, ensure_user, get_template, list_templates
from .firebaseDB.db_proxy import disconnect as disconnect_connection
from .firebaseDB.db_proxy import fetch_columns as fetch_db_columns
from .firebaseDB.db_proxy import search_rows as search_db_rows
from .firebaseDB.db_proxy import test_and_create_connection
from .firebaseDB.firebase_service import RequestUser, verify_id_token
from .firebaseDB.storage_service import (
    delete_pdf,
    is_gcs_path,
    stream_pdf,
    upload_form_pdf,
    upload_template_pdf,
)

logger = get_logger(__name__)
_API_SESSION_CACHE: Dict[str, Dict[str, Any]] = {}


class PdfFormField(BaseModel):
    """Per-field payload used for AI field mapping requests."""

    name: str
    type: Optional[str] = "text"
    context: Optional[str] = ""
    confidence: Optional[float] = None
    coordinates: Optional[Dict[str, float]] = None


class MapFieldsRequest(BaseModel):
    """JSON request body for AI field mapping."""

    sessionId: str = Field(..., min_length=1)
    databaseFields: List[str]
    pdfFormFields: Optional[List[PdfFormField]] = None


class DbConnectionRequest(BaseModel):
    """Connection info payload for database preview + mapping."""

    type: str
    host: str
    port: Optional[int] = None
    database: str
    schema_name: Optional[str] = Field(
        default=None,
        validation_alias="schema",
        serialization_alias="schema",
    )
    view: str
    user: str
    password: str
    ssl: Optional[bool] = False
    ttlMs: Optional[int] = None

    model_config = {
        "populate_by_name": True,
        "extra": "ignore",
    }


def _resolve_cors_origins() -> list[str]:
    raw = os.getenv("SANDBOX_CORS_ORIGINS", "").strip()
    if raw == "*":
        if debug_enabled():
            return ["*"]
        raw = ""
    if raw:
        return [origin.strip() for origin in raw.split(",") if origin.strip()]
    return [
        "http://localhost:5173",
        "http://localhost:5174",
        "http://localhost:5175",
        "http://localhost:5176",
    ]


def _verify_token(authorization: Optional[str]) -> Dict[str, Any]:
    """Validate Firebase auth headers and return the decoded token."""
    try:
        return verify_id_token(authorization)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Missing Authorization token") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail="Firebase authentication is not configured") from exc
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


def _require_admin(authorization: Optional[str], x_admin_token: Optional[str]) -> None:
    """Gate admin-only endpoints with ADMIN_TOKEN (or debug password in debug)."""
    token = os.getenv("ADMIN_TOKEN")
    if not token and debug_enabled():
        token = get_debug_password()
    if not token:
        _verify_token(authorization)
        return
    bearer = None
    if authorization and authorization.lower().startswith("bearer "):
        bearer = authorization.split(" ", 1)[1].strip()
    if bearer == token or (x_admin_token and x_admin_token == token):
        return
    require_admin = os.getenv("SANDBOX_DB_REQUIRE_ADMIN", "").strip().lower() in {"1", "true", "yes"}
    if require_admin:
        raise HTTPException(status_code=401, detail="Unauthorized")
    _verify_token(authorization)
    return


def _sanitize_basename_segment(value: str, fallback: str) -> str:
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


def _cleanup_paths(paths: List[Path]) -> None:
    for path in paths:
        try:
            path.unlink(missing_ok=True)
        except Exception as exc:
            logger.debug("Failed to delete temp file %s: %s", path, exc)


def _coerce_field_payloads(raw_fields: List[Any]) -> List[Dict[str, Any]]:
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


def _parse_database_fields(raw_text: str) -> List[str]:
    """
    Parse a newline-delimited text file into DB field names.

    We ignore blank lines and comment lines starting with '#'.
    """
    fields = []
    seen = set()
    for line in raw_text.splitlines():
        cleaned = line.strip()
        if not cleaned or cleaned.startswith("#"):
            continue
        if cleaned in seen:
            continue
        seen.add(cleaned)
        fields.append(cleaned)
    return fields


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


def _resolve_fields_upload_limit() -> tuple[int, int]:
    """
    Resolve the max upload size for .txt field lists.

    We keep this small to prevent accidental multi-megabyte uploads from
    occupying memory during parsing.
    """
    try:
        max_kb = int(os.getenv("SANDBOX_MAX_FIELDS_TXT_KB", "256"))
    except ValueError:
        max_kb = 256
    if max_kb < 1:
        max_kb = 1
    return max_kb, max_kb * 1024


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
    return {"status": "ok"}


@app.get("/api/health")
async def api_health() -> Dict[str, str]:
    return {"status": "ok"}


@app.post("/api/process-pdf")
async def process_pdf(
    pdf: UploadFile = File(...),
    pipeline: Optional[str] = None,
    pipeline_form: Optional[str] = Form(None, alias="pipeline"),
) -> Dict[str, Any]:
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

    pipeline_choice = (pipeline or pipeline_form or "commonforms").strip().lower()
    if pipeline_choice in {"sandbox", "auto"}:
        pipeline_run = run_pipeline(
            pdf_bytes,
            session_id=session_id,
            source_pdf=source_pdf,
            pipeline="auto",
        )
        resolved = dict(pipeline_run.result)
    elif pipeline_choice == "commonforms":
        temp_path = Path(tempfile.mkstemp(suffix=".pdf")[1])
        try:
            temp_path.write_bytes(pdf_bytes)
            resolved = detect_commonforms_fields(Path(temp_path))
        finally:
            temp_path.unlink(missing_ok=True)
        resolved["pipeline"] = "commonforms"
    else:
        raise HTTPException(status_code=400, detail="Unsupported pipeline selection")

    fields = resolved.get("fields", [])
    _API_SESSION_CACHE[session_id] = {
        "pdf_bytes": pdf_bytes,
        "fields": fields,
        "source_pdf": source_pdf,
        "result": resolved,
    }
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
) -> Dict[str, Any]:
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

    _API_SESSION_CACHE[session_id] = {
        "pdf_bytes": pdf_bytes,
        "fields": [],
        "source_pdf": source_pdf,
        "result": {},
    }
    return {
        "success": True,
        "sessionId": session_id,
        "originalFilename": source_pdf,
    }


@app.get("/api/detected-fields")
async def get_detected_fields(sessionId: str) -> Dict[str, Any]:
    entry = _API_SESSION_CACHE.get(sessionId)
    if not entry:
        raise HTTPException(status_code=404, detail="Session not found")
    fields = entry.get("fields", [])
    return {
        "success": True,
        "sessionId": sessionId,
        "items": fields,
        "total": len(fields),
    }


@app.get("/download/{session_id}")
async def download_session_pdf(session_id: str):
    entry = _API_SESSION_CACHE.get(session_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Session not found")
    filename = _safe_pdf_download_filename(entry.get("source_pdf") or "document")
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return StreamingResponse(io.BytesIO(entry["pdf_bytes"]), media_type="application/pdf", headers=headers)


@app.post("/detect-fields")
async def detect_fields(
    file: UploadFile = File(...),
    openai: bool = False,
    use_openai: bool = Form(False),
    pipeline: Optional[str] = None,
    pipeline_form: Optional[str] = Form(None, alias="pipeline"),
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    auth_payload = _verify_token(authorization)
    if not file:
        raise HTTPException(status_code=400, detail="Missing PDF upload")

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
    logger.info("Session %s -> starting detection for %s", session_id, source_pdf)

    pipeline_choice = (pipeline or pipeline_form or "sandbox").strip().lower()
    run_openai = openai or use_openai

    if pipeline_choice in {"sandbox", "auto"}:
        pipeline_run = run_pipeline(
            pdf_bytes,
            session_id=session_id,
            source_pdf=source_pdf,
            pipeline="auto",
        )
        resolved = dict(pipeline_run.result)

        if run_openai:
            logger.info("Session %s -> running OpenAI rename pass", session_id)
            try:
                output_root = Path(__file__).resolve().parent / "fieldDetecting" / "outputArtifacts"
                layout = ensure_output_layout(output_root)
                prefix = temp_prefix_from_pdf(Path(source_pdf), fallback=session_id)
                rename_dir = layout.overlays_dir / f"{prefix}_openai"
                rename_report, renamed_fields = run_openai_rename_pipeline(
                    pipeline_run.artifacts.rendered_pages,
                    pipeline_run.artifacts.candidates,
                    resolved.get("fields", []),
                    output_dir=rename_dir,
                )
                resolved["fields"] = renamed_fields
                resolved["renames"] = rename_report.get("renames", [])
                resolved["openaiModel"] = rename_report.get("model")
                resolved["openaiDropped"] = rename_report.get("dropped", [])
            except Exception as exc:
                logger.exception("Session %s -> OpenAI rename failed: %s", session_id, exc)
                resolved["openaiError"] = str(exc)

        logger.info(
            "Session %s -> %s final fields produced (%s pipeline)",
            session_id,
            len(resolved.get("fields", [])),
            pipeline_run.pipeline,
        )
        return resolved

    if pipeline_choice == "commonforms":
        temp_path = Path(tempfile.mkstemp(suffix=".pdf")[1])
        try:
            temp_path.write_bytes(pdf_bytes)
            resolved = detect_commonforms_fields(Path(temp_path))
        finally:
            temp_path.unlink(missing_ok=True)

        if run_openai:
            logger.info("Session %s -> running OpenAI rename pass (commonforms)", session_id)
            try:
                output_root = Path(__file__).resolve().parent / "fieldDetecting" / "outputArtifacts"
                layout = ensure_output_layout(output_root)
                prefix = temp_prefix_from_pdf(Path(source_pdf), fallback=session_id)
                rename_dir = layout.overlays_dir / f"{prefix}_openai_commonforms"
                rendered_pages = render_pdf_to_images(pdf_bytes)
                labels_by_page = extract_labels(pdf_bytes, rendered_pages=rendered_pages)
                candidates = []
                for page in rendered_pages:
                    page_idx = int(page.get("page_index") or 1)
                    candidates.append(
                        {
                            "page": page_idx,
                            "pageWidth": float(page.get("width_points") or 0.0),
                            "pageHeight": float(page.get("height_points") or 0.0),
                            "rotation": int(page.get("rotation") or 0),
                            "imageWidthPx": int(page.get("image_width_px") or 0),
                            "imageHeightPx": int(page.get("image_height_px") or 0),
                            "labels": labels_by_page.get(page_idx, []),
                        }
                    )
                rename_report, renamed_fields = run_openai_rename_pipeline(
                    rendered_pages,
                    candidates,
                    resolved.get("fields", []),
                    output_dir=rename_dir,
                    confidence_profile="commonforms",
                    adjust_field_confidence=True,
                )
                resolved["fields"] = renamed_fields
                resolved["renames"] = rename_report.get("renames", [])
                resolved["openaiModel"] = rename_report.get("model")
                resolved["openaiDropped"] = rename_report.get("dropped", [])
            except Exception as exc:
                logger.exception("Session %s -> OpenAI rename failed (commonforms): %s", session_id, exc)
                resolved["openaiError"] = str(exc)
        resolved["pipeline"] = "commonforms"
        logger.info(
            "Session %s -> %s final fields produced (commonforms pipeline)",
            session_id,
            len(resolved.get("fields", [])),
        )
        return resolved

    raise HTTPException(status_code=400, detail="Unsupported pipeline selection")


@app.post("/api/upload-fields")
async def upload_fields(
    fields: UploadFile = File(...),
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    _verify_token(authorization)
    if not fields:
        raise HTTPException(status_code=400, detail="No file uploaded")

    filename = fields.filename or "fields.txt"
    content_type = (fields.content_type or "").lower()
    if not filename.lower().endswith(".txt") and content_type not in {"text/plain", "application/octet-stream"}:
        raise HTTPException(status_code=400, detail="Only .txt files are allowed")

    max_kb, max_bytes = _resolve_fields_upload_limit()
    raw_bytes = await _read_upload_bytes(
        fields,
        max_bytes=max_bytes,
        limit_message=f"Fields file exceeds {max_kb}KB upload limit",
    )
    raw_text = raw_bytes.decode("utf-8", errors="ignore")
    database_fields = _parse_database_fields(raw_text)
    if not database_fields:
        raise HTTPException(status_code=400, detail="The uploaded file contains no valid field names")

    logger.debug("Parsed database fields", {"count": len(database_fields)})
    return {
        "success": True,
        "filename": filename,
        "databaseFields": database_fields,
        "totalFields": len(database_fields),
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
    }


@app.post("/api/map-fields")
async def map_fields(
    payload: MapFieldsRequest,
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    _verify_token(authorization)
    if not payload.sessionId:
        raise HTTPException(status_code=400, detail="Missing sessionId")
    if not payload.databaseFields:
        raise HTTPException(status_code=400, detail="databaseFields is required")

    pdf_fields = payload.pdfFormFields or []
    if not pdf_fields:
        raise HTTPException(status_code=400, detail="pdfFormFields is required")

    logger.debug(
        "AI mapping request",
        {"sessionId": payload.sessionId, "dbCount": len(payload.databaseFields), "pdfCount": len(pdf_fields)},
    )

    mapping_service = FieldMappingService()
    mapping_result = mapping_service.map_fields(
        payload.databaseFields,
        [field.model_dump() for field in pdf_fields],
    )

    if not mapping_result.success and mapping_result.status_code:
        raise HTTPException(status_code=int(mapping_result.status_code), detail=mapping_result.error or "Mapping failed")

    sanitized_mappings = []
    for entry in mapping_result.mappings:
        if not entry:
            continue
        original_pdf = entry.get("pdfField")
        desired_name = _sanitize_pdf_field_name_candidate(
            entry.get("databaseField") or original_pdf or "field",
            entry.get("databaseField") or original_pdf or "field",
        )
        sanitized = dict(entry)
        if original_pdf:
            sanitized["originalPdfField"] = original_pdf
        sanitized["pdfField"] = desired_name
        sanitized_mappings.append(sanitized)

    mapping_payload = {
        "success": mapping_result.success,
        "mappings": sanitized_mappings,
        "templateRules": mapping_result.template_rules,
        "identifierKey": mapping_result.identifier_key,
        "notes": mapping_result.notes,
        "unmappedDatabaseFields": mapping_result.unmapped_database_fields,
        "unmappedPdfFields": mapping_result.unmapped_pdf_fields,
        "confidence": mapping_result.confidence,
        "totalMappings": len(sanitized_mappings),
    }

    return {
        "success": mapping_result.success,
        "sessionId": payload.sessionId,
        "mappingResults": mapping_payload,
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
    }


@app.post("/api/forms/materialize")
async def materialize_form(
    background_tasks: BackgroundTasks,
    pdf: UploadFile = File(...),
    fields: str = Form(...),
    authorization: Optional[str] = Header(default=None),
):
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
        return FileResponse(
            str(temp_path),
            media_type="application/pdf",
            filename=output_name,
            background=background_tasks,
        )

    template.setdefault("coordinateSystem", "originTop")
    template["fields"] = _coerce_field_payloads(raw_fields)

    template_path = Path(tempfile.mkstemp(suffix=".json")[1])
    template_path.write_text(json.dumps(template), encoding="utf-8")
    output_path = Path(tempfile.mkstemp(suffix=".pdf")[1])

    try:
        inject_fields(temp_path, template_path, output_path)
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Failed to generate fillable PDF") from exc
    finally:
        background_tasks.add_task(_cleanup_paths, [temp_path, template_path, output_path])

    stem = os.path.splitext(filename)[0] or "form"
    output_name = _safe_pdf_download_filename(f"{stem}-fillable", "form")
    return FileResponse(
        str(output_path),
        media_type="application/pdf",
        filename=output_name,
        background=background_tasks,
    )


@app.get("/api/saved-forms")
async def list_saved_forms(authorization: Optional[str] = Header(default=None)) -> Dict[str, Any]:
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
async def download_saved_form(form_id: str, authorization: Optional[str] = Header(default=None)):
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
    return StreamingResponse(stream, media_type="application/pdf", headers=headers)


@app.post("/api/saved-forms")
async def save_form(
    pdf: UploadFile = File(...),
    name: str = Form("Saved form"),
    sessionId: Optional[str] = Form(default=None),
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
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


@app.post("/api/connections/test")
async def test_connection(
    payload: DbConnectionRequest,
    authorization: Optional[str] = Header(default=None),
    x_admin_token: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    _require_admin(authorization, x_admin_token)
    try:
        result = test_and_create_connection(payload.model_dump(by_alias=True))
        logger.debug("Connected to database", {"connId": result.get("connId"), "columns": len(result.get("columns") or [])})
        return {"success": True, **result}
    except Exception as exc:
        logger.error("/api/connections/test failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/db/columns")
async def get_columns(
    connId: Optional[str] = None,
    authorization: Optional[str] = Header(default=None),
    x_admin_token: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    _require_admin(authorization, x_admin_token)
    if not connId:
        raise HTTPException(status_code=400, detail="connId is required")
    try:
        cols = fetch_db_columns(connId)
    except Exception as exc:
        logger.error("/api/db/columns failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"columns": cols}


@app.get("/api/db/search")
async def search_db(
    connId: Optional[str] = None,
    key: Optional[str] = None,
    query: Optional[str] = None,
    mode: Optional[str] = "contains",
    limit: Optional[int] = 25,
    authorization: Optional[str] = Header(default=None),
    x_admin_token: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    _require_admin(authorization, x_admin_token)
    if not connId:
        raise HTTPException(status_code=400, detail="connId is required")
    if not key:
        raise HTTPException(status_code=400, detail="key is required")
    if query is None:
        raise HTTPException(status_code=400, detail="query is required")
    try:
        rows = search_db_rows(connId, key, query, mode=mode or "contains", limit=limit or 25)
    except Exception as exc:
        logger.error("/api/db/search failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"rows": rows}


@app.delete("/api/connections/{conn_id}")
async def disconnect_db(
    conn_id: str,
    authorization: Optional[str] = Header(default=None),
    x_admin_token: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    _require_admin(authorization, x_admin_token)
    if not conn_id:
        raise HTTPException(status_code=400, detail="Missing connId")
    removed = disconnect_connection(conn_id)
    return {"success": True, "removed": bool(removed)}


def run():
    """Convenience entrypoint for `python -m backend.main`."""
    import uvicorn

    uvicorn.run(
        "backend.main:app",
        host="0.0.0.0",
        port=int(8000),
        reload=False,
    )


if __name__ == "__main__":
    run()
