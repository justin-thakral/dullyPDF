"""Regression checks for OpenAI worker deploy hardening."""

from __future__ import annotations

from pathlib import Path


SCRIPT_PATH = Path("scripts/deploy-openai-workers.sh")


def _script_text() -> str:
    return SCRIPT_PATH.read_text(encoding="utf-8")


def test_deploy_openai_workers_requires_dedicated_runtime_service_accounts_in_prod() -> None:
    text = _script_text()
    assert 'require_exact FIREBASE_USE_ADC "true"' in text
    assert "require_empty FIREBASE_CREDENTIALS" in text
    assert "require_empty FIREBASE_CREDENTIALS_SECRET" in text
    assert "require_empty GOOGLE_APPLICATION_CREDENTIALS" in text
    assert 'RENAME_RUNTIME_SA="${OPENAI_RENAME_RUNTIME_SERVICE_ACCOUNT:-}"' in text
    assert 'REMAP_RUNTIME_SA="${OPENAI_REMAP_RUNTIME_SERVICE_ACCOUNT:-}"' in text
    assert "OPENAI_*_RUNTIME_SERVICE_ACCOUNT must differ from the matching worker caller service account in prod." in text
    assert "OPENAI_RENAME_RUNTIME_SERVICE_ACCOUNT and OPENAI_REMAP_RUNTIME_SERVICE_ACCOUNT must be distinct in prod." in text


def test_deploy_openai_workers_filters_env_to_a_worker_allowlist() -> None:
    text = _script_text()
    assert "allowed_exact = {" in text
    assert '"OPENAI_API_KEY",' in text
    assert '"OPENAI_RENAME_",' in text
    assert '"OPENAI_REMAP_",' in text
    assert '"OPENAI_TASKS_",' in text
    assert '"OPENAI_PREWARM_",' in text
    assert '"SANDBOX_SESSION_",' in text
    assert '"FIREBASE_CREDENTIALS"' not in text
    assert '"GOOGLE_APPLICATION_CREDENTIALS"' not in text
    assert '"STRIPE_' not in text
    assert '"FORMS_BUCKET"' not in text
    assert '"TEMPLATES_BUCKET"' not in text


def test_deploy_openai_workers_only_binds_the_openai_api_secret() -> None:
    text = _script_text()
    assert '"OPENAI_API_KEY_SECRET": "OPENAI_API_KEY"' in text
    assert "GMAIL_CLIENT_SECRET_SECRET" not in text
    assert "ADMIN_TOKEN_SECRET" not in text
    assert '"GMAIL_CLIENT_SECRET"' in text
    assert '"ADMIN_TOKEN"' in text


def test_deploy_openai_workers_resets_invoker_policy_to_only_the_expected_caller() -> None:
    text = _script_text()
    assert 'gcloud run services get-iam-policy "$service_name"' in text
    assert 'binding.get("role") != "roles/run.invoker"' in text
    assert 'bindings.append({"role": "roles/run.invoker", "members": [allowed_member]})' in text
    assert 'gcloud run services set-iam-policy "$service_name" "$tmp_policy"' in text
