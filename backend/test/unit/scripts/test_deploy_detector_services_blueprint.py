"""Regression checks for detector deploy script auth env syncing."""

from __future__ import annotations

from pathlib import Path


SCRIPT_PATH = Path("scripts/deploy-detector-services.sh")


def _script_text() -> str:
    return SCRIPT_PATH.read_text(encoding="utf-8")


def test_deploy_detector_services_syncs_generic_auth_env_to_service_url() -> None:
    text = _script_text()
    assert 'gcloud run services update "$service_name"' in text
    assert 'DETECTOR_SERVICE_URL=${service_url}' in text
    assert 'DETECTOR_TASKS_AUDIENCE=${runtime_audience}' in text


def test_deploy_detector_services_syncs_profile_specific_auth_env_to_service_url() -> None:
    text = _script_text()
    assert 'profile_upper="${profile^^}"' in text
    assert 'DETECTOR_SERVICE_URL_${profile_upper}=${service_url}' in text
    assert 'DETECTOR_TASKS_AUDIENCE_${profile_upper}=${runtime_audience}' in text


def test_deploy_detector_services_documents_why_runtime_auth_sync_is_required() -> None:
    text = _script_text()
    assert "The detector verifies its incoming OIDC token" in text
    assert "not the backend routing" in text


def test_deploy_detector_services_requires_a_dedicated_runtime_service_account_in_prod() -> None:
    text = _script_text()
    assert 'require_exact FIREBASE_USE_ADC "true"' in text
    assert "require_empty FIREBASE_CREDENTIALS" in text
    assert "require_empty FIREBASE_CREDENTIALS_SECRET" in text
    assert "require_empty GOOGLE_APPLICATION_CREDENTIALS" in text
    assert 'RUNTIME_SA="${DETECTOR_RUNTIME_SERVICE_ACCOUNT:-}"' in text
    assert "DETECTOR_RUNTIME_SERVICE_ACCOUNT must differ from DETECTOR_TASKS_SERVICE_ACCOUNT in prod." in text


def test_deploy_detector_services_filters_env_to_a_detector_allowlist() -> None:
    text = _script_text()
    assert "allowed_exact = {" in text
    assert '"COMMONFORMS_",' in text
    assert '"DETECTOR_",' in text
    assert '"OPENAI_RENAME_",' in text
    assert '"OPENAI_REMAP_",' in text
    assert '"FIREBASE_CREDENTIALS"' not in text
    assert '"GOOGLE_APPLICATION_CREDENTIALS"' not in text
    assert '"FORMS_BUCKET"' not in text
    assert '"TEMPLATES_BUCKET"' not in text
    assert '"STRIPE_' not in text


def test_deploy_detector_services_resets_invoker_policy_instead_of_patch_adding_members() -> None:
    text = _script_text()
    assert 'gcloud run services get-iam-policy "$service_name"' in text
    assert 'binding.get("role") != "roles/run.invoker"' in text
    assert 'gcloud run services set-iam-policy "$service_name" "$tmp_policy"' in text
