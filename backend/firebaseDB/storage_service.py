"""Google Cloud Storage helpers for PDFs and templates.
"""

import io
import os
import re
from typing import Tuple

from ..fieldDetecting.rename_pipeline.combinedSrc.config import get_logger
from .firebase_service import get_storage_bucket


logger = get_logger(__name__)

FORMS_BUCKET = (os.getenv("FORMS_BUCKET") or "").strip()
TEMPLATES_BUCKET = (os.getenv("TEMPLATES_BUCKET") or "").strip()
ALLOWED_BUCKETS = {name for name in (FORMS_BUCKET, TEMPLATES_BUCKET) if name}


def _require_bucket_config() -> None:
    """
    Ensure storage bucket names are configured.
    """
    if not FORMS_BUCKET or not TEMPLATES_BUCKET:
        raise RuntimeError("FORMS_BUCKET and TEMPLATES_BUCKET must be set")


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


def delete_pdf(bucket_path: str) -> None:
    """Delete a PDF object from an allowlisted bucket.
    """
    _require_bucket_config()
    bucket_name, file_path = _parse_gs_uri(bucket_path)
    bucket = get_storage_bucket(bucket_name)
    bucket.blob(file_path).delete(if_generation_match=None)
    logger.debug("Deleted PDF from storage: %s", bucket_path)


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
