"""Integration tests for the signing envelope (multi-signer) endpoints.

These tests exercise the real FastAPI route handlers with a FakeFirestoreClient
and InMemorySigningStorage, catching runtime errors that mocked unit tests miss.
"""

from __future__ import annotations

from io import BytesIO

from fastapi.testclient import TestClient
import pytest
from pypdf import PdfWriter

import backend.main as main
import backend.api.routes.signing as signing_routes
import backend.api.routes.signing_public as signing_public_routes
import backend.firebaseDB.signing_database as signing_database
from backend.services.signing_service import sha256_hex_for_bytes
from backend.services.pdf_export_service import build_immutable_signing_source_pdf
from backend.test.integration.signing_test_support import (
    AUTH_HEADERS,
    InMemorySigningStorage,
    bootstrap_and_verify_public_signing_session as _bootstrap_and_verify_public_signing_session,
    mock_signing_verification_delivery,
    patch_signing_artifact_storage,
    patch_signing_authenticated_owner,
    signing_user as _signing_user,
)
from backend.test.unit.firebase._fakes import FakeFirestoreClient


@pytest.fixture
def client() -> TestClient:
    return TestClient(main.app)


@pytest.fixture(autouse=True)
def allow_public_signing_rate_limits(mocker) -> None:
    mocker.patch.object(signing_public_routes, "_check_public_rate_limits", return_value=True)


def _pdf_bytes(*, width: float = 200, height: float = 200) -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=width, height=height)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def _immutable_source_pdf_sha256(source_pdf_bytes: bytes) -> str:
    return sha256_hex_for_bytes(build_immutable_signing_source_pdf(source_pdf_bytes))


def _envelope_create_payload(source_pdf_bytes: bytes, **overrides) -> dict:
    payload = {
        "title": "Multi-Signer Envelope Test",
        "mode": "sign",
        "signatureMode": "business",
        "signingMode": "sequential",
        "sourceType": "workspace",
        "sourceId": "form-alpha",
        "sourceDocumentName": "Multi-Sign Packet",
        "sourceTemplateId": "form-alpha",
        "sourceTemplateName": "Multi-Sign Template",
        "sourcePdfSha256": _immutable_source_pdf_sha256(source_pdf_bytes),
        "documentCategory": "ordinary_business_form",
        "esignEligibilityConfirmed": True,
        "manualFallbackEnabled": True,
        "anchors": [
            {
                "kind": "signature",
                "page": 1,
                "rect": {"x": 100, "y": 400, "width": 180, "height": 36},
                "assignedSignerOrder": 1,
            },
            {
                "kind": "signature",
                "page": 1,
                "rect": {"x": 100, "y": 500, "width": 180, "height": 36},
                "assignedSignerOrder": 2,
            },
        ],
        "recipients": [
            {"name": "Alice First", "email": "alice@example.com", "order": 1},
            {"name": "Bob Second", "email": "bob@example.com", "order": 2},
        ],
    }
    payload.update(overrides)
    return payload


def _setup_env(mocker, monkeypatch):
    """Wire up FakeFirestore, auth, and storage for envelope tests."""
    firestore_client = FakeFirestoreClient()
    request_user = _signing_user()
    storage = InMemorySigningStorage()

    monkeypatch.setenv("SANDBOX_SIGNING_REQUESTS_MONTHLY_MAX_BASE", "100")
    mocker.patch.object(signing_database, "get_firestore_client", return_value=firestore_client)
    patch_signing_authenticated_owner(mocker, request_user)
    patch_signing_artifact_storage(mocker, storage, patch_delete=True)

    return firestore_client, request_user, storage


def _complete_public_envelope_signer(
    client: TestClient,
    request_payload: dict,
    *,
    adopted_name: str,
    browser_name: str,
) -> dict:
    public_token = request_payload["publicToken"]
    browser_headers = {"User-Agent": browser_name}
    session_token = _bootstrap_and_verify_public_signing_session(
        client,
        public_token,
        browser_headers=browser_headers,
    )

    review_response = client.post(
        f"/api/signing/public/{public_token}/review",
        headers={"X-Signing-Session": session_token, **browser_headers},
        json={"reviewConfirmed": True},
    )
    assert review_response.status_code == 200, review_response.text

    adopt_response = client.post(
        f"/api/signing/public/{public_token}/adopt-signature",
        headers={"X-Signing-Session": session_token, **browser_headers},
        json={"signatureType": "typed", "adoptedName": adopted_name},
    )
    assert adopt_response.status_code == 200, adopt_response.text

    complete_response = client.post(
        f"/api/signing/public/{public_token}/complete",
        headers={"X-Signing-Session": session_token, **browser_headers},
        json={"intentConfirmed": True},
    )
    assert complete_response.status_code == 200, complete_response.text
    return complete_response.json()["request"]


# ---------------------------------------------------------------------------
# Envelope create
# ---------------------------------------------------------------------------


def test_envelope_create_returns_envelope_and_child_requests(
    client: TestClient, mocker, monkeypatch
) -> None:
    _setup_env(mocker, monkeypatch)
    source_pdf_bytes = _pdf_bytes()

    response = client.post(
        "/api/signing/envelopes",
        headers=AUTH_HEADERS,
        json=_envelope_create_payload(source_pdf_bytes),
    )

    assert response.status_code == 201, response.text
    body = response.json()
    envelope = body["envelope"]
    requests = body["requests"]

    assert envelope["signingMode"] == "sequential"
    assert envelope["signerCount"] == 2
    assert envelope["completedSignerCount"] == 0
    assert envelope["status"] == "draft"

    assert len(requests) == 2
    assert requests[0]["signerEmail"] == "alice@example.com"
    assert requests[0]["signerOrder"] == 1
    assert requests[0]["envelopeId"] == envelope["id"]
    assert requests[1]["signerEmail"] == "bob@example.com"
    assert requests[1]["signerOrder"] == 2
    assert requests[1]["envelopeId"] == envelope["id"]


def test_envelope_create_parallel(
    client: TestClient, mocker, monkeypatch
) -> None:
    _setup_env(mocker, monkeypatch)
    source_pdf_bytes = _pdf_bytes()

    response = client.post(
        "/api/signing/envelopes",
        headers=AUTH_HEADERS,
        json=_envelope_create_payload(source_pdf_bytes, signingMode="parallel"),
    )

    assert response.status_code == 201
    assert response.json()["envelope"]["signingMode"] == "parallel"


def test_envelope_create_rejects_empty_recipients(
    client: TestClient, mocker, monkeypatch
) -> None:
    _setup_env(mocker, monkeypatch)
    source_pdf_bytes = _pdf_bytes()

    response = client.post(
        "/api/signing/envelopes",
        headers=AUTH_HEADERS,
        json=_envelope_create_payload(source_pdf_bytes, recipients=[]),
    )

    assert response.status_code == 422  # Pydantic min_length=1 validation


def test_envelope_create_rejects_missing_sha256(
    client: TestClient, mocker, monkeypatch
) -> None:
    _setup_env(mocker, monkeypatch)
    source_pdf_bytes = _pdf_bytes()

    response = client.post(
        "/api/signing/envelopes",
        headers=AUTH_HEADERS,
        json=_envelope_create_payload(source_pdf_bytes, sourcePdfSha256=None),
    )

    assert response.status_code == 400


def test_envelope_create_rejects_duplicate_recipient_orders(
    client: TestClient, mocker, monkeypatch
) -> None:
    _setup_env(mocker, monkeypatch)
    source_pdf_bytes = _pdf_bytes()

    response = client.post(
        "/api/signing/envelopes",
        headers=AUTH_HEADERS,
        json=_envelope_create_payload(
            source_pdf_bytes,
            recipients=[
                {"name": "Alice First", "email": "alice@example.com", "order": 1},
                {"name": "Bob Second", "email": "bob@example.com", "order": 1},
            ],
        ),
    )

    assert response.status_code == 400
    assert "unique order values" in response.json()["detail"]


def test_envelope_create_rejects_nonconsecutive_recipient_orders(
    client: TestClient, mocker, monkeypatch
) -> None:
    _setup_env(mocker, monkeypatch)
    source_pdf_bytes = _pdf_bytes()

    response = client.post(
        "/api/signing/envelopes",
        headers=AUTH_HEADERS,
        json=_envelope_create_payload(
            source_pdf_bytes,
            recipients=[
                {"name": "Alice First", "email": "alice@example.com", "order": 1},
                {"name": "Bob Second", "email": "bob@example.com", "order": 3},
            ],
        ),
    )

    assert response.status_code == 400
    assert "consecutive starting at 1" in response.json()["detail"]


# ---------------------------------------------------------------------------
# Envelope send
# ---------------------------------------------------------------------------


def test_envelope_send_transitions_to_sent(
    client: TestClient, mocker, monkeypatch
) -> None:
    _setup_env(mocker, monkeypatch)
    source_pdf_bytes = _pdf_bytes()

    create_response = client.post(
        "/api/signing/envelopes",
        headers=AUTH_HEADERS,
        json=_envelope_create_payload(source_pdf_bytes),
    )
    assert create_response.status_code == 201
    envelope_id = create_response.json()["envelope"]["id"]

    send_response = client.post(
        f"/api/signing/envelopes/{envelope_id}/send",
        headers=AUTH_HEADERS,
        files={"pdf": ("packet.pdf", source_pdf_bytes, "application/pdf")},
        data={
            "sourcePdfSha256": _immutable_source_pdf_sha256(source_pdf_bytes),
        },
    )

    assert send_response.status_code == 200, send_response.text
    body = send_response.json()
    assert body["envelope"]["status"] == "sent"

    sent_requests = body["requests"]
    # Sequential: all child requests are frozen and sent, but only signer 1 is active.
    first = next(r for r in sent_requests if r["signerOrder"] == 1)
    second = next(r for r in sent_requests if r["signerOrder"] == 2)
    assert first["status"] == "sent"
    assert first["turnActivatedAt"] is not None
    assert first["inviteDeliveryStatus"] in {"sent", "skipped", "failed"}
    assert second["status"] == "sent"
    assert second["turnActivatedAt"] is None
    assert second["inviteDeliveryStatus"] == "queued"


def test_envelope_send_parallel_sends_all(
    client: TestClient, mocker, monkeypatch
) -> None:
    _setup_env(mocker, monkeypatch)
    source_pdf_bytes = _pdf_bytes()

    create_response = client.post(
        "/api/signing/envelopes",
        headers=AUTH_HEADERS,
        json=_envelope_create_payload(source_pdf_bytes, signingMode="parallel"),
    )
    assert create_response.status_code == 201
    envelope_id = create_response.json()["envelope"]["id"]

    send_response = client.post(
        f"/api/signing/envelopes/{envelope_id}/send",
        headers=AUTH_HEADERS,
        files={"pdf": ("packet.pdf", source_pdf_bytes, "application/pdf")},
        data={
            "sourcePdfSha256": _immutable_source_pdf_sha256(source_pdf_bytes),
        },
    )

    assert send_response.status_code == 200, send_response.text
    body = send_response.json()
    assert body["envelope"]["status"] == "sent"

    # Parallel: all signers should be sent
    for req in body["requests"]:
        assert req["status"] == "sent", f"Signer {req['signerEmail']} should be sent"


def test_envelope_send_hash_mismatch_invalidates_drafts(
    client: TestClient, mocker, monkeypatch
) -> None:
    firestore_client, _request_user, storage = _setup_env(mocker, monkeypatch)
    source_pdf_bytes = _pdf_bytes()
    changed_pdf_bytes = _pdf_bytes(width=320, height=320)

    create_response = client.post(
        "/api/signing/envelopes",
        headers=AUTH_HEADERS,
        json=_envelope_create_payload(source_pdf_bytes),
    )
    assert create_response.status_code == 201
    envelope_id = create_response.json()["envelope"]["id"]

    send_response = client.post(
        f"/api/signing/envelopes/{envelope_id}/send",
        headers=AUTH_HEADERS,
        files={"pdf": ("packet.pdf", changed_pdf_bytes, "application/pdf")},
        data={
            "sourcePdfSha256": _immutable_source_pdf_sha256(changed_pdf_bytes),
        },
    )

    assert send_response.status_code == 409, send_response.text
    assert "source pdf changed" in send_response.json()["detail"].lower()

    envelope = signing_database.get_signing_envelope(envelope_id, client=firestore_client)
    assert envelope is not None
    assert envelope.status == "invalidated"

    requests = signing_database.list_signing_requests_for_envelope(envelope_id, client=firestore_client)
    assert {request.status for request in requests} == {"invalidated"}
    assert storage.objects == {}


def test_envelope_send_quota_failure_rolls_back_all_child_requests(
    client: TestClient, mocker, monkeypatch
) -> None:
    firestore_client, _request_user, storage = _setup_env(mocker, monkeypatch)
    monkeypatch.setenv("SANDBOX_SIGNING_REQUESTS_MONTHLY_MAX_BASE", "1")
    source_pdf_bytes = _pdf_bytes()

    create_response = client.post(
        "/api/signing/envelopes",
        headers=AUTH_HEADERS,
        json=_envelope_create_payload(source_pdf_bytes, signingMode="parallel"),
    )
    assert create_response.status_code == 201
    envelope_id = create_response.json()["envelope"]["id"]

    send_response = client.post(
        f"/api/signing/envelopes/{envelope_id}/send",
        headers=AUTH_HEADERS,
        files={"pdf": ("packet.pdf", source_pdf_bytes, "application/pdf")},
        data={
            "sourcePdfSha256": _immutable_source_pdf_sha256(source_pdf_bytes),
        },
    )

    assert send_response.status_code == 403, send_response.text
    assert "sent signing request limit" in send_response.json()["detail"]

    envelope = signing_database.get_signing_envelope(envelope_id, client=firestore_client)
    assert envelope is not None
    assert envelope.status == "draft"
    assert envelope.source_pdf_bucket_path is None

    requests = signing_database.list_signing_requests_for_envelope(envelope_id, client=firestore_client)
    assert {request.status for request in requests} == {"draft"}
    assert all(request.sent_at is None for request in requests)
    assert all(request.quota_month_key is None for request in requests)
    assert all(request.source_pdf_bucket_path is None for request in requests)
    assert storage.objects == {}


def test_parallel_envelope_completion_generates_artifacts_for_every_signer(
    client: TestClient, mocker, monkeypatch
) -> None:
    _setup_env(mocker, monkeypatch)
    mock_signing_verification_delivery(mocker)
    source_pdf_bytes = _pdf_bytes()

    create_response = client.post(
        "/api/signing/envelopes",
        headers=AUTH_HEADERS,
        json=_envelope_create_payload(source_pdf_bytes, signingMode="parallel"),
    )
    assert create_response.status_code == 201, create_response.text
    envelope_id = create_response.json()["envelope"]["id"]

    send_response = client.post(
        f"/api/signing/envelopes/{envelope_id}/send",
        headers=AUTH_HEADERS,
        files={"pdf": ("packet.pdf", source_pdf_bytes, "application/pdf")},
        data={
            "sourcePdfSha256": _immutable_source_pdf_sha256(source_pdf_bytes),
        },
    )
    assert send_response.status_code == 200, send_response.text
    sent_requests = send_response.json()["requests"]
    alice_request = next(request for request in sent_requests if request["signerOrder"] == 1)
    bob_request = next(request for request in sent_requests if request["signerOrder"] == 2)

    alice_complete = _complete_public_envelope_signer(
        client,
        alice_request,
        adopted_name="Alice Envelope",
        browser_name="integration-envelope-alice/1.0",
    )
    assert alice_complete["status"] == "completed"
    assert alice_complete["artifacts"]["signedPdf"]["available"] is False
    assert alice_complete["artifacts"]["auditReceipt"]["available"] is False
    assert alice_complete["envelope"]["signerCount"] == 2
    assert alice_complete["envelope"]["completedSignerCount"] == 1

    bob_complete = _complete_public_envelope_signer(
        client,
        bob_request,
        adopted_name="Bob Envelope",
        browser_name="integration-envelope-bob/1.0",
    )
    assert bob_complete["status"] == "completed"
    assert bob_complete["artifacts"]["signedPdf"]["available"] is True
    assert bob_complete["artifacts"]["auditReceipt"]["available"] is True
    assert bob_complete["validationPath"].startswith("/verify-signing/")
    assert bob_complete["envelope"]["signerCount"] == 2
    assert bob_complete["envelope"]["completedSignerCount"] == 2

    for request_payload in (alice_request, bob_request):
        request_id = request_payload["id"]
        public_token = request_payload["publicToken"]

        detail_response = client.get(f"/api/signing/requests/{request_id}", headers=AUTH_HEADERS)
        assert detail_response.status_code == 200, detail_response.text
        detail_payload = detail_response.json()["request"]
        assert detail_payload["artifacts"]["signedPdf"]["available"] is True
        assert detail_payload["artifacts"]["auditManifest"]["available"] is True
        assert detail_payload["artifacts"]["auditReceipt"]["available"] is True
        assert detail_payload["artifacts"]["disputePackage"]["available"] is True
        assert detail_payload["validationPath"].startswith("/verify-signing/")

        preview_response = client.get(f"/api/signing/public/{public_token}")
        assert preview_response.status_code == 200, preview_response.text
        preview_payload = preview_response.json()["request"]
        assert preview_payload["artifacts"]["signedPdf"]["available"] is True
        assert preview_payload["artifacts"]["auditReceipt"]["available"] is True

        validation_token = detail_payload["validationPath"].split("/verify-signing/", 1)[-1]
        validation_response = client.get(f"/api/signing/public/validation/{validation_token}")
        assert validation_response.status_code == 200, validation_response.text
        validation_payload = validation_response.json()["validation"]
        assert validation_payload["available"] is True
        assert validation_payload["valid"] is True

    signed_download = client.get(
        f"/api/signing/requests/{alice_request['id']}/artifacts/signed_pdf",
        headers=AUTH_HEADERS,
    )
    assert signed_download.status_code == 200
    assert signed_download.headers["content-type"].startswith("application/pdf")

    audit_receipt_download = client.get(
        f"/api/signing/requests/{alice_request['id']}/artifacts/audit_receipt",
        headers=AUTH_HEADERS,
    )
    assert audit_receipt_download.status_code == 200
    assert audit_receipt_download.headers["content-type"].startswith("application/pdf")

    dispute_package_download = client.get(
        f"/api/signing/requests/{alice_request['id']}/artifacts/dispute_package",
        headers=AUTH_HEADERS,
    )
    assert dispute_package_download.status_code == 200
    assert dispute_package_download.headers["content-type"].startswith("application/zip")


def test_sequential_envelope_only_activates_next_signer_after_previous_completion(
    client: TestClient, mocker, monkeypatch
) -> None:
    _setup_env(mocker, monkeypatch)
    mock_signing_verification_delivery(mocker)
    source_pdf_bytes = _pdf_bytes()

    create_response = client.post(
        "/api/signing/envelopes",
        headers=AUTH_HEADERS,
        json=_envelope_create_payload(source_pdf_bytes, signingMode="sequential"),
    )
    assert create_response.status_code == 201, create_response.text
    envelope_id = create_response.json()["envelope"]["id"]

    send_response = client.post(
        f"/api/signing/envelopes/{envelope_id}/send",
        headers=AUTH_HEADERS,
        files={"pdf": ("packet.pdf", source_pdf_bytes, "application/pdf")},
        data={
            "sourcePdfSha256": _immutable_source_pdf_sha256(source_pdf_bytes),
        },
    )
    assert send_response.status_code == 200, send_response.text
    sent_requests = send_response.json()["requests"]
    alice_request = next(request for request in sent_requests if request["signerOrder"] == 1)
    bob_request = next(request for request in sent_requests if request["signerOrder"] == 2)

    blocked_bootstrap = client.post(
        f"/api/signing/public/{bob_request['publicToken']}/bootstrap",
        headers={"User-Agent": "integration-envelope-bob/1.0"},
    )
    assert blocked_bootstrap.status_code == 403, blocked_bootstrap.text
    assert "not your turn" in blocked_bootstrap.json()["detail"].lower()

    alice_complete = _complete_public_envelope_signer(
        client,
        alice_request,
        adopted_name="Alice Sequential",
        browser_name="integration-envelope-alice/1.0",
    )
    assert alice_complete["status"] == "completed"
    assert alice_complete["artifacts"]["signedPdf"]["available"] is False
    assert alice_complete["envelope"]["completedSignerCount"] == 1

    bob_detail_after_activation = client.get(
        f"/api/signing/requests/{bob_request['id']}",
        headers=AUTH_HEADERS,
    )
    assert bob_detail_after_activation.status_code == 200, bob_detail_after_activation.text
    bob_request_after_activation = bob_detail_after_activation.json()["request"]
    assert bob_request_after_activation["status"] == "sent"
    assert bob_request_after_activation["turnActivatedAt"] is not None
    assert bob_request_after_activation["inviteLastAttemptAt"] is not None
    assert bob_request_after_activation["inviteDeliveryStatus"] in {"sent", "skipped", "failed"}

    bob_complete = _complete_public_envelope_signer(
        client,
        bob_request_after_activation,
        adopted_name="Bob Sequential",
        browser_name="integration-envelope-bob/1.0",
    )
    assert bob_complete["status"] == "completed"
    assert bob_complete["artifacts"]["signedPdf"]["available"] is True
    assert bob_complete["artifacts"]["auditReceipt"]["available"] is True
    assert bob_complete["envelope"]["completedSignerCount"] == 2


def test_envelope_send_rejects_already_sent(
    client: TestClient, mocker, monkeypatch
) -> None:
    _setup_env(mocker, monkeypatch)
    source_pdf_bytes = _pdf_bytes()

    create_response = client.post(
        "/api/signing/envelopes",
        headers=AUTH_HEADERS,
        json=_envelope_create_payload(source_pdf_bytes),
    )
    envelope_id = create_response.json()["envelope"]["id"]

    # First send
    first_send = client.post(
        f"/api/signing/envelopes/{envelope_id}/send",
        headers=AUTH_HEADERS,
        files={"pdf": ("packet.pdf", source_pdf_bytes, "application/pdf")},
        data={"sourcePdfSha256": _immutable_source_pdf_sha256(source_pdf_bytes)},
    )
    assert first_send.status_code == 200

    # Second send should fail
    second_send = client.post(
        f"/api/signing/envelopes/{envelope_id}/send",
        headers=AUTH_HEADERS,
        files={"pdf": ("packet.pdf", source_pdf_bytes, "application/pdf")},
        data={"sourcePdfSha256": _immutable_source_pdf_sha256(source_pdf_bytes)},
    )
    assert second_send.status_code == 409


# ---------------------------------------------------------------------------
# Envelope get / list
# ---------------------------------------------------------------------------


def test_envelope_get_returns_envelope_and_requests(
    client: TestClient, mocker, monkeypatch
) -> None:
    _setup_env(mocker, monkeypatch)
    source_pdf_bytes = _pdf_bytes()

    create_response = client.post(
        "/api/signing/envelopes",
        headers=AUTH_HEADERS,
        json=_envelope_create_payload(source_pdf_bytes),
    )
    envelope_id = create_response.json()["envelope"]["id"]

    get_response = client.get(
        f"/api/signing/envelopes/{envelope_id}",
        headers=AUTH_HEADERS,
    )

    assert get_response.status_code == 200
    body = get_response.json()
    assert body["envelope"]["id"] == envelope_id
    assert len(body["requests"]) == 2


def test_envelope_list_returns_user_envelopes(
    client: TestClient, mocker, monkeypatch
) -> None:
    _setup_env(mocker, monkeypatch)
    source_pdf_bytes = _pdf_bytes()

    client.post(
        "/api/signing/envelopes",
        headers=AUTH_HEADERS,
        json=_envelope_create_payload(source_pdf_bytes),
    )

    list_response = client.get(
        "/api/signing/envelopes",
        headers=AUTH_HEADERS,
    )

    assert list_response.status_code == 200
    assert len(list_response.json()["envelopes"]) >= 1


def test_envelope_not_found_returns_404(
    client: TestClient, mocker, monkeypatch
) -> None:
    _setup_env(mocker, monkeypatch)

    response = client.get(
        "/api/signing/envelopes/nonexistent",
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Envelope revoke
# ---------------------------------------------------------------------------


def test_envelope_revoke_invalidates_child_requests(
    client: TestClient, mocker, monkeypatch
) -> None:
    _setup_env(mocker, monkeypatch)
    source_pdf_bytes = _pdf_bytes()

    create_response = client.post(
        "/api/signing/envelopes",
        headers=AUTH_HEADERS,
        json=_envelope_create_payload(source_pdf_bytes),
    )
    envelope_id = create_response.json()["envelope"]["id"]

    revoke_response = client.post(
        f"/api/signing/envelopes/{envelope_id}/revoke",
        headers=AUTH_HEADERS,
    )

    assert revoke_response.status_code == 200
    body = revoke_response.json()
    assert body["envelope"]["status"] == "invalidated"
    for req in body["requests"]:
        assert req["status"] == "invalidated"


def test_envelope_revoke_rejects_completed_signers(
    client: TestClient, mocker, monkeypatch
) -> None:
    _setup_env(mocker, monkeypatch)
    mock_signing_verification_delivery(mocker)
    source_pdf_bytes = _pdf_bytes()

    create_response = client.post(
        "/api/signing/envelopes",
        headers=AUTH_HEADERS,
        json=_envelope_create_payload(source_pdf_bytes, signingMode="sequential"),
    )
    assert create_response.status_code == 201, create_response.text
    envelope_id = create_response.json()["envelope"]["id"]

    send_response = client.post(
        f"/api/signing/envelopes/{envelope_id}/send",
        headers=AUTH_HEADERS,
        files={"pdf": ("packet.pdf", source_pdf_bytes, "application/pdf")},
        data={"sourcePdfSha256": _immutable_source_pdf_sha256(source_pdf_bytes)},
    )
    assert send_response.status_code == 200, send_response.text
    alice_request = next(
        request for request in send_response.json()["requests"] if request["signerOrder"] == 1
    )

    alice_complete = _complete_public_envelope_signer(
        client,
        alice_request,
        adopted_name="Alice Completed",
        browser_name="integration-envelope-alice/1.0",
    )
    assert alice_complete["status"] == "completed"

    revoke_response = client.post(
        f"/api/signing/envelopes/{envelope_id}/revoke",
        headers=AUTH_HEADERS,
    )

    assert revoke_response.status_code == 409
    assert "completed signers" in revoke_response.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Existing single-signer flow still works (regression guard)
# ---------------------------------------------------------------------------


def test_single_signer_create_and_send_still_works(
    client: TestClient, mocker, monkeypatch
) -> None:
    """Ensure the legacy single-signer path is not broken by envelope additions."""
    _setup_env(mocker, monkeypatch)
    source_pdf_bytes = _pdf_bytes()
    sha256 = _immutable_source_pdf_sha256(source_pdf_bytes)

    create_response = client.post(
        "/api/signing/requests",
        headers=AUTH_HEADERS,
        json={
            "title": "Single Signer Test",
            "mode": "sign",
            "signatureMode": "business",
            "sourceType": "workspace",
            "sourceDocumentName": "Test Doc",
            "sourceTemplateId": "form-alpha",
            "sourcePdfSha256": sha256,
            "documentCategory": "ordinary_business_form",
            "esignEligibilityConfirmed": True,
            "manualFallbackEnabled": True,
            "signerName": "Solo Signer",
            "signerEmail": "solo@example.com",
            "anchors": [
                {
                    "kind": "signature",
                    "page": 1,
                    "rect": {"x": 50, "y": 100, "width": 150, "height": 30},
                },
            ],
        },
    )

    assert create_response.status_code == 201
    request_id = create_response.json()["request"]["id"]
    # Verify envelope fields are null for single-signer
    assert create_response.json()["request"]["envelopeId"] is None
    assert create_response.json()["request"]["signerOrder"] == 1

    send_response = client.post(
        f"/api/signing/requests/{request_id}/send",
        headers=AUTH_HEADERS,
        files={"pdf": ("test.pdf", source_pdf_bytes, "application/pdf")},
        data={"sourcePdfSha256": sha256},
    )

    assert send_response.status_code == 200, f"Send failed: {send_response.text}"
    assert send_response.json()["request"]["status"] == "sent"


# ---------------------------------------------------------------------------
# Per-signer anchor assignment
# ---------------------------------------------------------------------------


def test_envelope_child_requests_only_get_assigned_anchors(
    client: TestClient, mocker, monkeypatch
) -> None:
    """Each child request should only contain anchors assigned to that signer."""
    _setup_env(mocker, monkeypatch)
    source_pdf_bytes = _pdf_bytes()

    response = client.post(
        "/api/signing/envelopes",
        headers=AUTH_HEADERS,
        json=_envelope_create_payload(source_pdf_bytes),
    )

    assert response.status_code == 201
    requests = response.json()["requests"]
    alice_req = next(r for r in requests if r["signerEmail"] == "alice@example.com")
    bob_req = next(r for r in requests if r["signerEmail"] == "bob@example.com")

    # Alice (order=1) should only get the anchor assigned to order 1
    alice_sig_anchors = [a for a in alice_req["anchors"] if a["kind"] == "signature"]
    assert len(alice_sig_anchors) == 1
    assert alice_sig_anchors[0].get("assignedSignerOrder") == 1

    # Bob (order=2) should only get the anchor assigned to order 2
    bob_sig_anchors = [a for a in bob_req["anchors"] if a["kind"] == "signature"]
    assert len(bob_sig_anchors) == 1
    assert bob_sig_anchors[0].get("assignedSignerOrder") == 2


def test_envelope_rejects_unassigned_signature_anchors(
    client: TestClient, mocker, monkeypatch
) -> None:
    """All envelope anchors must be assigned to a signer."""
    _setup_env(mocker, monkeypatch)
    source_pdf_bytes = _pdf_bytes()

    response = client.post(
        "/api/signing/envelopes",
        headers=AUTH_HEADERS,
        json=_envelope_create_payload(source_pdf_bytes, anchors=[
            {
                "kind": "signature",
                "page": 1,
                "rect": {"x": 100, "y": 400, "width": 180, "height": 36},
                # No assignedSignerOrder
            },
        ]),
    )

    assert response.status_code == 400
    assert "assigned to a signer" in response.json()["detail"]


def test_envelope_rejects_unassigned_non_signature_anchors(
    client: TestClient, mocker, monkeypatch
) -> None:
    _setup_env(mocker, monkeypatch)
    source_pdf_bytes = _pdf_bytes()

    response = client.post(
        "/api/signing/envelopes",
        headers=AUTH_HEADERS,
        json=_envelope_create_payload(
            source_pdf_bytes,
            anchors=[
                {
                    "kind": "signature",
                    "page": 1,
                    "rect": {"x": 100, "y": 400, "width": 180, "height": 36},
                    "assignedSignerOrder": 1,
                },
                {
                    "kind": "signature",
                    "page": 1,
                    "rect": {"x": 100, "y": 500, "width": 180, "height": 36},
                    "assignedSignerOrder": 2,
                },
                {
                    "kind": "signed_date",
                    "page": 1,
                    "rect": {"x": 100, "y": 550, "width": 100, "height": 20},
                },
            ],
        ),
    )

    assert response.status_code == 400
    assert "assigned to a signer" in response.json()["detail"]


def test_envelope_rejects_anchor_assignment_for_unknown_recipient(
    client: TestClient, mocker, monkeypatch
) -> None:
    _setup_env(mocker, monkeypatch)
    source_pdf_bytes = _pdf_bytes()

    response = client.post(
        "/api/signing/envelopes",
        headers=AUTH_HEADERS,
        json=_envelope_create_payload(
            source_pdf_bytes,
            anchors=[
                {
                    "kind": "signature",
                    "page": 1,
                    "rect": {"x": 100, "y": 400, "width": 180, "height": 36},
                    "assignedSignerOrder": 1,
                },
                {
                    "kind": "signature",
                    "page": 1,
                    "rect": {"x": 100, "y": 500, "width": 180, "height": 36},
                    "assignedSignerOrder": 2,
                },
                {
                    "kind": "initials",
                    "page": 1,
                    "rect": {"x": 100, "y": 550, "width": 80, "height": 20},
                    "assignedSignerOrder": 3,
                },
            ],
        ),
    )

    assert response.status_code == 400
    assert "no recipient has that order" in response.json()["detail"]


def test_envelope_allows_multiple_anchors_per_signer(
    client: TestClient, mocker, monkeypatch
) -> None:
    """Multiple signature fields can be assigned to the same signer."""
    _setup_env(mocker, monkeypatch)
    source_pdf_bytes = _pdf_bytes()

    response = client.post(
        "/api/signing/envelopes",
        headers=AUTH_HEADERS,
        json=_envelope_create_payload(source_pdf_bytes, anchors=[
            {
                "kind": "signature",
                "page": 1,
                "rect": {"x": 100, "y": 400, "width": 180, "height": 36},
                "assignedSignerOrder": 1,
            },
            {
                "kind": "signature",
                "page": 1,
                "rect": {"x": 100, "y": 500, "width": 180, "height": 36},
                "assignedSignerOrder": 1,
            },
            {
                "kind": "signed_date",
                "page": 1,
                "rect": {"x": 100, "y": 550, "width": 100, "height": 20},
                "assignedSignerOrder": 1,
            },
            {
                "kind": "signature",
                "page": 1,
                "rect": {"x": 100, "y": 600, "width": 180, "height": 36},
                "assignedSignerOrder": 2,
            },
        ]),
    )

    assert response.status_code == 201
    requests = response.json()["requests"]
    alice_req = next(r for r in requests if r["signerEmail"] == "alice@example.com")
    # Alice should get all 3 anchors (2 signature + 1 signed_date)
    assert len(alice_req["anchors"]) == 3
    # Bob should still get only the anchor assigned to order 2.
    bob_req = next(r for r in requests if r["signerEmail"] == "bob@example.com")
    assert len(bob_req["anchors"]) == 1
    assert bob_req["anchors"][0]["kind"] == "signature"
    assert bob_req["anchors"][0]["assignedSignerOrder"] == 2


def test_envelope_rejects_recipient_without_signature_anchor(
    client: TestClient, mocker, monkeypatch
) -> None:
    _setup_env(mocker, monkeypatch)
    source_pdf_bytes = _pdf_bytes()

    response = client.post(
        "/api/signing/envelopes",
        headers=AUTH_HEADERS,
        json=_envelope_create_payload(
            source_pdf_bytes,
            anchors=[
                {
                    "kind": "signature",
                    "page": 1,
                    "rect": {"x": 100, "y": 400, "width": 180, "height": 36},
                    "assignedSignerOrder": 1,
                },
                {
                    "kind": "signed_date",
                    "page": 1,
                    "rect": {"x": 100, "y": 550, "width": 100, "height": 20},
                    "assignedSignerOrder": 1,
                },
            ],
        ),
    )

    assert response.status_code == 400
    assert "at least one signature anchor" in response.json()["detail"].lower()
