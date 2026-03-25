"""Regression checks for frontend hosting rewrites."""

from __future__ import annotations

import json
from pathlib import Path


FIREBASE_CONFIG_PATH = Path("firebase.json")


def _firebase_payload() -> dict:
    return json.loads(FIREBASE_CONFIG_PATH.read_text(encoding="utf-8"))


def _firebase_rewrites() -> list[dict]:
    return _firebase_payload()["hosting"]["rewrites"]


def _firebase_headers() -> list[dict]:
    return _firebase_payload()["hosting"].get("headers", [])


def test_firebase_hosting_rewrites_only_known_spa_and_backend_routes() -> None:
    rewrites = _firebase_rewrites()
    rewrite_sources = {entry["source"] for entry in rewrites}

    assert "**" not in rewrite_sources

    assert {
        "/account-action",
        "/verify-email",
        "/upload",
        "/ui",
        "/ui/profile",
        "/ui/forms/:formId",
        "/ui/groups/:groupId",
        "/respond/:token",
        "/sign/:token",
        "/api",
        "/api/**",
        "/detect-fields",
        "/detect-fields/**",
    }.issubset(rewrite_sources)


def test_firebase_hosting_marks_public_token_routes_no_store() -> None:
    headers = _firebase_headers()
    token_headers = {
        entry["source"]: {header["key"]: header["value"] for header in entry.get("headers", [])}
        for entry in headers
        if entry.get("source") in {"/respond/**", "/sign/**"}
    }

    assert token_headers["/respond/**"]["Cache-Control"] == "no-store,max-age=0"
    assert token_headers["/sign/**"]["Cache-Control"] == "no-store,max-age=0"
