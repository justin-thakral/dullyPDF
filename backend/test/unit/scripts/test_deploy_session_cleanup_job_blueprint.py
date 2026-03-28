"""Regression checks for the session cleanup job deploy script."""

from __future__ import annotations

from pathlib import Path


SCRIPT_PATH = Path("scripts/deploy-session-cleanup-job.sh")


def _script_text() -> str:
    return SCRIPT_PATH.read_text(encoding="utf-8")


def test_deploy_session_cleanup_job_reuses_a_versioned_backend_image() -> None:
    text = _script_text()
    assert 'source "${SCRIPT_DIR}/_artifact_registry_guard.sh"' in text
    assert 'REGION="${SESSION_CLEANUP_REGION:-${BACKEND_REGION:-${IMAGE_SOURCE_REGION:-us-east4}}}"' in text
    assert 'LEGACY_JOB_REGION="${SESSION_CLEANUP_LEGACY_REGION:-us-central1}"' in text
    assert 'SESSION_CLEANUP_IMAGE="${SESSION_CLEANUP_IMAGE:-${BACKEND_IMAGE:-}}"' in text
    assert 'gcloud run services describe "$IMAGE_SOURCE_SERVICE"' in text
    assert "spec.template.spec.containers[0].image" in text
    assert 'require_prod_artifact_registry_image "SESSION_CLEANUP_IMAGE" "$SESSION_CLEANUP_IMAGE"' in text


def test_deploy_session_cleanup_job_enforces_prod_adc_and_session_env() -> None:
    text = _script_text()
    assert 'Expected ENV=prod in $ENV_FILE for session-cleanup deploy.' in text
    assert 'Refusing to deploy prod session cleanup job outside us-east4' in text
    assert 'require_exact FIREBASE_USE_ADC "true"' in text
    assert "require_nonempty SANDBOX_SESSION_BUCKET" in text
    assert "require_integer_ge SANDBOX_SESSION_TTL_SECONDS 1" in text
    assert "require_integer_ge SESSION_CLEANUP_GRACE_SECONDS 0" in text


def test_deploy_session_cleanup_job_runs_cleanup_sessions_execute() -> None:
    text = _script_text()
    assert 'gcloud run jobs deploy "$JOB_NAME"' in text
    assert 'gcloud run jobs delete "$JOB_NAME"' in text
    assert '--command "python3"' in text
    assert '--args "/app/scripts/cleanup_sessions.py,--execute"' in text
    assert 'ENV=prod,FIREBASE_PROJECT_ID=${FIREBASE_PROJECT_ID},FIREBASE_USE_ADC=true' in text


def test_deploy_session_cleanup_job_also_reconciles_the_scheduler_by_default() -> None:
    text = _script_text()
    assert 'SESSION_CLEANUP_SKIP_SCHEDULER="${SESSION_CLEANUP_SKIP_SCHEDULER:-false}"' in text
    assert 'bash "${SCRIPT_DIR}/deploy-session-cleanup-scheduler.sh" "$ENV_FILE"' in text
