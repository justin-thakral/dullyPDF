"""FastAPI service bootstrap and compatibility exports.

The application is now structured under `backend/api` and `backend/services`.
`backend/main.py` remains as the runtime entrypoint (`python -m backend.main`) and
re-exports commonly used helpers to reduce migration churn for internal callers/tests.
"""

from __future__ import annotations

import httpx
import fitz
import uuid

from backend.ai.rename_pipeline import run_openai_rename_on_pdf
from backend.ai.schema_mapping import (
    build_allowlist_payload,
    call_openai_schema_mapping_chunked,
    validate_payload_size,
)
from backend.api import app, create_app
from backend.api.schemas import (
    ContactRequest,
    RecaptchaAssessmentRequest,
    RenameFieldsRequest,
    SavedFormSessionRequest,
    SchemaCreateRequest,
    SchemaField,
    SchemaMappingRequest,
    TemplateOverlayField,
)
from backend.api.schemas.models import _rect_from_corners, _rect_from_xywh
from backend.detection_tasks import enqueue_detection_task, resolve_detector_profile, resolve_task_config
from backend.env_utils import env_truthy as _env_truthy, env_value as _env_value, int_env as _int_env
from backend.fieldDetecting.rename_pipeline.combinedSrc.form_filler import inject_fields
from backend.fieldDetecting.rename_pipeline.debug_flags import debug_enabled, get_debug_password
from backend.firebaseDB.app_database import (
    consume_openai_credits,
    create_template,
    delete_template,
    ensure_user,
    get_template,
    get_user_profile,
    list_templates,
    refund_openai_credits,
    update_template,
)
from backend.firebaseDB.detection_database import record_detection_request, update_detection_request
from backend.firebaseDB.firebase_service import verify_id_token
from backend.firebaseDB.schema_database import (
    create_schema,
    get_schema,
    list_schemas,
    record_openai_rename_request,
    record_openai_request,
)
from backend.firebaseDB.session_database import get_session_metadata
from backend.firebaseDB.storage_service import (
    delete_pdf,
    download_pdf_bytes,
    download_session_json,
    is_gcs_path,
    stream_pdf,
    upload_form_pdf,
    upload_pdf_to_bucket_path,
    upload_template_pdf,
)
from backend.security.rate_limit import check_rate_limit
from backend.services.app_config import (
    commonforms_available as _commonforms_available,
    docs_enabled as _docs_enabled,
    is_prod as _is_prod,
    legacy_endpoints_enabled as _legacy_endpoints_enabled,
    require_prod_env as _require_prod_env,
    resolve_cors_origins as _resolve_cors_origins,
    resolve_detection_mode as _resolve_detection_mode,
    resolve_stream_cors_headers as _resolve_stream_cors_headers,
)
from backend.services.auth_service import (
    enforce_email_verification as _enforce_email_verification,
    has_admin_override as _has_admin_override,
    is_password_sign_in as _is_password_sign_in,
    require_user as _require_user,
    verify_token as _verify_token,
)
from backend.services.contact_service import (
    _GMAIL_TOKEN_CACHE,
    format_reply_to_header as _format_reply_to_header,
    get_gmail_access_token as _get_gmail_access_token,
    get_google_access_token as _get_google_access_token,
    is_public_ip as _is_public_ip,
    recaptcha_hostname_allowed as _recaptcha_hostname_allowed,
    resolve_client_ip as _resolve_client_ip,
    resolve_contact_body as _resolve_contact_body,
    resolve_contact_rate_limits as _resolve_contact_rate_limits,
    resolve_contact_subject as _resolve_contact_subject,
    resolve_gmail_user_id as _resolve_gmail_user_id,
    resolve_recaptcha_allowed_hostnames as _resolve_recaptcha_allowed_hostnames,
    resolve_recaptcha_min_score as _resolve_recaptcha_min_score,
    resolve_recaptcha_project_id as _resolve_recaptcha_project_id,
    resolve_signup_rate_limits as _resolve_signup_rate_limits,
    resolve_signup_recaptcha_action as _resolve_signup_recaptcha_action,
    sanitize_email_header_value as _sanitize_email_header_value,
    send_contact_email as _send_contact_email,
    trust_proxy_headers as _trust_proxy_headers,
    verify_contact_recaptcha as _verify_contact_recaptcha,
    verify_recaptcha_token as _verify_recaptcha_token,
)
from backend.services.detection_service import (
    enqueue_detection_job as _enqueue_detection_job,
    run_local_detection as _run_local_detection,
)
from backend.services.limits_service import (
    resolve_detect_max_pages as _resolve_detect_max_pages,
    resolve_fillable_max_pages as _resolve_fillable_max_pages,
    resolve_role_limits as _resolve_role_limits,
    resolve_saved_forms_limit as _resolve_saved_forms_limit,
)
from backend.services.mapping_service import (
    build_schema_mapping_payload as _build_schema_mapping_payload,
    template_fields_to_rename_fields as _template_fields_to_rename_fields,
)
from backend.services.pdf_service import (
    cleanup_paths as _cleanup_paths,
    coerce_field_payloads as _coerce_field_payloads,
    get_pdf_page_count as _get_pdf_page_count,
    log_pdf_label as _log_pdf_label,
    parse_json_list_form_field as _parse_json_list_form_field,
    read_upload_bytes as _read_upload_bytes,
    resolve_upload_limit as _resolve_upload_limit,
    safe_pdf_download_filename as _safe_pdf_download_filename,
    sanitize_basename_segment as _sanitize_basename_segment,
    validate_pdf_for_detection as _validate_pdf_for_detection,
    write_upload_to_temp as _write_upload_to_temp,
)
from backend.sessions.session_store import (
    get_session_entry as _get_session_entry,
    get_session_entry_if_present as _get_session_entry_if_present,
    store_session_entry as _store_session_entry,
    touch_session_entry as _touch_session_entry,
    update_session_entry as _update_session_entry,
)


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
