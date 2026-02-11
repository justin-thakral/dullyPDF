"""Unit tests for `backend/firebaseDB/firebase_service.py`."""

import json

import pytest

from backend.firebaseDB import firebase_service as fs


@pytest.fixture(autouse=True)
def _reset_firebase_state():
    fs._firebase_app = None
    fs._firebase_init_error = None
    fs._firebase_project_id = None
    yield
    fs._firebase_app = None
    fs._firebase_init_error = None
    fs._firebase_project_id = None


def test_load_firebase_credentials_returns_none_when_env_missing(monkeypatch) -> None:
    monkeypatch.delenv("FIREBASE_CREDENTIALS", raising=False)
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)

    cred, project_id = fs._load_firebase_credentials()

    assert cred is None
    assert project_id is None


def test_load_firebase_credentials_from_file_path(monkeypatch, mocker, tmp_path) -> None:
    cred_file = tmp_path / "service-account.json"
    cred_file.write_text(json.dumps({"project_id": "project-from-file"}), encoding="utf-8")
    monkeypatch.setenv("FIREBASE_CREDENTIALS", str(cred_file))
    cert = mocker.patch("backend.firebaseDB.firebase_service.credentials.Certificate", return_value="cert-from-file")

    cred, project_id = fs._load_firebase_credentials()

    cert.assert_called_once_with(str(cred_file))
    assert cred == "cert-from-file"
    assert project_id == "project-from-file"


def test_load_firebase_credentials_from_file_path_handles_unreadable_json(monkeypatch, mocker, tmp_path) -> None:
    cred_file = tmp_path / "service-account.json"
    cred_file.write_text("{not-valid-json", encoding="utf-8")
    monkeypatch.setenv("FIREBASE_CREDENTIALS", str(cred_file))
    cert = mocker.patch("backend.firebaseDB.firebase_service.credentials.Certificate", return_value="cert-from-file")

    cred, project_id = fs._load_firebase_credentials()

    cert.assert_called_once_with(str(cred_file))
    assert cred == "cert-from-file"
    assert project_id is None


def test_load_firebase_credentials_from_json_string(monkeypatch, mocker) -> None:
    payload = {
        "project_id": "project-from-json",
        "private_key": "-----BEGIN KEY-----\\nline\\n-----END KEY-----",
        "client_email": "firebase-admin@example.com",
    }
    monkeypatch.setenv("FIREBASE_CREDENTIALS", json.dumps(payload))
    cert = mocker.patch("backend.firebaseDB.firebase_service.credentials.Certificate", side_effect=lambda value: value)

    cred, project_id = fs._load_firebase_credentials()

    cert.assert_called_once()
    assert isinstance(cred, dict)
    assert "\\n" not in cred["private_key"]
    assert "\n" in cred["private_key"]
    assert project_id == "project-from-json"


def test_load_firebase_credentials_rejects_invalid_json(monkeypatch) -> None:
    monkeypatch.setenv("FIREBASE_CREDENTIALS", "not-json-and-not-a-path")

    with pytest.raises(RuntimeError, match="FIREBASE_CREDENTIALS must be JSON or a valid file path"):
        fs._load_firebase_credentials()


def test_load_firebase_credentials_uses_google_application_credentials_fallback(monkeypatch, mocker) -> None:
    payload = {"project_id": "fallback-project", "private_key": "k", "client_email": "x@example.com"}
    monkeypatch.delenv("FIREBASE_CREDENTIALS", raising=False)
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", json.dumps(payload))
    cert = mocker.patch("backend.firebaseDB.firebase_service.credentials.Certificate", side_effect=lambda value: value)

    cred, project_id = fs._load_firebase_credentials()

    cert.assert_called_once()
    assert isinstance(cred, dict)
    assert project_id == "fallback-project"


def test_check_revoked_enabled_respects_override_and_prod_default(monkeypatch) -> None:
    monkeypatch.setenv("FIREBASE_CHECK_REVOKED", "true")
    assert fs._check_revoked_enabled() is True

    monkeypatch.setenv("FIREBASE_CHECK_REVOKED", "0")
    assert fs._check_revoked_enabled() is False

    monkeypatch.delenv("FIREBASE_CHECK_REVOKED", raising=False)
    monkeypatch.setenv("ENV", "production")
    assert fs._check_revoked_enabled() is True

    monkeypatch.setenv("ENV", "test")
    assert fs._check_revoked_enabled() is False


def test_init_firebase_uses_project_precedence_and_caches(monkeypatch, mocker) -> None:
    app_obj = object()
    monkeypatch.setenv("FIREBASE_PROJECT_ID", "project-explicit")
    mocker.patch("backend.firebaseDB.firebase_service._load_firebase_credentials", return_value=("cred", "embedded-project"))
    initialize_app = mocker.patch("backend.firebaseDB.firebase_service.initialize_app", return_value=app_obj)

    fs.init_firebase()
    fs.init_firebase()

    initialize_app.assert_called_once_with("cred", {"projectId": "project-explicit"})
    assert fs._firebase_app is app_obj
    assert fs._firebase_project_id == "project-explicit"


def test_init_firebase_uses_gcp_project_id_fallback(monkeypatch, mocker) -> None:
    app_obj = object()
    monkeypatch.delenv("FIREBASE_PROJECT_ID", raising=False)
    monkeypatch.setenv("GCP_PROJECT_ID", "project-from-gcp-env")
    mocker.patch("backend.firebaseDB.firebase_service._load_firebase_credentials", return_value=(None, None))
    initialize_app = mocker.patch("backend.firebaseDB.firebase_service.initialize_app", return_value=app_obj)

    fs.init_firebase()

    initialize_app.assert_called_once_with(options={"projectId": "project-from-gcp-env"})
    assert fs._firebase_project_id == "project-from-gcp-env"


def test_init_firebase_caches_initialization_error(mocker) -> None:
    mocker.patch("backend.firebaseDB.firebase_service._load_firebase_credentials", return_value=(None, None))
    initialize_app = mocker.patch(
        "backend.firebaseDB.firebase_service.initialize_app",
        side_effect=RuntimeError("init-failed"),
    )

    fs.init_firebase()
    fs.init_firebase()

    assert initialize_app.call_count == 1
    assert isinstance(fs._firebase_init_error, RuntimeError)


def test_get_firestore_client_raises_when_init_failed(mocker) -> None:
    fs._firebase_init_error = RuntimeError("broken")
    mocker.patch("backend.firebaseDB.firebase_service.init_firebase")

    with pytest.raises(RuntimeError, match="Firebase authentication is not configured"):
        fs.get_firestore_client()


def test_get_firestore_client_returns_client_for_initialized_app(mocker) -> None:
    fs._firebase_app = object()
    fs._firebase_init_error = None
    mocker.patch("backend.firebaseDB.firebase_service.init_firebase")
    firestore_client = mocker.patch("backend.firebaseDB.firebase_service.firestore.client", return_value="client")

    client = fs.get_firestore_client()

    assert client == "client"
    firestore_client.assert_called_once_with(app=fs._firebase_app)


def test_get_storage_bucket_raises_when_init_failed(mocker) -> None:
    fs._firebase_init_error = RuntimeError("broken")
    mocker.patch("backend.firebaseDB.firebase_service.init_firebase")

    with pytest.raises(RuntimeError, match="Firebase authentication is not configured"):
        fs.get_storage_bucket("bucket")


def test_get_storage_bucket_returns_bucket_for_initialized_app(mocker) -> None:
    fs._firebase_app = object()
    fs._firebase_init_error = None
    mocker.patch("backend.firebaseDB.firebase_service.init_firebase")
    bucket = mocker.patch("backend.firebaseDB.firebase_service.storage.bucket", return_value="bucket-client")

    result = fs.get_storage_bucket("forms")

    assert result == "bucket-client"
    bucket.assert_called_once_with("forms", app=fs._firebase_app)


@pytest.mark.parametrize("authorization", [None, "", "Token abc", "Bearer   "])
def test_verify_id_token_rejects_missing_or_invalid_auth_header(authorization) -> None:
    with pytest.raises(ValueError, match="Missing Authorization token"):
        fs.verify_id_token(authorization)


def test_verify_id_token_raises_when_firebase_not_configured(mocker) -> None:
    fs._firebase_init_error = RuntimeError("broken")
    mocker.patch("backend.firebaseDB.firebase_service.init_firebase")

    with pytest.raises(RuntimeError, match="Firebase authentication is not configured"):
        fs.verify_id_token("Bearer token")


def test_verify_id_token_passes_clock_skew_and_revocation_mode(monkeypatch, mocker) -> None:
    fs._firebase_app = object()
    fs._firebase_init_error = None
    monkeypatch.setenv("FIREBASE_CLOCK_SKEW_SECONDS", "120")
    mocker.patch("backend.firebaseDB.firebase_service.init_firebase")
    mocker.patch("backend.firebaseDB.firebase_service._check_revoked_enabled", return_value=True)
    verify = mocker.patch("backend.firebaseDB.firebase_service.firebase_auth.verify_id_token", return_value={"uid": "u1"})

    payload = fs.verify_id_token("Bearer signed-token")

    assert payload == {"uid": "u1"}
    verify.assert_called_once_with(
        "signed-token",
        app=fs._firebase_app,
        clock_skew_seconds=120,
        check_revoked=True,
    )


def test_verify_id_token_uses_default_clock_skew_on_invalid_env(monkeypatch, mocker) -> None:
    fs._firebase_app = object()
    fs._firebase_init_error = None
    monkeypatch.setenv("FIREBASE_CLOCK_SKEW_SECONDS", "invalid")
    mocker.patch("backend.firebaseDB.firebase_service.init_firebase")
    mocker.patch("backend.firebaseDB.firebase_service._check_revoked_enabled", return_value=False)
    verify = mocker.patch("backend.firebaseDB.firebase_service.firebase_auth.verify_id_token", return_value={"uid": "u1"})

    fs.verify_id_token("Bearer signed-token")

    verify.assert_called_once_with(
        "signed-token",
        app=fs._firebase_app,
        clock_skew_seconds=60,
        check_revoked=False,
    )


def test_verify_id_token_debug_mode_attempts_unverified_decode_on_failure(mocker, monkeypatch) -> None:
    fs._firebase_app = object()
    fs._firebase_init_error = None
    mocker.patch("backend.firebaseDB.firebase_service.init_firebase")
    mocker.patch("backend.firebaseDB.firebase_service._check_revoked_enabled", return_value=False)
    monkeypatch.setattr(fs, "DEBUG_MODE", True)
    verify = mocker.patch(
        "backend.firebaseDB.firebase_service.firebase_auth.verify_id_token",
        side_effect=ValueError("invalid token"),
    )
    decode = mocker.patch(
        "backend.firebaseDB.firebase_service.jwt.decode",
        return_value={"aud": "a", "iss": "i", "sub": "s", "user_id": "u", "email": "e"},
    )

    with pytest.raises(ValueError, match="invalid token"):
        fs.verify_id_token("Bearer signed-token")

    verify.assert_called_once()
    decode.assert_called_once_with("signed-token", options={"verify_signature": False})


def test_verify_id_token_debug_mode_swallow_decode_error_and_reraise_original(mocker, monkeypatch) -> None:
    fs._firebase_app = object()
    fs._firebase_init_error = None
    mocker.patch("backend.firebaseDB.firebase_service.init_firebase")
    mocker.patch("backend.firebaseDB.firebase_service._check_revoked_enabled", return_value=False)
    monkeypatch.setattr(fs, "DEBUG_MODE", True)
    verify = mocker.patch(
        "backend.firebaseDB.firebase_service.firebase_auth.verify_id_token",
        side_effect=ValueError("invalid token"),
    )
    decode = mocker.patch(
        "backend.firebaseDB.firebase_service.jwt.decode",
        side_effect=ValueError("decode failed"),
    )

    with pytest.raises(ValueError, match="invalid token"):
        fs.verify_id_token("Bearer signed-token")

    verify.assert_called_once()
    decode.assert_called_once_with("signed-token", options={"verify_signature": False})


# ---------------------------------------------------------------------------
# Edge-case: _load_firebase_credentials JSON dict without `private_key` field
# ---------------------------------------------------------------------------
# When the JSON payload is a valid dict but has no "private_key" key, the code
# should skip the newline replacement step and still pass the payload through
# to credentials.Certificate.
def test_load_firebase_credentials_json_without_private_key_skips_newline_replacement(
    monkeypatch, mocker
) -> None:
    payload = {
        "project_id": "project-no-pk",
        "client_email": "firebase-admin@example.com",
    }
    monkeypatch.setenv("FIREBASE_CREDENTIALS", json.dumps(payload))
    cert = mocker.patch(
        "backend.firebaseDB.firebase_service.credentials.Certificate",
        side_effect=lambda value: value,
    )

    cred, project_id = fs._load_firebase_credentials()

    cert.assert_called_once()
    # The returned credential dict should be exactly the original payload
    # with no private_key manipulation applied.
    assert isinstance(cred, dict)
    assert "private_key" not in cred
    assert project_id == "project-no-pk"


# ---------------------------------------------------------------------------
# Edge-case: init_firebase when all project ID sources are None
# ---------------------------------------------------------------------------
# When FIREBASE_PROJECT_ID is unset, embedded project_id is None, and
# GCP_PROJECT_ID is unset, the options dict should remain empty and
# initialize_app should be called with options=None.
def test_init_firebase_with_no_project_id_sources(monkeypatch, mocker) -> None:
    app_obj = object()
    monkeypatch.delenv("FIREBASE_PROJECT_ID", raising=False)
    monkeypatch.delenv("GCP_PROJECT_ID", raising=False)
    mocker.patch(
        "backend.firebaseDB.firebase_service._load_firebase_credentials",
        return_value=(None, None),
    )
    initialize_app = mocker.patch(
        "backend.firebaseDB.firebase_service.initialize_app",
        return_value=app_obj,
    )

    fs.init_firebase()

    # With no credential and no project ID, options is empty dict which is
    # falsy, so it passes options=None.
    initialize_app.assert_called_once_with(options=None)
    assert fs._firebase_app is app_obj
    assert fs._firebase_project_id is None
