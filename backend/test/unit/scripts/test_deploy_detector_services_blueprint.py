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
