from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

def _patch_auth(mocker, app_main, user) -> None:
    mocker.patch.object(app_main, "_verify_token", return_value={"uid": user.app_user_id})
    mocker.patch.object(app_main, "ensure_user", return_value=user)


def test_owner_signing_artifact_download_sets_private_no_store_and_maps_missing_storage(
    client,
    app_main,
    base_user,
    mocker,
    auth_headers,
) -> None:
    _patch_auth(mocker, app_main, base_user)
    record = SimpleNamespace(id="req-1", retention_until=None)
    mocker.patch.object(app_main, "ensure_signing_storage_configuration", return_value=None)
    mocker.patch.object(app_main, "get_signing_request_for_user", return_value=record)
    mocker.patch.object(
        app_main,
        "_resolve_owner_artifact",
        return_value=("gs://signing/artifact.pdf", "application/pdf", "artifact.pdf"),
    )
    mocker.patch.object(
        app_main,
        "resolve_signing_storage_read_bucket_path",
        return_value="gs://signing/artifact.pdf",
    )
    mocker.patch.object(
        app_main,
        "resolve_stream_cors_headers",
        return_value={"Access-Control-Allow-Origin": "https://app.example.com"},
    )
    mocker.patch.object(app_main, "download_storage_bytes", return_value=b"%PDF-1.4\n")

    response = client.get(
        "/api/signing/requests/req-1/artifacts/signed_pdf",
        headers={**auth_headers, "Origin": "https://app.example.com"},
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["access-control-allow-origin"] == "https://app.example.com"

    mocker.patch.object(app_main, "download_storage_bytes", side_effect=FileNotFoundError("missing blob"))
    local_client = TestClient(app_main.app, raise_server_exceptions=False)
    missing_response = local_client.get(
        "/api/signing/requests/req-1/artifacts/signed_pdf",
        headers=auth_headers,
    )

    assert missing_response.status_code == 404
    assert "not available" in missing_response.text.lower()


def test_public_signing_document_missing_storage_blob_returns_404(app_main, mocker) -> None:
    record = SimpleNamespace(
        id="req-1",
        source_pdf_bucket_path="gs://signing/source.pdf",
        source_document_name="Packet",
        source_pdf_sha256="sha",
        source_version="v1",
        retention_until=None,
    )
    session = SimpleNamespace(id="sess-1", link_token_id="link-token-1")
    mocker.patch.object(app_main, "_check_public_rate_limits", return_value=True)
    mocker.patch.object(app_main, "_get_public_record_or_404", return_value=record)
    mocker.patch.object(app_main, "validate_public_signing_document_record", return_value=None)
    mocker.patch.object(
        app_main,
        "_require_public_signing_session",
        return_value=(record, session, "198.51.100.10", "ua"),
    )
    mocker.patch.object(app_main, "signing_record_requires_verification", return_value=False)
    mocker.patch.object(app_main, "record_signing_event", return_value=None)
    mocker.patch.object(
        app_main,
        "resolve_signing_storage_read_bucket_path",
        return_value="gs://signing/source.pdf",
    )
    mocker.patch.object(app_main, "stream_pdf", side_effect=FileNotFoundError("missing blob"))

    local_client = TestClient(app_main.app, raise_server_exceptions=False)
    response = local_client.get("/api/signing/public/token-1/document", headers={"x-signing-session": "sess"})

    assert response.status_code == 404
    assert "not available" in response.text.lower()


def test_public_signing_artifact_missing_storage_blob_returns_404(app_main, mocker) -> None:
    record = SimpleNamespace(source_document_name="Packet", retention_until=None)
    session = SimpleNamespace(id="sess-1")
    mocker.patch.object(app_main, "_check_public_rate_limits", return_value=True)
    mocker.patch.object(
        app_main,
        "parse_signing_public_artifact_token",
        return_value=("req-1", "sess-1", "audit_receipt", 9999999999),
    )
    mocker.patch.object(app_main, "ensure_signing_storage_configuration", return_value=None)
    mocker.patch.object(
        app_main,
        "_require_public_signing_artifact_session",
        return_value=(record, session, "198.51.100.10", "ua"),
    )
    mocker.patch.object(app_main, "signing_record_requires_verification", return_value=False)
    mocker.patch.object(
        app_main,
        "resolve_public_signing_artifact",
        return_value=SimpleNamespace(
            bucket_path="gs://signing/audit.pdf",
            media_type="application/pdf",
            filename="audit.pdf",
        ),
    )
    mocker.patch.object(
        app_main,
        "resolve_signing_storage_read_bucket_path",
        return_value="gs://signing/audit.pdf",
    )
    mocker.patch.object(app_main, "download_storage_bytes", side_effect=FileNotFoundError("missing blob"))

    local_client = TestClient(app_main.app, raise_server_exceptions=False)
    response = local_client.get("/api/signing/public/artifacts/artifact-token-1", headers={"x-signing-session": "sess"})

    assert response.status_code == 404
    assert "not available" in response.text.lower()


def test_public_signing_artifact_download_rejects_expired_or_invalid_tokens(app_main, mocker) -> None:
    mocker.patch.object(app_main, "_check_public_rate_limits", return_value=True)
    mocker.patch.object(app_main, "parse_signing_public_artifact_token", return_value=None)

    local_client = TestClient(app_main.app, raise_server_exceptions=False)
    response = local_client.get("/api/signing/public/artifacts/expired-token", headers={"x-signing-session": "sess"})

    assert response.status_code == 401
    assert "expired" in response.text.lower()


def test_public_signing_artifact_issue_returns_short_lived_download_path(app_main, mocker) -> None:
    record = SimpleNamespace(
        id="req-1",
        source_document_name="Packet",
        retention_until=None,
    )
    session = SimpleNamespace(id="sess-1", verification_completed_at="2026-03-28T12:00:00Z")
    mocker.patch.object(app_main, "_check_public_rate_limits", return_value=True)
    mocker.patch.object(app_main, "ensure_signing_storage_configuration", return_value=None)
    mocker.patch.object(
        app_main,
        "_require_public_signing_session",
        return_value=(record, session, "198.51.100.10", "ua"),
    )
    mocker.patch.object(app_main, "signing_record_requires_verification", return_value=False)
    mocker.patch.object(
        app_main,
        "resolve_public_signing_artifact",
        return_value=SimpleNamespace(
            bucket_path="gs://signing/signed.pdf",
            media_type="application/pdf",
            filename="signed.pdf",
        ),
    )
    mocker.patch.object(app_main, "resolve_signing_artifact_token_ttl_seconds", return_value=300)
    build_token = mocker.patch.object(app_main, "build_signing_public_artifact_token", return_value="artifact-token-1")

    local_client = TestClient(app_main.app, raise_server_exceptions=False)
    response = local_client.post("/api/signing/public/token-1/artifacts/signed_pdf/issue", headers={"x-signing-session": "sess"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["artifactKey"] == "signed_pdf"
    assert payload["downloadPath"] == "/api/signing/public/artifacts/artifact-token-1"
    assert not payload["downloadPath"].startswith("/api/signing/public/token-1/")
    assert payload["mediaType"] == "application/pdf"
    assert payload["expiresAt"]
    build_token.assert_called_once()


def test_public_signing_artifact_issue_requires_verification_when_enabled(app_main, mocker) -> None:
    record = SimpleNamespace(
        id="req-1",
        source_document_name="Packet",
        retention_until=None,
    )
    session = SimpleNamespace(id="sess-1", verification_completed_at=None)
    mocker.patch.object(app_main, "_check_public_rate_limits", return_value=True)
    mocker.patch.object(app_main, "ensure_signing_storage_configuration", return_value=None)
    mocker.patch.object(
        app_main,
        "_require_public_signing_session",
        return_value=(record, session, "198.51.100.10", "ua"),
    )
    mocker.patch.object(app_main, "signing_record_requires_verification", return_value=True)

    local_client = TestClient(app_main.app, raise_server_exceptions=False)
    response = local_client.post("/api/signing/public/token-1/artifacts/signed_pdf/issue", headers={"x-signing-session": "sess"})

    assert response.status_code == 403
    assert "verify the email code" in response.text.lower()


def test_public_signing_artifact_download_requires_verification_when_enabled(app_main, mocker) -> None:
    record = SimpleNamespace(
        id="req-1",
        source_document_name="Packet",
        retention_until=None,
    )
    session = SimpleNamespace(id="sess-1", verification_completed_at=None)
    mocker.patch.object(app_main, "_check_public_rate_limits", return_value=True)
    mocker.patch.object(
        app_main,
        "parse_signing_public_artifact_token",
        return_value=("req-1", "sess-1", "signed_pdf", 9999999999),
    )
    mocker.patch.object(app_main, "ensure_signing_storage_configuration", return_value=None)
    mocker.patch.object(
        app_main,
        "_require_public_signing_artifact_session",
        return_value=(record, session, "198.51.100.10", "ua"),
    )
    mocker.patch.object(app_main, "signing_record_requires_verification", return_value=True)

    local_client = TestClient(app_main.app, raise_server_exceptions=False)
    response = local_client.get("/api/signing/public/artifacts/artifact-token-1", headers={"x-signing-session": "sess"})

    assert response.status_code == 403
    assert "verify the email code" in response.text.lower()


def test_public_signing_legacy_artifact_route_returns_410(app_main) -> None:
    local_client = TestClient(app_main.app, raise_server_exceptions=False)
    response = local_client.get("/api/signing/public/token-1/artifacts/audit_receipt")

    assert response.status_code == 410
    assert "reload" in response.text.lower()


def test_public_signing_document_rejects_session_from_reissued_link(app_main, mocker) -> None:
    record = SimpleNamespace(
        id="req-1",
        status="sent",
        source_pdf_bucket_path="gs://signing/source.pdf",
        source_document_name="Packet",
        source_pdf_sha256="sha",
        source_version="v1",
    )
    stale_session = SimpleNamespace(
        id="sess-1",
        request_id="req-1",
        link_token_id="link-token-old",
        binding_ip_scope=None,
        binding_user_agent_hash=None,
    )
    mocker.patch.object(app_main, "_check_public_rate_limits", return_value=True)
    mocker.patch.object(app_main, "_get_public_record_or_404", return_value=record)
    mocker.patch.object(app_main, "validate_public_signing_document_record", return_value=None)
    mocker.patch.object(app_main, "validate_public_signing_actionable_record", return_value=None)
    mocker.patch.object(app_main, "parse_signing_public_session_token", return_value=("req-1", "sess-1", 9999999999))
    mocker.patch.object(app_main, "get_signing_session_for_request", return_value=stale_session)
    mocker.patch.object(app_main, "build_signing_link_token_id", return_value="link-token-current")
    mocker.patch.object(app_main, "resolve_client_ip", return_value="198.51.100.10")
    mocker.patch.object(app_main, "normalize_signing_user_agent", return_value="ua")

    local_client = TestClient(app_main.app, raise_server_exceptions=False)
    response = local_client.get("/api/signing/public/token-1/document", headers={"x-signing-session": "sess"})

    assert response.status_code == 401
    assert "session expired" in response.text.lower()
