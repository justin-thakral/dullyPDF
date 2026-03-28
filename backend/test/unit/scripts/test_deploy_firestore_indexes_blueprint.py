"""Regression checks for Firestore index deployment script coverage."""

from __future__ import annotations

import json
from pathlib import Path


SCRIPT_PATH = Path("scripts/deploy-firestore-indexes.sh")
INDEXES_PATH = Path("firestore.indexes.json")
FIREBASE_CONFIG_PATH = Path("firebase.json")


def _script_text() -> str:
    return SCRIPT_PATH.read_text(encoding="utf-8")


def _indexes_payload() -> dict:
    return json.loads(INDEXES_PATH.read_text(encoding="utf-8"))


def _firebase_config() -> dict:
    return json.loads(FIREBASE_CONFIG_PATH.read_text(encoding="utf-8"))


def test_deploy_firestore_indexes_script_guards_non_prod_and_deploys_indexes() -> None:
    text = _script_text()
    assert 'PROJECT_ID="${PROJECT_ID:-dullypdf}"' in text
    assert 'DULLYPDF_ALLOW_NON_PROD' in text
    assert 'firebase deploy --only firestore:indexes --project "$PROJECT_ID"' in text


def test_firestore_indexes_file_declares_template_api_endpoint_event_ordering() -> None:
    payload = _indexes_payload()
    assert payload["indexes"] == [
        {
            "collectionGroup": "template_api_endpoint_events",
            "queryScope": "COLLECTION",
            "fields": [
                {"fieldPath": "endpoint_id", "order": "ASCENDING"},
                {"fieldPath": "created_at", "order": "DESCENDING"},
                {"fieldPath": "__name__", "order": "DESCENDING"},
            ],
            "density": "SPARSE_ALL",
        }
    ]


def test_firestore_indexes_file_tracks_ttl_field_overrides() -> None:
    payload = _indexes_payload()
    assert payload["fieldOverrides"] == [
        {
            "collectionGroup": "detection_requests",
            "fieldPath": "expires_at",
            "ttl": True,
            "indexes": [
                {"order": "ASCENDING", "queryScope": "COLLECTION"},
                {"order": "DESCENDING", "queryScope": "COLLECTION"},
                {"arrayConfig": "CONTAINS", "queryScope": "COLLECTION"},
            ],
        },
        {
            "collectionGroup": "openai_rename_requests",
            "fieldPath": "expires_at",
            "ttl": True,
            "indexes": [
                {"order": "ASCENDING", "queryScope": "COLLECTION"},
                {"order": "DESCENDING", "queryScope": "COLLECTION"},
                {"arrayConfig": "CONTAINS", "queryScope": "COLLECTION"},
            ],
        },
        {
            "collectionGroup": "openai_requests",
            "fieldPath": "expires_at",
            "ttl": True,
            "indexes": [
                {"order": "ASCENDING", "queryScope": "COLLECTION"},
                {"order": "DESCENDING", "queryScope": "COLLECTION"},
                {"arrayConfig": "CONTAINS", "queryScope": "COLLECTION"},
            ],
        },
        {
            "collectionGroup": "rate_limits",
            "fieldPath": "expires_at",
            "ttl": True,
            "indexes": [
                {"order": "ASCENDING", "queryScope": "COLLECTION"},
                {"order": "DESCENDING", "queryScope": "COLLECTION"},
                {"arrayConfig": "CONTAINS", "queryScope": "COLLECTION"},
            ],
        },
        {
            "collectionGroup": "schema_metadata",
            "fieldPath": "expires_at",
            "ttl": True,
            "indexes": [
                {"order": "ASCENDING", "queryScope": "COLLECTION"},
                {"order": "DESCENDING", "queryScope": "COLLECTION"},
                {"arrayConfig": "CONTAINS", "queryScope": "COLLECTION"},
            ],
        },
        {
            "collectionGroup": "signing_sessions",
            "fieldPath": "expires_at",
            "ttl": True,
            "indexes": [
                {"order": "ASCENDING", "queryScope": "COLLECTION"},
                {"order": "DESCENDING", "queryScope": "COLLECTION"},
                {"arrayConfig": "CONTAINS", "queryScope": "COLLECTION"},
            ],
        },
        {
            "collectionGroup": "session_cache",
            "fieldPath": "expires_at",
            "ttl": True,
            "indexes": [
                {"order": "ASCENDING", "queryScope": "COLLECTION"},
                {"order": "DESCENDING", "queryScope": "COLLECTION"},
                {"arrayConfig": "CONTAINS", "queryScope": "COLLECTION"},
            ],
        },
    ]


def test_firebase_config_points_firestore_to_repo_managed_indexes() -> None:
    payload = _firebase_config()
    assert payload["firestore"]["indexes"] == "firestore.indexes.json"
