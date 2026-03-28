"""Regression checks for the session cleanup scheduler deploy script."""

from __future__ import annotations

from pathlib import Path


SCRIPT_PATH = Path("scripts/deploy-session-cleanup-scheduler.sh")


def _script_text() -> str:
    return SCRIPT_PATH.read_text(encoding="utf-8")


def test_deploy_session_cleanup_scheduler_defaults_to_east4_and_targets_job_run_api() -> None:
    text = _script_text()
    assert 'SESSION_CLEANUP_REGION="${SESSION_CLEANUP_REGION:-${BACKEND_REGION:-us-east4}}"' in text
    assert 'SCHEDULER_LOCATION="${SESSION_CLEANUP_SCHEDULER_LOCATION:-${SESSION_CLEANUP_REGION}}"' in text
    assert 'SCHEDULER_SCHEDULE="${SESSION_CLEANUP_SCHEDULE:-0 * * * *}"' in text
    assert 'RUN_URI="https://${SESSION_CLEANUP_REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT_ID}/jobs/${JOB_NAME}:run"' in text
    assert '--oauth-token-scope "https://www.googleapis.com/auth/cloud-platform"' in text


def test_deploy_session_cleanup_scheduler_rejects_non_east4_prod_targets() -> None:
    text = _script_text()
    assert 'Expected ENV=prod in $ENV_FILE for session-cleanup scheduler deploy.' in text
    assert 'Refusing to target prod session cleanup scheduler at non-east4 job region' in text
    assert 'Refusing to deploy prod session cleanup scheduler outside us-east4' in text


def test_deploy_session_cleanup_scheduler_grants_run_permission_and_cleans_legacy_location() -> None:
    text = _script_text()
    assert 'gcloud run jobs add-iam-policy-binding "$JOB_NAME"' in text
    assert '--role "roles/run.jobsExecutor"' in text
    assert 'gcloud scheduler jobs create http "$SCHEDULER_NAME"' in text
    assert 'gcloud scheduler jobs update http "$SCHEDULER_NAME"' in text
    assert 'gcloud scheduler jobs delete "$SCHEDULER_NAME"' in text
