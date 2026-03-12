"""Regression checks for prod frontend deploy auth safeguards."""

from __future__ import annotations

from pathlib import Path


SCRIPT_PATH = Path("scripts/deploy-frontend.sh")


def _script_text() -> str:
    return SCRIPT_PATH.read_text(encoding="utf-8")


def test_deploy_frontend_requires_firebase_hosted_auth_domain_in_prod() -> None:
    text = _script_text()
    assert 'require_exact VITE_FIREBASE_AUTH_DOMAIN "${PROJECT_ID}.firebaseapp.com"' in text


def test_deploy_frontend_requires_oauth_csp_sources_before_hosting_deploy() -> None:
    text = _script_text()
    assert 'require_file_contains "firebase.json" "https://apis.google.com"' in text
    assert 'require_file_contains "firebase.json" "https://${PROJECT_ID}.firebaseapp.com"' in text


def test_deploy_frontend_requires_google_ads_csp_source_when_ads_are_enabled() -> None:
    text = _script_text()
    assert 'if [[ -n "${VITE_GOOGLE_ADS_TAG_ID:-}" ]]; then' in text
    assert 'require_file_contains "firebase.json" "https://googleads.g.doubleclick.net"' in text
