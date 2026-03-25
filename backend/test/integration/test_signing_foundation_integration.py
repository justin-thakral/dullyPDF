"""Integration coverage for signing foundation routes."""

from __future__ import annotations

from dataclasses import replace
from io import BytesIO
import json

from fastapi.testclient import TestClient
import pytest
from pypdf import PdfWriter

import backend.main as main
import backend.api.middleware.security as security_middleware
import backend.api.routes.signing as signing_routes
import backend.api.routes.signing_public as signing_public_routes
import backend.firebaseDB.signing_database as signing_database
import backend.firebaseDB.user_database as user_database
from backend.firebaseDB.firebase_service import RequestUser
from backend.services.signing_audit_service import verify_signing_audit_envelope
from backend.services.signing_service import build_signing_public_token, sha256_hex_for_bytes
from backend.test.unit.firebase._fakes import FakeFirestoreClient


AUTH_HEADERS = {"Authorization": "Bearer integration-token"}


@pytest.fixture
def client() -> TestClient:
    return TestClient(main.app)


def _signing_user() -> RequestUser:
    return RequestUser(
        uid="firebase-user-signing",
        app_user_id="user-signing",
        email="owner@example.com",
        display_name="Owner Example",
        role=user_database.ROLE_BASE,
    )


def _pdf_bytes(*, width: float = 200, height: float = 200) -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=width, height=height)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def test_signing_owner_endpoints_require_authentication(client: TestClient) -> None:
    for method, path in (
        ("get", "/api/signing/options"),
        ("get", "/api/signing/requests"),
        ("post", "/api/signing/requests"),
    ):
        if method == "post":
            response = client.post(path, json={})
        else:
            response = getattr(client, method)(path)
        assert response.status_code == 401
        assert "authorization" in response.text.lower()


def test_signing_foundation_creates_lists_and_exposes_public_shell(client: TestClient, mocker) -> None:
    firestore_client = FakeFirestoreClient()
    request_user = _signing_user()
    source_pdf_bytes = _pdf_bytes()

    mocker.patch.object(signing_database, "get_firestore_client", return_value=firestore_client)
    mocker.patch.object(signing_routes, "require_user", return_value=request_user)
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

    create_response = client.post(
        "/api/signing/requests",
        headers=AUTH_HEADERS,
        json={
            "title": "Bravo Packet Signature Request",
            "mode": "sign",
            "signatureMode": "business",
            "sourceType": "workspace",
            "sourceId": "form-alpha",
            "sourceDocumentName": "Bravo Packet",
            "sourceTemplateId": "form-alpha",
            "sourceTemplateName": "Bravo Packet",
            "sourcePdfSha256": sha256_hex_for_bytes(source_pdf_bytes),
            "documentCategory": "ordinary_business_form",
            "manualFallbackEnabled": True,
            "signerName": "Alex Signer",
            "signerEmail": "alex@example.com",
            "anchors": [
                {
                    "kind": "signature",
                    "page": 2,
                    "rect": {"x": 100, "y": 400, "width": 180, "height": 36},
                    "fieldId": "field-sign-1",
                    "fieldName": "signature_primary",
                }
            ],
        },
    )

    assert create_response.status_code == 201
    create_payload = create_response.json()["request"]
    assert create_payload["status"] == "draft"
    assert create_payload["documentCategory"] == "ordinary_business_form"
    assert create_payload["documentCategoryLabel"] == "Ordinary business form"
    assert create_payload["signerEmail"] == "alex@example.com"
    assert create_payload["publicPath"] is None
    assert create_payload["publicToken"] is None
    assert create_payload["sourceVersion"].startswith("workspace:form-alpha:")
    assert create_payload["anchors"][0]["kind"] == "signature"

    request_id = create_payload["id"]
    public_token = build_signing_public_token(request_id)

    list_response = client.get("/api/signing/requests", headers=AUTH_HEADERS)
    assert list_response.status_code == 200
    requests_payload = list_response.json()["requests"]
    assert len(requests_payload) == 1
    assert requests_payload[0]["id"] == request_id

    detail_response = client.get(f"/api/signing/requests/{request_id}", headers=AUTH_HEADERS)
    assert detail_response.status_code == 200
    assert detail_response.json()["request"]["sourceTemplateId"] == "form-alpha"

    public_response = client.get(f"/api/signing/public/{public_token}")
    assert public_response.status_code == 200
    public_payload = public_response.json()["request"]
    assert public_payload["id"] == request_id
    assert public_payload["signerName"] == "Alex Signer"
    assert public_payload["sourceDocumentName"] == "Bravo Packet"
    assert public_payload["anchors"][0]["fieldName"] == "signature_primary"


def test_signing_foundation_blocks_excluded_categories(client: TestClient, mocker) -> None:
    request_user = _signing_user()
    mocker.patch.object(signing_routes, "require_user", return_value=request_user)
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

    response = client.post(
        "/api/signing/requests",
        headers=AUTH_HEADERS,
        json={
            "mode": "sign",
            "signatureMode": "business",
            "sourceType": "workspace",
            "sourceDocumentName": "Will Packet",
            "sourcePdfSha256": sha256_hex_for_bytes(_pdf_bytes()),
            "documentCategory": "will_trust_estate",
            "manualFallbackEnabled": True,
            "signerName": "Blocked Signer",
            "signerEmail": "blocked@example.com",
            "anchors": [],
        },
    )

    assert response.status_code == 400
    assert "blocked" in response.json()["detail"].lower()


def test_signing_send_transitions_draft_to_sent_with_immutable_snapshot(client: TestClient, mocker) -> None:
    firestore_client = FakeFirestoreClient()
    request_user = _signing_user()
    source_pdf_bytes = _pdf_bytes()
    source_sha256 = sha256_hex_for_bytes(source_pdf_bytes)

    mocker.patch.object(signing_database, "get_firestore_client", return_value=firestore_client)
    mocker.patch.object(signing_routes, "require_user", return_value=request_user)
    mocker.patch.object(signing_routes, "upload_signing_pdf_bytes", return_value="gs://signing-bucket/users/user-signing/signing/req/source.pdf")
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

    create_response = client.post(
        "/api/signing/requests",
        headers=AUTH_HEADERS,
        json={
            "title": "Bravo Packet Signature Request",
            "mode": "sign",
            "signatureMode": "business",
            "sourceType": "workspace",
            "sourceId": "form-alpha",
            "sourceDocumentName": "Bravo Packet",
            "sourceTemplateId": "form-alpha",
            "sourceTemplateName": "Bravo Packet",
            "sourcePdfSha256": source_sha256,
            "documentCategory": "ordinary_business_form",
            "manualFallbackEnabled": True,
            "signerName": "Alex Signer",
            "signerEmail": "alex@example.com",
            "anchors": [
                {
                    "kind": "signature",
                    "page": 2,
                    "rect": {"x": 100, "y": 400, "width": 180, "height": 36},
                }
            ],
        },
    )
    request_id = create_response.json()["request"]["id"]

    send_response = client.post(
        f"/api/signing/requests/{request_id}/send",
        headers=AUTH_HEADERS,
        files={"pdf": ("bravo.pdf", source_pdf_bytes, "application/pdf")},
        data={"sourcePdfSha256": source_sha256},
    )

    assert send_response.status_code == 200
    sent_payload = send_response.json()["request"]
    assert sent_payload["status"] == "sent"
    assert sent_payload["sourcePdfSha256"] == source_sha256
    assert sent_payload["sourcePdfPath"] == "gs://signing-bucket/users/user-signing/signing/req/source.pdf"
    assert sent_payload["sentAt"]


def test_signing_send_cleans_up_uploaded_source_when_transition_turns_stale(client: TestClient, mocker) -> None:
    firestore_client = FakeFirestoreClient()
    request_user = _signing_user()
    source_pdf_bytes = _pdf_bytes()
    source_sha256 = sha256_hex_for_bytes(source_pdf_bytes)
    deleted_paths: list[str] = []

    mocker.patch.object(signing_database, "get_firestore_client", return_value=firestore_client)
    mocker.patch.object(signing_routes, "require_user", return_value=request_user)
    mocker.patch.object(signing_routes, "upload_signing_pdf_bytes", return_value="gs://signing-bucket/users/user-signing/signing/req/source.pdf")
    mocker.patch.object(signing_routes, "delete_storage_object", side_effect=lambda bucket_path: deleted_paths.append(bucket_path))
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

    create_response = client.post(
        "/api/signing/requests",
        headers=AUTH_HEADERS,
        json={
            "title": "Bravo Packet Signature Request",
            "mode": "sign",
            "signatureMode": "business",
            "sourceType": "workspace",
            "sourceId": "form-alpha",
            "sourceDocumentName": "Bravo Packet",
            "sourceTemplateId": "form-alpha",
            "sourceTemplateName": "Bravo Packet",
            "sourcePdfSha256": source_sha256,
            "documentCategory": "ordinary_business_form",
            "manualFallbackEnabled": True,
            "signerName": "Alex Signer",
            "signerEmail": "alex@example.com",
            "anchors": [
                {
                    "kind": "signature",
                    "page": 2,
                    "rect": {"x": 100, "y": 400, "width": 180, "height": 36},
                }
            ],
        },
    )
    request_payload = create_response.json()["request"]
    request_id = request_payload["id"]
    stale_invalidated_record = replace(
        signing_database.get_signing_request(request_id, client=firestore_client),
        status="invalidated",
        invalidation_reason="Source changed elsewhere",
    )
    mocker.patch.object(signing_routes, "mark_signing_request_sent", return_value=stale_invalidated_record)

    send_response = client.post(
        f"/api/signing/requests/{request_id}/send",
        headers=AUTH_HEADERS,
        files={"pdf": ("bravo.pdf", source_pdf_bytes, "application/pdf")},
        data={"sourcePdfSha256": source_sha256},
    )

    assert send_response.status_code == 409
    assert "source changed elsewhere" in send_response.json()["detail"].lower()
    assert deleted_paths == ["gs://signing-bucket/users/user-signing/signing/req/source.pdf"]


def test_signing_send_invalidates_draft_when_source_pdf_changes(client: TestClient, mocker) -> None:
    firestore_client = FakeFirestoreClient()
    request_user = _signing_user()
    original_pdf_bytes = _pdf_bytes()
    changed_pdf_bytes = _pdf_bytes(width=201, height=200)

    mocker.patch.object(signing_database, "get_firestore_client", return_value=firestore_client)
    mocker.patch.object(signing_routes, "require_user", return_value=request_user)
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

    create_response = client.post(
        "/api/signing/requests",
        headers=AUTH_HEADERS,
        json={
            "title": "Bravo Packet Signature Request",
            "mode": "sign",
            "signatureMode": "business",
            "sourceType": "workspace",
            "sourceId": "form-alpha",
            "sourceDocumentName": "Bravo Packet",
            "sourceTemplateId": "form-alpha",
            "sourceTemplateName": "Bravo Packet",
            "sourcePdfSha256": sha256_hex_for_bytes(original_pdf_bytes),
            "documentCategory": "ordinary_business_form",
            "manualFallbackEnabled": True,
            "signerName": "Alex Signer",
            "signerEmail": "alex@example.com",
            "anchors": [
                {
                    "kind": "signature",
                    "page": 2,
                    "rect": {"x": 100, "y": 400, "width": 180, "height": 36},
                }
            ],
        },
    )
    request_id = create_response.json()["request"]["id"]

    send_response = client.post(
        f"/api/signing/requests/{request_id}/send",
        headers=AUTH_HEADERS,
        files={"pdf": ("bravo.pdf", changed_pdf_bytes, "application/pdf")},
        data={"sourcePdfSha256": sha256_hex_for_bytes(changed_pdf_bytes)},
    )

    assert send_response.status_code == 409
    assert "changed" in send_response.json()["detail"].lower()

    detail_response = client.get(f"/api/signing/requests/{request_id}", headers=AUTH_HEADERS)
    assert detail_response.status_code == 200
    detail_payload = detail_response.json()["request"]
    assert detail_payload["status"] == "invalidated"
    assert "changed" in (detail_payload["invalidationReason"] or "").lower()


def test_signing_send_rejects_malformed_client_sha256_with_400(client: TestClient, mocker) -> None:
    firestore_client = FakeFirestoreClient()
    request_user = _signing_user()
    source_pdf_bytes = _pdf_bytes()

    mocker.patch.object(signing_database, "get_firestore_client", return_value=firestore_client)
    mocker.patch.object(signing_routes, "require_user", return_value=request_user)
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

    create_response = client.post(
        "/api/signing/requests",
        headers=AUTH_HEADERS,
        json={
            "title": "Bravo Packet Signature Request",
            "mode": "sign",
            "signatureMode": "business",
            "sourceType": "workspace",
            "sourceId": "form-alpha",
            "sourceDocumentName": "Bravo Packet",
            "sourceTemplateId": "form-alpha",
            "sourceTemplateName": "Bravo Packet",
            "sourcePdfSha256": sha256_hex_for_bytes(source_pdf_bytes),
            "documentCategory": "ordinary_business_form",
            "manualFallbackEnabled": True,
            "signerName": "Alex Signer",
            "signerEmail": "alex@example.com",
            "anchors": [
                {
                    "kind": "signature",
                    "page": 2,
                    "rect": {"x": 100, "y": 400, "width": 180, "height": 36},
                }
            ],
        },
    )
    request_id = create_response.json()["request"]["id"]

    send_response = client.post(
        f"/api/signing/requests/{request_id}/send",
        headers=AUTH_HEADERS,
        files={"pdf": ("bravo.pdf", source_pdf_bytes, "application/pdf")},
        data={"sourcePdfSha256": "NOT-A-REAL-SHA"},
    )

    assert send_response.status_code == 400
    assert "sha-256" in send_response.json()["detail"].lower()


def test_fill_and_sign_send_requires_owner_review_and_persists_response_provenance(client: TestClient, mocker) -> None:
    firestore_client = FakeFirestoreClient()
    request_user = _signing_user()
    source_pdf_bytes = _pdf_bytes()
    source_sha256 = sha256_hex_for_bytes(source_pdf_bytes)

    mocker.patch.object(signing_database, "get_firestore_client", return_value=firestore_client)
    mocker.patch.object(signing_routes, "require_user", return_value=request_user)
    mocker.patch.object(
        signing_routes,
        "upload_signing_pdf_bytes",
        return_value="gs://signing-bucket/users/user-signing/signing/req/fill-source.pdf",
    )
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

    create_response = client.post(
        "/api/signing/requests",
        headers=AUTH_HEADERS,
        json={
            "title": "Bravo Packet Fill And Sign",
            "mode": "fill_and_sign",
            "signatureMode": "business",
            "sourceType": "fill_link_response",
            "sourceId": "resp-42",
            "sourceLinkId": "link-7",
            "sourceRecordLabel": "Ada Lovelace",
            "sourceDocumentName": "Bravo Packet",
            "sourceTemplateId": "form-alpha",
            "sourceTemplateName": "Bravo Packet",
            "sourcePdfSha256": source_sha256,
            "documentCategory": "ordinary_business_form",
            "manualFallbackEnabled": True,
            "signerName": "Alex Signer",
            "signerEmail": "alex@example.com",
            "anchors": [
                {
                    "kind": "signature",
                    "page": 1,
                    "rect": {"x": 100, "y": 400, "width": 180, "height": 36},
                }
            ],
        },
    )
    assert create_response.status_code == 201
    create_payload = create_response.json()["request"]
    assert create_payload["sourceType"] == "fill_link_response"
    assert create_payload["sourceId"] == "resp-42"
    assert create_payload["sourceLinkId"] == "link-7"
    assert create_payload["sourceRecordLabel"] == "Ada Lovelace"
    request_id = create_payload["id"]

    blocked_send = client.post(
        f"/api/signing/requests/{request_id}/send",
        headers=AUTH_HEADERS,
        files={"pdf": ("bravo-fill.pdf", source_pdf_bytes, "application/pdf")},
        data={"sourcePdfSha256": source_sha256},
    )
    assert blocked_send.status_code == 400
    assert "review" in blocked_send.json()["detail"].lower()

    send_response = client.post(
        f"/api/signing/requests/{request_id}/send",
        headers=AUTH_HEADERS,
        files={"pdf": ("bravo-fill.pdf", source_pdf_bytes, "application/pdf")},
        data={"sourcePdfSha256": source_sha256, "ownerReviewConfirmed": "true"},
    )
    assert send_response.status_code == 200
    sent_payload = send_response.json()["request"]
    assert sent_payload["status"] == "sent"
    assert sent_payload["sourcePdfPath"] == "gs://signing-bucket/users/user-signing/signing/req/fill-source.pdf"
    assert sent_payload["ownerReviewConfirmedAt"]


def test_public_signing_happy_path_records_ceremony_evidence(client: TestClient, mocker) -> None:
    firestore_client = FakeFirestoreClient()
    request_user = _signing_user()
    source_pdf_bytes = _pdf_bytes()
    source_sha256 = sha256_hex_for_bytes(source_pdf_bytes)
    stored_objects: dict[str, bytes] = {}

    def _fake_upload_pdf_bytes(payload: bytes, destination_path: str) -> str:
        uri = f"gs://signing-bucket/{destination_path}"
        stored_objects[uri] = bytes(payload)
        return uri

    def _fake_upload_json(payload, destination_path: str) -> str:
        uri = f"gs://signing-bucket/{destination_path}"
        stored_objects[uri] = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return uri

    def _fake_download_storage_bytes(bucket_path: str) -> bytes:
        return stored_objects[bucket_path]

    mocker.patch.object(signing_database, "get_firestore_client", return_value=firestore_client)
    mocker.patch.object(signing_routes, "require_user", return_value=request_user)
    mocker.patch.object(signing_routes, "upload_signing_pdf_bytes", side_effect=_fake_upload_pdf_bytes)
    mocker.patch.object(signing_routes, "download_storage_bytes", side_effect=_fake_download_storage_bytes)
    mocker.patch.object(signing_public_routes, "check_rate_limit", return_value=True)
    mocker.patch.object(signing_public_routes, "stream_pdf", return_value=BytesIO(source_pdf_bytes))
    mocker.patch.object(signing_public_routes, "upload_signing_pdf_bytes", side_effect=_fake_upload_pdf_bytes)
    mocker.patch.object(signing_public_routes, "upload_signing_json", side_effect=_fake_upload_json)
    mocker.patch.object(signing_public_routes, "download_storage_bytes", side_effect=_fake_download_storage_bytes)
    mocker.patch.object(signing_public_routes, "build_signing_bucket_uri", side_effect=lambda path: f"gs://signing-bucket/{path}")
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

    create_response = client.post(
        "/api/signing/requests",
        headers=AUTH_HEADERS,
        json={
            "title": "Bravo Packet Signature Request",
            "mode": "sign",
            "signatureMode": "business",
            "sourceType": "workspace",
            "sourceId": "form-alpha",
            "sourceDocumentName": "Bravo Packet",
            "sourceTemplateId": "form-alpha",
            "sourceTemplateName": "Bravo Packet",
            "sourcePdfSha256": source_sha256,
            "documentCategory": "ordinary_business_form",
            "manualFallbackEnabled": True,
            "signerName": "Alex Signer",
            "signerEmail": "alex@example.com",
            "anchors": [
                {
                    "kind": "signature",
                    "page": 1,
                    "rect": {"x": 100, "y": 400, "width": 180, "height": 36},
                }
            ],
        },
    )
    request_payload = create_response.json()["request"]
    request_id = request_payload["id"]
    public_token = build_signing_public_token(request_id)

    send_response = client.post(
        f"/api/signing/requests/{request_id}/send",
        headers=AUTH_HEADERS,
        files={"pdf": ("bravo.pdf", source_pdf_bytes, "application/pdf")},
        data={"sourcePdfSha256": source_sha256},
    )
    assert send_response.status_code == 200

    preview_response = client.get(f"/api/signing/public/{public_token}")
    assert preview_response.status_code == 200
    assert preview_response.json()["request"]["status"] == "sent"

    bootstrap_response = client.post(
        f"/api/signing/public/{public_token}/bootstrap",
        headers={"User-Agent": "integration-browser/1.0"},
    )
    assert bootstrap_response.status_code == 200
    bootstrap_payload = bootstrap_response.json()
    session_token = bootstrap_payload["session"]["token"]
    assert bootstrap_payload["request"]["openedAt"]

    document_response = client.get(f"/api/signing/public/{public_token}/document")
    assert document_response.status_code == 200
    assert document_response.headers["content-type"].startswith("application/pdf")

    review_response = client.post(
        f"/api/signing/public/{public_token}/review",
        headers={"X-Signing-Session": session_token},
        json={"reviewConfirmed": True},
    )
    assert review_response.status_code == 200
    assert review_response.json()["request"]["reviewedAt"]

    adopt_response = client.post(
        f"/api/signing/public/{public_token}/adopt-signature",
        headers={"X-Signing-Session": session_token},
        json={"adoptedName": "Alex Signer"},
    )
    assert adopt_response.status_code == 200
    assert adopt_response.json()["request"]["signatureAdoptedName"] == "Alex Signer"

    complete_response = client.post(
        f"/api/signing/public/{public_token}/complete",
        headers={"X-Signing-Session": session_token},
        json={"intentConfirmed": True},
    )
    assert complete_response.status_code == 200
    assert complete_response.json()["request"]["status"] == "completed"
    assert complete_response.json()["request"]["completedAt"]
    assert complete_response.json()["request"]["artifacts"]["signedPdf"]["downloadPath"]
    assert complete_response.json()["request"]["artifacts"]["auditReceipt"]["downloadPath"]

    detail_response = client.get(f"/api/signing/requests/{request_id}", headers=AUTH_HEADERS)
    assert detail_response.status_code == 200
    detail_payload = detail_response.json()["request"]
    assert detail_payload["openedAt"]
    assert detail_payload["reviewedAt"]
    assert detail_payload["signatureAdoptedAt"]
    assert detail_payload["completedAt"]
    assert detail_payload["artifacts"]["signedPdf"]["available"] is True
    assert detail_payload["artifacts"]["auditManifest"]["available"] is True
    assert detail_payload["artifacts"]["auditReceipt"]["available"] is True
    assert detail_payload["retentionUntil"]

    artifacts_response = client.get(f"/api/signing/requests/{request_id}/artifacts", headers=AUTH_HEADERS)
    assert artifacts_response.status_code == 200
    assert artifacts_response.json()["artifacts"]["signedPdf"]["available"] is True

    owner_manifest_download = client.get(
        f"/api/signing/requests/{request_id}/artifacts/audit_manifest",
        headers=AUTH_HEADERS,
    )
    assert owner_manifest_download.status_code == 200
    envelope_payload = json.loads(owner_manifest_download.content.decode("utf-8"))
    assert verify_signing_audit_envelope(envelope_payload) is True

    owner_signed_pdf_download = client.get(
        f"/api/signing/requests/{request_id}/artifacts/signed_pdf",
        headers=AUTH_HEADERS,
    )
    assert owner_signed_pdf_download.status_code == 200
    assert owner_signed_pdf_download.headers["content-type"].startswith("application/pdf")

    public_receipt_download = client.get(f"/api/signing/public/{public_token}/artifacts/audit_receipt")
    assert public_receipt_download.status_code == 200
    assert public_receipt_download.headers["content-type"].startswith("application/pdf")

    event_types = [event.event_type for event in signing_database.list_signing_events_for_request(request_id, client=firestore_client)]
    assert event_types == [
        "session_started",
        "opened",
        "review_confirmed",
        "signature_adopted",
        "completed",
    ]


def test_public_signing_consumer_requires_consent_and_records_manual_fallback(client: TestClient, mocker) -> None:
    firestore_client = FakeFirestoreClient()
    request_user = _signing_user()
    source_pdf_bytes = _pdf_bytes()
    source_sha256 = sha256_hex_for_bytes(source_pdf_bytes)

    mocker.patch.object(signing_database, "get_firestore_client", return_value=firestore_client)
    mocker.patch.object(signing_routes, "require_user", return_value=request_user)
    mocker.patch.object(signing_routes, "upload_signing_pdf_bytes", return_value="gs://signing-bucket/users/user-signing/signing/req/source.pdf")
    mocker.patch.object(signing_public_routes, "check_rate_limit", return_value=True)
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

    create_response = client.post(
        "/api/signing/requests",
        headers=AUTH_HEADERS,
        json={
            "title": "Consumer Signature Request",
            "mode": "sign",
            "signatureMode": "consumer",
            "sourceType": "workspace",
            "sourceDocumentName": "Consumer Packet",
            "sourcePdfSha256": source_sha256,
            "documentCategory": "authorization_consent_form",
            "manualFallbackEnabled": True,
            "signerName": "Alex Signer",
            "signerEmail": "alex@example.com",
            "anchors": [
                {
                    "kind": "signature",
                    "page": 1,
                    "rect": {"x": 100, "y": 400, "width": 180, "height": 36},
                }
            ],
        },
    )
    request_payload = create_response.json()["request"]
    request_id = request_payload["id"]
    public_token = build_signing_public_token(request_id)

    send_response = client.post(
        f"/api/signing/requests/{request_id}/send",
        headers=AUTH_HEADERS,
        files={"pdf": ("consumer.pdf", source_pdf_bytes, "application/pdf")},
        data={"sourcePdfSha256": source_sha256},
    )
    assert send_response.status_code == 200

    bootstrap_response = client.post(f"/api/signing/public/{public_token}/bootstrap")
    assert bootstrap_response.status_code == 200
    session_token = bootstrap_response.json()["session"]["token"]

    review_response = client.post(
        f"/api/signing/public/{public_token}/review",
        headers={"X-Signing-Session": session_token},
        json={"reviewConfirmed": True},
    )
    assert review_response.status_code == 409
    assert "consent" in review_response.json()["detail"].lower()

    fallback_response = client.post(
        f"/api/signing/public/{public_token}/manual-fallback",
        headers={"X-Signing-Session": session_token},
        json={"note": "Needs paper copy"},
    )
    assert fallback_response.status_code == 200
    assert fallback_response.json()["request"]["manualFallbackRequestedAt"]

    consent_response = client.post(
        f"/api/signing/public/{public_token}/consent",
        headers={"X-Signing-Session": session_token},
        json={"accepted": True},
    )
    assert consent_response.status_code == 409
    assert "fallback" in consent_response.json()["detail"].lower()

    second_bootstrap_response = client.post(f"/api/signing/public/{public_token}/bootstrap")
    assert second_bootstrap_response.status_code == 409
    assert "fallback" in second_bootstrap_response.json()["detail"].lower()

    detail_response = client.get(f"/api/signing/requests/{request_id}", headers=AUTH_HEADERS)
    assert detail_response.status_code == 200
    detail_payload = detail_response.json()["request"]
    assert detail_payload["manualFallbackRequestedAt"]
    assert not detail_payload["consentedAt"]

    event_types = [event.event_type for event in signing_database.list_signing_events_for_request(request_id, client=firestore_client)]
    assert "manual_fallback_requested" in event_types
    assert "consent_accepted" not in event_types


def test_public_signing_review_rejects_stale_transition_without_logging_event(client: TestClient, mocker) -> None:
    firestore_client = FakeFirestoreClient()
    request_user = _signing_user()
    source_pdf_bytes = _pdf_bytes()
    source_sha256 = sha256_hex_for_bytes(source_pdf_bytes)

    mocker.patch.object(signing_database, "get_firestore_client", return_value=firestore_client)
    mocker.patch.object(signing_routes, "require_user", return_value=request_user)
    mocker.patch.object(signing_routes, "upload_signing_pdf_bytes", return_value="gs://signing-bucket/users/user-signing/signing/req/source.pdf")
    mocker.patch.object(signing_public_routes, "check_rate_limit", return_value=True)
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

    create_response = client.post(
        "/api/signing/requests",
        headers=AUTH_HEADERS,
        json={
            "title": "Racey Review Request",
            "mode": "sign",
            "signatureMode": "business",
            "sourceType": "workspace",
            "sourceDocumentName": "Racey Packet",
            "sourcePdfSha256": source_sha256,
            "documentCategory": "ordinary_business_form",
            "manualFallbackEnabled": True,
            "signerName": "Alex Signer",
            "signerEmail": "alex@example.com",
            "anchors": [
                {
                    "kind": "signature",
                    "page": 1,
                    "rect": {"x": 100, "y": 400, "width": 180, "height": 36},
                }
            ],
        },
    )
    request_payload = create_response.json()["request"]
    request_id = request_payload["id"]
    public_token = build_signing_public_token(request_id)

    send_response = client.post(
        f"/api/signing/requests/{request_id}/send",
        headers=AUTH_HEADERS,
        files={"pdf": ("racey.pdf", source_pdf_bytes, "application/pdf")},
        data={"sourcePdfSha256": source_sha256},
    )
    assert send_response.status_code == 200

    bootstrap_response = client.post(f"/api/signing/public/{public_token}/bootstrap")
    assert bootstrap_response.status_code == 200
    session_token = bootstrap_response.json()["session"]["token"]

    current_record = signing_database.get_signing_request(request_id, client=firestore_client)
    assert current_record is not None
    stale_completed_record = replace(
        current_record,
        status="completed",
        completed_at="2026-03-25T10:00:00+00:00",
    )

    mocker.patch.object(signing_public_routes, "mark_signing_request_reviewed", return_value=stale_completed_record)
    record_event_mock = mocker.patch.object(signing_public_routes, "record_signing_event")

    review_response = client.post(
        f"/api/signing/public/{public_token}/review",
        headers={"X-Signing-Session": session_token},
        json={"reviewConfirmed": True},
    )

    assert review_response.status_code == 409
    assert "completed" in review_response.json()["detail"].lower()
    record_event_mock.assert_not_called()


def test_public_signing_bootstrap_rejects_stale_open_transition_without_logging_events(client: TestClient, mocker) -> None:
    firestore_client = FakeFirestoreClient()
    request_user = _signing_user()
    source_pdf_bytes = _pdf_bytes()
    source_sha256 = sha256_hex_for_bytes(source_pdf_bytes)

    mocker.patch.object(signing_database, "get_firestore_client", return_value=firestore_client)
    mocker.patch.object(signing_routes, "require_user", return_value=request_user)
    mocker.patch.object(signing_routes, "upload_signing_pdf_bytes", return_value="gs://signing-bucket/users/user-signing/signing/req/source.pdf")
    mocker.patch.object(signing_public_routes, "check_rate_limit", return_value=True)
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

    create_response = client.post(
        "/api/signing/requests",
        headers=AUTH_HEADERS,
        json={
            "title": "Racey Bootstrap Request",
            "mode": "sign",
            "signatureMode": "business",
            "sourceType": "workspace",
            "sourceDocumentName": "Racey Bootstrap Packet",
            "sourcePdfSha256": source_sha256,
            "documentCategory": "ordinary_business_form",
            "manualFallbackEnabled": True,
            "signerName": "Alex Signer",
            "signerEmail": "alex@example.com",
            "anchors": [
                {
                    "kind": "signature",
                    "page": 1,
                    "rect": {"x": 100, "y": 400, "width": 180, "height": 36},
                }
            ],
        },
    )
    request_payload = create_response.json()["request"]
    request_id = request_payload["id"]
    public_token = build_signing_public_token(request_id)

    send_response = client.post(
        f"/api/signing/requests/{request_id}/send",
        headers=AUTH_HEADERS,
        files={"pdf": ("racey-bootstrap.pdf", source_pdf_bytes, "application/pdf")},
        data={"sourcePdfSha256": source_sha256},
    )
    assert send_response.status_code == 200

    current_record = signing_database.get_signing_request(request_id, client=firestore_client)
    assert current_record is not None
    stale_completed_record = replace(
        current_record,
        status="completed",
        completed_at="2026-03-25T10:15:00+00:00",
    )

    mocker.patch.object(signing_public_routes, "mark_signing_request_opened", return_value=stale_completed_record)
    record_event_mock = mocker.patch.object(signing_public_routes, "record_signing_event")

    bootstrap_response = client.post(f"/api/signing/public/{public_token}/bootstrap")

    assert bootstrap_response.status_code == 409
    assert "completed" in bootstrap_response.json()["detail"].lower()
    record_event_mock.assert_not_called()


def test_public_signing_complete_cleans_up_uploaded_artifacts_on_stale_completion(client: TestClient, mocker) -> None:
    firestore_client = FakeFirestoreClient()
    request_user = _signing_user()
    source_pdf_bytes = _pdf_bytes()
    source_sha256 = sha256_hex_for_bytes(source_pdf_bytes)
    stored_objects: dict[str, bytes] = {}

    def _fake_upload_pdf_bytes(payload: bytes, destination_path: str) -> str:
        uri = f"gs://signing-bucket/{destination_path}"
        stored_objects[uri] = bytes(payload)
        return uri

    def _fake_upload_json(payload, destination_path: str) -> str:
        uri = f"gs://signing-bucket/{destination_path}"
        stored_objects[uri] = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return uri

    def _fake_download_storage_bytes(bucket_path: str) -> bytes:
        return stored_objects[bucket_path]

    def _fake_delete_storage_object(bucket_path: str) -> None:
        stored_objects.pop(bucket_path, None)

    mocker.patch.object(signing_database, "get_firestore_client", return_value=firestore_client)
    mocker.patch.object(signing_routes, "require_user", return_value=request_user)
    mocker.patch.object(signing_routes, "upload_signing_pdf_bytes", side_effect=_fake_upload_pdf_bytes)
    mocker.patch.object(signing_public_routes, "check_rate_limit", return_value=True)
    mocker.patch.object(signing_public_routes, "upload_signing_pdf_bytes", side_effect=_fake_upload_pdf_bytes)
    mocker.patch.object(signing_public_routes, "upload_signing_json", side_effect=_fake_upload_json)
    mocker.patch.object(signing_public_routes, "download_storage_bytes", side_effect=_fake_download_storage_bytes)
    mocker.patch.object(signing_public_routes, "delete_storage_object", side_effect=_fake_delete_storage_object)
    mocker.patch.object(signing_public_routes, "build_signing_bucket_uri", side_effect=lambda path: f"gs://signing-bucket/{path}")
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

    create_response = client.post(
        "/api/signing/requests",
        headers=AUTH_HEADERS,
        json={
            "title": "Racey Complete Request",
            "mode": "sign",
            "signatureMode": "business",
            "sourceType": "workspace",
            "sourceDocumentName": "Racey Complete Packet",
            "sourcePdfSha256": source_sha256,
            "documentCategory": "ordinary_business_form",
            "manualFallbackEnabled": True,
            "signerName": "Alex Signer",
            "signerEmail": "alex@example.com",
            "anchors": [
                {
                    "kind": "signature",
                    "page": 1,
                    "rect": {"x": 100, "y": 400, "width": 180, "height": 36},
                }
            ],
        },
    )
    request_payload = create_response.json()["request"]
    request_id = request_payload["id"]
    public_token = build_signing_public_token(request_id)

    send_response = client.post(
        f"/api/signing/requests/{request_id}/send",
        headers=AUTH_HEADERS,
        files={"pdf": ("racey-complete.pdf", source_pdf_bytes, "application/pdf")},
        data={"sourcePdfSha256": source_sha256},
    )
    assert send_response.status_code == 200

    source_path = send_response.json()["request"]["sourcePdfPath"]
    stored_objects[source_path] = source_pdf_bytes

    bootstrap_response = client.post(f"/api/signing/public/{public_token}/bootstrap")
    assert bootstrap_response.status_code == 200
    session_token = bootstrap_response.json()["session"]["token"]

    review_response = client.post(
        f"/api/signing/public/{public_token}/review",
        headers={"X-Signing-Session": session_token},
        json={"reviewConfirmed": True},
    )
    assert review_response.status_code == 200

    adopt_response = client.post(
        f"/api/signing/public/{public_token}/adopt-signature",
        headers={"X-Signing-Session": session_token},
        json={"adoptedName": "Alex Signer"},
    )
    assert adopt_response.status_code == 200

    current_record = signing_database.get_signing_request(request_id, client=firestore_client)
    assert current_record is not None
    stale_sent_record = replace(current_record, status="sent")
    mocker.patch.object(signing_public_routes, "complete_signing_request", return_value=stale_sent_record)

    complete_response = client.post(
        f"/api/signing/public/{public_token}/complete",
        headers={"X-Signing-Session": session_token},
        json={"intentConfirmed": True},
    )

    assert complete_response.status_code == 409
    assert "ready for review and signature" in complete_response.json()["detail"].lower()
    assert list(stored_objects.keys()) == [source_path]
