"""Regression checks for the manual signing retention lock helper."""

from __future__ import annotations

from pathlib import Path


SCRIPT_PATH = Path("scripts/lock-signing-storage-retention.sh")


def test_lock_signing_storage_retention_requires_explicit_confirmation() -> None:
    text = SCRIPT_PATH.read_text(encoding="utf-8")
    assert "--yes-lock-retention" in text
    assert "irreversibly lock the retention policy" in text
    assert "Usage:" in text


def test_lock_signing_storage_retention_targets_signing_bucket_and_lock_flag() -> None:
    text = SCRIPT_PATH.read_text(encoding="utf-8")
    assert 'SIGNING_BUCKET="${SIGNING_BUCKET:-}"' in text
    assert 'gcloud storage buckets update "${BUCKET_URL}" --project "${PROJECT_ID}" --lock-retention-period' in text
    assert "retention_policy.isLocked" in text
    assert "retention_policy.retentionPeriod" in text
