"""Integration coverage for Fill By Link public submission behavior."""

from __future__ import annotations

from fastapi.testclient import TestClient
import pytest

import backend.main as main
import backend.firebaseDB.fill_link_database as fill_link_database
import backend.firebaseDB.template_database as template_database
import backend.api.routes.fill_links_public as fill_links_public_routes
import backend.services.recaptcha_service as recaptcha_service
from backend.services.fill_links_service import build_fill_link_public_token
from backend.test.unit.firebase._fakes import FakeFirestoreClient


@pytest.fixture
def client() -> TestClient:
    return TestClient(main.app)


@pytest.fixture(autouse=True)
def _no_transaction_wrapper(mocker):
    mocker.patch.object(fill_link_database.firebase_firestore, "transactional", side_effect=lambda fn: fn)


def test_public_submit_accepts_then_closes_at_cap(client: TestClient, mocker) -> None:
    signed_token = build_fill_link_public_token("link-1")
    firestore_client = FakeFirestoreClient()
    firestore_client.collection(template_database.TEMPLATES_COLLECTION).document("tpl-1").seed(
        {
            "user_id": "user-1",
            "metadata": {"name": "Template One"},
            "pdf_bucket_path": "gs://bucket/template-one.pdf",
            "template_bucket_path": "gs://bucket/template-one.json",
            "created_at": "2024-01-01T00:00:00+00:00",
            "updated_at": "2024-01-01T00:00:00+00:00",
        }
    )
    firestore_client.collection(fill_link_database.FILL_LINKS_COLLECTION).document("link-1").seed(
        {
            "user_id": "user-1",
            "template_id": "tpl-1",
            "template_name": "Template One",
            "title": "Template One Intake",
            "public_token": None,
            "status": "active",
            "max_responses": 1,
            "response_count": 0,
            "questions": [{"key": "full_name", "label": "Full Name", "type": "text"}],
            "require_all_fields": False,
            "created_at": "2024-01-01T00:00:00+00:00",
            "updated_at": "2024-01-01T00:00:00+00:00",
            "published_at": "2024-01-01T00:00:00+00:00",
        }
    )

    mocker.patch.object(fill_link_database, "get_firestore_client", return_value=firestore_client)
    mocker.patch.object(template_database, "get_firestore_client", return_value=firestore_client)
    mocker.patch.object(fill_links_public_routes, "check_rate_limit", return_value=True)
    mocker.patch.object(fill_links_public_routes, "resolve_fill_link_submit_rate_limits", return_value=(300, 10, 0))
    mocker.patch.object(fill_links_public_routes, "resolve_client_ip", return_value="198.51.100.20")
    mocker.patch.object(recaptcha_service, "verify_recaptcha_token", return_value=None)
    mocker.patch.object(fill_links_public_routes, "verify_recaptcha_token", return_value=None)
    mocker.patch.object(fill_links_public_routes, "resolve_fill_link_recaptcha_action", return_value="fill_link_submit")
    mocker.patch.object(fill_links_public_routes, "recaptcha_required_for_fill_link", return_value=False)
    mocker.patch.object(fill_link_database, "now_iso", return_value="ts-submit")

    response = client.post(
        f"/api/fill-links/public/{signed_token}/submit",
        json={"answers": {"full_name": "Ada Lovelace"}},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["link"]["status"] == "closed"
    assert payload["responseDownloadAvailable"] is False
    assert payload["responseDownloadPath"] is None
    stored_link = firestore_client.collection(fill_link_database.FILL_LINKS_COLLECTION).document("link-1").get().to_dict()
    assert stored_link["response_count"] == 1
    assert stored_link["closed_reason"] == "response_limit"

    closed_response = client.post(
        f"/api/fill-links/public/{signed_token}/submit",
        json={"answers": {"full_name": "Grace Hopper"}},
    )

    assert closed_response.status_code == 409


def test_public_submit_reuses_duplicate_attempt_without_consuming_extra_capacity(client: TestClient, mocker) -> None:
    signed_token = build_fill_link_public_token("link-1")
    firestore_client = FakeFirestoreClient()
    firestore_client.collection(template_database.TEMPLATES_COLLECTION).document("tpl-1").seed(
        {
            "user_id": "user-1",
            "metadata": {"name": "Template One"},
            "pdf_bucket_path": "gs://bucket/template-one.pdf",
            "template_bucket_path": "gs://bucket/template-one.json",
            "created_at": "2024-01-01T00:00:00+00:00",
            "updated_at": "2024-01-01T00:00:00+00:00",
        }
    )
    firestore_client.collection(fill_link_database.FILL_LINKS_COLLECTION).document("link-1").seed(
        {
            "user_id": "user-1",
            "template_id": "tpl-1",
            "template_name": "Template One",
            "title": "Template One Intake",
            "public_token": None,
            "status": "active",
            "max_responses": 1,
            "response_count": 0,
            "questions": [{"key": "full_name", "label": "Full Name", "type": "text"}],
            "require_all_fields": False,
            "created_at": "2024-01-01T00:00:00+00:00",
            "updated_at": "2024-01-01T00:00:00+00:00",
            "published_at": "2024-01-01T00:00:00+00:00",
        }
    )

    mocker.patch.object(fill_link_database, "get_firestore_client", return_value=firestore_client)
    mocker.patch.object(template_database, "get_firestore_client", return_value=firestore_client)
    mocker.patch.object(fill_links_public_routes, "check_rate_limit", return_value=True)
    mocker.patch.object(fill_links_public_routes, "resolve_fill_link_submit_rate_limits", return_value=(300, 10, 0))
    mocker.patch.object(fill_links_public_routes, "resolve_client_ip", return_value="198.51.100.20")
    mocker.patch.object(recaptcha_service, "verify_recaptcha_token", return_value=None)
    mocker.patch.object(fill_links_public_routes, "verify_recaptcha_token", return_value=None)
    mocker.patch.object(fill_links_public_routes, "resolve_fill_link_recaptcha_action", return_value="fill_link_submit")
    mocker.patch.object(fill_links_public_routes, "recaptcha_required_for_fill_link", return_value=False)
    mocker.patch.object(fill_link_database, "now_iso", return_value="ts-submit")

    first = client.post(
        f"/api/fill-links/public/{signed_token}/submit",
        json={"answers": {"full_name": "Ada Lovelace"}, "attemptId": "attempt-1"},
    )
    second = client.post(
        f"/api/fill-links/public/{signed_token}/submit",
        json={"answers": {"full_name": "Ada Lovelace"}, "attemptId": "attempt-1"},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["responseId"] == first.json()["responseId"]
    stored_link = firestore_client.collection(fill_link_database.FILL_LINKS_COLLECTION).document("link-1").get().to_dict()
    assert stored_link["response_count"] == 1
    assert stored_link["status"] == "closed"


def test_public_submit_rejects_missing_required_answers(client: TestClient, mocker) -> None:
    signed_token = build_fill_link_public_token("link-1")
    firestore_client = FakeFirestoreClient()
    firestore_client.collection(template_database.TEMPLATES_COLLECTION).document("tpl-1").seed(
        {
            "user_id": "user-1",
            "metadata": {"name": "Template One"},
            "pdf_bucket_path": "gs://bucket/template-one.pdf",
            "template_bucket_path": "gs://bucket/template-one.json",
            "created_at": "2024-01-01T00:00:00+00:00",
            "updated_at": "2024-01-01T00:00:00+00:00",
        }
    )
    firestore_client.collection(fill_link_database.FILL_LINKS_COLLECTION).document("link-1").seed(
        {
            "user_id": "user-1",
            "template_id": "tpl-1",
            "template_name": "Template One",
            "title": "Template One Intake",
            "public_token": None,
            "status": "active",
            "max_responses": 5,
            "response_count": 0,
            "questions": [
                {"key": "full_name", "label": "Full Name", "type": "text"},
                {"key": "dob", "label": "DOB", "type": "date"},
            ],
            "require_all_fields": True,
            "created_at": "2024-01-01T00:00:00+00:00",
            "updated_at": "2024-01-01T00:00:00+00:00",
            "published_at": "2024-01-01T00:00:00+00:00",
        }
    )

    mocker.patch.object(fill_link_database, "get_firestore_client", return_value=firestore_client)
    mocker.patch.object(template_database, "get_firestore_client", return_value=firestore_client)
    mocker.patch.object(fill_links_public_routes, "check_rate_limit", return_value=True)
    mocker.patch.object(fill_links_public_routes, "resolve_fill_link_submit_rate_limits", return_value=(300, 10, 0))
    mocker.patch.object(fill_links_public_routes, "resolve_client_ip", return_value="198.51.100.20")
    mocker.patch.object(recaptcha_service, "verify_recaptcha_token", return_value=None)
    mocker.patch.object(fill_links_public_routes, "verify_recaptcha_token", return_value=None)
    mocker.patch.object(fill_links_public_routes, "resolve_fill_link_recaptcha_action", return_value="fill_link_submit")
    mocker.patch.object(fill_links_public_routes, "recaptcha_required_for_fill_link", return_value=False)

    response = client.post(
        f"/api/fill-links/public/{signed_token}/submit",
        json={"answers": {"full_name": "Ada Lovelace"}},
    )

    assert response.status_code == 400
    assert "all fields are required" in response.text.lower()
    stored_responses = firestore_client.collection(fill_link_database.FILL_LINK_RESPONSES_COLLECTION).where(
        "link_id",
        "==",
        "link-1",
    ).get()
    assert stored_responses == []


def test_public_get_closed_link_hides_schema_and_specific_closure_reason(client: TestClient, mocker) -> None:
    signed_token = build_fill_link_public_token("link-1")
    firestore_client = FakeFirestoreClient()
    firestore_client.collection(fill_link_database.FILL_LINKS_COLLECTION).document("link-1").seed(
        {
            "user_id": "user-1",
            "template_id": "tpl-1",
            "template_name": "Template One",
            "title": "Template One Intake",
            "public_token": None,
            "status": "closed",
            "closed_reason": "downgrade_retention",
            "max_responses": 5,
            "response_count": 0,
            "questions": [{"key": "ssn", "label": "SSN", "type": "text"}],
            "require_all_fields": True,
            "created_at": "2024-01-01T00:00:00+00:00",
            "updated_at": "2024-01-01T00:00:00+00:00",
            "published_at": "2024-01-01T00:00:00+00:00",
            "closed_at": "2024-01-02T00:00:00+00:00",
        }
    )

    mocker.patch.object(fill_link_database, "get_firestore_client", return_value=firestore_client)
    mocker.patch.object(fill_links_public_routes, "check_rate_limit", return_value=True)
    mocker.patch.object(fill_links_public_routes, "resolve_fill_link_view_rate_limits", return_value=(60, 60, 0))
    mocker.patch.object(fill_links_public_routes, "resolve_client_ip", return_value="198.51.100.20")

    response = client.get(f"/api/fill-links/public/{signed_token}")

    assert response.status_code == 200
    payload = response.json()["link"]
    assert payload["status"] == "closed"
    assert payload["statusMessage"] == "This link is no longer accepting responses."
    assert "closedReason" not in payload
    assert "requireAllFields" not in payload
    assert "questions" not in payload


def test_public_get_invalid_active_link_does_not_persist_close_state(client: TestClient, mocker) -> None:
    signed_token = build_fill_link_public_token("link-1")
    firestore_client = FakeFirestoreClient()
    firestore_client.collection(fill_link_database.FILL_LINKS_COLLECTION).document("link-1").seed(
        {
            "user_id": "user-1",
            "template_id": "tpl-missing",
            "template_name": "Template One",
            "title": "Template One Intake",
            "public_token": None,
            "status": "active",
            "max_responses": 5,
            "response_count": 0,
            "questions": [{"key": "ssn", "label": "SSN", "type": "text"}],
            "require_all_fields": True,
            "created_at": "2024-01-01T00:00:00+00:00",
            "updated_at": "2024-01-01T00:00:00+00:00",
            "published_at": "2024-01-01T00:00:00+00:00",
        }
    )

    mocker.patch.object(fill_link_database, "get_firestore_client", return_value=firestore_client)
    mocker.patch.object(fill_links_public_routes, "check_rate_limit", return_value=True)
    mocker.patch.object(fill_links_public_routes, "resolve_fill_link_view_rate_limits", return_value=(60, 60, 0))
    mocker.patch.object(fill_links_public_routes, "resolve_client_ip", return_value="198.51.100.20")

    response = client.get(f"/api/fill-links/public/{signed_token}")

    assert response.status_code == 200
    payload = response.json()["link"]
    assert payload["status"] == "closed"
    assert payload["statusMessage"] == "This link is no longer accepting responses."
    stored_link = firestore_client.collection(fill_link_database.FILL_LINKS_COLLECTION).document("link-1").get().to_dict()
    assert stored_link["status"] == "active"
    assert stored_link.get("closed_reason") is None


def test_public_download_materializes_saved_template_snapshot(client: TestClient, mocker, tmp_path) -> None:
    signed_token = build_fill_link_public_token("link-1")
    firestore_client = FakeFirestoreClient()
    firestore_client.collection(fill_link_database.FILL_LINKS_COLLECTION).document("link-1").seed(
        {
            "user_id": "user-1",
            "template_id": "tpl-1",
            "template_name": "Template One",
            "title": "Template One Intake",
            "public_token": None,
            "status": "closed",
            "closed_reason": "response_limit",
            "max_responses": 5,
            "response_count": 1,
            "questions": [{"key": "full_name", "label": "Full Name", "type": "text"}],
            "require_all_fields": False,
            "respondent_pdf_download_enabled": True,
            "respondent_pdf_snapshot": {
                "version": 1,
                "sourcePdfPath": "gs://bucket/template-one.pdf",
                "filename": "template-one-response.pdf",
                "fields": [{"name": "full_name", "type": "text", "page": 1, "rect": [1, 2, 4, 6]}],
            },
            "created_at": "2024-01-01T00:00:00+00:00",
            "updated_at": "2024-01-01T00:00:00+00:00",
            "published_at": "2024-01-01T00:00:00+00:00",
            "closed_at": "2024-01-02T00:00:00+00:00",
        }
    )
    firestore_client.collection(fill_link_database.FILL_LINK_RESPONSES_COLLECTION).document("resp-1").seed(
        {
            "link_id": "link-1",
            "user_id": "user-1",
            "scope_type": "template",
            "template_id": "tpl-1",
            "respondent_label": "Ada Lovelace",
            "answers": {"full_name": "Ada Lovelace"},
            "search_text": "ada lovelace",
            "submitted_at": "2024-02-01T00:00:00+00:00",
        }
    )
    output_path = tmp_path / "response.pdf"
    output_path.write_bytes(b"%PDF-1.4\n%stub\n")

    mocker.patch.object(fill_link_database, "get_firestore_client", return_value=firestore_client)
    mocker.patch.object(fill_links_public_routes, "check_rate_limit", return_value=True)
    mocker.patch.object(fill_links_public_routes, "resolve_fill_link_download_rate_limits", return_value=(300, 10, 0))
    mocker.patch.object(fill_links_public_routes, "resolve_client_ip", return_value="198.51.100.20")
    materialize_mock = mocker.patch.object(
        fill_links_public_routes,
        "materialize_fill_link_response_download",
        return_value=(output_path, [output_path], "template-one-response.pdf"),
    )

    response = client.get(f"/api/fill-links/public/{signed_token}/responses/resp-1/download")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert "template-one-response.pdf" in response.headers["content-disposition"]
    materialize_mock.assert_called_once_with(
        {
            "version": 1,
            "sourcePdfPath": "gs://bucket/template-one.pdf",
            "filename": "template-one-response.pdf",
            "fields": [{"name": "full_name", "type": "text", "page": 1, "rect": [1, 2, 4, 6]}],
        },
        answers={"full_name": "Ada Lovelace"},
    )


def test_public_submit_returns_signing_handoff_when_template_requires_signature(client: TestClient, mocker, tmp_path) -> None:
    signed_token = build_fill_link_public_token("link-1")
    firestore_client = FakeFirestoreClient()
    firestore_client.collection(template_database.TEMPLATES_COLLECTION).document("tpl-1").seed(
        {
            "user_id": "user-1",
            "metadata": {"name": "Template One"},
            "pdf_bucket_path": "gs://bucket/template-one.pdf",
            "template_bucket_path": "gs://bucket/template-one.json",
            "created_at": "2024-01-01T00:00:00+00:00",
            "updated_at": "2024-01-01T00:00:00+00:00",
        }
    )
    firestore_client.collection(fill_link_database.FILL_LINKS_COLLECTION).document("link-1").seed(
        {
            "user_id": "user-1",
            "template_id": "tpl-1",
            "template_name": "Template One",
            "title": "Template One Intake",
            "public_token": None,
            "status": "active",
            "max_responses": 5,
            "response_count": 0,
            "questions": [
                {"key": "full_name", "label": "Full Name", "type": "text", "visible": True},
                {"key": "email", "label": "Email", "type": "email", "visible": True},
            ],
            "require_all_fields": False,
            "signing_config": {
                "enabled": True,
                "signature_mode": "consumer",
                "document_category": "client_intake_form",
                "document_category_label": "Client intake form",
                "manual_fallback_enabled": True,
                "signer_name_question_key": "full_name",
                "signer_email_question_key": "email",
            },
            "respondent_pdf_download_enabled": False,
            "respondent_pdf_snapshot": {
                "version": 1,
                "sourcePdfPath": "gs://bucket/template-one.pdf",
                "filename": "template-one-response.pdf",
                "fields": [
                    {"name": "Signer", "type": "signature", "page": 1, "rect": {"x": 1, "y": 2, "width": 3, "height": 1}},
                    {"name": "full_name", "type": "text", "page": 1, "rect": {"x": 1, "y": 3, "width": 3, "height": 1}},
                ],
            },
            "created_at": "2024-01-01T00:00:00+00:00",
            "updated_at": "2024-01-01T00:00:00+00:00",
            "published_at": "2024-01-01T00:00:00+00:00",
        }
    )
    output_path = tmp_path / "response-signing.pdf"
    output_path.write_bytes(b"%PDF-1.4\n%stub\n")

    mocker.patch.object(fill_link_database, "get_firestore_client", return_value=firestore_client)
    mocker.patch.object(template_database, "get_firestore_client", return_value=firestore_client)
    mocker.patch.object(fill_links_public_routes, "check_rate_limit", return_value=True)
    mocker.patch.object(fill_links_public_routes, "resolve_fill_link_submit_rate_limits", return_value=(300, 10, 0))
    mocker.patch.object(fill_links_public_routes, "resolve_client_ip", return_value="198.51.100.20")
    mocker.patch.object(recaptcha_service, "verify_recaptcha_token", return_value=None)
    mocker.patch.object(fill_links_public_routes, "verify_recaptcha_token", return_value=None)
    mocker.patch.object(fill_links_public_routes, "resolve_fill_link_recaptcha_action", return_value="fill_link_submit")
    mocker.patch.object(fill_links_public_routes, "recaptcha_required_for_fill_link", return_value=False)
    mocker.patch.object(
        fill_links_public_routes,
        "materialize_fill_link_response_download",
        return_value=(output_path, [output_path], "template-one-response.pdf"),
    )
    mocker.patch.object(
        fill_links_public_routes,
        "ensure_fill_link_response_signing_request",
        return_value=mocker.Mock(id="sign-1", status="sent"),
    )
    mocker.patch.object(fill_links_public_routes, "build_signing_public_path", return_value="/sign/public-token")

    response = client.post(
        f"/api/fill-links/public/{signed_token}/submit",
        json={"answers": {"full_name": "Ada Lovelace", "email": "ada@example.com"}},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["responseDownloadAvailable"] is False
    assert payload["signing"] == {
        "enabled": True,
        "available": True,
        "requestId": "sign-1",
        "status": "sent",
        "publicPath": "/sign/public-token",
    }
    stored_responses = firestore_client.collection(fill_link_database.FILL_LINK_RESPONSES_COLLECTION).where(
        "link_id",
        "==",
        "link-1",
    ).get()
    assert len(stored_responses) == 1


def test_public_retry_signing_reuses_stored_response_snapshot(client: TestClient, mocker, tmp_path) -> None:
    signed_token = build_fill_link_public_token("link-1")
    firestore_client = FakeFirestoreClient()
    firestore_client.collection(fill_link_database.FILL_LINKS_COLLECTION).document("link-1").seed(
        {
            "user_id": "user-1",
            "template_id": "tpl-1",
            "template_name": "Template One",
            "title": "Template One Intake",
            "public_token": None,
            "status": "active",
            "max_responses": 5,
            "response_count": 1,
            "questions": [
                {"key": "full_name", "label": "Full Name", "type": "text", "visible": True},
                {"key": "email", "label": "Email", "type": "email", "visible": True},
            ],
            "require_all_fields": False,
            "signing_config": {
                "enabled": True,
                "signature_mode": "business",
                "document_category": "ordinary_business_form",
                "document_category_label": "Ordinary business form",
                "manual_fallback_enabled": True,
                "signer_name_question_key": "full_name",
                "signer_email_question_key": "email",
            },
            "respondent_pdf_snapshot": {
                "version": 1,
                "sourcePdfPath": "gs://bucket/template-one.pdf",
                "filename": "template-one-response.pdf",
                "fields": [
                    {"name": "Signer", "type": "signature", "page": 1, "rect": {"x": 1, "y": 2, "width": 3, "height": 1}},
                ],
            },
        }
    )
    firestore_client.collection(fill_link_database.FILL_LINK_RESPONSES_COLLECTION).document("resp-1").seed(
        {
            "id": "resp-1",
            "link_id": "link-1",
            "user_id": "user-1",
            "respondent_label": "Ada Lovelace",
            "answers": {"full_name": "Ada Lovelace", "email": "ada@example.com"},
            "respondent_pdf_snapshot": {
                "version": 1,
                "sourcePdfPath": "gs://bucket/template-one.pdf",
                "filename": "template-one-response.pdf",
                "fields": [
                    {"name": "Signer", "type": "signature", "page": 1, "rect": {"x": 1, "y": 2, "width": 3, "height": 1}},
                ],
            },
            "submitted_at": "2024-01-01T00:00:00+00:00",
        }
    )
    output_path = tmp_path / "retry-response-signing.pdf"
    output_path.write_bytes(b"%PDF-1.4\n%retry\n")

    mocker.patch.object(fill_link_database, "get_firestore_client", return_value=firestore_client)
    mocker.patch.object(fill_links_public_routes, "check_rate_limit", return_value=True)
    mocker.patch.object(fill_links_public_routes, "resolve_fill_link_submit_rate_limits", return_value=(300, 10, 0))
    mocker.patch.object(fill_links_public_routes, "resolve_client_ip", return_value="198.51.100.20")
    mocker.patch.object(
        fill_links_public_routes,
        "materialize_fill_link_response_download",
        return_value=(output_path, [output_path], "template-one-response.pdf"),
    )
    mocker.patch.object(
        fill_links_public_routes,
        "ensure_fill_link_response_signing_request",
        return_value=mocker.Mock(id="sign-retry-1", status="sent"),
    )
    mocker.patch.object(fill_links_public_routes, "build_signing_public_path", return_value="/sign/retry-token")

    response = client.post(
        f"/api/fill-links/public/{signed_token}/retry-signing",
        json={"responseId": "resp-1"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["responseId"] == "resp-1"
    assert payload["signing"] == {
        "enabled": True,
        "available": True,
        "requestId": "sign-retry-1",
        "status": "sent",
        "publicPath": "/sign/retry-token",
    }
