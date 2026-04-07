from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

def test_public_signing_complete_missing_source_blob_returns_409(app_main, mocker) -> None:
    record = SimpleNamespace(
        id="req-1",
        user_id="user-1",
        source_pdf_bucket_path="gs://signing/source.pdf",
        anchors=[],
        signature_adopted_name="Alex Signer",
        signer_name="Alex Signer",
        verification_method="email_otp",
        retention_until=None,
    )
    session = SimpleNamespace(
        id="session-1",
        link_token_id="link-token-1",
        verification_completed_at="2026-03-28T10:00:00+00:00",
    )

    mocker.patch.object(
        app_main,
        "_require_public_signing_session",
        return_value=(record, session, "203.0.113.5", "browser/1.0"),
    )
    mocker.patch.object(app_main, "_require_public_signing_session_verified", return_value=None)
    mocker.patch.object(app_main, "validate_public_signing_completable_record", return_value=None)
    mocker.patch.object(app_main, "is_gcs_path", return_value=True)
    mocker.patch.object(app_main, "ensure_signing_storage_configuration", return_value=None)
    mocker.patch.object(
        app_main,
        "resolve_signing_storage_read_bucket_path",
        return_value="gs://signing/source.pdf",
    )
    mocker.patch.object(app_main, "download_storage_bytes", side_effect=FileNotFoundError("missing blob"))

    client = TestClient(app_main.app, raise_server_exceptions=False)
    response = client.post(
        "/api/signing/public/token-1/complete",
        headers={"X-Signing-Session": "session-token-1"},
        json={"intentConfirmed": True},
    )

    assert response.status_code == 409
    assert response.headers["cache-control"] == "private, no-store"
    assert "immutable source pdf is missing" in response.json()["detail"].lower()


def test_public_signing_complete_rolls_back_when_final_artifact_promotion_fails(app_main, mocker) -> None:
    record = SimpleNamespace(
        id="req-1",
        status="sent",
        source_pdf_bucket_path="gs://signing/source.pdf",
        anchors=[],
        signature_adopted_name="Alex Signer",
        signer_name="Alex Signer",
        verification_method="email_otp",
        retention_until="2033-03-28T10:00:00+00:00",
    )
    session = SimpleNamespace(
        id="session-1",
        link_token_id="link-token-1",
        verification_completed_at="2026-03-28T10:00:00+00:00",
    )
    prepared_completion = SimpleNamespace(
        signed_pdf_bytes=b"%PDF-signed",
        signed_pdf_object_path="users/u/signing/r/artifacts/signed_pdf/signed.pdf",
        signed_pdf_bucket_path="gs://signing/artifacts/signed.pdf",
        audit_manifest_object_path="users/u/signing/r/artifacts/audit_manifest/audit.json",
        audit_manifest_bucket_path="gs://signing/artifacts/audit.json",
        audit_receipt_object_path="users/u/signing/r/artifacts/audit_receipt/receipt.pdf",
        audit_receipt_bucket_path="gs://signing/artifacts/receipt.pdf",
        audit_bundle=SimpleNamespace(
            envelope_payload={"ok": True},
            receipt_pdf_bytes=b"%PDF-receipt",
        ),
        artifact_updates={"signed_pdf_bucket_path": "gs://signing/artifacts/signed.pdf"},
        completed_verification_completed_at="2026-03-28T10:00:00+00:00",
    )
    updated_record = SimpleNamespace(
        id="req-1",
        status="completed",
        retention_until="2033-03-28T10:00:00+00:00",
    )

    mocker.patch.object(
        app_main,
        "_require_public_signing_session",
        return_value=(record, session, "203.0.113.5", "browser/1.0"),
    )
    mocker.patch.object(app_main, "_require_public_signing_session_verified", return_value=None)
    mocker.patch.object(app_main, "validate_public_signing_completable_record", return_value=None)
    mocker.patch.object(app_main, "is_gcs_path", return_value=True)
    mocker.patch.object(app_main, "ensure_signing_storage_configuration", return_value=None)
    mocker.patch.object(
        app_main,
        "resolve_signing_storage_read_bucket_path",
        return_value="gs://signing/source.pdf",
    )
    mocker.patch.object(app_main, "download_storage_bytes", return_value=b"%PDF-source")
    mocker.patch.object(app_main, "list_signing_events_for_request", return_value=[])
    mocker.patch.object(app_main, "prepare_public_signing_completion", mocker.AsyncMock(return_value=prepared_completion))
    mocker.patch.object(
        app_main,
        "upload_signing_staging_pdf_bytes_for_final",
        side_effect=[
            "gs://stage/artifacts/signed.pdf",
            "gs://stage/artifacts/receipt.pdf",
        ],
    )
    mocker.patch.object(
        app_main,
        "upload_signing_staging_json_for_final",
        return_value="gs://stage/artifacts/audit.json",
    )
    mocker.patch.object(app_main, "complete_signing_request_transactional", return_value=updated_record)
    mocker.patch.object(app_main, "_require_public_transition_applied", return_value=updated_record)
    promote_mock = mocker.patch.object(
        app_main,
        "promote_signing_staged_object",
        side_effect=RuntimeError("final bucket unavailable"),
    )
    rollback_mock = mocker.patch.object(
        app_main,
        "rollback_completed_signing_request_transactional",
        return_value=SimpleNamespace(id="req-1", status="sent"),
    )
    delete_mock = mocker.patch.object(app_main, "delete_storage_object", return_value=None)
    touch_mock = mocker.patch.object(app_main, "touch_signing_session", return_value=None)
    event_mock = mocker.patch.object(app_main, "_record_public_signing_event", return_value=None)

    client = TestClient(app_main.app, raise_server_exceptions=False)
    response = client.post(
        "/api/signing/public/token-1/complete",
        headers={"X-Signing-Session": "session-token-1"},
        json={"intentConfirmed": True},
    )

    assert response.status_code == 503
    assert response.headers["cache-control"] == "private, no-store"
    assert "failed to finalize retained signing artifacts" in response.json()["detail"].lower()
    promote_mock.assert_called_once_with(
        "gs://signing/artifacts/signed.pdf",
        retain_until="2033-03-28T10:00:00+00:00",
    )
    rollback_mock.assert_called_once_with(
        "req-1",
        session_id="session-1",
        completed_at=mocker.ANY,
    )
    assert delete_mock.call_count == 6
    touch_mock.assert_not_called()
    event_mock.assert_not_called()


def test_public_signing_envelope_completion_rejects_stale_completed_snapshot(app_main, mocker) -> None:
    record = SimpleNamespace(
        id="req-1",
        status="sent",
        envelope_id="env-1",
        source_pdf_bucket_path="gs://signing/source.pdf",
        source_pdf_sha256="abc123",
        source_version="workspace:form-alpha:abc123",
        anchors=[],
        signature_adopted_name="Alex Signer",
        signer_name="Alex Signer",
        verification_method="email_otp",
        retention_until=None,
    )
    session = SimpleNamespace(
        id="session-1",
        link_token_id="link-token-1",
        verification_completed_at="2026-03-28T10:00:00+00:00",
    )
    stale_record = SimpleNamespace(
        id="req-1",
        status="completed",
        envelope_id="env-1",
        completed_at="2026-03-28T09:00:00+00:00",
        completed_session_id="session-old",
        invalidation_reason=None,
        representative_title=None,
        representative_company_name=None,
        authority_attested_at=None,
    )

    mocker.patch.object(
        app_main,
        "_require_public_signing_session",
        return_value=(record, session, "203.0.113.5", "browser/1.0"),
    )
    mocker.patch.object(app_main, "_require_public_signing_session_verified", return_value=None)
    mocker.patch.object(app_main, "validate_public_signing_completable_record", return_value=None)
    mocker.patch.object(
        app_main,
        "resolve_company_authority_completion_payload",
        return_value={
            "representative_title": None,
            "representative_company_name": None,
        },
    )
    mocker.patch.object(app_main, "is_gcs_path", return_value=True)
    mocker.patch.object(app_main, "ensure_signing_storage_configuration", return_value=None)
    mocker.patch.object(
        app_main,
        "resolve_signing_storage_read_bucket_path",
        return_value="gs://signing/source.pdf",
    )
    mocker.patch.object(app_main, "download_storage_bytes", return_value=b"%PDF-source")
    mocker.patch.object(app_main, "complete_signing_request_transactional", return_value=stale_record)
    touch_mock = mocker.patch.object(app_main, "touch_signing_session", return_value=None)
    event_mock = mocker.patch.object(app_main, "_record_public_signing_event", return_value=None)

    client = TestClient(app_main.app, raise_server_exceptions=False)
    response = client.post(
        "/api/signing/public/token-1/complete",
        headers={"X-Signing-Session": "session-token-1"},
        json={"intentConfirmed": True},
    )

    assert response.status_code == 409
    assert "already been completed" in response.json()["detail"].lower()
    touch_mock.assert_not_called()
    event_mock.assert_not_called()
