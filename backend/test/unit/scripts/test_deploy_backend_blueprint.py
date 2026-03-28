"""Regression checks for prod backend deploy script hardening."""

from __future__ import annotations

from pathlib import Path


SCRIPT_PATH = Path("scripts/deploy-backend.sh")
PROD_ENV_EXAMPLE_PATH = Path("config/backend.prod.env.example")


def _script_text() -> str:
    return SCRIPT_PATH.read_text(encoding="utf-8")


def _prod_env_example_text() -> str:
    return PROD_ENV_EXAMPLE_PATH.read_text(encoding="utf-8")


def test_deploy_backend_requires_stripe_secret_bindings() -> None:
    text = _script_text()
    assert "require_value_or_secret STRIPE_SECRET_KEY STRIPE_SECRET_KEY_SECRET" in text
    assert "require_value_or_secret STRIPE_WEBHOOK_SECRET STRIPE_WEBHOOK_SECRET_SECRET" in text
    assert "literal STRIPE_* values are not allowed" in text


def test_deploy_backend_omits_literal_stripe_env_when_secret_binding_is_present() -> None:
    text = _script_text()
    assert '"FILL_LINK_TOKEN_SECRET_SECRET": "FILL_LINK_TOKEN_SECRET"' in text
    assert '"STRIPE_SECRET_KEY_SECRET": "STRIPE_SECRET_KEY"' in text
    assert '"STRIPE_WEBHOOK_SECRET_SECRET": "STRIPE_WEBHOOK_SECRET"' in text


def test_deploy_backend_updates_cloud_run_stripe_secret_bindings() -> None:
    text = _script_text()
    assert "FILL_LINK_TOKEN_SECRET=${FILL_LINK_TOKEN_SECRET_SECRET}:latest" in text
    assert "STRIPE_SECRET_KEY=${STRIPE_SECRET_KEY_SECRET}:latest" in text
    assert "STRIPE_WEBHOOK_SECRET=${STRIPE_WEBHOOK_SECRET_SECRET}:latest" in text


def test_deploy_backend_runs_required_billing_integration_test_gate() -> None:
    text = _script_text()
    assert 'BILLING_INTEGRATION_TEST_PATH="backend/test/integration/test_billing_webhook_integration.py"' in text
    assert 'ENV=test python3 -m pytest -q "$BILLING_INTEGRATION_TEST_PATH"' in text


def test_deploy_backend_requires_fill_link_token_secret_and_recaptcha() -> None:
    text = _script_text()
    assert "require_value_or_secret FILL_LINK_TOKEN_SECRET FILL_LINK_TOKEN_SECRET_SECRET" in text
    assert "Use FILL_LINK_TOKEN_SECRET_SECRET for prod; literal FILL_LINK_TOKEN_SECRET is not allowed." in text
    assert "FILL_LINK_REQUIRE_RECAPTCHA must be true in prod" in text
    assert "require_nonempty RECAPTCHA_ALLOWED_HOSTNAMES" in text


def test_deploy_backend_requires_signing_secret_kms_bucket_and_rate_limits() -> None:
    text = _script_text()
    assert "require_nonempty SIGNING_LINK_TOKEN_SECRET" in text
    assert "require_signing_link_secret_quality SIGNING_LINK_TOKEN_SECRET" in text
    assert "require_nonempty SIGNING_AUDIT_KMS_KEY" in text
    assert "require_nonempty SIGNING_BUCKET" in text
    assert 'python3 scripts/validate-signing-storage.py' in text
    assert "require_integer_ge SIGNING_RETENTION_DAYS 2555" in text
    assert "require_integer_ge SIGNING_SESSION_TTL_SECONDS 300" in text
    assert "require_integer_ge SIGNING_VIEW_RATE_WINDOW_SECONDS 1" in text
    assert "require_integer_ge SIGNING_VIEW_RATE_PER_IP 1" in text
    assert "require_integer_ge SIGNING_VIEW_RATE_GLOBAL 0" in text
    assert "require_integer_ge SIGNING_ACTION_RATE_WINDOW_SECONDS 1" in text
    assert "require_integer_ge SIGNING_ACTION_RATE_PER_IP 1" in text
    assert "require_integer_ge SIGNING_ACTION_RATE_GLOBAL 0" in text
    assert "require_integer_ge SIGNING_DOCUMENT_RATE_WINDOW_SECONDS 1" in text
    assert "require_integer_ge SIGNING_DOCUMENT_RATE_PER_IP 1" in text
    assert "require_integer_ge SIGNING_DOCUMENT_RATE_GLOBAL 0" in text


def test_deploy_backend_requires_adc_only_firebase_auth_in_prod() -> None:
    text = _script_text()
    assert 'require_exact FIREBASE_USE_ADC "true"' in text
    assert "require_nonempty BACKEND_RUNTIME_SERVICE_ACCOUNT" in text
    assert 'service_account_has_project_iam_permission "$runtime_sa" "firebaseauth.users.get"' in text
    assert "roles/firebaseauth.viewer" in text
    assert "require_firebase_auth_runtime_access" in text
    assert "require_empty FIREBASE_CREDENTIALS" in text
    assert "require_empty FIREBASE_CREDENTIALS_SECRET" in text
    assert "require_empty GOOGLE_APPLICATION_CREDENTIALS" in text
    assert '"BACKEND_RUNTIME_SERVICE_ACCOUNT"' in text
    assert '"FIREBASE_CREDENTIALS"' in text
    assert '"GOOGLE_APPLICATION_CREDENTIALS"' in text
    assert '"FIREBASE_CREDENTIALS_SECRET"' in text
    assert '--service-account "$BACKEND_RUNTIME_SERVICE_ACCOUNT"' in text


def test_deploy_backend_only_sets_prod_min_instances_when_explicitly_configured() -> None:
    text = _script_text()
    assert 'BACKEND_MIN_INSTANCES="${BACKEND_MIN_INSTANCES:-}"' in text
    assert "require_optional_integer_ge BACKEND_MIN_INSTANCES 0" in text
    assert 'DEPLOY_ARGS+=(--min "$BACKEND_MIN_INSTANCES")' in text


def test_deploy_backend_defaults_to_east4_public_service_without_changing_detector_region_fallback() -> None:
    text = _script_text()
    assert 'source "${SCRIPT_DIR}/_artifact_registry_guard.sh"' in text
    assert 'BACKEND_REGION="${BACKEND_REGION:-${REGION:-us-east4}}"' in text
    assert 'SERVICE_NAME="${BACKEND_SERVICE:-dullypdf-backend-east4}"' in text
    assert 'ARTIFACT_REGISTRY_LOCATION="${ARTIFACT_REGISTRY_LOCATION:-us-east4}"' in text
    assert 'BACKEND_ARTIFACT_REPO="${BACKEND_ARTIFACT_REPO:-dullypdf-backend}"' in text
    assert 'BACKEND_IMAGE="${BACKEND_IMAGE:-${ARTIFACT_REGISTRY_LOCATION}-docker.pkg.dev/${PROJECT_ID}/${BACKEND_ARTIFACT_REPO}/backend:${TAG}}"' in text
    assert 'require_prod_artifact_registry_location "backend Artifact Registry location" "$ARTIFACT_REGISTRY_LOCATION"' in text
    assert 'require_prod_artifact_registry_repo "BACKEND_ARTIFACT_REPO" "$BACKEND_ARTIFACT_REPO"' in text
    assert 'require_prod_artifact_registry_image "BACKEND_IMAGE" "$BACKEND_IMAGE" "$BACKEND_ARTIFACT_REPO"' in text
    assert 'Refusing to deploy the retired prod backend service name dullypdf-backend.' in text
    assert 'Use BACKEND_SERVICE=dullypdf-backend-east4 instead.' in text
    assert 'DETECTOR_SERVICE_REGION="${DETECTOR_SERVICE_REGION:-${DETECTOR_TASKS_LOCATION:-${REGION:-us-east4}}}"' in text
    assert '--region "$BACKEND_REGION"' in text


def test_deploy_backend_resolves_openai_worker_urls_from_cloud_run_before_deploy() -> None:
    text = _script_text()
    assert 'resolve_cloud_run_service_url()' in text
    assert 'OPENAI_RENAME_SERVICE_REGION="${OPENAI_RENAME_SERVICE_REGION:-${OPENAI_RENAME_TASKS_LOCATION:-${REGION:-us-east4}}}"' in text
    assert 'OPENAI_REMAP_SERVICE_REGION="${OPENAI_REMAP_SERVICE_REGION:-${OPENAI_REMAP_TASKS_LOCATION:-${REGION:-us-east4}}}"' in text
    assert 'OPENAI_RENAME_SERVICE_NAME_LIGHT="${OPENAI_RENAME_SERVICE_NAME_LIGHT:-dullypdf-openai-rename-light}"' in text
    assert 'OPENAI_REMAP_SERVICE_NAME_HEAVY="${OPENAI_REMAP_SERVICE_NAME_HEAVY:-dullypdf-openai-remap-heavy}"' in text
    assert 'OPENAI_RENAME_SERVICE_URL_LIGHT_ACTIVE="$(' in text
    assert 'OPENAI_REMAP_SERVICE_URL_HEAVY_ACTIVE="$(' in text
    assert 'OPENAI_RENAME_TASKS_AUDIENCE_LIGHT_ACTIVE="$OPENAI_RENAME_SERVICE_URL_LIGHT_ACTIVE"' in text
    assert 'OPENAI_REMAP_TASKS_AUDIENCE_HEAVY_ACTIVE="$OPENAI_REMAP_SERVICE_URL_HEAVY_ACTIVE"' in text
    assert '"OPENAI_RENAME_SERVICE_URL_LIGHT"' in text
    assert '"OPENAI_REMAP_TASKS_AUDIENCE_HEAVY"' in text
    assert 'OPENAI_RENAME_SERVICE_URL: {json.dumps(rename_light_url)}' in text
    assert 'OPENAI_REMAP_TASKS_AUDIENCE_HEAVY: {json.dumps(remap_heavy_audience)}' in text


def test_backend_prod_env_example_documents_stripe_as_required() -> None:
    stripe_heading = next(
        line.strip()
        for line in _prod_env_example_text().splitlines()
        if line.strip().startswith("# Stripe billing")
    )
    assert "required" in stripe_heading.lower()
    assert "optional" not in stripe_heading.lower()


def test_backend_prod_env_example_documents_stripe_idempotency_and_event_history_knobs() -> None:
    text = _prod_env_example_text()
    assert "STRIPE_CHECKOUT_IDEMPOTENCY_WINDOW_SECONDS=300" in text
    assert "STRIPE_MAX_PROCESSED_EVENTS=256" in text


def test_backend_prod_env_example_documents_adc_only_and_fill_link_placeholder_rules() -> None:
    text = _prod_env_example_text()
    assert "at least 32 characters" in text
    assert "must use ADC" in text
    assert "roles/firebaseauth.viewer" in text
    assert "ARTIFACT_REGISTRY_LOCATION=us-east4" in text
    assert "Canonical prod Artifact Registry location and repo" in text
    assert "BACKEND_REGION=us-east4" in text
    assert "BACKEND_SERVICE=dullypdf-backend-east4" in text
    assert "reject BACKEND_SERVICE=dullypdf-backend" in text
    assert "BACKEND_RUNTIME_SERVICE_ACCOUNT=dullypdf-backend-runtime@dullypdf.iam.gserviceaccount.com" in text
    assert "# BACKEND_MIN_INSTANCES=0" in text
    assert "preserve the current service min instances across deploys" in text
    assert "your-service-123456789012.us-east4.run.app" in text
    assert "# FIREBASE_CREDENTIALS_SECRET=" in text
    assert "GOOGLE_APPLICATION_CREDENTIALS unset" in text
    assert "SANDBOX_TRUST_PROXY_HEADERS=true" in text
    assert "FILL_LINK_TOKEN_SECRET_SECRET=dullypdf-prod-fill-link-token-secret" in text


def test_backend_prod_env_example_documents_signing_prod_requirements() -> None:
    text = _prod_env_example_text()
    assert "SESSION_CLEANUP_GRACE_SECONDS=300" in text
    assert 'SESSION_CLEANUP_SCHEDULE="0 * * * *"' in text
    assert "SIGNING_LINK_TOKEN_SECRET=" in text
    assert "SIGNING_AUDIT_KMS_KEY=projects/dullypdf/locations/us-east4/keyRings/dullypdf-signing/cryptoKeys/signing-audit" in text
    assert "SIGNING_BUCKET=dullypdf-signing" in text
    assert "SIGNING_RETENTION_DAYS=2555" in text
    assert "SIGNING_SESSION_TTL_SECONDS=3600" in text
    assert "SIGNING_VIEW_RATE_WINDOW_SECONDS=60" in text
    assert "SIGNING_ACTION_RATE_WINDOW_SECONDS=300" in text
    assert "SIGNING_DOCUMENT_RATE_WINDOW_SECONDS=300" in text
    assert "Cloud KMS" in text


def test_backend_prod_env_example_documents_gpu_busy_cpu_spillover_knobs() -> None:
    text = _prod_env_example_text()
    assert "DETECTOR_ROUTING_MODE=gpu" in text
    assert "DETECTOR_SERIALIZE_GPU_TASKS=true" in text
    assert "DETECTOR_GPU_BUSY_FALLBACK_TO_CPU=true" in text
    assert "DETECTOR_GPU_BUSY_FALLBACK_PAGE_THRESHOLD=5" in text
    assert "DETECTOR_GPU_BUSY_ACTIVE_WINDOW_SECONDS=1800" in text
    assert "DETECTOR_TASKS_QUEUE_LIGHT_CPU=commonforms-detect-light-cpu" in text
    assert "DETECTOR_TASKS_QUEUE_HEAVY=commonforms-detect-light" in text


def test_backend_prod_env_example_documents_east4_hot_path_buckets() -> None:
    text = _prod_env_example_text()
    assert "COMMONFORMS_MODEL_GCS_URI=gs://dullypdf-models-east4/commonforms/FFDNet-L.pt" in text
    assert "FORMS_BUCKET=dullypdf-forms-east4" in text
    assert "TEMPLATES_BUCKET=dullypdf-templates-east4" in text
    assert "SANDBOX_SESSION_BUCKET=dullypdf-sessions-east4" in text
