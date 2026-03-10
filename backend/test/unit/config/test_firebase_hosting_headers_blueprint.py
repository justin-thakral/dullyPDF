"""Regression checks for frontend hosting security headers."""

from __future__ import annotations

import json
from pathlib import Path


FIREBASE_CONFIG_PATH = Path("firebase.json")


def _firebase_headers() -> list[dict]:
    payload = json.loads(FIREBASE_CONFIG_PATH.read_text(encoding="utf-8"))
    return payload["hosting"]["headers"]


def test_firebase_hosting_config_applies_security_headers_globally() -> None:
    headers = _firebase_headers()
    global_entry = next(entry for entry in headers if entry.get("source") == "**")
    header_values = {item["key"]: item["value"] for item in global_entry["headers"]}

    assert header_values["Content-Security-Policy"] == (
        "default-src 'self'; base-uri 'self'; frame-ancestors 'none'; object-src 'none'; "
        "form-action 'self'; script-src 'self' https://www.googletagmanager.com "
        "https://www.google.com https://www.gstatic.com; style-src 'self' 'unsafe-inline' "
        "https://fonts.googleapis.com; font-src 'self' data: https://fonts.gstatic.com; "
        "img-src 'self' data: blob: https:; connect-src 'self' https: wss:; "
        "frame-src https://www.google.com https://recaptcha.google.com; "
        "worker-src 'self' blob:; media-src 'self' data: blob: https:"
    )
    assert header_values["X-Frame-Options"] == "DENY"
    assert header_values["X-Content-Type-Options"] == "nosniff"
    assert header_values["Referrer-Policy"] == "strict-origin-when-cross-origin"
