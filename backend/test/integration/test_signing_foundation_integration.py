"""Integration coverage for signing foundation routes."""

from __future__ import annotations

import base64
from dataclasses import replace
from io import BytesIO
import json
from types import SimpleNamespace

from asn1crypto import pem as asn1_pem
from asn1crypto import x509 as asn1_x509
from fastapi.testclient import TestClient
import pytest
from PIL import Image, ImageDraw
from pypdf import PdfReader
from pyhanko.pdf_utils.reader import PdfFileReader
from pyhanko.sign.validation import validate_pdf_signature
from pyhanko_certvalidator import ValidationContext

import backend.main as main
import backend.api.middleware.security as security_middleware
import backend.api.routes.signing as signing_routes
import backend.api.routes.signing_public as signing_public_routes
import backend.firebaseDB.signing_database as signing_database
import backend.firebaseDB.user_database as user_database
import backend.services.signing_provenance_service as signing_provenance_service
from backend.services.signing_audit_service import verify_signing_audit_envelope
import backend.services.signing_pdf_digital_service as signing_pdf_digital_service
from backend.services.signing_pdf_digital_service import export_pdf_signing_certificate_pem
from backend.services.signing_service import (
    build_signing_consumer_access_code,
    build_signing_public_token,
    sha256_hex_for_bytes,
)
from backend.services.signing_verification_service import SigningVerificationDeliveryResult
from backend.test.integration.signing_test_support import (
    AUTH_HEADERS,
    InMemorySigningStorage,
    bootstrap_and_verify_public_signing_session as _bootstrap_and_verify_public_signing_session,
    mock_signing_verification_delivery as _mock_signing_verification_delivery,
    patch_signing_artifact_storage,
    patch_signing_authenticated_owner,
    pdf_bytes as _pdf_bytes,
    signing_user as _signing_user,
)
from backend.test.unit.firebase._fakes import FakeFirestoreClient


@pytest.fixture
def client() -> TestClient:
    return TestClient(main.app)


@pytest.fixture(autouse=True)
def allow_public_signing_rate_limits(mocker) -> None:
    mocker.patch.object(signing_public_routes, "_check_public_rate_limits", return_value=True)


def _patch_owner_signing_environment(
    mocker,
    firestore_client,
    request_user,
    *,
    storage: InMemorySigningStorage | None = None,
    stream_pdf_bytes: bytes | None = None,
    mock_digital_signing: bool = True,
) -> InMemorySigningStorage:
    resolved_storage = storage or InMemorySigningStorage()
    mocker.patch.object(signing_database, "get_firestore_client", return_value=firestore_client)
    patch_signing_authenticated_owner(mocker, request_user)
    patch_signing_artifact_storage(
        mocker,
        resolved_storage,
        stream_pdf_bytes=stream_pdf_bytes,
        mock_digital_signing=mock_digital_signing,
    )
    return resolved_storage


def _owner_signing_create_payload(source_pdf_bytes: bytes, **overrides) -> dict:
    payload = {
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
        "esignEligibilityConfirmed": True,
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
    }
    payload.update(overrides)
    return payload


def _signature_image_data_url() -> str:
    image = Image.new("RGBA", (240, 96), (255, 255, 255, 0))
    draw = ImageDraw.Draw(image)
    draw.line((18, 62, 78, 34, 146, 60, 220, 28), fill=(17, 24, 39, 255), width=6)
    output = BytesIO()
    image.save(output, format="PNG")
    return "data:image/png;base64," + base64.b64encode(output.getvalue()).decode("ascii")


def _configure_bundled_pdf_signing_identity(monkeypatch) -> None:
    for name in (
        "SIGNING_PDF_PKCS12_B64",
        "SIGNING_PDF_PKCS12_PASSWORD",
        "SIGNING_PDF_P12_BASE64",
        "SIGNING_PDF_P12_PATH",
        "SIGNING_PDF_P12_PASSWORD",
        "SIGNING_PDF_CERT_PEM",
        "SIGNING_PDF_CERT_PEM_BASE64",
        "SIGNING_PDF_CERT_PATH",
        "SIGNING_PDF_CERT_CHAIN_PEM",
        "SIGNING_PDF_CERT_CHAIN_PEM_BASE64",
        "SIGNING_PDF_CERT_CHAIN_PATH",
        "SIGNING_PDF_KMS_KEY",
        "SIGNING_AUDIT_KMS_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("SIGNING_PDF_USE_BUNDLED_DEV_CERT", "1")
    signing_pdf_digital_service._resolve_pdf_signing_identity.cache_clear()


def _seed_openai_credit_profile(
    firestore_client: FakeFirestoreClient,
    request_user,
    *,
    credits: int = 7,
) -> None:
    firestore_client.collection(user_database.USERS_COLLECTION).document(request_user.app_user_id).seed(
        {
            "email": request_user.email,
            "displayName": request_user.display_name,
            user_database.ROLE_FIELD: request_user.role,
            user_database.OPENAI_CREDITS_FIELD: credits,
            user_database.OPENAI_CREDITS_REFILL_FIELD: 0,
            "created_at": "2026-03-28T00:00:00+00:00",
            "updated_at": "2026-03-28T00:00:00+00:00",
        }
    )


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
            "esignEligibilityConfirmed": True,
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
    assert create_payload["verificationRequired"] is True
    assert create_payload["verificationMethod"] == "email_otp"
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
    assert public_payload["verificationRequired"] is True
    assert public_payload["sourceDocumentName"] == "Bravo Packet"
    assert public_payload["anchors"][0]["fieldName"] == "signature_primary"


def test_signing_owner_create_enforces_per_document_limit_and_revoked_drafts_release_slots(
    client: TestClient,
    mocker,
    monkeypatch,
) -> None:
    firestore_client = FakeFirestoreClient()
    request_user = _signing_user()
    source_pdf_bytes = _pdf_bytes()

    monkeypatch.setenv("SANDBOX_SIGNING_REQUESTS_PER_DOCUMENT_MAX_BASE", "1")
    mocker.patch.object(signing_database, "get_firestore_client", return_value=firestore_client)
    patch_signing_authenticated_owner(mocker, request_user)

    first_response = client.post(
        "/api/signing/requests",
        headers=AUTH_HEADERS,
        json=_owner_signing_create_payload(source_pdf_bytes),
    )

    assert first_response.status_code == 201
    first_request_id = first_response.json()["request"]["id"]

    blocked_response = client.post(
        "/api/signing/requests",
        headers=AUTH_HEADERS,
        json=_owner_signing_create_payload(
            source_pdf_bytes,
            signerEmail="jamie@example.com",
            signerName="Jamie Signer",
        ),
    )

    assert blocked_response.status_code == 403
    assert "1 signature request limit" in blocked_response.json()["detail"]

    revoke_response = client.post(
        f"/api/signing/requests/{first_request_id}/revoke",
        headers=AUTH_HEADERS,
    )

    assert revoke_response.status_code == 200
    assert revoke_response.json()["request"]["status"] == "invalidated"

    replacement_response = client.post(
        "/api/signing/requests",
        headers=AUTH_HEADERS,
        json=_owner_signing_create_payload(
            source_pdf_bytes,
            signerEmail="jamie@example.com",
            signerName="Jamie Signer",
        ),
    )

    assert replacement_response.status_code == 201


def test_signing_owner_create_keeps_sent_request_slots_consumed_after_revoke(
    client: TestClient,
    mocker,
    monkeypatch,
) -> None:
    firestore_client = FakeFirestoreClient()
    request_user = _signing_user()
    source_pdf_bytes = _pdf_bytes()
    storage = InMemorySigningStorage()

    monkeypatch.setenv("SANDBOX_SIGNING_REQUESTS_PER_DOCUMENT_MAX_BASE", "1")
    mocker.patch.object(signing_database, "get_firestore_client", return_value=firestore_client)
    patch_signing_authenticated_owner(mocker, request_user)
    patch_signing_artifact_storage(mocker, storage)

    create_response = client.post(
        "/api/signing/requests",
        headers=AUTH_HEADERS,
        json=_owner_signing_create_payload(source_pdf_bytes),
    )

    assert create_response.status_code == 201
    request_id = create_response.json()["request"]["id"]

    send_response = client.post(
        f"/api/signing/requests/{request_id}/send",
        headers=AUTH_HEADERS,
        files={"pdf": ("bravo.pdf", source_pdf_bytes, "application/pdf")},
        data={"sourcePdfSha256": sha256_hex_for_bytes(source_pdf_bytes)},
    )

    assert send_response.status_code == 200
    assert send_response.json()["request"]["status"] == "sent"

    revoke_response = client.post(
        f"/api/signing/requests/{request_id}/revoke",
        headers=AUTH_HEADERS,
    )

    assert revoke_response.status_code == 200
    assert revoke_response.json()["request"]["status"] == "invalidated"

    blocked_response = client.post(
        "/api/signing/requests",
        headers=AUTH_HEADERS,
        json=_owner_signing_create_payload(
            source_pdf_bytes,
            signerEmail="jamie@example.com",
            signerName="Jamie Signer",
        ),
    )

    assert blocked_response.status_code == 403
    assert "1 signature request limit" in blocked_response.json()["detail"]


def test_signing_owner_create_and_send_do_not_debit_openai_credits(
    client: TestClient,
    mocker,
) -> None:
    firestore_client = FakeFirestoreClient()
    request_user = _signing_user()
    source_pdf_bytes = _pdf_bytes()
    storage = InMemorySigningStorage()

    _seed_openai_credit_profile(firestore_client, request_user, credits=7)
    mocker.patch.object(signing_database, "get_firestore_client", return_value=firestore_client)
    mocker.patch.object(user_database, "get_firestore_client", return_value=firestore_client)
    patch_signing_authenticated_owner(mocker, request_user)
    patch_signing_artifact_storage(mocker, storage)

    before_profile = user_database.get_user_profile(request_user.app_user_id)
    assert before_profile is not None
    assert before_profile.openai_credits_remaining == 7
    assert before_profile.openai_credits_available == 7

    create_response = client.post(
        "/api/signing/requests",
        headers=AUTH_HEADERS,
        json=_owner_signing_create_payload(source_pdf_bytes),
    )

    assert create_response.status_code == 201
    request_id = create_response.json()["request"]["id"]

    send_response = client.post(
        f"/api/signing/requests/{request_id}/send",
        headers=AUTH_HEADERS,
        files={"pdf": ("bravo.pdf", source_pdf_bytes, "application/pdf")},
        data={"sourcePdfSha256": sha256_hex_for_bytes(source_pdf_bytes)},
    )

    assert send_response.status_code == 200
    assert send_response.json()["request"]["status"] == "sent"

    after_profile = user_database.get_user_profile(request_user.app_user_id)
    assert after_profile is not None
    assert after_profile.openai_credits_remaining == 7
    assert after_profile.openai_credits_available == 7

    stored_user = firestore_client.collection(user_database.USERS_COLLECTION).document(request_user.app_user_id).get().to_dict()
    assert stored_user[user_database.OPENAI_CREDITS_FIELD] == 7


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
            "esignEligibilityConfirmed": True,
            "manualFallbackEnabled": True,
            "signerName": "Blocked Signer",
            "signerEmail": "blocked@example.com",
            "anchors": [],
        },
    )

    assert response.status_code == 400
    assert "blocked" in response.json()["detail"].lower()


def test_signing_foundation_requires_explicit_esign_eligibility_attestation(client: TestClient, mocker) -> None:
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
            "sourceDocumentName": "Business Packet",
            "sourcePdfSha256": sha256_hex_for_bytes(_pdf_bytes()),
            "documentCategory": "ordinary_business_form",
            "manualFallbackEnabled": True,
            "signerName": "Alex Signer",
            "signerEmail": "alex@example.com",
            "anchors": [],
        },
    )

    assert response.status_code == 400
    assert "eligible for dullypdf" in response.json()["detail"].lower()


def test_signing_send_transitions_draft_to_sent_with_immutable_snapshot(client: TestClient, mocker) -> None:
    firestore_client = FakeFirestoreClient()
    request_user = _signing_user()
    source_pdf_bytes = _pdf_bytes()
    source_sha256 = sha256_hex_for_bytes(source_pdf_bytes)
    storage = InMemorySigningStorage()

    mocker.patch.object(signing_database, "get_firestore_client", return_value=firestore_client)
    patch_signing_authenticated_owner(mocker, request_user)
    patch_signing_artifact_storage(mocker, storage)

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
            "esignEligibilityConfirmed": True,
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
    firestore_client.collection(signing_database.SIGNING_REQUESTS_COLLECTION).document(request_id).set(
        {
            "verification_required": False,
            "verification_method": None,
        },
        merge=True,
    )

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
    assert sent_payload["sourcePdfPath"].startswith(
        f"gs://signing-bucket/users/user-signing/signing/{request_id}/source/"
    )
    assert sent_payload["sourcePdfPath"].endswith(".pdf")
    assert storage.download_storage_bytes(sent_payload["sourcePdfPath"]) == source_pdf_bytes
    assert sent_payload["sentAt"]
    assert sent_payload["verificationRequired"] is True
    assert sent_payload["verificationMethod"] == "email_otp"


def test_owner_manual_share_records_provenance_event(client: TestClient, mocker) -> None:
    firestore_client = FakeFirestoreClient()
    request_user = _signing_user()
    source_pdf_bytes = _pdf_bytes()
    source_sha256 = sha256_hex_for_bytes(source_pdf_bytes)
    _patch_owner_signing_environment(mocker, firestore_client, request_user)

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
            "esignEligibilityConfirmed": True,
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

    manual_share_response = client.post(
        f"/api/signing/requests/{request_id}/manual-share",
        headers=AUTH_HEADERS,
    )
    assert manual_share_response.status_code == 200
    shared_payload = manual_share_response.json()["request"]
    assert shared_payload["inviteMethod"] == "manual_link"
    assert shared_payload["manualLinkSharedAt"]
    assert shared_payload["senderEmail"] == "owner@example.com"

    event_types = [event.event_type for event in signing_database.list_signing_events_for_request(request_id, client=firestore_client)]
    assert event_types == [
        "request_created",
        "request_sent",
        "invite_skipped",
        "manual_link_shared",
    ]


def test_signing_send_cleans_up_uploaded_source_when_transition_turns_stale(client: TestClient, mocker) -> None:
    firestore_client = FakeFirestoreClient()
    request_user = _signing_user()
    source_pdf_bytes = _pdf_bytes()
    source_sha256 = sha256_hex_for_bytes(source_pdf_bytes)
    deleted_paths: list[str] = []

    storage = _patch_owner_signing_environment(mocker, firestore_client, request_user)
    mocker.patch.object(
        signing_routes,
        "delete_storage_object",
        side_effect=lambda bucket_path: (deleted_paths.append(bucket_path), storage.delete_storage_object(bucket_path))[1],
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
            "esignEligibilityConfirmed": True,
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
    assert len(deleted_paths) == 1
    assert "/_staging/users/user-signing/signing/" in deleted_paths[0]
    assert deleted_paths[0].endswith(".pdf")


def test_signing_send_invalidates_draft_when_source_pdf_changes(client: TestClient, mocker) -> None:
    firestore_client = FakeFirestoreClient()
    request_user = _signing_user()
    original_pdf_bytes = _pdf_bytes()
    changed_pdf_bytes = _pdf_bytes(width=201, height=200)
    _patch_owner_signing_environment(mocker, firestore_client, request_user)

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
            "esignEligibilityConfirmed": True,
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
    _patch_owner_signing_environment(mocker, firestore_client, request_user)

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
            "esignEligibilityConfirmed": True,
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
    storage = InMemorySigningStorage()

    mocker.patch.object(signing_database, "get_firestore_client", return_value=firestore_client)
    patch_signing_authenticated_owner(mocker, request_user)
    patch_signing_artifact_storage(mocker, storage)

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
            "esignEligibilityConfirmed": True,
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
    assert sent_payload["sourcePdfPath"].startswith(
        f"gs://signing-bucket/users/user-signing/signing/{request_id}/source/"
    )
    assert sent_payload["sourcePdfPath"].endswith(".pdf")
    assert storage.download_storage_bytes(sent_payload["sourcePdfPath"]) == source_pdf_bytes
    assert sent_payload["ownerReviewConfirmedAt"]


def test_public_signing_happy_path_records_ceremony_evidence(client: TestClient, mocker) -> None:
    firestore_client = FakeFirestoreClient()
    request_user = _signing_user()
    source_pdf_bytes = _pdf_bytes()
    source_sha256 = sha256_hex_for_bytes(source_pdf_bytes)
    storage = InMemorySigningStorage()

    _mock_signing_verification_delivery(mocker)
    owner_webhook_mock = mocker.patch.object(signing_provenance_service, "dispatch_signing_webhook_event")
    public_webhook_mock = mocker.patch.object(signing_public_routes, "dispatch_signing_webhook_event")
    mocker.patch.object(signing_database, "get_firestore_client", return_value=firestore_client)
    patch_signing_authenticated_owner(mocker, request_user)
    patch_signing_artifact_storage(mocker, storage, stream_pdf_bytes=source_pdf_bytes)

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
            "esignEligibilityConfirmed": True,
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
    assert preview_response.json()["request"]["isExpired"] is False
    assert preview_response.json()["request"]["verificationRequired"] is True

    browser_headers = {"User-Agent": "integration-browser/1.0"}
    session_token = _bootstrap_and_verify_public_signing_session(
        client,
        public_token,
        browser_headers=browser_headers,
    )
    bootstrap_payload = client.get(f"/api/signing/public/{public_token}").json()
    assert bootstrap_payload["request"]["verificationCompletedAt"]
    assert bootstrap_payload["request"]["openedAt"]
    assert bootstrap_payload["request"]["expiresAt"]

    document_response = client.get(
        f"/api/signing/public/{public_token}/document",
        headers={"X-Signing-Session": session_token, **browser_headers},
    )
    assert document_response.status_code == 200
    assert document_response.headers["content-type"].startswith("application/pdf")

    review_response = client.post(
        f"/api/signing/public/{public_token}/review",
        headers={"X-Signing-Session": session_token, **browser_headers},
        json={"reviewConfirmed": True},
    )
    assert review_response.status_code == 200
    assert review_response.json()["request"]["reviewedAt"]

    adopt_response = client.post(
        f"/api/signing/public/{public_token}/adopt-signature",
        headers={"X-Signing-Session": session_token, **browser_headers},
        json={"adoptedName": "Alex Signer"},
    )
    assert adopt_response.status_code == 200
    assert adopt_response.json()["request"]["signatureAdoptedName"] == "Alex Signer"

    complete_response = client.post(
        f"/api/signing/public/{public_token}/complete",
        headers={"X-Signing-Session": session_token, **browser_headers},
        json={"intentConfirmed": True},
    )
    assert complete_response.status_code == 200
    assert complete_response.json()["request"]["status"] == "completed"
    assert complete_response.json()["request"]["completedAt"]
    assert complete_response.json()["request"]["validationPath"].startswith("/verify-signing/")
    assert complete_response.json()["request"]["artifacts"]["signedPdf"]["available"] is True
    assert complete_response.json()["request"]["artifacts"]["signedPdf"]["downloadPath"] is None
    assert complete_response.json()["request"]["artifacts"]["auditReceipt"]["available"] is True
    assert complete_response.json()["request"]["artifacts"]["auditReceipt"]["downloadPath"] is None

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
    assert detail_payload["validationPath"].startswith("/verify-signing/")

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
    assert envelope_payload["manifest"]["signer"]["email"] == "alex@example.com"
    assert envelope_payload["manifest"]["sender"]["ownerUserId"] == "user-signing"
    assert envelope_payload["manifest"]["sender"]["senderEmail"] == "owner@example.com"
    assert envelope_payload["manifest"]["sender"]["inviteMethod"] == "email"
    assert envelope_payload["manifest"]["sender"]["inviteDeliveryStatus"] == "skipped"

    owner_signed_pdf_download = client.get(
        f"/api/signing/requests/{request_id}/artifacts/signed_pdf",
        headers=AUTH_HEADERS,
    )
    assert owner_signed_pdf_download.status_code == 200
    assert owner_signed_pdf_download.headers["content-type"].startswith("application/pdf")

    stale_public_receipt_route = client.get(
        f"/api/signing/public/{public_token}/artifacts/audit_receipt",
        headers={"X-Signing-Session": session_token, **browser_headers},
    )
    assert stale_public_receipt_route.status_code == 410

    public_receipt_without_session = client.post(f"/api/signing/public/{public_token}/artifacts/audit_receipt/issue")
    assert public_receipt_without_session.status_code == 401

    public_receipt_issue = client.post(
        f"/api/signing/public/{public_token}/artifacts/audit_receipt/issue",
        headers={"X-Signing-Session": session_token, **browser_headers},
    )
    assert public_receipt_issue.status_code == 200
    public_receipt_download_path = public_receipt_issue.json()["downloadPath"]
    assert public_token not in public_receipt_download_path

    public_signed_pdf_issue = client.post(
        f"/api/signing/public/{public_token}/artifacts/signed_pdf/issue",
        headers={"X-Signing-Session": session_token, **browser_headers},
    )
    assert public_signed_pdf_issue.status_code == 200
    public_signed_pdf_download_path = public_signed_pdf_issue.json()["downloadPath"]
    assert public_token not in public_signed_pdf_download_path

    public_receipt_download = client.get(
        public_receipt_download_path,
        headers={"X-Signing-Session": session_token, **browser_headers},
    )
    assert public_receipt_download.status_code == 200
    assert public_receipt_download.headers["content-type"].startswith("application/pdf")
    receipt_text = "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(public_receipt_download.content)).pages)
    assert "Validation URL: http://localhost:5173/verify-signing/" in receipt_text
    assert "alex@example.com" not in receipt_text
    assert "integration-browser/1.0" not in receipt_text
    assert "203.0.113" not in receipt_text

    public_signed_pdf_download = client.get(
        public_signed_pdf_download_path,
        headers={"X-Signing-Session": session_token, **browser_headers},
    )
    assert public_signed_pdf_download.status_code == 200
    assert public_signed_pdf_download.headers["content-type"].startswith("application/pdf")

    validation_token = str(detail_payload["validationPath"]).split("/verify-signing/", 1)[-1]
    validation_response = client.get(f"/api/signing/public/validation/{validation_token}")
    assert validation_response.status_code == 200
    validation_payload = validation_response.json()["validation"]
    assert validation_payload["valid"] is True
    assert validation_payload["requestId"] == request_id
    assert validation_payload["checks"]
    assert all(check["passed"] for check in validation_payload["checks"])

    event_types = [event.event_type for event in signing_database.list_signing_events_for_request(request_id, client=firestore_client)]
    assert event_types == [
        "request_created",
        "request_sent",
        "invite_skipped",
        "session_started",
        "opened",
        "verification_started",
        "verification_passed",
        "document_accessed",
        "review_confirmed",
        "signature_adopted",
        "completed",
    ]
    assert [call.kwargs["event_type"] for call in owner_webhook_mock.call_args_list] == [
        "request_created",
        "request_sent",
        "invite_skipped",
    ]
    assert [call.kwargs["event_type"] for call in public_webhook_mock.call_args_list] == [
        "session_started",
        "opened",
        "verification_started",
        "verification_passed",
        "document_accessed",
        "review_confirmed",
        "signature_adopted",
        "completed",
    ]


def test_public_signing_completion_embeds_valid_pdf_signature(client: TestClient, mocker, monkeypatch) -> None:
    firestore_client = FakeFirestoreClient()
    request_user = _signing_user()
    source_pdf_bytes = _pdf_bytes()
    source_sha256 = sha256_hex_for_bytes(source_pdf_bytes)
    storage = InMemorySigningStorage()

    _configure_bundled_pdf_signing_identity(monkeypatch)
    _mock_signing_verification_delivery(mocker)
    mocker.patch.object(signing_database, "get_firestore_client", return_value=firestore_client)
    patch_signing_authenticated_owner(mocker, request_user)
    patch_signing_artifact_storage(
        mocker,
        storage,
        stream_pdf_bytes=source_pdf_bytes,
        mock_digital_signing=False,
    )

    create_response = client.post(
        "/api/signing/requests",
        headers=AUTH_HEADERS,
        json={
            "title": "Digitally Signed Packet",
            "mode": "sign",
            "signatureMode": "business",
            "sourceType": "workspace",
            "sourceId": "form-digital",
            "sourceDocumentName": "Digitally Signed Packet",
            "sourceTemplateId": "form-digital",
            "sourceTemplateName": "Digitally Signed Packet",
            "sourcePdfSha256": source_sha256,
            "documentCategory": "ordinary_business_form",
            "esignEligibilityConfirmed": True,
            "manualFallbackEnabled": True,
            "signerName": "Alex Signer",
            "signerEmail": "alex@example.com",
            "anchors": [
                {
                    "kind": "signature",
                    "page": 1,
                    "rect": {"x": 80, "y": 120, "width": 160, "height": 40},
                }
            ],
        },
    )
    request_id = create_response.json()["request"]["id"]
    public_token = build_signing_public_token(request_id)

    send_response = client.post(
        f"/api/signing/requests/{request_id}/send",
        headers=AUTH_HEADERS,
        files={"pdf": ("digitally-signed.pdf", source_pdf_bytes, "application/pdf")},
        data={"sourcePdfSha256": source_sha256},
    )
    assert send_response.status_code == 200

    session_token = _bootstrap_and_verify_public_signing_session(client, public_token)

    review_response = client.post(
        f"/api/signing/public/{public_token}/review",
        headers={"X-Signing-Session": session_token},
        json={"reviewConfirmed": True},
    )
    assert review_response.status_code == 200

    adopt_response = client.post(
        f"/api/signing/public/{public_token}/adopt-signature",
        headers={"X-Signing-Session": session_token},
        json={
            "signatureType": "drawn",
            "adoptedName": "Alex Signer",
            "signatureImageDataUrl": _signature_image_data_url(),
        },
    )
    assert adopt_response.status_code == 200
    adopt_payload = adopt_response.json()["request"]
    assert adopt_payload["signatureAdoptedMode"] == "drawn"
    assert adopt_payload["signatureAdoptedImageDataUrl"].startswith("data:image/png;base64,")

    complete_response = client.post(
        f"/api/signing/public/{public_token}/complete",
        headers={"X-Signing-Session": session_token},
        json={"intentConfirmed": True},
    )
    assert complete_response.status_code == 200
    complete_payload = complete_response.json()["request"]
    assert complete_payload["status"] == "completed"
    assert complete_payload["artifacts"]["signedPdf"]["digitalSignature"]["available"] is True
    assert complete_payload["artifacts"]["signedPdf"]["digitalSignature"]["method"] == "dev_pem"
    assert complete_payload["artifacts"]["signedPdf"]["digitalSignature"]["fieldName"] == "DullyPDFDigitalSignature"

    owner_signed_pdf_download = client.get(
        f"/api/signing/requests/{request_id}/artifacts/signed_pdf",
        headers=AUTH_HEADERS,
    )
    assert owner_signed_pdf_download.status_code == 200

    pdf_reader = PdfFileReader(BytesIO(owner_signed_pdf_download.content), strict=False)
    embedded_signatures = list(pdf_reader.embedded_signatures)
    assert len(embedded_signatures) == 1

    cert_pem = export_pdf_signing_certificate_pem()
    _, _, cert_der = asn1_pem.unarmor(cert_pem)
    validation_context = ValidationContext(trust_roots=[asn1_x509.Certificate.load(cert_der)])
    validation_status = validate_pdf_signature(
        embedded_signatures[0],
        signer_validation_context=validation_context,
    )
    assert validation_status.bottom_line is True
    assert "TRUSTED" in validation_status.summary()


def test_public_signing_issued_artifact_links_require_the_same_completed_session(client: TestClient, mocker) -> None:
    firestore_client = FakeFirestoreClient()
    request_user = _signing_user()
    source_pdf_bytes = _pdf_bytes()
    source_sha256 = sha256_hex_for_bytes(source_pdf_bytes)
    storage = InMemorySigningStorage()

    _mock_signing_verification_delivery(mocker)
    mocker.patch.object(signing_database, "get_firestore_client", return_value=firestore_client)
    patch_signing_authenticated_owner(mocker, request_user)
    patch_signing_artifact_storage(mocker, storage, stream_pdf_bytes=source_pdf_bytes)

    create_response = client.post(
        "/api/signing/requests",
        headers=AUTH_HEADERS,
        json={
            "title": "Artifact Session Binding Request",
            "mode": "sign",
            "signatureMode": "business",
            "sourceType": "workspace",
            "sourceId": "form-artifact-binding",
            "sourceDocumentName": "Binding Packet",
            "sourceTemplateId": "form-artifact-binding",
            "sourceTemplateName": "Binding Packet",
            "sourcePdfSha256": source_sha256,
            "documentCategory": "ordinary_business_form",
            "esignEligibilityConfirmed": True,
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
    request_id = create_response.json()["request"]["id"]
    public_token = build_signing_public_token(request_id)

    send_response = client.post(
        f"/api/signing/requests/{request_id}/send",
        headers=AUTH_HEADERS,
        files={"pdf": ("binding.pdf", source_pdf_bytes, "application/pdf")},
        data={"sourcePdfSha256": source_sha256},
    )
    assert send_response.status_code == 200

    browser_headers = {"User-Agent": "integration-browser/1.0"}
    session_token = _bootstrap_and_verify_public_signing_session(
        client,
        public_token,
        browser_headers=browser_headers,
    )

    document_response = client.get(
        f"/api/signing/public/{public_token}/document",
        headers={"X-Signing-Session": session_token, **browser_headers},
    )
    assert document_response.status_code == 200

    review_response = client.post(
        f"/api/signing/public/{public_token}/review",
        headers={"X-Signing-Session": session_token, **browser_headers},
        json={"reviewConfirmed": True},
    )
    assert review_response.status_code == 200

    adopt_response = client.post(
        f"/api/signing/public/{public_token}/adopt-signature",
        headers={"X-Signing-Session": session_token, **browser_headers},
        json={"adoptedName": "Alex Signer"},
    )
    assert adopt_response.status_code == 200

    complete_response = client.post(
        f"/api/signing/public/{public_token}/complete",
        headers={"X-Signing-Session": session_token, **browser_headers},
        json={"intentConfirmed": True},
    )
    assert complete_response.status_code == 200

    receipt_issue_response = client.post(
        f"/api/signing/public/{public_token}/artifacts/audit_receipt/issue",
        headers={"X-Signing-Session": session_token, **browser_headers},
    )
    assert receipt_issue_response.status_code == 200
    receipt_download_path = receipt_issue_response.json()["downloadPath"]

    second_session_token = _bootstrap_and_verify_public_signing_session(
        client,
        public_token,
        browser_headers=browser_headers,
    )
    mismatched_session_download = client.get(
        receipt_download_path,
        headers={"X-Signing-Session": second_session_token, **browser_headers},
    )
    assert mismatched_session_download.status_code == 401
    assert "does not match this download" in mismatched_session_download.text.lower()

    matching_session_download = client.get(
        receipt_download_path,
        headers={"X-Signing-Session": session_token, **browser_headers},
    )
    assert matching_session_download.status_code == 200
    assert matching_session_download.headers["content-type"].startswith("application/pdf")


def test_public_signing_completion_rolls_back_when_final_artifact_promotion_fails(client: TestClient, mocker) -> None:
    firestore_client = FakeFirestoreClient()
    request_user = _signing_user()
    source_pdf_bytes = _pdf_bytes()
    source_sha256 = sha256_hex_for_bytes(source_pdf_bytes)
    storage = InMemorySigningStorage()

    _mock_signing_verification_delivery(mocker)
    mocker.patch.object(signing_database, "get_firestore_client", return_value=firestore_client)
    patch_signing_authenticated_owner(mocker, request_user)
    patch_signing_artifact_storage(mocker, storage, stream_pdf_bytes=source_pdf_bytes, patch_delete=True)

    create_response = client.post(
        "/api/signing/requests",
        headers=AUTH_HEADERS,
        json={
            "title": "Promotion Failure Request",
            "mode": "sign",
            "signatureMode": "business",
            "sourceType": "workspace",
            "sourceId": "form-promotion-failure",
            "sourceDocumentName": "Promotion Failure Packet",
            "sourceTemplateId": "form-promotion-failure",
            "sourceTemplateName": "Promotion Failure Packet",
            "sourcePdfSha256": source_sha256,
            "documentCategory": "ordinary_business_form",
            "esignEligibilityConfirmed": True,
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
    request_id = create_response.json()["request"]["id"]
    public_token = build_signing_public_token(request_id)

    send_response = client.post(
        f"/api/signing/requests/{request_id}/send",
        headers=AUTH_HEADERS,
        files={"pdf": ("promotion-failure.pdf", source_pdf_bytes, "application/pdf")},
        data={"sourcePdfSha256": source_sha256},
    )
    assert send_response.status_code == 200
    source_path = send_response.json()["request"]["sourcePdfPath"]

    session_token = _bootstrap_and_verify_public_signing_session(client, public_token)

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

    original_promote = storage.promote_staged_object

    def _fail_signed_artifact_promotion(final_bucket_path: str, *, retain_until: str | None = None, delete_stage: bool = True) -> str:
        if "/artifacts/signed_pdf/" in final_bucket_path:
            raise FileNotFoundError("missing finalized signing bucket")
        return original_promote(final_bucket_path, retain_until=retain_until, delete_stage=delete_stage)

    mocker.patch.object(
        signing_public_routes,
        "promote_signing_staged_object",
        side_effect=_fail_signed_artifact_promotion,
    )

    complete_response = client.post(
        f"/api/signing/public/{public_token}/complete",
        headers={"X-Signing-Session": session_token},
        json={"intentConfirmed": True},
    )

    assert complete_response.status_code == 503
    assert "failed to finalize retained signing artifacts" in complete_response.json()["detail"].lower()

    rolled_back_record = signing_database.get_signing_request(request_id, client=firestore_client)
    assert rolled_back_record is not None
    assert rolled_back_record.status == "sent"
    assert rolled_back_record.completed_at is None
    assert rolled_back_record.signed_pdf_bucket_path is None
    assert rolled_back_record.audit_manifest_bucket_path is None
    assert rolled_back_record.audit_receipt_bucket_path is None

    event_types = [event.event_type for event in signing_database.list_signing_events_for_request(request_id, client=firestore_client)]
    assert "completed" not in event_types
    assert list(storage.objects.keys()) == [source_path]


def test_public_signing_fill_link_requests_require_email_otp_before_document_review_and_completion(client: TestClient, mocker) -> None:
    firestore_client = FakeFirestoreClient()
    request_user = _signing_user()
    source_pdf_bytes = _pdf_bytes()
    source_sha256 = sha256_hex_for_bytes(source_pdf_bytes)
    storage = InMemorySigningStorage()
    verification_attempted_at = signing_public_routes.now_iso()
    verification_sent_at = signing_public_routes.now_iso()

    mocker.patch.object(signing_database, "get_firestore_client", return_value=firestore_client)
    patch_signing_authenticated_owner(mocker, request_user)
    patch_signing_artifact_storage(mocker, storage, stream_pdf_bytes=source_pdf_bytes)
    mocker.patch.object(signing_public_routes, "generate_signing_email_otp_code", return_value="123456")
    mocker.patch.object(
        signing_public_routes,
        "send_signing_verification_email",
        mocker.AsyncMock(
            return_value=SigningVerificationDeliveryResult(
                delivery_status="sent",
                attempted_at=verification_attempted_at,
                sent_at=verification_sent_at,
                message_id="gmail-verification-1",
            ),
        ),
    )
    create_response = client.post(
        "/api/signing/requests",
        headers=AUTH_HEADERS,
        json={
            "title": "Fill By Link Signature Request",
            "mode": "sign",
            "signatureMode": "business",
            "sourceType": "fill_link_response",
            "sourceId": "response-1",
            "sourceLinkId": "link-1",
            "sourceRecordLabel": "Ada Lovelace",
            "sourceDocumentName": "Submitted Packet",
            "sourceTemplateId": "template-1",
            "sourceTemplateName": "Submitted Packet",
            "sourcePdfSha256": source_sha256,
            "documentCategory": "ordinary_business_form",
            "esignEligibilityConfirmed": True,
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
        files={"pdf": ("submitted.pdf", source_pdf_bytes, "application/pdf")},
        data={"sourcePdfSha256": source_sha256},
    )
    assert send_response.status_code == 200

    preview_response = client.get(f"/api/signing/public/{public_token}")
    assert preview_response.status_code == 200
    preview_payload = preview_response.json()["request"]
    assert preview_payload["verificationRequired"] is True
    assert preview_payload["verificationMethod"] == "email_otp"
    assert preview_payload["signerEmailHint"] == "a***@example.com"

    browser_headers = {"User-Agent": "integration-browser/2.0"}
    bootstrap_response = client.post(
        f"/api/signing/public/{public_token}/bootstrap",
        headers=browser_headers,
    )
    assert bootstrap_response.status_code == 200
    bootstrap_payload = bootstrap_response.json()
    session_token = bootstrap_payload["session"]["token"]
    assert bootstrap_payload["session"]["verifiedAt"] is None

    document_response = client.get(
        f"/api/signing/public/{public_token}/document",
        headers={"X-Signing-Session": session_token, **browser_headers},
    )
    assert document_response.status_code == 403
    assert "verify the email code" in document_response.json()["detail"].lower()

    review_before_verify = client.post(
        f"/api/signing/public/{public_token}/review",
        headers={"X-Signing-Session": session_token, **browser_headers},
        json={"reviewConfirmed": True},
    )
    assert review_before_verify.status_code == 403
    assert "verify the email code" in review_before_verify.json()["detail"].lower()

    fallback_before_verify = client.post(
        f"/api/signing/public/{public_token}/manual-fallback",
        headers={"X-Signing-Session": session_token, **browser_headers},
        json={"note": "Need paper"},
    )
    assert fallback_before_verify.status_code == 403
    assert "verify the email code" in fallback_before_verify.json()["detail"].lower()

    send_code_response = client.post(
        f"/api/signing/public/{public_token}/verification/send",
        headers={"X-Signing-Session": session_token, **browser_headers},
    )
    assert send_code_response.status_code == 200
    assert send_code_response.json()["session"]["verificationSentAt"] == verification_sent_at

    immediate_resend_response = client.post(
        f"/api/signing/public/{public_token}/verification/send",
        headers={"X-Signing-Session": session_token, **browser_headers},
    )
    assert immediate_resend_response.status_code == 429
    assert "wait before requesting" in immediate_resend_response.json()["detail"].lower()

    wrong_code_response = client.post(
        f"/api/signing/public/{public_token}/verification/verify",
        headers={"X-Signing-Session": session_token, **browser_headers},
        json={"code": "000000"},
    )
    assert wrong_code_response.status_code == 400
    assert "invalid" in wrong_code_response.json()["detail"].lower()

    verify_response = client.post(
        f"/api/signing/public/{public_token}/verification/verify",
        headers={"X-Signing-Session": session_token, **browser_headers},
        json={"code": "123456"},
    )
    assert verify_response.status_code == 200
    assert verify_response.json()["session"]["verifiedAt"]
    assert verify_response.json()["request"]["verificationCompletedAt"]

    verified_document_response = client.get(
        f"/api/signing/public/{public_token}/document",
        headers={"X-Signing-Session": session_token, **browser_headers},
    )
    assert verified_document_response.status_code == 200
    assert verified_document_response.headers["content-type"].startswith("application/pdf")

    review_response = client.post(
        f"/api/signing/public/{public_token}/review",
        headers={"X-Signing-Session": session_token, **browser_headers},
        json={"reviewConfirmed": True},
    )
    assert review_response.status_code == 200

    adopt_response = client.post(
        f"/api/signing/public/{public_token}/adopt-signature",
        headers={"X-Signing-Session": session_token, **browser_headers},
        json={"adoptedName": "Alex Signer"},
    )
    assert adopt_response.status_code == 200

    complete_response = client.post(
        f"/api/signing/public/{public_token}/complete",
        headers={"X-Signing-Session": session_token, **browser_headers},
        json={"intentConfirmed": True},
    )
    assert complete_response.status_code == 200
    assert complete_response.json()["request"]["status"] == "completed"

    detail_response = client.get(f"/api/signing/requests/{request_id}", headers=AUTH_HEADERS)
    assert detail_response.status_code == 200
    detail_payload = detail_response.json()["request"]
    assert detail_payload["verificationRequired"] is True
    assert detail_payload["verificationMethod"] == "email_otp"
    assert detail_payload["verificationCompletedAt"]

    owner_manifest_download = client.get(
        f"/api/signing/requests/{request_id}/artifacts/audit_manifest",
        headers=AUTH_HEADERS,
    )
    assert owner_manifest_download.status_code == 200
    envelope_payload = json.loads(owner_manifest_download.content.decode("utf-8"))
    assert envelope_payload["manifest"]["request"]["verificationRequired"] is True
    assert envelope_payload["manifest"]["request"]["verificationMethod"] == "email_otp"
    assert envelope_payload["manifest"]["ceremony"]["verificationCompletedAt"]
    assert envelope_payload["manifest"]["sender"]["inviteMethod"] == "email"
    assert envelope_payload["manifest"]["sender"]["senderEmail"] == "owner@example.com"
    assert envelope_payload["manifest"]["sender"]["inviteDeliveryStatus"] == "skipped"

    event_types = [event.event_type for event in signing_database.list_signing_events_for_request(request_id, client=firestore_client)]
    assert event_types == [
        "request_created",
        "request_sent",
        "invite_skipped",
        "session_started",
        "opened",
        "verification_started",
        "verification_failed",
        "verification_passed",
        "document_accessed",
        "review_confirmed",
        "signature_adopted",
        "completed",
    ]


def test_public_signing_consumer_requires_consent_and_records_manual_fallback(client: TestClient, mocker) -> None:
    firestore_client = FakeFirestoreClient()
    request_user = _signing_user()
    source_pdf_bytes = _pdf_bytes()
    source_sha256 = sha256_hex_for_bytes(source_pdf_bytes)
    storage = InMemorySigningStorage()

    _mock_signing_verification_delivery(mocker)
    _patch_owner_signing_environment(mocker, firestore_client, request_user, storage=storage)

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
            "esignEligibilityConfirmed": True,
            "manualFallbackEnabled": True,
            "consumerPaperCopyProcedure": "Email owner@example.com to request a paper copy or offline processing for this request.",
            "consumerPaperCopyFeeDescription": "No paper-copy fee is charged for this request.",
            "consumerWithdrawalProcedure": "Use the withdraw option or email owner@example.com before completion to stop electronic processing.",
            "consumerWithdrawalConsequences": "Withdrawing consent ends the electronic process and requires offline follow-up.",
            "consumerContactUpdateProcedure": "Email owner@example.com if your contact details change before completion.",
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

    session_token = _bootstrap_and_verify_public_signing_session(client, public_token)
    access_code = build_signing_consumer_access_code(request_id)

    access_pdf_response = client.get(f"/api/signing/public/{public_token}/consumer-access-pdf")
    assert access_pdf_response.status_code == 200
    assert access_pdf_response.headers["content-type"] == "application/pdf"

    document_response = client.get(
        f"/api/signing/public/{public_token}/document",
        headers={"X-Signing-Session": session_token},
    )
    assert document_response.status_code == 409
    assert "consent" in document_response.json()["detail"].lower()

    missing_access_code_response = client.post(
        f"/api/signing/public/{public_token}/consent",
        headers={"X-Signing-Session": session_token},
        json={"accepted": True},
    )
    assert missing_access_code_response.status_code == 400
    assert "access code" in missing_access_code_response.json()["detail"].lower()

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
        json={"accepted": True, "accessCode": access_code},
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
    assert detail_payload["consumerDisclosurePresentedAt"]
    assert detail_payload["consumerConsentScope"] == (
        "This consent applies only to this signing request and its related electronic records."
    )

    event_types = [event.event_type for event in signing_database.list_signing_events_for_request(request_id, client=firestore_client)]
    assert "manual_fallback_requested" in event_types
    assert "consent_accepted" not in event_types


def test_public_signing_consumer_access_check_allows_consent_then_withdrawal(client: TestClient, mocker) -> None:
    firestore_client = FakeFirestoreClient()
    request_user = _signing_user()
    source_pdf_bytes = _pdf_bytes()
    source_sha256 = sha256_hex_for_bytes(source_pdf_bytes)
    storage = InMemorySigningStorage()

    _mock_signing_verification_delivery(mocker)
    mocker.patch.object(signing_database, "get_firestore_client", return_value=firestore_client)
    patch_signing_authenticated_owner(mocker, request_user)
    patch_signing_artifact_storage(mocker, storage)

    create_response = client.post(
        "/api/signing/requests",
        headers=AUTH_HEADERS,
        json={
            "title": "Consumer Consent Request",
            "mode": "sign",
            "signatureMode": "consumer",
            "sourceType": "workspace",
            "sourceDocumentName": "Consumer Packet",
            "sourcePdfSha256": source_sha256,
            "documentCategory": "authorization_consent_form",
            "esignEligibilityConfirmed": True,
            "manualFallbackEnabled": True,
            "consumerPaperCopyProcedure": "Email owner@example.com to request a paper copy or offline processing for this request.",
            "consumerPaperCopyFeeDescription": "No paper-copy fee is charged for this request.",
            "consumerWithdrawalProcedure": "Use the withdraw option or email owner@example.com before completion to stop electronic processing.",
            "consumerWithdrawalConsequences": "Withdrawing consent ends the electronic process and requires offline follow-up.",
            "consumerContactUpdateProcedure": "Email owner@example.com if your contact details change before completion.",
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
    request_id = create_response.json()["request"]["id"]
    public_token = build_signing_public_token(request_id)
    access_code = build_signing_consumer_access_code(request_id)

    send_response = client.post(
        f"/api/signing/requests/{request_id}/send",
        headers=AUTH_HEADERS,
        files={"pdf": ("consumer.pdf", source_pdf_bytes, "application/pdf")},
        data={"sourcePdfSha256": source_sha256},
    )
    assert send_response.status_code == 200

    preview_response = client.get(f"/api/signing/public/{public_token}")
    assert preview_response.status_code == 200
    disclosure = preview_response.json()["request"]["disclosure"]
    assert disclosure["accessCheck"]["required"] is True
    assert disclosure["accessCheck"]["accessPath"].endswith("/consumer-access-pdf")
    assert disclosure["sha256"]
    assert disclosure["sender"]["displayName"] == "Owner Example"
    assert disclosure["sender"]["contactEmail"] == "owner@example.com"
    assert disclosure["consentScope"] == "This consent applies only to this signing request and its related electronic records."
    assert preview_response.json()["request"]["verificationRequired"] is True
    assert preview_response.json()["request"]["senderDisplayName"] == "Owner Example"
    assert preview_response.json()["request"]["senderContactEmail"] == "owner@example.com"

    browser_headers = {"User-Agent": "consumer-browser/1.0"}
    session_token = _bootstrap_and_verify_public_signing_session(
        client,
        public_token,
        browser_headers=browser_headers,
    )
    bootstrap_preview = client.get(f"/api/signing/public/{public_token}")
    assert bootstrap_preview.status_code == 200
    assert bootstrap_preview.json()["request"]["consumerDisclosurePresentedAt"]
    assert bootstrap_preview.json()["request"]["disclosure"]["presentedAt"]

    access_pdf_response = client.get(f"/api/signing/public/{public_token}/consumer-access-pdf")
    assert access_pdf_response.status_code == 200
    assert access_pdf_response.headers["content-type"] == "application/pdf"

    consent_response = client.post(
        f"/api/signing/public/{public_token}/consent",
        headers={"X-Signing-Session": session_token, **browser_headers},
        json={"accepted": True, "accessCode": access_code},
    )
    assert consent_response.status_code == 200
    assert consent_response.json()["request"]["consentedAt"]
    assert consent_response.json()["request"]["consumerAccessDemonstratedAt"]
    assert consent_response.json()["request"]["consumerAccessDemonstrationMethod"] == "consumer_access_pdf_code"
    assert consent_response.json()["request"]["disclosure"]["acceptedAt"]
    assert consent_response.json()["request"]["disclosure"]["accessDemonstratedAt"]

    document_response = client.get(
        f"/api/signing/public/{public_token}/document",
        headers={"X-Signing-Session": session_token, **browser_headers},
    )
    assert document_response.status_code == 200
    assert document_response.headers["content-type"].startswith("application/pdf")

    withdraw_response = client.post(
        f"/api/signing/public/{public_token}/withdraw-consent",
        headers={"X-Signing-Session": session_token, **browser_headers},
        json={"confirmed": True},
    )
    assert withdraw_response.status_code == 200
    assert withdraw_response.json()["request"]["consentWithdrawnAt"]

    review_response = client.post(
        f"/api/signing/public/{public_token}/review",
        headers={"X-Signing-Session": session_token, **browser_headers},
        json={"reviewConfirmed": True},
    )
    assert review_response.status_code == 409
    assert "withdrawn" in review_response.json()["detail"].lower()

    detail_response = client.get(f"/api/signing/requests/{request_id}", headers=AUTH_HEADERS)
    assert detail_response.status_code == 200
    detail_payload = detail_response.json()["request"]
    assert detail_payload["consentedAt"]
    assert detail_payload["consentWithdrawnAt"]
    assert detail_payload["consumerDisclosurePresentedAt"]
    assert detail_payload["consumerAccessDemonstratedAt"]
    assert detail_payload["consumerAccessDemonstrationMethod"] == "consumer_access_pdf_code"

    event_types = [
        event.event_type
        for event in signing_database.list_signing_events_for_request(request_id, client=firestore_client)
    ]
    assert "consent_accepted" in event_types
    assert "consent_withdrawn" in event_types
    assert "document_accessed" in event_types


def test_public_signing_consumer_completion_seals_disclosure_evidence_in_audit_manifest(client: TestClient, mocker) -> None:
    firestore_client = FakeFirestoreClient()
    request_user = _signing_user()
    source_pdf_bytes = _pdf_bytes()
    source_sha256 = sha256_hex_for_bytes(source_pdf_bytes)
    storage = InMemorySigningStorage()

    _mock_signing_verification_delivery(mocker)
    mocker.patch.object(signing_database, "get_firestore_client", return_value=firestore_client)
    patch_signing_authenticated_owner(mocker, request_user)
    patch_signing_artifact_storage(mocker, storage, stream_pdf_bytes=source_pdf_bytes)

    create_response = client.post(
        "/api/signing/requests",
        headers=AUTH_HEADERS,
        json={
            "title": "Consumer Completion Request",
            "mode": "sign",
            "signatureMode": "consumer",
            "sourceType": "workspace",
            "sourceDocumentName": "Consumer Packet",
            "sourcePdfSha256": source_sha256,
            "documentCategory": "authorization_consent_form",
            "esignEligibilityConfirmed": True,
            "manualFallbackEnabled": True,
            "consumerPaperCopyProcedure": "Email owner@example.com to request a paper copy or offline processing for this request.",
            "consumerPaperCopyFeeDescription": "No paper-copy fee is charged for this request.",
            "consumerWithdrawalProcedure": "Use the withdraw option or email owner@example.com before completion to stop electronic processing.",
            "consumerWithdrawalConsequences": "Withdrawing consent ends the electronic process and requires offline follow-up.",
            "consumerContactUpdateProcedure": "Email owner@example.com if your contact details change before completion.",
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
    request_id = create_response.json()["request"]["id"]
    public_token = build_signing_public_token(request_id)
    access_code = build_signing_consumer_access_code(request_id)

    send_response = client.post(
        f"/api/signing/requests/{request_id}/send",
        headers=AUTH_HEADERS,
        files={"pdf": ("consumer.pdf", source_pdf_bytes, "application/pdf")},
        data={"sourcePdfSha256": source_sha256},
    )
    assert send_response.status_code == 200
    assert send_response.json()["request"]["consumerConsentScope"] == (
        "This consent applies only to this signing request and its related electronic records."
    )

    browser_headers = {"User-Agent": "consumer-completion-browser/1.0"}
    session_token = _bootstrap_and_verify_public_signing_session(
        client,
        public_token,
        browser_headers=browser_headers,
    )

    consent_response = client.post(
        f"/api/signing/public/{public_token}/consent",
        headers={"X-Signing-Session": session_token, **browser_headers},
        json={"accepted": True, "accessCode": access_code},
    )
    assert consent_response.status_code == 200

    document_response = client.get(
        f"/api/signing/public/{public_token}/document",
        headers={"X-Signing-Session": session_token, **browser_headers},
    )
    assert document_response.status_code == 200

    review_response = client.post(
        f"/api/signing/public/{public_token}/review",
        headers={"X-Signing-Session": session_token, **browser_headers},
        json={"reviewConfirmed": True},
    )
    assert review_response.status_code == 200

    adopt_response = client.post(
        f"/api/signing/public/{public_token}/adopt-signature",
        headers={"X-Signing-Session": session_token, **browser_headers},
        json={"adoptedName": "Alex Signer"},
    )
    assert adopt_response.status_code == 200

    complete_response = client.post(
        f"/api/signing/public/{public_token}/complete",
        headers={"X-Signing-Session": session_token, **browser_headers},
        json={"intentConfirmed": True},
    )
    assert complete_response.status_code == 200
    assert complete_response.json()["request"]["status"] == "completed"

    owner_manifest_download = client.get(
        f"/api/signing/requests/{request_id}/artifacts/audit_manifest",
        headers=AUTH_HEADERS,
    )
    assert owner_manifest_download.status_code == 200
    envelope_payload = json.loads(owner_manifest_download.content.decode("utf-8"))
    consumer_consent = envelope_payload["manifest"]["consumerConsent"]
    disclosure = envelope_payload["manifest"]["disclosure"]
    assert consumer_consent["disclosureVersion"] == "us-esign-consumer-v1"
    assert consumer_consent["disclosureSha256"]
    assert consumer_consent["disclosurePresentedAt"]
    assert consumer_consent["consentAcceptedAt"]
    assert consumer_consent["accessDemonstratedAt"]
    assert consumer_consent["accessDemonstrationMethod"] == "consumer_access_pdf_code"
    assert disclosure["payloadSha256"] == consumer_consent["disclosureSha256"]
    assert disclosure["payload"]["accessCheck"]["accessPath"].endswith("/consumer-access-pdf")

    owner_receipt_download = client.get(
        f"/api/signing/requests/{request_id}/artifacts/audit_receipt",
        headers=AUTH_HEADERS,
    )
    assert owner_receipt_download.status_code == 200
    receipt_text = "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(owner_receipt_download.content)).pages)
    assert "Consumer Disclosure Version: us-esign-consumer-v1" in receipt_text
    assert "Access Method: consumer_access_pdf_code" in receipt_text


def test_owner_can_revoke_sent_signing_request(client: TestClient, mocker) -> None:
    firestore_client = FakeFirestoreClient()
    request_user = _signing_user()
    source_pdf_bytes = _pdf_bytes()
    source_sha256 = sha256_hex_for_bytes(source_pdf_bytes)
    _patch_owner_signing_environment(mocker, firestore_client, request_user)

    create_response = client.post(
        "/api/signing/requests",
        headers=AUTH_HEADERS,
        json={
            "title": "Revocable Signature Request",
            "mode": "sign",
            "signatureMode": "business",
            "sourceType": "workspace",
            "sourceDocumentName": "Revocable Packet",
            "sourcePdfSha256": source_sha256,
            "documentCategory": "ordinary_business_form",
            "esignEligibilityConfirmed": True,
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
    request_id = create_response.json()["request"]["id"]
    public_token = build_signing_public_token(request_id)

    send_response = client.post(
        f"/api/signing/requests/{request_id}/send",
        headers=AUTH_HEADERS,
        files={"pdf": ("revocable.pdf", source_pdf_bytes, "application/pdf")},
        data={"sourcePdfSha256": source_sha256},
    )
    assert send_response.status_code == 200

    revoke_response = client.post(f"/api/signing/requests/{request_id}/revoke", headers=AUTH_HEADERS)
    assert revoke_response.status_code == 200
    revoke_payload = revoke_response.json()["request"]
    assert revoke_payload["status"] == "invalidated"
    assert revoke_payload["publicLinkRevokedAt"]
    assert "revoked by the sender" in revoke_payload["invalidationReason"].lower()

    public_response = client.get(f"/api/signing/public/{public_token}")
    assert public_response.status_code == 200
    assert public_response.json()["request"]["status"] == "invalidated"

    bootstrap_response = client.post(f"/api/signing/public/{public_token}/bootstrap")
    assert bootstrap_response.status_code == 409
    assert "revoked by the sender" in bootstrap_response.json()["detail"].lower()

    document_response = client.get(f"/api/signing/public/{public_token}/document")
    assert document_response.status_code == 409
    assert "revoked by the sender" in document_response.json()["detail"].lower()

    event_types = [
        event.event_type
        for event in signing_database.list_signing_events_for_request(request_id, client=firestore_client)
    ]
    assert "link_revoked" in event_types


def test_owner_can_reissue_sent_signing_request_and_invalidate_previous_token(client: TestClient, mocker) -> None:
    firestore_client = FakeFirestoreClient()
    request_user = _signing_user()
    source_pdf_bytes = _pdf_bytes()
    source_sha256 = sha256_hex_for_bytes(source_pdf_bytes)
    storage = InMemorySigningStorage()

    mocker.patch.object(signing_database, "get_firestore_client", return_value=firestore_client)
    patch_signing_authenticated_owner(mocker, request_user)
    patch_signing_artifact_storage(mocker, storage)
    mocker.patch.object(
        signing_routes,
        "deliver_signing_invite_for_request",
        side_effect=lambda **kwargs: SimpleNamespace(record=kwargs["record"], delivery=None),
    )

    create_response = client.post(
        "/api/signing/requests",
        headers=AUTH_HEADERS,
        json={
            "title": "Reissuable Signature Request",
            "mode": "sign",
            "signatureMode": "business",
            "sourceType": "workspace",
            "sourceDocumentName": "Reissuable Packet",
            "sourcePdfSha256": source_sha256,
            "documentCategory": "ordinary_business_form",
            "esignEligibilityConfirmed": True,
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
    request_id = create_response.json()["request"]["id"]
    original_public_token = build_signing_public_token(request_id)

    send_response = client.post(
        f"/api/signing/requests/{request_id}/send",
        headers=AUTH_HEADERS,
        files={"pdf": ("reissuable.pdf", source_pdf_bytes, "application/pdf")},
        data={"sourcePdfSha256": source_sha256},
    )
    assert send_response.status_code == 200
    firestore_client.collection(signing_database.SIGNING_REQUESTS_COLLECTION).document(request_id).set(
        {
            "verification_required": False,
            "verification_method": None,
        },
        merge=True,
    )

    reissue_response = client.post(f"/api/signing/requests/{request_id}/reissue", headers=AUTH_HEADERS)
    assert reissue_response.status_code == 200
    reissue_payload = reissue_response.json()["request"]
    assert reissue_payload["status"] == "sent"
    assert reissue_payload["publicLinkVersion"] == 2
    assert reissue_payload["publicLinkLastReissuedAt"]
    assert reissue_payload["publicToken"] != original_public_token
    assert reissue_payload["verificationRequired"] is True
    assert reissue_payload["verificationMethod"] == "email_otp"

    stale_public_response = client.get(f"/api/signing/public/{original_public_token}")
    assert stale_public_response.status_code == 404

    stale_bootstrap_response = client.post(f"/api/signing/public/{original_public_token}/bootstrap")
    assert stale_bootstrap_response.status_code == 404

    stale_document_response = client.get(f"/api/signing/public/{original_public_token}/document")
    assert stale_document_response.status_code == 404

    replacement_public_token = reissue_payload["publicToken"]
    replacement_public_response = client.get(f"/api/signing/public/{replacement_public_token}")
    assert replacement_public_response.status_code == 200
    assert replacement_public_response.json()["request"]["status"] == "sent"

    firestore_client.collection(signing_database.SIGNING_REQUESTS_COLLECTION).document(request_id).set(
        {
            "verification_required": False,
            "verification_method": None,
        },
        merge=True,
    )
    browser_headers = {"user-agent": "integration-browser/1.0"}
    replacement_bootstrap_response = client.post(
        f"/api/signing/public/{replacement_public_token}/bootstrap",
        headers=browser_headers,
    )
    assert replacement_bootstrap_response.status_code == 200
    replacement_session_token = replacement_bootstrap_response.json()["session"]["token"]

    replacement_document_response = client.get(
        f"/api/signing/public/{replacement_public_token}/document",
        headers={"X-Signing-Session": replacement_session_token, **browser_headers},
    )
    assert replacement_document_response.status_code == 200
    assert replacement_document_response.headers["content-type"].startswith("application/pdf")

    event_types = [
        event.event_type
        for event in signing_database.list_signing_events_for_request(request_id, client=firestore_client)
    ]
    assert "link_reissued" in event_types


def test_public_signing_rejects_changed_session_user_agent(client: TestClient, mocker) -> None:
    firestore_client = FakeFirestoreClient()
    request_user = _signing_user()
    source_pdf_bytes = _pdf_bytes()
    source_sha256 = sha256_hex_for_bytes(source_pdf_bytes)
    storage = InMemorySigningStorage()

    _mock_signing_verification_delivery(mocker)
    _patch_owner_signing_environment(mocker, firestore_client, request_user, storage=storage)

    create_response = client.post(
        "/api/signing/requests",
        headers=AUTH_HEADERS,
        json={
            "title": "Device Bound Request",
            "mode": "sign",
            "signatureMode": "business",
            "sourceType": "workspace",
            "sourceDocumentName": "Device Bound Packet",
            "sourcePdfSha256": source_sha256,
            "documentCategory": "ordinary_business_form",
            "esignEligibilityConfirmed": True,
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
    request_id = create_response.json()["request"]["id"]
    public_token = build_signing_public_token(request_id)

    send_response = client.post(
        f"/api/signing/requests/{request_id}/send",
        headers=AUTH_HEADERS,
        files={"pdf": ("device-bound.pdf", source_pdf_bytes, "application/pdf")},
        data={"sourcePdfSha256": source_sha256},
    )
    assert send_response.status_code == 200

    session_token = _bootstrap_and_verify_public_signing_session(
        client,
        public_token,
        browser_headers={"User-Agent": "integration-browser/1.0"},
    )

    review_response = client.post(
        f"/api/signing/public/{public_token}/review",
        headers={"X-Signing-Session": session_token, "User-Agent": "other-browser/9.9"},
        json={"reviewConfirmed": True},
    )
    assert review_response.status_code == 401
    assert "does not match this device" in review_response.json()["detail"].lower()


def test_public_signing_marks_expired_requests_as_inactive(client: TestClient, mocker) -> None:
    firestore_client = FakeFirestoreClient()
    request_user = _signing_user()
    source_pdf_bytes = _pdf_bytes()
    source_sha256 = sha256_hex_for_bytes(source_pdf_bytes)
    _patch_owner_signing_environment(mocker, firestore_client, request_user)

    create_response = client.post(
        "/api/signing/requests",
        headers=AUTH_HEADERS,
        json={
            "title": "Expiring Signature Request",
            "mode": "sign",
            "signatureMode": "business",
            "sourceType": "workspace",
            "sourceDocumentName": "Expiring Packet",
            "sourcePdfSha256": source_sha256,
            "documentCategory": "ordinary_business_form",
            "esignEligibilityConfirmed": True,
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
    request_id = create_response.json()["request"]["id"]
    public_token = build_signing_public_token(request_id)

    send_response = client.post(
        f"/api/signing/requests/{request_id}/send",
        headers=AUTH_HEADERS,
        files={"pdf": ("expiring.pdf", source_pdf_bytes, "application/pdf")},
        data={"sourcePdfSha256": source_sha256},
    )
    assert send_response.status_code == 200

    firestore_client.collection(signing_database.SIGNING_REQUESTS_COLLECTION).document(request_id).set(
        {"expires_at": "2000-01-01T00:00:00+00:00"},
        merge=True,
    )

    owner_detail_response = client.get(f"/api/signing/requests/{request_id}", headers=AUTH_HEADERS)
    assert owner_detail_response.status_code == 200
    assert owner_detail_response.json()["request"]["isExpired"] is True

    preview_response = client.get(f"/api/signing/public/{public_token}")
    assert preview_response.status_code == 200
    preview_payload = preview_response.json()["request"]
    assert preview_payload["status"] == "sent"
    assert preview_payload["isExpired"] is True
    assert "expired" in preview_payload["statusMessage"].lower()

    bootstrap_response = client.post(f"/api/signing/public/{public_token}/bootstrap")
    assert bootstrap_response.status_code == 409
    assert "expired" in bootstrap_response.json()["detail"].lower()

    document_response = client.get(f"/api/signing/public/{public_token}/document")
    assert document_response.status_code == 409
    assert "expired" in document_response.json()["detail"].lower()


def test_public_signing_review_rejects_stale_transition_without_logging_event(client: TestClient, mocker) -> None:
    firestore_client = FakeFirestoreClient()
    request_user = _signing_user()
    source_pdf_bytes = _pdf_bytes()
    source_sha256 = sha256_hex_for_bytes(source_pdf_bytes)
    storage = InMemorySigningStorage()

    _mock_signing_verification_delivery(mocker)
    _patch_owner_signing_environment(mocker, firestore_client, request_user, storage=storage)

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
            "esignEligibilityConfirmed": True,
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

    session_token = _bootstrap_and_verify_public_signing_session(client, public_token)

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
    _patch_owner_signing_environment(mocker, firestore_client, request_user)

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
            "esignEligibilityConfirmed": True,
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
    storage = InMemorySigningStorage()

    _mock_signing_verification_delivery(mocker)
    mocker.patch.object(signing_database, "get_firestore_client", return_value=firestore_client)
    patch_signing_authenticated_owner(mocker, request_user)
    patch_signing_artifact_storage(mocker, storage, patch_delete=True)

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
            "esignEligibilityConfirmed": True,
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
    storage.objects[source_path] = source_pdf_bytes

    session_token = _bootstrap_and_verify_public_signing_session(client, public_token)

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
    mocker.patch.object(signing_public_routes, "complete_signing_request_transactional", return_value=stale_sent_record)

    complete_response = client.post(
        f"/api/signing/public/{public_token}/complete",
        headers={"X-Signing-Session": session_token},
        json={"intentConfirmed": True},
    )

    assert complete_response.status_code == 409
    assert "ready for review and signature" in complete_response.json()["detail"].lower()
    assert list(storage.objects.keys()) == [source_path]
