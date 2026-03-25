"""Integration coverage for authenticated workspace bootstrap endpoints."""

from __future__ import annotations

from fastapi.testclient import TestClient
import pytest

import backend.main as main
import backend.api.routes.groups as groups_routes
import backend.api.middleware.security as security_middleware
import backend.api.routes.profile as profile_routes
import backend.api.routes.saved_forms as saved_forms_routes
import backend.firebaseDB.group_database as group_database
import backend.firebaseDB.template_database as template_database
import backend.firebaseDB.user_database as user_database
from backend.firebaseDB.firebase_service import RequestUser
from backend.test.unit.firebase._fakes import FakeFirestoreClient


AUTH_HEADERS = {"Authorization": "Bearer integration-token"}


@pytest.fixture
def client() -> TestClient:
    return TestClient(main.app)


def _workspace_user() -> RequestUser:
    return RequestUser(
        uid="firebase-user-1",
        app_user_id="user-1",
        email="justin@ttcommercial.com",
        display_name="Justin QA",
        role=user_database.ROLE_BASE,
    )


def _seed_workspace_bootstrap(firestore_client: FakeFirestoreClient) -> None:
    firestore_client.collection(user_database.USERS_COLLECTION).document("user-1").seed(
        {
            "email": "justin@ttcommercial.com",
            "displayName": "Justin QA",
            user_database.ROLE_FIELD: user_database.ROLE_BASE,
            user_database.OPENAI_CREDITS_FIELD: 7,
        }
    )

    firestore_client.collection(template_database.TEMPLATES_COLLECTION).document("form-alpha").seed(
        {
            "user_id": "user-1",
            "pdf_bucket_path": "gs://forms/bravo.pdf",
            "template_bucket_path": "gs://templates/bravo.json",
            "metadata": {
                "name": "Bravo Packet",
            },
            "created_at": "2026-03-15T12:00:00+00:00",
            "updated_at": "2026-03-15T12:00:00+00:00",
        }
    )
    firestore_client.collection(template_database.TEMPLATES_COLLECTION).document("form-beta").seed(
        {
            "user_id": "user-1",
            "pdf_bucket_path": "gs://forms/alpha.pdf",
            "template_bucket_path": "gs://templates/alpha.json",
            "metadata": {
                "name": "Alpha Packet",
            },
            "created_at": "2026-03-16T12:00:00+00:00",
            "updated_at": "2026-03-16T12:00:00+00:00",
        }
    )

    firestore_client.collection(group_database.GROUPS_COLLECTION).document("group-a").seed(
        {
            "user_id": "user-1",
            "name": "Admissions Packet",
            "normalized_name": "admissions packet",
            "template_ids": ["form-alpha", "form-beta"],
            "created_at": "2026-03-16T13:00:00+00:00",
            "updated_at": "2026-03-16T13:00:00+00:00",
        }
    )
    firestore_client.collection(group_database.GROUPS_COLLECTION).document("group-b").seed(
        {
            "user_id": "user-1",
            "name": "Billing Packet",
            "normalized_name": "billing packet",
            "template_ids": ["form-alpha"],
            "created_at": "2026-03-16T14:00:00+00:00",
            "updated_at": "2026-03-16T14:00:00+00:00",
        }
    )


@pytest.mark.parametrize(
    ("path", "method"),
    [
        ("/api/profile", "get"),
        ("/api/saved-forms", "get"),
        ("/api/saved-forms/form-beta", "get"),
        ("/api/groups", "get"),
        ("/api/groups/group-a", "get"),
    ],
)
def test_workspace_bootstrap_endpoints_require_authentication(
    client: TestClient,
    path: str,
    method: str,
) -> None:
    response = getattr(client, method)(path)

    assert response.status_code == 401
    assert "authorization" in response.text.lower()


def test_workspace_bootstrap_endpoints_return_profile_saved_forms_and_groups(
    client: TestClient,
    mocker,
) -> None:
    firestore_client = FakeFirestoreClient()
    request_user = _workspace_user()
    _seed_workspace_bootstrap(firestore_client)

    for module in (user_database, template_database, group_database):
        mocker.patch.object(module, "get_firestore_client", return_value=firestore_client)
    for route_module in (profile_routes, saved_forms_routes, groups_routes):
        mocker.patch.object(route_module, "require_user", return_value=request_user)

    mocker.patch.object(
        security_middleware,
        "verify_token",
        return_value={
            "uid": request_user.uid,
            "email": request_user.email,
            "name": request_user.display_name,
            user_database.ROLE_FIELD: request_user.role,
        },
    )
    mocker.patch.object(profile_routes, "billing_enabled", return_value=False)
    mocker.patch.object(profile_routes, "sync_user_downgrade_retention", return_value=None)

    profile_response = client.get("/api/profile", headers=AUTH_HEADERS)
    saved_forms_response = client.get("/api/saved-forms", headers=AUTH_HEADERS)
    saved_form_detail_response = client.get("/api/saved-forms/form-beta", headers=AUTH_HEADERS)
    groups_response = client.get("/api/groups", headers=AUTH_HEADERS)
    group_detail_response = client.get("/api/groups/group-a", headers=AUTH_HEADERS)

    assert profile_response.status_code == 200
    assert saved_forms_response.status_code == 200
    assert saved_form_detail_response.status_code == 200
    assert groups_response.status_code == 200
    assert group_detail_response.status_code == 200

    profile_payload = profile_response.json()
    assert profile_payload["email"] == "justin@ttcommercial.com"
    assert profile_payload["displayName"] == "Justin QA"
    assert profile_payload["role"] == user_database.ROLE_BASE
    assert profile_payload["creditsRemaining"] == 7
    assert profile_payload["availableCredits"] == 7
    assert profile_payload["billing"] == {
        "enabled": False,
        "plans": {},
        "hasSubscription": False,
        "subscriptionStatus": None,
        "cancelAtPeriodEnd": None,
        "cancelAt": None,
        "currentPeriodEnd": None,
    }
    assert profile_payload["retention"] is None
    assert profile_payload["limits"]["savedFormsMax"] >= 1

    saved_forms_payload = saved_forms_response.json()["forms"]
    assert [entry["id"] for entry in saved_forms_payload] == ["form-beta", "form-alpha"]
    assert [entry["name"] for entry in saved_forms_payload] == ["Alpha Packet", "Bravo Packet"]

    saved_form_detail_payload = saved_form_detail_response.json()
    assert saved_form_detail_payload == {
        "url": "/api/saved-forms/form-beta/download",
        "name": "Alpha Packet",
        "sessionId": "form-beta",
        "fillRules": {
            "version": 1,
            "checkboxRules": [],
            "textTransformRules": [],
        },
    }

    groups_payload = groups_response.json()["groups"]
    assert [entry["id"] for entry in groups_payload] == ["group-a", "group-b"]
    assert [entry["name"] for entry in groups_payload] == ["Admissions Packet", "Billing Packet"]
    assert groups_payload[0]["templateIds"] == ["form-beta", "form-alpha"]
    assert [entry["name"] for entry in groups_payload[0]["templates"]] == ["Alpha Packet", "Bravo Packet"]

    group_detail_payload = group_detail_response.json()["group"]
    assert group_detail_payload["id"] == "group-a"
    assert group_detail_payload["name"] == "Admissions Packet"
    assert group_detail_payload["templateIds"] == ["form-beta", "form-alpha"]
    assert [entry["id"] for entry in group_detail_payload["templates"]] == ["form-beta", "form-alpha"]
