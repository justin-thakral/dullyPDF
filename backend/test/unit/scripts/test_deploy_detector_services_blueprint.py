"""Regression checks for detector deploy script auth env syncing."""

from __future__ import annotations

from pathlib import Path


SCRIPT_PATH = Path("scripts/deploy-detector-services.sh")


def _script_text() -> str:
    return SCRIPT_PATH.read_text(encoding="utf-8")


def test_deploy_detector_services_syncs_generic_auth_env_to_service_url() -> None:
    text = _script_text()
    assert 'desired_service_url="$(detector_service_url_for_target "$current_target" "$profile")"' in text
    assert 'desired_runtime_audience="$(' in text
    assert 'should_sync_runtime_env="false"' in text
    assert 'if [[ "$should_sync_runtime_env" == "true" ]]; then' in text
    assert 'gcloud run services update "$service_name"' in text
    assert 'DETECTOR_SERVICE_URL=${service_url}' in text
    assert 'DETECTOR_TASKS_AUDIENCE=${runtime_audience}' in text


def test_deploy_detector_services_syncs_profile_specific_auth_env_to_service_url() -> None:
    text = _script_text()
    assert 'entries[f"DETECTOR_SERVICE_URL_{profile}"] = json.dumps(desired_service_url)' in text
    assert 'entries[f"DETECTOR_TASKS_AUDIENCE_{profile}"] = json.dumps(desired_runtime_audience)' in text
    assert 'profile_upper="${profile^^}"' in text
    assert 'DETECTOR_SERVICE_URL_${profile_upper}=${service_url}' in text
    assert 'DETECTOR_TASKS_AUDIENCE_${profile_upper}=${runtime_audience}' in text


def test_deploy_detector_services_documents_why_runtime_auth_sync_is_required() -> None:
    text = _script_text()
    assert "The detector verifies its incoming OIDC token" in text
    assert "not the backend routing" in text


def test_deploy_detector_services_recreates_single_gpu_service_instead_of_rolling_a_second_revision() -> None:
    text = _script_text()
    assert 'if [[ "$current_target" == "gpu" ]] \\' in text
    assert '&& detector_share_single_gpu_service "$DETECTOR_ROUTING_MODE" \\' in text
    assert "Single-GPU detector deploys require DETECTOR_USE_STABLE_AUDIENCE=true" in text
    assert 'if [[ -n "$stable_audience" ]] || [[ -n "$desired_service_url" && -n "$desired_runtime_audience" ]]; then' in text
    assert 'delete_cloud_run_service_if_present "$service_name" "$DEPLOY_REGION"' in text
    assert 'run_detector_deploy_with_quota_retry()' in text
    assert 'DETECTOR_SINGLE_GPU_RETRY_ATTEMPTS' in text
    assert 'DETECTOR_SINGLE_GPU_RETRY_WAIT_SECONDS' in text
    assert "Cloud Run is still releasing the prior GPU allocation" in text
    assert 'run_detector_deploy_with_quota_retry "$service_name" "${deploy_command[@]}"' in text
    assert "single-GPU mode cannot roll a second GPU revision under quota 1" in text


def test_deploy_detector_services_requires_a_dedicated_runtime_service_account_in_prod() -> None:
    text = _script_text()
    assert 'REGION="${REGION:-${DETECTOR_TASKS_LOCATION:-us-east4}}"' in text
    assert 'source "${SCRIPT_DIR}/_artifact_registry_guard.sh"' in text
    assert 'ARTIFACT_REGISTRY_LOCATION="${ARTIFACT_REGISTRY_LOCATION:-us-east4}"' in text
    assert 'require_prod_artifact_registry_location "detector Artifact Registry location" "$ARTIFACT_REGISTRY_LOCATION"' in text
    assert 'require_prod_artifact_registry_repo "DETECTOR_ARTIFACT_REPO" "$ARTIFACT_REPO"' in text
    assert 'DETECTOR_IMAGE="${DETECTOR_IMAGE:-${ARTIFACT_REGISTRY_LOCATION}-docker.pkg.dev/${PROJECT_ID}/${ARTIFACT_REPO}/detector-service:${TAG}}"' in text
    assert 'require_prod_artifact_registry_image "DETECTOR_IMAGE" "$DETECTOR_IMAGE" "$ARTIFACT_REPO"' in text
    assert 'require_exact FIREBASE_USE_ADC "true"' in text
    assert "require_empty FIREBASE_CREDENTIALS" in text
    assert "require_empty FIREBASE_CREDENTIALS_SECRET" in text
    assert "require_empty GOOGLE_APPLICATION_CREDENTIALS" in text
    assert "require_integer_ge DETECTOR_TASKS_MAX_ATTEMPTS 1" in text
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


def test_deploy_detector_services_skips_second_gpu_service_in_single_gpu_serialized_mode() -> None:
    text = _script_text()
    assert 'if detector_share_single_gpu_service "$DETECTOR_ROUTING_MODE"; then' in text
    assert 'gpu_heavy_name=""' in text
