import pytest


def test_is_prod_and_docs_enabled(monkeypatch, app_main, mocker) -> None:
    monkeypatch.setenv("ENV", "prod")
    assert app_main._is_prod() is True
    assert app_main._docs_enabled() is False

    monkeypatch.setenv("ENV", "test")
    assert app_main._is_prod() is False
    assert app_main._docs_enabled() is True

    mocker.patch.object(app_main, "_is_prod", return_value=True)
    assert app_main._docs_enabled() is False


def test_legacy_endpoints_enabled_by_env(monkeypatch, app_main, mocker) -> None:
    mocker.patch.object(app_main, "_is_prod", return_value=False)
    monkeypatch.delenv("SANDBOX_ENABLE_LEGACY_ENDPOINTS", raising=False)
    assert app_main._legacy_endpoints_enabled() is True

    monkeypatch.setenv("SANDBOX_ENABLE_LEGACY_ENDPOINTS", "false")
    assert app_main._legacy_endpoints_enabled() is False

    mocker.patch.object(app_main, "_is_prod", return_value=True)
    assert app_main._legacy_endpoints_enabled() is False


def test_resolve_detection_mode_local_tasks_fallback(monkeypatch, app_main, mocker) -> None:
    monkeypatch.setenv("DETECTOR_MODE", "local")
    monkeypatch.setenv("DETECTOR_TASKS_QUEUE", "queue-1")
    mocker.patch.object(app_main, "_commonforms_available", return_value=False)
    assert app_main._resolve_detection_mode() == "tasks"

    mocker.patch.object(app_main, "_commonforms_available", return_value=True)
    assert app_main._resolve_detection_mode() == "local"

    monkeypatch.setenv("DETECTOR_MODE", "tasks")
    assert app_main._resolve_detection_mode() == "tasks"

    monkeypatch.delenv("DETECTOR_MODE", raising=False)
    assert app_main._resolve_detection_mode() == "tasks"

    monkeypatch.delenv("DETECTOR_TASKS_QUEUE", raising=False)
    assert app_main._resolve_detection_mode() == "local"


def test_require_prod_env_skips_outside_prod(app_main, mocker) -> None:
    mocker.patch.object(app_main, "_is_prod", return_value=False)
    app_main._require_prod_env()


def test_require_prod_env_reports_missing_keys(app_main, mocker) -> None:
    mocker.patch.object(app_main, "_is_prod", return_value=True)
    mocker.patch.object(app_main, "_recaptcha_required_any", return_value=True)
    mocker.patch.object(app_main, "_resolve_detection_mode", return_value="tasks")
    mocker.patch.object(app_main, "_env_value", return_value="")
    mocker.patch.object(app_main, "_env_truthy", return_value=False)
    with pytest.raises(RuntimeError) as ctx:
        app_main._require_prod_env()
    message = str(ctx.value)
    assert "Missing required prod env vars" in message
    assert "SANDBOX_CORS_ORIGINS" in message
    assert "DETECTOR_TASKS_SERVICE_ACCOUNT" in message


def test_require_prod_env_rejects_wildcard_cors(monkeypatch, app_main, mocker) -> None:
    values = {
        "SANDBOX_CORS_ORIGINS": "*",
        "FIREBASE_PROJECT_ID": "proj",
        "FIREBASE_CREDENTIALS": "x",
        "FORMS_BUCKET": "forms",
        "TEMPLATES_BUCKET": "templates",
        "CONTACT_TO_EMAIL": "to@example.com",
        "CONTACT_FROM_EMAIL": "from@example.com",
        "GMAIL_CLIENT_ID": "cid",
        "GMAIL_CLIENT_SECRET": "secret",
        "GMAIL_REFRESH_TOKEN": "refresh",
        "RECAPTCHA_SITE_KEY": "site",
        "RECAPTCHA_PROJECT_ID": "proj",
        "DETECTOR_TASKS_PROJECT": "proj",
        "DETECTOR_TASKS_LOCATION": "us-central1",
        "DETECTOR_TASKS_QUEUE": "queue",
        "DETECTOR_SERVICE_URL": "https://detector",
        "DETECTOR_TASKS_SERVICE_ACCOUNT": "sa@example.com",
    }
    mocker.patch.object(app_main, "_is_prod", return_value=True)
    mocker.patch.object(app_main, "_recaptcha_required_any", return_value=True)
    mocker.patch.object(app_main, "_resolve_detection_mode", return_value="tasks")
    mocker.patch.object(app_main, "_env_truthy", return_value=True)
    mocker.patch.object(app_main, "_env_value", side_effect=lambda key: values.get(key, ""))
    with pytest.raises(RuntimeError) as ctx:
        app_main._require_prod_env()
    assert "cannot be '*'" in str(ctx.value)


def test_require_prod_env_accepts_complete_matrix(app_main, mocker) -> None:
    values = {
        "SANDBOX_CORS_ORIGINS": "https://app.example.com",
        "FIREBASE_PROJECT_ID": "proj",
        "FIREBASE_CREDENTIALS": "x",
        "FORMS_BUCKET": "forms",
        "TEMPLATES_BUCKET": "templates",
        "CONTACT_TO_EMAIL": "to@example.com",
        "CONTACT_FROM_EMAIL": "from@example.com",
        "GMAIL_CLIENT_ID": "cid",
        "GMAIL_CLIENT_SECRET": "secret",
        "GMAIL_REFRESH_TOKEN": "refresh",
        "RECAPTCHA_SITE_KEY": "site",
        "RECAPTCHA_PROJECT_ID": "proj",
        "DETECTOR_TASKS_PROJECT": "proj",
        "DETECTOR_TASKS_LOCATION": "us-central1",
        "DETECTOR_TASKS_QUEUE": "queue",
        "DETECTOR_SERVICE_URL": "https://detector",
        "DETECTOR_TASKS_SERVICE_ACCOUNT": "sa@example.com",
    }
    mocker.patch.object(app_main, "_is_prod", return_value=True)
    mocker.patch.object(app_main, "_recaptcha_required_any", return_value=True)
    mocker.patch.object(app_main, "_resolve_detection_mode", return_value="tasks")
    mocker.patch.object(app_main, "_env_truthy", return_value=True)
    mocker.patch.object(app_main, "_env_value", side_effect=lambda key: values.get(key, ""))
    app_main._require_prod_env()


def test_resolve_cors_origins_wildcard_debug_gating(monkeypatch, app_main, mocker) -> None:
    monkeypatch.setenv("SANDBOX_CORS_ORIGINS", "*")
    mocker.patch.object(app_main, "debug_enabled", return_value=True)
    assert app_main._resolve_cors_origins() == ["*"]

    mocker.patch.object(app_main, "debug_enabled", return_value=False)
    mocker.patch.object(app_main, "_is_prod", return_value=False)
    origins = app_main._resolve_cors_origins()
    assert "*" not in origins
    assert "http://localhost:5173" in origins


def test_resolve_cors_origins_dedupes_and_handles_malformed_values(monkeypatch, app_main, mocker) -> None:
    monkeypatch.setenv("SANDBOX_CORS_ORIGINS", " https://a.example.com , , https://a.example.com ")
    mocker.patch.object(app_main, "_is_prod", return_value=True)
    origins = app_main._resolve_cors_origins()
    assert origins == ["https://a.example.com"]


def test_resolve_stream_cors_headers_variants(app_main, mocker) -> None:
    assert app_main._resolve_stream_cors_headers(None) == {}

    mocker.patch.object(app_main, "_resolve_cors_origins", return_value=["*"])
    assert app_main._resolve_stream_cors_headers("https://any.example.com") == {
        "Access-Control-Allow-Origin": "*"
    }

    mocker.patch.object(app_main, "_resolve_cors_origins", return_value=["https://allowed.example.com"])
    assert app_main._resolve_stream_cors_headers("https://allowed.example.com") == {
        "Access-Control-Allow-Origin": "https://allowed.example.com",
        "Vary": "Origin",
    }
    assert app_main._resolve_stream_cors_headers("https://blocked.example.com") == {}


# ---------------------------------------------------------------------------
# Edge-case: commonforms_available() returns False when find_spec raises
# ---------------------------------------------------------------------------
# The function wraps importlib.util.find_spec in a blanket except so any
# import-time error degrades gracefully to False instead of crashing startup.
def test_commonforms_available_returns_false_on_find_spec_exception(monkeypatch, app_main, mocker) -> None:
    import importlib.util

    mocker.patch.object(
        importlib.util,
        "find_spec",
        side_effect=ModuleNotFoundError("broken loader"),
    )
    assert app_main._commonforms_available() is False


def test_resolve_detection_mode_defaults_to_tasks_when_only_light_queue_is_configured(
    monkeypatch,
    app_main,
) -> None:
    """If only DETECTOR_TASKS_QUEUE_LIGHT is configured, startup should still
    resolve tasks mode so the API does not attempt local CommonForms."""
    monkeypatch.delenv("DETECTOR_MODE", raising=False)
    monkeypatch.delenv("DETECTOR_TASKS_QUEUE", raising=False)
    monkeypatch.setenv("DETECTOR_TASKS_QUEUE_LIGHT", "light-queue")

    assert app_main._resolve_detection_mode() == "tasks"


def test_resolve_detection_mode_local_falls_back_to_tasks_with_light_queue_only(
    monkeypatch,
    app_main,
    mocker,
) -> None:
    """When local mode is requested but CommonForms is unavailable, the code
    should fall back to tasks if either queue env variant is present."""
    monkeypatch.setenv("DETECTOR_MODE", "local")
    monkeypatch.delenv("DETECTOR_TASKS_QUEUE", raising=False)
    monkeypatch.setenv("DETECTOR_TASKS_QUEUE_LIGHT", "light-queue")
    mocker.patch.object(app_main, "_commonforms_available", return_value=False)

    assert app_main._resolve_detection_mode() == "tasks"
