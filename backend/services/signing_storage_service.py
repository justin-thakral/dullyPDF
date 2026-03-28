"""Signing storage policy and staging/finalization helpers.

Phase 5 needs two different behaviors at once:

1. finalized signing artifacts must live in a dedicated storage bucket with a
   retention-capable policy; and
2. stale in-flight uploads must remain deletable while completion/send races
   settle.

This module keeps the staging-path derivation, promotion flow, and retention
validation in one place so the routes can reuse the same policy everywhere.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from backend.firebaseDB.firebase_service import get_storage_bucket
from backend.firebaseDB.storage_service import (
    SIGNING_BUCKET,
    SIGNING_STAGING_BUCKET,
    build_signing_bucket_uri,
    build_signing_staging_bucket_uri,
    copy_storage_object,
    delete_storage_object,
    parse_storage_bucket_path,
    storage_object_exists,
    upload_signing_staging_json,
    upload_signing_staging_pdf_bytes,
)
from backend.logging_config import get_logger
from backend.services.signing_service import resolve_signing_retention_days


logger = get_logger(__name__)

_STAGING_PREFIX = "_staging"


@dataclass(frozen=True)
class SigningStorageValidationResult:
    final_bucket_name: str
    staging_bucket_name: str
    retention_days: int
    retention_period_seconds: Optional[int]
    object_retention_mode: Optional[str]
    policy_mode: str


def _parse_iso_datetime(value: Optional[str]) -> Optional[datetime]:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _required_retention_seconds() -> int:
    return resolve_signing_retention_days() * 24 * 60 * 60


def is_signing_storage_not_found_error(exc: Exception) -> bool:
    if isinstance(exc, FileNotFoundError):
        return True
    status_code = getattr(exc, "status_code", None)
    if status_code is None:
        status_code = getattr(exc, "code", None)
    if status_code == 404:
        return True
    return exc.__class__.__name__.lower() == "notfound"


def build_signing_stage_object_path(final_object_path: str) -> str:
    normalized = str(final_object_path or "").strip().lstrip("/")
    if not normalized:
        raise ValueError("Final signing object path is required")
    if normalized.startswith(f"{_STAGING_PREFIX}/"):
        return normalized
    return f"{_STAGING_PREFIX}/{normalized}"


def resolve_signing_stage_bucket_path(final_bucket_path: str) -> str:
    _, final_object_path = parse_storage_bucket_path(final_bucket_path)
    return build_signing_staging_bucket_uri(build_signing_stage_object_path(final_object_path))


def upload_signing_staging_pdf_bytes_for_final(pdf_bytes: bytes, final_object_path: str) -> str:
    return upload_signing_staging_pdf_bytes(pdf_bytes, build_signing_stage_object_path(final_object_path))


def upload_signing_staging_json_for_final(payload, final_object_path: str) -> str:
    return upload_signing_staging_json(payload, build_signing_stage_object_path(final_object_path))


def ensure_signing_storage_configuration(*, validate_remote: bool = False) -> SigningStorageValidationResult:
    final_bucket_name, _ = parse_storage_bucket_path(build_signing_bucket_uri("_signing-healthcheck"))
    staging_bucket_name, _ = parse_storage_bucket_path(build_signing_staging_bucket_uri("_signing-healthcheck"))
    retention_days = resolve_signing_retention_days()
    if not validate_remote:
        return SigningStorageValidationResult(
            final_bucket_name=final_bucket_name,
            staging_bucket_name=staging_bucket_name,
            retention_days=retention_days,
            retention_period_seconds=None,
            object_retention_mode=None,
            policy_mode="config_only",
        )

    bucket = get_storage_bucket(final_bucket_name)
    bucket.reload()
    retention_period_seconds = int(getattr(bucket, "retention_period", 0) or 0)
    object_retention_mode = str(getattr(bucket, "object_retention_mode", "") or "").strip() or None
    required_seconds = _required_retention_seconds()

    if retention_period_seconds >= required_seconds:
        policy_mode = "bucket_retention"
    elif object_retention_mode:
        policy_mode = "object_retention"
    else:
        raise RuntimeError(
            "SIGNING_BUCKET must expose either a bucket retention policy covering SIGNING_RETENTION_DAYS "
            "or object retention mode for finalized signing artifacts."
        )

    return SigningStorageValidationResult(
        final_bucket_name=final_bucket_name,
        staging_bucket_name=staging_bucket_name,
        retention_days=retention_days,
        retention_period_seconds=retention_period_seconds or None,
        object_retention_mode=object_retention_mode,
        policy_mode=policy_mode,
    )


def enforce_signing_object_retention(final_bucket_path: str, *, retain_until: Optional[str]) -> None:
    if not retain_until:
        return
    validation = ensure_signing_storage_configuration(validate_remote=True)
    bucket_name, file_path = parse_storage_bucket_path(final_bucket_path)
    if bucket_name != validation.final_bucket_name:
        raise RuntimeError("Finalized signing artifacts must live in the configured SIGNING_BUCKET.")
    if validation.policy_mode == "bucket_retention":
        return
    target = _parse_iso_datetime(retain_until)
    if target is None:
        raise ValueError("Retention timestamp must be a valid ISO-8601 value")
    bucket = get_storage_bucket(bucket_name)
    blob = bucket.blob(file_path)
    blob.reload()
    current_retention = getattr(getattr(blob, "retention", None), "retain_until_time", None)
    if current_retention is not None and current_retention >= target:
        return
    blob.retention.retain_until_time = target
    blob.patch(override_unlocked_retention=True)


def promote_signing_staged_object(
    final_bucket_path: str,
    *,
    retain_until: Optional[str] = None,
    delete_stage: bool = True,
) -> str:
    ensure_signing_storage_configuration(validate_remote=False)
    stage_bucket_path = resolve_signing_stage_bucket_path(final_bucket_path)
    final_exists = storage_object_exists(final_bucket_path)
    stage_exists = storage_object_exists(stage_bucket_path)

    if not final_exists and not stage_exists:
        raise FileNotFoundError("Signing artifact is not available in final or staging storage.")

    if not final_exists and stage_exists:
        try:
            copy_storage_object(stage_bucket_path, final_bucket_path, if_generation_match=0)
        except Exception as exc:
            if not storage_object_exists(final_bucket_path):
                raise exc
        final_exists = True

    if final_exists:
        enforce_signing_object_retention(final_bucket_path, retain_until=retain_until)
        if delete_stage and stage_exists:
            try:
                delete_storage_object(stage_bucket_path)
            except Exception:
                logger.warning("Failed to delete signing staging object after promotion: %s", stage_bucket_path)
        return final_bucket_path

    return stage_bucket_path


def resolve_signing_storage_read_bucket_path(final_bucket_path: str, *, retain_until: Optional[str] = None) -> str:
    try:
        if storage_object_exists(final_bucket_path):
            return final_bucket_path
    except Exception as exc:
        if not is_signing_storage_not_found_error(exc):
            logger.debug("Skipping signing final-object existence probe for %s: %s", final_bucket_path, exc)
            return final_bucket_path
    stage_bucket_path = resolve_signing_stage_bucket_path(final_bucket_path)
    try:
        stage_exists = storage_object_exists(stage_bucket_path)
    except Exception as exc:
        if not is_signing_storage_not_found_error(exc):
            logger.debug("Skipping signing staging-object existence probe for %s: %s", stage_bucket_path, exc)
        return final_bucket_path
    if not stage_exists:
        return final_bucket_path
    try:
        return promote_signing_staged_object(final_bucket_path, retain_until=retain_until, delete_stage=True)
    except Exception as exc:
        logger.warning(
            "Serving signing staging object because promotion to finalized storage failed (%s -> %s): %s",
            stage_bucket_path,
            final_bucket_path,
            exc,
        )
        return stage_bucket_path


def describe_signing_storage_policy() -> dict[str, object]:
    validation = ensure_signing_storage_configuration(validate_remote=True)
    return {
        "finalBucket": validation.final_bucket_name or SIGNING_BUCKET,
        "stagingBucket": validation.staging_bucket_name or SIGNING_STAGING_BUCKET,
        "retentionDays": validation.retention_days,
        "policyMode": validation.policy_mode,
        "bucketRetentionSeconds": validation.retention_period_seconds,
        "objectRetentionMode": validation.object_retention_mode,
    }
