"""Shared helpers for signing integration tests."""

from __future__ import annotations

from io import BytesIO
import json
from types import SimpleNamespace
from typing import Optional

from fastapi.testclient import TestClient
from pypdf import PdfWriter

import backend.api.middleware.security as security_middleware
import backend.api.routes.signing as signing_routes
import backend.api.routes.signing_public as signing_public_routes
import backend.services.fill_link_signing_service as fill_link_signing_service
import backend.services.signing_public_artifact_service as signing_public_artifact_service
import backend.services.signing_validation_service as signing_validation_service
import backend.firebaseDB.user_database as user_database
from backend.firebaseDB.firebase_service import RequestUser
from backend.services.signing_verification_service import SigningVerificationDeliveryResult


AUTH_HEADERS = {"Authorization": "Bearer integration-token"}


def signing_user() -> RequestUser:
    return RequestUser(
        uid="firebase-user-signing",
        app_user_id="user-signing",
        email="owner@example.com",
        display_name="Owner Example",
        role=user_database.ROLE_BASE,
    )


def pdf_bytes(*, width: float = 200, height: float = 200) -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=width, height=height)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def mock_signing_verification_delivery(mocker, *, verification_code: str = "123456") -> tuple[str, str]:
    attempted_at = signing_public_routes.now_iso()
    sent_at = signing_public_routes.now_iso()
    mocker.patch.object(signing_public_routes, "generate_signing_email_otp_code", return_value=verification_code)
    mocker.patch.object(
        signing_public_routes,
        "send_signing_verification_email",
        mocker.AsyncMock(
            return_value=SigningVerificationDeliveryResult(
                delivery_status="sent",
                attempted_at=attempted_at,
                sent_at=sent_at,
                message_id="gmail-verification-1",
            ),
        ),
    )
    return attempted_at, sent_at


def bootstrap_and_verify_public_signing_session(
    client: TestClient,
    public_token: str,
    *,
    browser_headers: Optional[dict[str, str]] = None,
    verification_code: str = "123456",
) -> str:
    headers = dict(browser_headers or {})
    bootstrap_response = client.post(
        f"/api/signing/public/{public_token}/bootstrap",
        headers=headers,
    )
    assert bootstrap_response.status_code == 200
    session_token = bootstrap_response.json()["session"]["token"]

    send_code_response = client.post(
        f"/api/signing/public/{public_token}/verification/send",
        headers={"X-Signing-Session": session_token, **headers},
    )
    assert send_code_response.status_code == 200

    verify_response = client.post(
        f"/api/signing/public/{public_token}/verification/verify",
        headers={"X-Signing-Session": session_token, **headers},
        json={"code": verification_code},
    )
    assert verify_response.status_code == 200
    assert verify_response.json()["session"]["verifiedAt"]
    return session_token


class InMemorySigningStorage:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.final_bucket = "signing-bucket"
        self.staging_bucket = "signing-staging-bucket"

    def upload_pdf_bytes(self, payload: bytes, destination_path: str) -> str:
        uri = f"gs://{self.final_bucket}/{destination_path}"
        self.objects[uri] = bytes(payload)
        return uri

    def upload_json(self, payload, destination_path: str) -> str:
        uri = f"gs://{self.final_bucket}/{destination_path}"
        self.objects[uri] = json.dumps(
            payload,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return uri

    def _stage_uri_for_final(self, final_object_path: str) -> str:
        return f"gs://{self.staging_bucket}/_staging/{final_object_path}"

    def upload_staging_pdf_for_final(self, payload: bytes, final_object_path: str) -> str:
        uri = self._stage_uri_for_final(final_object_path)
        self.objects[uri] = bytes(payload)
        return uri

    def upload_staging_json_for_final(self, payload, final_object_path: str) -> str:
        uri = self._stage_uri_for_final(final_object_path)
        self.objects[uri] = json.dumps(
            payload,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return uri

    def download_storage_bytes(self, bucket_path: str) -> bytes:
        return self.objects[bucket_path]

    def delete_storage_object(self, bucket_path: str) -> None:
        self.objects.pop(bucket_path, None)

    def build_bucket_uri(self, object_path: str) -> str:
        return f"gs://{self.final_bucket}/{object_path}"

    def resolve_read_bucket_path(self, final_bucket_path: str, *, retain_until: str | None = None) -> str:
        if final_bucket_path in self.objects:
            return final_bucket_path
        _, object_path = final_bucket_path.split("/", 3)[2:]
        stage_uri = self._stage_uri_for_final(object_path)
        return stage_uri if stage_uri in self.objects else final_bucket_path

    def promote_staged_object(self, final_bucket_path: str, *, retain_until: str | None = None, delete_stage: bool = True) -> str:
        _, object_path = final_bucket_path.split("/", 3)[2:]
        stage_uri = self._stage_uri_for_final(object_path)
        if stage_uri in self.objects and final_bucket_path not in self.objects:
            self.objects[final_bucket_path] = bytes(self.objects[stage_uri])
        if delete_stage:
            self.objects.pop(stage_uri, None)
        return final_bucket_path


def patch_signing_authenticated_owner(mocker, request_user: Optional[RequestUser] = None) -> RequestUser:
    resolved_user = request_user or signing_user()
    mocker.patch.object(signing_routes, "require_user", return_value=resolved_user)
    mocker.patch.object(
        security_middleware,
        "verify_token",
        return_value={
            "uid": resolved_user.uid,
            "email": resolved_user.email,
            "name": resolved_user.display_name,
            user_database.ROLE_FIELD: resolved_user.role,
        },
    )
    return resolved_user


def patch_signing_artifact_storage(
    mocker,
    storage: InMemorySigningStorage,
    *,
    stream_pdf_bytes: Optional[bytes] = None,
    patch_delete: bool = False,
    mock_digital_signing: bool = True,
) -> None:
    mocker.patch.object(signing_routes, "ensure_signing_storage_configuration", return_value=None)
    mocker.patch.object(signing_routes, "build_signing_bucket_uri", side_effect=storage.build_bucket_uri)
    mocker.patch.object(signing_routes, "upload_signing_staging_pdf_bytes_for_final", side_effect=storage.upload_staging_pdf_for_final)
    mocker.patch.object(signing_routes, "promote_signing_staged_object", side_effect=storage.promote_staged_object)
    mocker.patch.object(signing_routes, "resolve_signing_storage_read_bucket_path", side_effect=storage.resolve_read_bucket_path)
    mocker.patch.object(signing_routes, "download_storage_bytes", side_effect=storage.download_storage_bytes)
    mocker.patch.object(fill_link_signing_service, "ensure_signing_storage_configuration", return_value=None)
    mocker.patch.object(fill_link_signing_service, "build_signing_bucket_uri", side_effect=storage.build_bucket_uri)
    mocker.patch.object(fill_link_signing_service, "upload_signing_staging_pdf_bytes_for_final", side_effect=storage.upload_staging_pdf_for_final)
    mocker.patch.object(fill_link_signing_service, "promote_signing_staged_object", side_effect=storage.promote_staged_object)
    mocker.patch.object(signing_public_routes, "_check_public_rate_limits", return_value=True)
    mocker.patch.object(signing_public_routes, "check_rate_limit", return_value=True)
    mocker.patch.object(signing_public_routes, "ensure_signing_storage_configuration", return_value=None)
    if stream_pdf_bytes is not None:
        mocker.patch.object(signing_public_routes, "stream_pdf", return_value=BytesIO(stream_pdf_bytes))
    else:
        mocker.patch.object(
            signing_public_routes,
            "stream_pdf",
            side_effect=lambda bucket_path: BytesIO(storage.download_storage_bytes(bucket_path)),
        )
    mocker.patch.object(signing_public_routes, "upload_signing_staging_pdf_bytes_for_final", side_effect=storage.upload_staging_pdf_for_final)
    mocker.patch.object(signing_public_routes, "upload_signing_staging_json_for_final", side_effect=storage.upload_staging_json_for_final)
    mocker.patch.object(signing_public_routes, "promote_signing_staged_object", side_effect=storage.promote_staged_object)
    mocker.patch.object(signing_public_routes, "resolve_signing_storage_read_bucket_path", side_effect=storage.resolve_read_bucket_path)
    mocker.patch.object(signing_public_routes, "download_storage_bytes", side_effect=storage.download_storage_bytes)
    mocker.patch.object(signing_public_routes, "build_signing_bucket_uri", side_effect=storage.build_bucket_uri)
    mocker.patch.object(signing_validation_service, "download_storage_bytes", side_effect=storage.download_storage_bytes)
    if mock_digital_signing:
        mocker.patch.object(
            signing_public_artifact_service,
            "_apply_digital_pdf_signature",
            new=mocker.AsyncMock(
                side_effect=lambda *, pdf_bytes, signer_name, source_document_name: SimpleNamespace(
                    pdf_bytes=bytes(pdf_bytes),
                    signature_info=SimpleNamespace(
                        signature_method="pkcs12",
                        signature_algorithm="sha256_rsa",
                        field_name="DullyPDFDigitalSignature",
                        subfilter="/ETSI.CAdES.detached",
                        timestamped=False,
                        certificate_subject="CN=DullyPDF Test Signer",
                        certificate_issuer="CN=DullyPDF Test Issuer",
                        certificate_serial_number="01",
                        certificate_fingerprint_sha256="f" * 64,
                    ),
                )
            ),
        )
    if patch_delete:
        mocker.patch.object(signing_routes, "delete_storage_object", side_effect=storage.delete_storage_object)
        mocker.patch.object(fill_link_signing_service, "delete_storage_object", side_effect=storage.delete_storage_object)
        mocker.patch.object(signing_public_routes, "delete_storage_object", side_effect=storage.delete_storage_object)
