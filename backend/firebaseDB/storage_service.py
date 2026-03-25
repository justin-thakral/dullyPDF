"""Google Cloud Storage helpers for PDFs, templates, and sessions.
"""

import io
import json
import os
import re
from typing import Tuple

from backend.logging_config import get_logger
from .firebase_service import get_storage_bucket


logger = get_logger(__name__)

FORMS_BUCKET = (os.getenv("FORMS_BUCKET") or "").strip()
TEMPLATES_BUCKET = (os.getenv("TEMPLATES_BUCKET") or "").strip()
SESSION_BUCKET = (os.getenv("SANDBOX_SESSION_BUCKET") or os.getenv("SESSION_BUCKET") or "").strip()
SIGNING_BUCKET = (os.getenv("SIGNING_BUCKET") or "").strip()
ALLOWED_BUCKETS = {name for name in (FORMS_BUCKET, TEMPLATES_BUCKET, SESSION_BUCKET, SIGNING_BUCKET) if name}


def _require_bucket_config() -> None:
    """
    Ensure storage bucket names are configured.
    """
    if not FORMS_BUCKET or not TEMPLATES_BUCKET:
        raise RuntimeError("FORMS_BUCKET and TEMPLATES_BUCKET must be set")


def _require_session_bucket_config() -> str:
    """
    Return the bucket name used for session artifacts.
    """
    bucket_name = SESSION_BUCKET or FORMS_BUCKET
    if not bucket_name:
        raise RuntimeError("SANDBOX_SESSION_BUCKET or FORMS_BUCKET must be set for sessions")
    return bucket_name


def _require_signing_bucket_config() -> str:
    """
    Return the bucket name used for signing artifacts.
    """
    bucket_name = SIGNING_BUCKET or SESSION_BUCKET or FORMS_BUCKET
    if not bucket_name:
        raise RuntimeError("SIGNING_BUCKET, SANDBOX_SESSION_BUCKET, or FORMS_BUCKET must be set for signing artifacts")
    return bucket_name


def build_signing_bucket_uri(destination_path: str) -> str:
    """Build a gs:// URI for a signing artifact path without uploading it."""
    bucket_name = _require_signing_bucket_config()
    safe_destination = _assert_safe_object_path(destination_path)
    return f"gs://{bucket_name}/{safe_destination}"


def _assert_safe_object_path(destination_path: str) -> str:
    """Validate that storage object paths are relative and safe.
    """
    raw = str(destination_path or "").strip()
    if not raw:
        raise ValueError("Empty storage destination path")
    if len(raw) > 1024:
        raise ValueError("Storage destination path too long")
    if raw.startswith("/") or raw.startswith("\\"):
        raise ValueError("Storage destination path must be relative")
    if ".." in raw or "\\" in raw:
        raise ValueError("Refusing unsafe storage destination path")
    if re.search(r"[\r\n]", raw):
        raise ValueError("Invalid storage destination path")
    return raw


def _parse_gs_uri(bucket_path: str) -> Tuple[str, str]:
    """Parse and validate a gs:// bucket path.
    """
    match = re.match(r"^gs://([^/]+)/(.+)$", str(bucket_path or ""))
    if not match:
        raise ValueError(f"Invalid bucket path format: {bucket_path}")
    bucket_name, file_path = match.groups()
    if bucket_name not in ALLOWED_BUCKETS:
        raise ValueError(f"Refusing access to non-allowlisted bucket: {bucket_name}")
    return bucket_name, _assert_safe_object_path(file_path)


def is_gcs_path(value: str) -> bool:
    """Return True when the string is a gs:// URI.
    """
    return isinstance(value, str) and value.startswith("gs://")


def upload_form_pdf(local_file_path: str, destination_path: str) -> str:
    """Upload a PDF to the forms bucket.
    """
    _require_bucket_config()
    safe_destination = _assert_safe_object_path(destination_path)
    bucket = get_storage_bucket(FORMS_BUCKET)
    blob = bucket.blob(safe_destination)
    blob.cache_control = "private, no-store"
    blob.upload_from_filename(local_file_path, content_type="application/pdf")
    logger.debug("Uploaded form PDF: %s", safe_destination)
    return f"gs://{FORMS_BUCKET}/{safe_destination}"


def upload_template_pdf(local_file_path: str, destination_path: str) -> str:
    """Upload a template PDF to the templates bucket.
    """
    _require_bucket_config()
    safe_destination = _assert_safe_object_path(destination_path)
    bucket = get_storage_bucket(TEMPLATES_BUCKET)
    blob = bucket.blob(safe_destination)
    blob.cache_control = "private, no-store"
    blob.upload_from_filename(local_file_path, content_type="application/pdf")
    logger.debug("Uploaded template PDF: %s", safe_destination)
    return f"gs://{TEMPLATES_BUCKET}/{safe_destination}"


def upload_pdf_to_bucket_path(local_file_path: str, bucket_path: str) -> str:
    """Upload a PDF to an existing gs:// bucket path.
    """
    _require_bucket_config()
    bucket_name, file_path = _parse_gs_uri(bucket_path)
    bucket = get_storage_bucket(bucket_name)
    blob = bucket.blob(file_path)
    blob.cache_control = "private, no-store"
    blob.upload_from_filename(local_file_path, content_type="application/pdf")
    logger.debug("Uploaded PDF to existing path: %s", bucket_path)
    return f"gs://{bucket_name}/{file_path}"


def upload_session_pdf_bytes(pdf_bytes: bytes, destination_path: str) -> str:
    """Upload session PDF bytes to the session bucket.
    """
    bucket_name = _require_session_bucket_config()
    safe_destination = _assert_safe_object_path(destination_path)
    bucket = get_storage_bucket(bucket_name)
    blob = bucket.blob(safe_destination)
    blob.cache_control = "private, no-store"
    blob.upload_from_string(pdf_bytes, content_type="application/pdf")
    logger.debug("Uploaded session PDF bytes: %s", safe_destination)
    return f"gs://{bucket_name}/{safe_destination}"


def upload_signing_pdf_bytes(pdf_bytes: bytes, destination_path: str) -> str:
    """Upload immutable signing PDF bytes to the signing bucket."""
    bucket_name = _require_signing_bucket_config()
    safe_destination = _assert_safe_object_path(destination_path)
    bucket = get_storage_bucket(bucket_name)
    blob = bucket.blob(safe_destination)
    blob.cache_control = "private, no-store"
    blob.upload_from_string(pdf_bytes, content_type="application/pdf")
    logger.debug("Uploaded signing PDF bytes: %s", safe_destination)
    return f"gs://{bucket_name}/{safe_destination}"


def upload_signing_json(payload, destination_path: str) -> str:
    """Upload signing JSON payload to the signing bucket."""
    bucket_name = _require_signing_bucket_config()
    safe_destination = _assert_safe_object_path(destination_path)
    bucket = get_storage_bucket(bucket_name)
    blob = bucket.blob(safe_destination)
    blob.cache_control = "private, no-store"
    body = json.dumps(payload if payload is not None else {}, ensure_ascii=True, sort_keys=True).encode("utf-8")
    blob.upload_from_string(body, content_type="application/json")
    logger.debug("Uploaded signing JSON: %s", safe_destination)
    return f"gs://{bucket_name}/{safe_destination}"


def upload_session_json(payload, destination_path: str) -> str:
    """Upload session JSON payload to the session bucket.
    """
    bucket_name = _require_session_bucket_config()
    safe_destination = _assert_safe_object_path(destination_path)
    bucket = get_storage_bucket(bucket_name)
    blob = bucket.blob(safe_destination)
    blob.cache_control = "private, no-store"
    body = json.dumps(payload if payload is not None else {}, ensure_ascii=True).encode("utf-8")
    blob.upload_from_string(body, content_type="application/json")
    logger.debug("Uploaded session JSON: %s", safe_destination)
    return f"gs://{bucket_name}/{safe_destination}"


def upload_saved_form_snapshot_json(payload, destination_path: str) -> str:
    """Upload a saved-form editor snapshot JSON blob to storage."""
    return upload_session_json(payload, destination_path)


def delete_pdf(bucket_path: str) -> None:
    """Delete a PDF object from an allowlisted bucket.
    """
    _require_bucket_config()
    bucket_name, file_path = _parse_gs_uri(bucket_path)
    bucket = get_storage_bucket(bucket_name)
    bucket.blob(file_path).delete(if_generation_match=None)
    logger.debug("Deleted PDF from storage: %s", bucket_path)


def delete_storage_object(bucket_path: str) -> None:
    """Delete any allowlisted storage object regardless of content type."""
    bucket_name, file_path = _parse_gs_uri(bucket_path)
    bucket = get_storage_bucket(bucket_name)
    bucket.blob(file_path).delete(if_generation_match=None)
    logger.debug("Deleted object from storage: %s", bucket_path)


def stream_pdf(bucket_path: str):
    """Stream a PDF from storage, falling back to memory buffer on errors.
    """
    _require_bucket_config()
    bucket_name, file_path = _parse_gs_uri(bucket_path)
    bucket = get_storage_bucket(bucket_name)
    blob = bucket.blob(file_path)
    try:
        return blob.open("rb")
    except Exception as exc:
        logger.debug("Streaming fallback to in-memory download: %s", exc)
        data = blob.download_as_bytes()
        return io.BytesIO(data)


def download_pdf_bytes(bucket_path: str) -> bytes:
    """Download PDF bytes from an allowlisted bucket.
    """
    _require_session_bucket_config()
    bucket_name, file_path = _parse_gs_uri(bucket_path)
    bucket = get_storage_bucket(bucket_name)
    return bucket.blob(file_path).download_as_bytes()


def download_storage_bytes(bucket_path: str) -> bytes:
    """Download arbitrary bytes from an allowlisted storage path."""
    bucket_name, file_path = _parse_gs_uri(bucket_path)
    bucket = get_storage_bucket(bucket_name)
    return bucket.blob(file_path).download_as_bytes()


def download_session_json(bucket_path: str):
    """Download a session JSON payload from storage.
    """
    _require_session_bucket_config()
    bucket_name, file_path = _parse_gs_uri(bucket_path)
    bucket = get_storage_bucket(bucket_name)
    data = bucket.blob(file_path).download_as_bytes()
    return json.loads(data.decode("utf-8"))


def download_saved_form_snapshot_json(bucket_path: str):
    """Download a saved-form editor snapshot JSON blob from storage."""
    return download_session_json(bucket_path)
