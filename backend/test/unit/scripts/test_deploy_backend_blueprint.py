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
    assert "STRIPE_MAX_PROCESSED_EVENTS=0" in text
