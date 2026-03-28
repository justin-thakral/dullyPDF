"""Saved form storage and session endpoints."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse

from backend.api.schemas import (
    SavedFormEditorSnapshotUpdateRequest,
    SavedFormSessionRequest,
)
from backend.detection.status import DETECTION_STATUS_COMPLETE
from backend.firebaseDB.template_database import (
    create_template,
    get_template,
    list_templates,
    update_template,
)
from backend.firebaseDB.storage_service import (
    delete_pdf,
    download_pdf_bytes,
    is_gcs_path,
    stream_pdf,
    upload_form_pdf,
    upload_template_pdf,
)
from backend.logging_config import get_logger
from backend.sessions.session_store import (
    get_session_entry_if_present as _get_session_entry_if_present,
    store_session_entry as _store_session_entry,
)
from backend.services.saved_form_snapshot_service import (
    SAVED_FORM_EDITOR_SNAPSHOT_METADATA_KEY,
    get_saved_form_editor_snapshot_path,
    load_saved_form_editor_snapshot,
    normalize_saved_form_editor_snapshot_payload,
    parse_saved_form_editor_snapshot_form_value,
    upload_saved_form_editor_snapshot,
)
from backend.time_utils import now_iso
from backend.services.app_config import resolve_stream_cors_headers
from backend.services.auth_service import require_user
from backend.services.downgrade_retention_service import sync_user_downgrade_retention
from backend.services.limits_service import resolve_fillable_max_pages, resolve_saved_forms_limit
from backend.services.pdf_service import (
    coerce_field_payloads,
    get_pdf_page_count,
    parse_json_list_form_field,
    resolve_upload_limit,
    safe_pdf_download_filename,
    validate_pdf_for_detection,
    write_upload_to_temp,
)
from backend.services.template_cleanup_service import delete_saved_form_assets

router = APIRouter()
logger = get_logger(__name__)


def _is_storage_not_found_error(exc: Exception) -> bool:
    if isinstance(exc, FileNotFoundError):
        return True
    status_code = getattr(exc, "status_code", None)
    if status_code is None:
        status_code = getattr(exc, "code", None)
    if status_code == 404:
        return True
    return exc.__class__.__name__.lower() == "notfound"


def _cleanup_uploaded_paths(paths: List[str]) -> None:
    for path in paths:
        try:
            delete_pdf(path)
        except Exception:
            pass


@router.get("/api/saved-forms")
async def list_saved_forms(authorization: Optional[str] = Header(default=None)) -> Dict[str, Any]:
    """List saved form metadata for the current user."""
    user = require_user(authorization)
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


@router.get("/api/saved-forms/{form_id}")
async def get_saved_form(form_id: str, authorization: Optional[str] = Header(default=None)) -> Dict[str, Any]:
    """Return metadata for a saved form."""
    user = require_user(authorization)
    if not form_id:
        raise HTTPException(status_code=400, detail="Missing form id")
    template = get_template(form_id, user.app_user_id)
    if not template:
        raise HTTPException(status_code=404, detail="Form not found")
    response: Dict[str, Any] = {
        "url": f"/api/saved-forms/{form_id}/download",
        "name": template.name or template.pdf_bucket_path or "Saved form",
        "sessionId": template.id,
    }
    metadata = template.metadata if isinstance(template.metadata, dict) else {}
    fill_rules = metadata.get("fillRules") if isinstance(metadata.get("fillRules"), dict) else None
    if isinstance(fill_rules, dict):
        normalized_fill_rules = {
            key: value
            for key, value in fill_rules.items()
            if key != "checkboxHints"
        }
        if not isinstance(normalized_fill_rules.get("textTransformRules"), list):
            legacy_template_rules = normalized_fill_rules.get("templateRules")
            if isinstance(legacy_template_rules, list):
                normalized_fill_rules["textTransformRules"] = legacy_template_rules
        response["fillRules"] = normalized_fill_rules
    if isinstance(metadata.get("checkboxRules"), list):
        response["checkboxRules"] = metadata.get("checkboxRules")
    if isinstance(metadata.get("textTransformRules"), list):
        response["textTransformRules"] = metadata.get("textTransformRules")
    elif isinstance(metadata.get("templateRules"), list):
        # Backward compatibility for older saved forms that persisted templateRules.
        response["textTransformRules"] = metadata.get("templateRules")
    if isinstance(response.get("fillRules"), dict):
        fill_rules_payload = response["fillRules"]
        if not isinstance(fill_rules_payload.get("textTransformRules"), list):
            fill_rules_payload["textTransformRules"] = response.get("textTransformRules") or []
    if "fillRules" not in response:
        response["fillRules"] = {
            "version": 1,
            "checkboxRules": response.get("checkboxRules") or [],
            "textTransformRules": response.get("textTransformRules") or [],
        }
    editor_snapshot = load_saved_form_editor_snapshot(metadata)
    if editor_snapshot is not None:
        response["editorSnapshot"] = editor_snapshot
    return response


@router.get("/api/saved-forms/{form_id}/download")
async def download_saved_form(
    form_id: str,
    request: Request,
    authorization: Optional[str] = Header(default=None),
):
    """Stream a saved form PDF from storage."""
    user = require_user(authorization)
    if not form_id:
        raise HTTPException(status_code=400, detail="Missing form id")
    template = get_template(form_id, user.app_user_id)
    if not template:
        raise HTTPException(status_code=404, detail="Form not found")
    if not template.pdf_bucket_path or not is_gcs_path(template.pdf_bucket_path):
        raise HTTPException(status_code=404, detail="Form PDF not found in storage")

    try:
        stream = stream_pdf(template.pdf_bucket_path)
    except HTTPException:
        raise
    except Exception as exc:
        if _is_storage_not_found_error(exc):
            raise HTTPException(status_code=404, detail="Form PDF not found in storage") from exc
        raise HTTPException(status_code=500, detail="Failed to load saved form PDF") from exc
    filename = safe_pdf_download_filename(template.name or template.pdf_bucket_path or "form", "form")
    headers = {
        "Content-Disposition": f'inline; filename="{filename}"',
        "Cache-Control": "private, no-store",
    }
    headers.update(resolve_stream_cors_headers(request.headers.get("origin")))
    return StreamingResponse(stream, media_type="application/pdf", headers=headers)


@router.post("/api/saved-forms/{form_id}/session")
async def create_saved_form_session(
    form_id: str,
    payload: SavedFormSessionRequest,
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    """Create a detection session for a saved form using extracted fields."""
    user = require_user(authorization)
    if not form_id:
        raise HTTPException(status_code=400, detail="Missing form id")
    template = get_template(form_id, user.app_user_id)
    if not template:
        raise HTTPException(status_code=404, detail="Form not found")
    if not template.pdf_bucket_path or not is_gcs_path(template.pdf_bucket_path):
        raise HTTPException(status_code=404, detail="Form PDF not found in storage")

    fields = coerce_field_payloads(payload.fields)
    if not fields:
        raise HTTPException(status_code=400, detail="No fields provided for saved form session")

    try:
        pdf_bytes = download_pdf_bytes(template.pdf_bucket_path)
    except Exception as exc:
        if _is_storage_not_found_error(exc):
            raise HTTPException(status_code=404, detail="Form PDF not found in storage") from exc
        raise HTTPException(status_code=500, detail="Failed to load saved form PDF") from exc
    page_count = get_pdf_page_count(pdf_bytes)

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


@router.post("/api/saved-forms")
async def save_form(
    pdf: UploadFile = File(...),
    name: str = Form("Saved form"),
    sessionId: Optional[str] = Form(default=None),
    checkboxRules: Optional[str] = Form(default=None),
    textTransformRules: Optional[str] = Form(default=None),
    templateRules: Optional[str] = Form(default=None),
    editorSnapshot: Optional[str] = Form(default=None),
    overwriteFormId: Optional[str] = Form(default=None),
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    """Upload a PDF and persist it as a saved form + template for the user."""
    user = require_user(authorization)
    if not pdf:
        raise HTTPException(status_code=400, detail="No PDF file uploaded")

    filename = pdf.filename or "upload.pdf"
    content_type = (pdf.content_type or "").lower()
    if not filename.lower().endswith(".pdf") and content_type not in {"application/pdf", "application/octet-stream"}:
        raise HTTPException(status_code=400, detail="Only PDF uploads are supported")

    overwrite_form_id = overwriteFormId.strip() if overwriteFormId else ""
    overwrite_template = None
    if overwrite_form_id:
        overwrite_template = get_template(overwrite_form_id, user.app_user_id)
        if not overwrite_template:
            raise HTTPException(status_code=404, detail="Form not found")

    if not overwrite_template:
        max_saved_forms = resolve_saved_forms_limit(user.role)
        existing_templates = list_templates(user.app_user_id)
        if len(existing_templates) >= max_saved_forms:
            raise HTTPException(
                status_code=403,
                detail=f"Saved form limit reached ({max_saved_forms} max).",
            )

    temp_path: Optional[Path] = None
    uploaded_paths: List[str] = []
    try:
        max_mb, max_bytes = resolve_upload_limit()
        temp_path = write_upload_to_temp(
            pdf,
            max_bytes=max_bytes,
            limit_message=f"PDF exceeds {max_mb}MB upload limit",
        )
        try:
            pdf_bytes = temp_path.read_bytes()
        except Exception as exc:
            raise HTTPException(status_code=400, detail="Invalid PDF upload") from exc
        validation = validate_pdf_for_detection(pdf_bytes)
        max_pages = resolve_fillable_max_pages(user.role)
        if validation.page_count > max_pages:
            raise HTTPException(
                status_code=403,
                detail=f"Fillable upload limited to {max_pages} pages for your tier (got {validation.page_count}).",
            )

        form_id = uuid.uuid4().hex
        timestamp = int(datetime.now(tz=timezone.utc).timestamp() * 1000)
        forms_object = f"users/{user.app_user_id}/forms/{timestamp}-{form_id}.pdf"
        templates_object = f"users/{user.app_user_id}/templates/{timestamp}-{form_id}.pdf"

        metadata = {"name": name}
        sanitized_session_id = sessionId.strip() if sessionId else ""
        if sanitized_session_id:
            metadata["originalSessionId"] = sanitized_session_id

        checkbox_rules_payload = parse_json_list_form_field(checkboxRules, "checkboxRules")
        text_transform_rules_payload = parse_json_list_form_field(
            textTransformRules,
            "textTransformRules",
        )
        legacy_template_rules_payload = parse_json_list_form_field(
            templateRules,
            "templateRules",
        )
        if text_transform_rules_payload is None and legacy_template_rules_payload is not None:
            text_transform_rules_payload = legacy_template_rules_payload
        if (
            checkbox_rules_payload is None
            or text_transform_rules_payload is None
        ) and sanitized_session_id:
            session_entry = _get_session_entry_if_present(
                sanitized_session_id,
                user,
                include_pdf_bytes=False,
                include_fields=False,
                include_result=False,
                include_renames=False,
                include_checkbox_rules=True,
                include_text_transform_rules=True,
            )
            if checkbox_rules_payload is None and session_entry and isinstance(session_entry.get("checkboxRules"), list):
                checkbox_rules_payload = [entry for entry in session_entry.get("checkboxRules") if isinstance(entry, dict)]
            if text_transform_rules_payload is None and session_entry and isinstance(session_entry.get("textTransformRules"), list):
                text_transform_rules_payload = [entry for entry in session_entry.get("textTransformRules") if isinstance(entry, dict)]
            if text_transform_rules_payload is None and session_entry and isinstance(session_entry.get("templateRules"), list):
                text_transform_rules_payload = [entry for entry in session_entry.get("templateRules") if isinstance(entry, dict)]
        if checkbox_rules_payload is not None:
            metadata["checkboxRules"] = checkbox_rules_payload
        if text_transform_rules_payload is not None:
            metadata["textTransformRules"] = text_transform_rules_payload
        if (
            checkbox_rules_payload is not None
            or text_transform_rules_payload is not None
        ):
            metadata["fillRules"] = {
                "version": 1,
                "checkboxRules": checkbox_rules_payload or [],
                "textTransformRules": text_transform_rules_payload or [],
            }

        if overwrite_template and isinstance(overwrite_template.metadata, dict):
            metadata = {**overwrite_template.metadata, **metadata}
        metadata.pop("checkboxHints", None)
        fill_rules_metadata = metadata.get("fillRules") if isinstance(metadata.get("fillRules"), dict) else None
        if fill_rules_metadata is not None:
            normalized_fill_rules = {
                key: value
                for key, value in fill_rules_metadata.items()
                if key != "checkboxHints"
            }
            metadata["fillRules"] = normalized_fill_rules
        metadata.pop(SAVED_FORM_EDITOR_SNAPSHOT_METADATA_KEY, None)
        old_snapshot_path = get_saved_form_editor_snapshot_path(
            overwrite_template.metadata if overwrite_template and isinstance(overwrite_template.metadata, dict) else None,
        )
        editor_snapshot_payload = None
        if editorSnapshot is not None:
            try:
                editor_snapshot_payload = parse_saved_form_editor_snapshot_form_value(editorSnapshot)
            except ValueError as exc:
                logger.warning("Ignoring invalid saved-form editor snapshot during save: %s", exc)

        old_pdf_path = overwrite_template.pdf_bucket_path if overwrite_template else None
        old_template_path = overwrite_template.template_bucket_path if overwrite_template else None
        # Overwrites upload to fresh storage objects first, then switch metadata.
        # That keeps the existing saved form intact until the Firestore update
        # succeeds and prevents partial replacement when a later step fails.
        pdf_bucket_path = upload_form_pdf(str(temp_path), forms_object)
        uploaded_paths.append(pdf_bucket_path)
        if overwrite_template and old_template_path and old_template_path == old_pdf_path:
            template_bucket_path = pdf_bucket_path
        else:
            template_bucket_path = upload_template_pdf(str(temp_path), templates_object)
            uploaded_paths.append(template_bucket_path)

        next_snapshot_path: str | None = None
        if editor_snapshot_payload is not None:
            try:
                next_snapshot_path, snapshot_manifest = upload_saved_form_editor_snapshot(
                    user_id=user.app_user_id,
                    form_id=overwrite_template.id if overwrite_template else form_id,
                    timestamp_ms=timestamp,
                    snapshot=editor_snapshot_payload,
                )
                metadata[SAVED_FORM_EDITOR_SNAPSHOT_METADATA_KEY] = snapshot_manifest
                uploaded_paths.append(next_snapshot_path)
            except Exception as exc:
                logger.warning("Failed to persist saved-form editor snapshot user=%s form=%s error=%s", user.app_user_id, overwrite_template.id if overwrite_template else form_id, exc)

        if overwrite_template:
            updated_template = update_template(
                overwrite_template.id,
                user.app_user_id,
                pdf_path=pdf_bucket_path,
                template_path=template_bucket_path,
                metadata=metadata,
            )
            if not updated_template:
                raise HTTPException(status_code=500, detail="Failed to update saved form")
            if old_pdf_path and old_pdf_path != pdf_bucket_path and is_gcs_path(old_pdf_path):
                try:
                    delete_pdf(old_pdf_path)
                except Exception:
                    pass
            if (
                old_template_path
                and old_template_path != template_bucket_path
                and old_template_path != old_pdf_path
                and is_gcs_path(old_template_path)
            ):
                try:
                    delete_pdf(old_template_path)
                except Exception:
                    pass
            if old_snapshot_path and old_snapshot_path != next_snapshot_path and is_gcs_path(old_snapshot_path):
                try:
                    delete_pdf(old_snapshot_path)
                except Exception:
                    pass
            return {
                "success": True,
                "id": updated_template.id,
                "name": updated_template.name or name,
            }

        template = create_template(
            user_id=user.app_user_id,
            pdf_path=pdf_bucket_path,
            template_path=template_bucket_path,
            metadata=metadata,
        )

        return {
            "success": True,
            "id": template.id,
            "name": template.name or name,
        }
    except Exception:
        _cleanup_uploaded_paths(uploaded_paths)
        raise
    finally:
        if temp_path and temp_path.exists():
            try:
                temp_path.unlink()
            except Exception:
                pass


@router.delete("/api/saved-forms/{form_id}")
async def delete_saved_form(form_id: str, authorization: Optional[str] = Header(default=None)) -> Dict[str, Any]:
    """Delete a saved form and its storage objects."""
    user = require_user(authorization)
    if not form_id:
        raise HTTPException(status_code=400, detail="Missing form id")
    try:
        removed = delete_saved_form_assets(form_id, user.app_user_id, hard_delete_link_records=False)
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Failed to delete saved form") from exc
    if not removed:
        raise HTTPException(status_code=404, detail="Form not found")
    sync_user_downgrade_retention(user.app_user_id)
    return {"success": True}


@router.patch("/api/saved-forms/{form_id}/editor-snapshot")
async def update_saved_form_editor_snapshot(
    form_id: str,
    payload: SavedFormEditorSnapshotUpdateRequest,
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    """Persist a ready-to-hydrate editor snapshot for an existing saved form."""
    user = require_user(authorization)
    if not form_id:
        raise HTTPException(status_code=400, detail="Missing form id")
    template = get_template(form_id, user.app_user_id)
    if not template:
        raise HTTPException(status_code=404, detail="Form not found")
    try:
        normalized_snapshot = normalize_saved_form_editor_snapshot_payload(payload.snapshot)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    timestamp = int(datetime.now(tz=timezone.utc).timestamp() * 1000)
    metadata = dict(template.metadata or {}) if isinstance(template.metadata, dict) else {}
    old_snapshot_path = get_saved_form_editor_snapshot_path(metadata)
    new_snapshot_path: str | None = None
    try:
        new_snapshot_path, snapshot_manifest = upload_saved_form_editor_snapshot(
            user_id=user.app_user_id,
            form_id=form_id,
            timestamp_ms=timestamp,
            snapshot=normalized_snapshot,
        )
        metadata[SAVED_FORM_EDITOR_SNAPSHOT_METADATA_KEY] = snapshot_manifest
        updated_template = update_template(
            form_id,
            user.app_user_id,
            metadata=metadata,
        )
        if not updated_template:
            raise HTTPException(status_code=500, detail="Failed to update saved form snapshot")
    except HTTPException:
        if new_snapshot_path and is_gcs_path(new_snapshot_path):
            try:
                delete_pdf(new_snapshot_path)
            except Exception:
                pass
        raise
    except Exception as exc:
        if new_snapshot_path and is_gcs_path(new_snapshot_path):
            try:
                delete_pdf(new_snapshot_path)
            except Exception:
                pass
        raise HTTPException(status_code=500, detail="Failed to update saved form snapshot") from exc

    if old_snapshot_path and old_snapshot_path != new_snapshot_path and is_gcs_path(old_snapshot_path):
        try:
            delete_pdf(old_snapshot_path)
        except Exception:
            pass

    return {"success": True}
