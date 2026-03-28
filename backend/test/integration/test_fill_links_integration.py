"""Integration coverage for Fill By Link public submission behavior."""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

import backend.main as main
import backend.firebaseDB.signing_database as signing_database
import backend.firebaseDB.fill_link_database as fill_link_database
import backend.firebaseDB.template_database as template_database
import backend.firebaseDB.user_database as user_database
import backend.api.routes.fill_links_public as fill_links_public_routes
import backend.services.recaptcha_service as recaptcha_service
from backend.services.fill_link_signing_service import FillLinkSigningRequestMaterialization
from backend.services.fill_links_service import build_fill_link_public_token
from backend.test.integration.signing_test_support import InMemorySigningStorage, patch_signing_artifact_storage
from backend.test.unit.firebase._fakes import FakeFirestoreClient


@pytest.fixture
def client() -> TestClient:
    return TestClient(main.app)


@pytest.fixture(autouse=True)
def _no_transaction_wrapper(mocker):
    mocker.patch.object(fill_link_database.firebase_firestore, "transactional", side_effect=lambda fn: fn)


def _seed_owner_credit_profile(
    firestore_client: FakeFirestoreClient,
    *,
    user_id: str = "user-1",
    email: str = "owner@example.com",
    display_name: str = "Owner Example",
    role: str = user_database.ROLE_BASE,
    credits: int = 7,
) -> None:
    firestore_client.collection(user_database.USERS_COLLECTION).document(user_id).seed(
        {
            "email": email,
            "displayName": display_name,
            user_database.ROLE_FIELD: role,
            user_database.OPENAI_CREDITS_FIELD: credits,
            user_database.OPENAI_CREDITS_REFILL_FIELD: 0,
            "created_at": "2026-03-28T00:00:00+00:00",
            "updated_at": "2026-03-28T00:00:00+00:00",
        }
    )


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
    mocker.patch.object(fill_links_public_routes, "persist_consumer_disclosure_artifact", return_value=None)
    provenance_mock = mocker.patch.object(fill_links_public_routes, "record_signing_provenance_event", return_value=None)
    mocker.patch.object(
        fill_links_public_routes,
        "ensure_fill_link_response_signing_request",
        return_value=FillLinkSigningRequestMaterialization(
            record=SimpleNamespace(
                id="sign-1",
                status="sent",
                source_type="fill_link_response",
                source_id="resp-1",
                source_link_id="link-1",
                created_at="2026-03-28T00:00:00+00:00",
                sent_at="2026-03-28T00:01:00+00:00",
                expires_at="2026-04-27T00:01:00+00:00",
                public_link_version=1,
                invite_last_attempt_at=None,
                invite_delivery_status=None,
                signer_email="ada@example.com",
            ),
            created_now=True,
            sent_now=True,
        ),
    )
    mocker.patch.object(fill_links_public_routes, "get_user_profile", return_value=mocker.Mock(email="owner@example.com"))
    mocker.patch.object(
        fill_links_public_routes,
        "deliver_signing_invite_for_request",
        return_value=SimpleNamespace(
            record=SimpleNamespace(
                id="sign-1",
                status="sent",
                invite_last_attempt_at="2099-01-01T00:05:00+00:00",
                invite_delivery_status="sent",
                signer_email="ada@example.com",
            ),
            delivery=SimpleNamespace(
                delivery_status="sent",
                provider=None,
                invite_message_id=None,
                error_code=None,
                error_message=None,
                sent_at=None,
                attempted_at=None,
            ),
        ),
    )

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
        "deliveryStatus": "sent",
        "emailHint": "a***@example.com",
        "canResend": False,
        "resendAvailableAt": "2099-01-01T00:10:00+00:00",
        "message": "We emailed the signing link for this response.",
        "errorMessage": None,
    }
    stored_responses = firestore_client.collection(fill_link_database.FILL_LINK_RESPONSES_COLLECTION).where(
        "link_id",
        "==",
        "link-1",
    ).get()
    assert len(stored_responses) == 1
    assert [call.kwargs["event_type"] for call in provenance_mock.call_args_list] == [
        "request_created",
        "request_sent",
        "invite_sent",
    ]


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
    mocker.patch.object(fill_links_public_routes, "persist_consumer_disclosure_artifact", return_value=None)
    mocker.patch.object(fill_links_public_routes, "record_signing_provenance_event", return_value=None)
    mocker.patch.object(
        fill_links_public_routes,
        "ensure_fill_link_response_signing_request",
        return_value=FillLinkSigningRequestMaterialization(
            record=SimpleNamespace(
                id="sign-retry-1",
                status="sent",
                invite_last_attempt_at=None,
                invite_delivery_status=None,
                signer_email="ada@example.com",
            ),
            created_now=False,
            sent_now=False,
        ),
    )
    mocker.patch.object(fill_links_public_routes, "get_user_profile", return_value=mocker.Mock(email="owner@example.com"))
    mocker.patch.object(
        fill_links_public_routes,
        "deliver_signing_invite_for_request",
        return_value=SimpleNamespace(
            record=SimpleNamespace(
                id="sign-retry-1",
                status="sent",
                invite_last_attempt_at="2099-01-01T00:05:00+00:00",
                invite_delivery_status="sent",
                signer_email="ada@example.com",
            ),
            delivery=SimpleNamespace(
                delivery_status="sent",
                provider=None,
                invite_message_id=None,
                error_code=None,
                error_message=None,
                sent_at=None,
                attempted_at=None,
            ),
        ),
    )

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
        "deliveryStatus": "sent",
        "emailHint": "a***@example.com",
        "canResend": False,
        "resendAvailableAt": "2099-01-01T00:10:00+00:00",
        "message": "We emailed the signing link for this response.",
        "errorMessage": None,
    }


def test_public_submit_and_retry_signing_preserve_owner_credits_and_enforce_document_limit(
    client: TestClient,
    mocker,
    tmp_path,
    monkeypatch,
) -> None:
    signed_token = build_fill_link_public_token("link-1")
    firestore_client = FakeFirestoreClient()
    storage = InMemorySigningStorage()
    monkeypatch.setenv("SANDBOX_SIGNING_REQUESTS_PER_DOCUMENT_MAX_BASE", "1")

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
                "signature_mode": "business",
                "document_category": "ordinary_business_form",
                "document_category_label": "Ordinary business form",
                "manual_fallback_enabled": True,
                "signer_name_question_key": "full_name",
                "signer_email_question_key": "email",
                "esign_eligibility_confirmed": True,
                "esign_eligibility_confirmed_at": "2026-03-28T00:00:00+00:00",
                "esign_eligibility_confirmed_source": "fill_link_publish",
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
    _seed_owner_credit_profile(firestore_client, user_id="user-1", credits=7)
    materialize_call_count = {"value": 0}

    for module in (fill_link_database, template_database, signing_database, user_database):
        mocker.patch.object(module, "get_firestore_client", return_value=firestore_client)
    patch_signing_artifact_storage(mocker, storage)
    mocker.patch.object(fill_links_public_routes, "check_rate_limit", return_value=True)
    mocker.patch.object(fill_links_public_routes, "resolve_fill_link_submit_rate_limits", return_value=(300, 10, 0))
    mocker.patch.object(fill_links_public_routes, "resolve_client_ip", return_value="198.51.100.20")
    mocker.patch.object(recaptcha_service, "verify_recaptcha_token", return_value=None)
    mocker.patch.object(fill_links_public_routes, "verify_recaptcha_token", return_value=None)
    mocker.patch.object(fill_links_public_routes, "resolve_fill_link_recaptcha_action", return_value="fill_link_submit")
    mocker.patch.object(fill_links_public_routes, "recaptcha_required_for_fill_link", return_value=False)
    def _materialize_response_download(*_args, **_kwargs):
        materialize_call_count["value"] += 1
        output_path = tmp_path / f"response-signing-limit-{materialize_call_count['value']}.pdf"
        output_path.write_bytes(b"%PDF-1.4\n%limit\n")
        return output_path, [output_path], "template-one-response.pdf"

    mocker.patch.object(
        fill_links_public_routes,
        "materialize_fill_link_response_download",
        side_effect=_materialize_response_download,
    )
    mocker.patch.object(fill_links_public_routes, "persist_consumer_disclosure_artifact", side_effect=lambda record: record)
    mocker.patch.object(fill_links_public_routes, "record_signing_provenance_event", return_value=None)

    def _invite_attempt(record, **_kwargs):
        invited_record = replace(
            record,
            invite_last_attempt_at="2099-01-01T00:05:00+00:00",
            invite_delivery_status="sent",
            invite_sent_at="2099-01-01T00:05:00+00:00",
            invite_message_id="gmail-message-1",
        )
        return SimpleNamespace(
            record=invited_record,
            delivery=SimpleNamespace(
                delivery_status="sent",
                provider="gmail_api",
                invite_message_id="gmail-message-1",
                error_code=None,
                error_message=None,
                sent_at="2099-01-01T00:05:00+00:00",
                attempted_at="2099-01-01T00:05:00+00:00",
            ),
        )

    mocker.patch.object(fill_links_public_routes, "deliver_signing_invite_for_request", side_effect=_invite_attempt)

    before_profile = user_database.get_user_profile("user-1")
    assert before_profile is not None
    assert before_profile.openai_credits_remaining == 7
    assert before_profile.openai_credits_available == 7

    submit_response = client.post(
        f"/api/fill-links/public/{signed_token}/submit",
        json={"answers": {"full_name": "Ada Lovelace", "email": "ada@example.com"}},
    )

    assert submit_response.status_code == 200
    submit_payload = submit_response.json()
    assert submit_payload["success"] is True
    assert submit_payload["signing"]["available"] is True
    request_id = submit_payload["signing"]["requestId"]
    assert request_id

    after_submit_profile = user_database.get_user_profile("user-1")
    assert after_submit_profile is not None
    assert after_submit_profile.openai_credits_remaining == 7
    assert after_submit_profile.openai_credits_available == 7

    invalidated = signing_database.invalidate_signing_request(
        request_id,
        "user-1",
        reason="Test revoke after send",
        client=firestore_client,
    )
    assert invalidated is not None
    assert invalidated.status == "invalidated"

    retry_response = client.post(
        f"/api/fill-links/public/{signed_token}/retry-signing",
        json={"responseId": submit_payload["responseId"]},
    )

    assert retry_response.status_code == 200
    retry_payload = retry_response.json()
    assert retry_payload["success"] is False
    assert retry_payload["signing"]["available"] is False
    assert retry_payload["signing"]["requestId"] is None
    assert retry_payload["signing"]["errorMessage"] == (
        "This submitted record has already reached the sender's signature request limit for this document. "
        "Contact the sender for an offline copy."
    )

    after_retry_profile = user_database.get_user_profile("user-1")
    assert after_retry_profile is not None
    assert after_retry_profile.openai_credits_remaining == 7
    assert after_retry_profile.openai_credits_available == 7

    stored_user = firestore_client.collection(user_database.USERS_COLLECTION).document("user-1").get().to_dict()
    assert stored_user[user_database.OPENAI_CREDITS_FIELD] == 7
    assert len(
        firestore_client.collection(signing_database.SIGNING_REQUESTS_COLLECTION).where("user_id", "==", "user-1").get()
    ) == 1
