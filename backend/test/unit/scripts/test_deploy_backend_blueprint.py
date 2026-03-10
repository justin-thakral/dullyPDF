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
    assert '"STRIPE_SECRET_KEY_SECRET": "STRIPE_SECRET_KEY"' in text
    assert '"STRIPE_WEBHOOK_SECRET_SECRET": "STRIPE_WEBHOOK_SECRET"' in text


def test_deploy_backend_updates_cloud_run_stripe_secret_bindings() -> None:
    text = _script_text()
    assert "STRIPE_SECRET_KEY=${STRIPE_SECRET_KEY_SECRET}:latest" in text
    assert "STRIPE_WEBHOOK_SECRET=${STRIPE_WEBHOOK_SECRET_SECRET}:latest" in text


def test_deploy_backend_runs_required_billing_integration_test_gate() -> None:
    text = _script_text()
    assert 'BILLING_INTEGRATION_TEST_PATH="backend/test/integration/test_billing_webhook_integration.py"' in text
    assert 'ENV=test python3 -m pytest -q "$BILLING_INTEGRATION_TEST_PATH"' in text


def test_deploy_backend_requires_fill_link_token_secret_and_recaptcha() -> None:
    text = _script_text()
    assert "require_nonempty FILL_LINK_TOKEN_SECRET" in text
    assert "require_fill_link_secret_quality FILL_LINK_TOKEN_SECRET" in text
    assert "must be at least 32 characters in prod" in text
    assert "FILL_LINK_REQUIRE_RECAPTCHA must be true in prod" in text
    assert "require_nonempty RECAPTCHA_ALLOWED_HOSTNAMES" in text


def test_deploy_backend_requires_adc_only_firebase_auth_in_prod() -> None:
    text = _script_text()
    assert 'require_exact FIREBASE_USE_ADC "true"' in text
    assert "require_nonempty BACKEND_RUNTIME_SERVICE_ACCOUNT" in text
    assert "require_empty FIREBASE_CREDENTIALS" in text
    assert "require_empty FIREBASE_CREDENTIALS_SECRET" in text
    assert "require_empty GOOGLE_APPLICATION_CREDENTIALS" in text
    assert '"BACKEND_RUNTIME_SERVICE_ACCOUNT"' in text
    assert '"FIREBASE_CREDENTIALS"' in text
    assert '"GOOGLE_APPLICATION_CREDENTIALS"' in text
    assert '"FIREBASE_CREDENTIALS_SECRET"' in text
    assert '--service-account "$BACKEND_RUNTIME_SERVICE_ACCOUNT"' in text


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
    assert "BACKEND_RUNTIME_SERVICE_ACCOUNT=dullypdf-backend-runtime@dullypdf.iam.gserviceaccount.com" in text
    assert "# FIREBASE_CREDENTIALS_SECRET=" in text
    assert "GOOGLE_APPLICATION_CREDENTIALS unset" in text
