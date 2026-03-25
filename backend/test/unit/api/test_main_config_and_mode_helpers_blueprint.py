import pytest


def test_is_prod_and_docs_enabled(monkeypatch, app_main, mocker) -> None:
    monkeypatch.setenv("ENV", "prod")
    assert app_main._is_prod() is True
    assert app_main._docs_enabled() is False

    monkeypatch.setenv("ENV", "test")
    monkeypatch.delenv("SANDBOX_ENABLE_DOCS", raising=False)
    assert app_main._is_prod() is False
    assert app_main._docs_enabled() is True

    monkeypatch.setenv("SANDBOX_ENABLE_DOCS", "false")
    assert app_main._docs_enabled() is False

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
    assert "SANDBOX_TRUSTED_HOSTS" in message
    assert "FIREBASE_USE_ADC=true" in message
    assert "RECAPTCHA_ALLOWED_HOSTNAMES" in message
    assert "STRIPE_SECRET_KEY" in message
    assert "DETECTOR_TASKS_SERVICE_ACCOUNT" in message
    assert "FILL_LINK_TOKEN_SECRET" in message


def test_require_prod_env_rejects_wildcard_cors(monkeypatch, app_main, mocker) -> None:
    values = {
        "SANDBOX_CORS_ORIGINS": "*",
        "SANDBOX_TRUSTED_HOSTS": "app.example.com",
        "FIREBASE_PROJECT_ID": "proj",
        "FIREBASE_USE_ADC": "true",
        "FORMS_BUCKET": "forms",
        "TEMPLATES_BUCKET": "templates",
        "FILL_LINK_TOKEN_SECRET": "fill-link-secret-0123456789abcdef",
        "CONTACT_TO_EMAIL": "to@example.com",
        "CONTACT_FROM_EMAIL": "from@example.com",
        "GMAIL_CLIENT_ID": "cid",
        "GMAIL_CLIENT_SECRET": "secret",
        "GMAIL_REFRESH_TOKEN": "refresh",
        "STRIPE_SECRET_KEY": "sk_live_abc",
        "STRIPE_WEBHOOK_SECRET": "whsec_abc",
        "STRIPE_PRICE_PRO_MONTHLY": "price_monthly",
        "STRIPE_PRICE_PRO_YEARLY": "price_yearly",
        "STRIPE_PRICE_REFILL_500": "price_refill",
        "STRIPE_CHECKOUT_SUCCESS_URL": "https://dullypdf.com/account?billing=success",
        "STRIPE_CHECKOUT_CANCEL_URL": "https://dullypdf.com/account?billing=cancel",
        "STRIPE_MAX_PROCESSED_EVENTS": "256",
        "RECAPTCHA_SITE_KEY": "site",
        "RECAPTCHA_PROJECT_ID": "proj",
        "RECAPTCHA_ALLOWED_HOSTNAMES": "dullypdf.com",
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


def test_require_prod_env_rejects_wildcard_trusted_hosts(app_main, mocker) -> None:
    values = {
        "SANDBOX_CORS_ORIGINS": "https://app.example.com",
        "SANDBOX_TRUSTED_HOSTS": "*",
        "FIREBASE_PROJECT_ID": "proj",
        "FIREBASE_USE_ADC": "true",
        "FORMS_BUCKET": "forms",
        "TEMPLATES_BUCKET": "templates",
        "FILL_LINK_TOKEN_SECRET": "fill-link-secret-0123456789abcdef",
        "CONTACT_TO_EMAIL": "to@example.com",
        "CONTACT_FROM_EMAIL": "from@example.com",
        "GMAIL_CLIENT_ID": "cid",
        "GMAIL_CLIENT_SECRET": "secret",
        "GMAIL_REFRESH_TOKEN": "refresh",
        "STRIPE_SECRET_KEY": "sk_live_abc",
        "STRIPE_WEBHOOK_SECRET": "whsec_abc",
        "STRIPE_PRICE_PRO_MONTHLY": "price_monthly",
        "STRIPE_PRICE_PRO_YEARLY": "price_yearly",
        "STRIPE_PRICE_REFILL_500": "price_refill",
        "STRIPE_CHECKOUT_SUCCESS_URL": "https://dullypdf.com/account?billing=success",
        "STRIPE_CHECKOUT_CANCEL_URL": "https://dullypdf.com/account?billing=cancel",
        "STRIPE_MAX_PROCESSED_EVENTS": "256",
        "RECAPTCHA_SITE_KEY": "site",
        "RECAPTCHA_PROJECT_ID": "proj",
        "RECAPTCHA_ALLOWED_HOSTNAMES": "dullypdf.com",
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
    assert "SANDBOX_TRUSTED_HOSTS (cannot be '*')" in str(ctx.value)


def test_require_prod_env_accepts_complete_matrix(app_main, mocker) -> None:
    values = {
        "SANDBOX_CORS_ORIGINS": "https://app.example.com",
        "SANDBOX_TRUSTED_HOSTS": "app.example.com",
        "FIREBASE_PROJECT_ID": "proj",
        "FIREBASE_USE_ADC": "true",
        "FORMS_BUCKET": "forms",
        "TEMPLATES_BUCKET": "templates",
        "FILL_LINK_TOKEN_SECRET": "fill-link-secret-0123456789abcdef",
        "CONTACT_TO_EMAIL": "to@example.com",
        "CONTACT_FROM_EMAIL": "from@example.com",
        "GMAIL_CLIENT_ID": "cid",
        "GMAIL_CLIENT_SECRET": "secret",
        "GMAIL_REFRESH_TOKEN": "refresh",
        "STRIPE_SECRET_KEY": "sk_live_abc",
        "STRIPE_WEBHOOK_SECRET": "whsec_abc",
        "STRIPE_PRICE_PRO_MONTHLY": "price_monthly",
        "STRIPE_PRICE_PRO_YEARLY": "price_yearly",
        "STRIPE_PRICE_REFILL_500": "price_refill",
        "STRIPE_CHECKOUT_SUCCESS_URL": "https://dullypdf.com/account?billing=success",
        "STRIPE_CHECKOUT_CANCEL_URL": "https://dullypdf.com/account?billing=cancel",
        "STRIPE_MAX_PROCESSED_EVENTS": "256",
        "RECAPTCHA_SITE_KEY": "site",
        "RECAPTCHA_PROJECT_ID": "proj",
        "RECAPTCHA_ALLOWED_HOSTNAMES": "dullypdf.com",
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


def test_require_prod_env_rejects_non_https_checkout_urls(app_main, mocker) -> None:
    values = {
        "SANDBOX_CORS_ORIGINS": "https://app.example.com",
        "SANDBOX_TRUSTED_HOSTS": "app.example.com",
        "FIREBASE_PROJECT_ID": "proj",
        "FIREBASE_USE_ADC": "true",
        "FORMS_BUCKET": "forms",
        "TEMPLATES_BUCKET": "templates",
        "FILL_LINK_TOKEN_SECRET": "fill-link-secret-0123456789abcdef",
        "CONTACT_TO_EMAIL": "to@example.com",
        "CONTACT_FROM_EMAIL": "from@example.com",
        "GMAIL_CLIENT_ID": "cid",
        "GMAIL_CLIENT_SECRET": "secret",
        "GMAIL_REFRESH_TOKEN": "refresh",
        "STRIPE_SECRET_KEY": "sk_live_abc",
        "STRIPE_WEBHOOK_SECRET": "whsec_abc",
        "STRIPE_PRICE_PRO_MONTHLY": "price_monthly",
        "STRIPE_PRICE_PRO_YEARLY": "price_yearly",
        "STRIPE_PRICE_REFILL_500": "price_refill",
        "STRIPE_CHECKOUT_SUCCESS_URL": "http://dullypdf.com/account?billing=success",
        "STRIPE_CHECKOUT_CANCEL_URL": "http://dullypdf.com/account?billing=cancel",
        "RECAPTCHA_SITE_KEY": "site",
        "RECAPTCHA_PROJECT_ID": "proj",
        "RECAPTCHA_ALLOWED_HOSTNAMES": "dullypdf.com",
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
    message = str(ctx.value)
    assert "STRIPE_CHECKOUT_SUCCESS_URL (must use https)" in message
    assert "STRIPE_CHECKOUT_CANCEL_URL (must use https)" in message


def test_require_prod_env_rejects_positive_stripe_processed_event_cap(app_main, mocker) -> None:
    values = {
        "SANDBOX_CORS_ORIGINS": "https://app.example.com",
        "SANDBOX_TRUSTED_HOSTS": "app.example.com",
        "FIREBASE_PROJECT_ID": "proj",
        "FIREBASE_USE_ADC": "true",
        "FORMS_BUCKET": "forms",
        "TEMPLATES_BUCKET": "templates",
        "FILL_LINK_TOKEN_SECRET": "fill-link-secret-0123456789abcdef",
        "CONTACT_TO_EMAIL": "to@example.com",
        "CONTACT_FROM_EMAIL": "from@example.com",
        "GMAIL_CLIENT_ID": "cid",
        "GMAIL_CLIENT_SECRET": "secret",
        "GMAIL_REFRESH_TOKEN": "refresh",
        "STRIPE_SECRET_KEY": "sk_live_abc",
        "STRIPE_WEBHOOK_SECRET": "whsec_abc",
        "STRIPE_PRICE_PRO_MONTHLY": "price_monthly",
        "STRIPE_PRICE_PRO_YEARLY": "price_yearly",
        "STRIPE_PRICE_REFILL_500": "price_refill",
        "STRIPE_CHECKOUT_SUCCESS_URL": "https://dullypdf.com/account?billing=success",
        "STRIPE_CHECKOUT_CANCEL_URL": "https://dullypdf.com/account?billing=cancel",
        "STRIPE_MAX_PROCESSED_EVENTS": "0",
        "RECAPTCHA_SITE_KEY": "site",
        "RECAPTCHA_PROJECT_ID": "proj",
        "RECAPTCHA_ALLOWED_HOSTNAMES": "dullypdf.com",
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
    assert "STRIPE_MAX_PROCESSED_EVENTS (must be a positive integer in prod)" in str(ctx.value)


def test_require_prod_env_rejects_disabled_fill_link_recaptcha(app_main, mocker) -> None:
    values = {
        "SANDBOX_CORS_ORIGINS": "https://app.example.com",
        "SANDBOX_TRUSTED_HOSTS": "app.example.com",
        "FIREBASE_PROJECT_ID": "proj",
        "FIREBASE_USE_ADC": "true",
        "FORMS_BUCKET": "forms",
        "TEMPLATES_BUCKET": "templates",
        "FILL_LINK_TOKEN_SECRET": "fill-link-secret-0123456789abcdef",
        "CONTACT_TO_EMAIL": "to@example.com",
        "CONTACT_FROM_EMAIL": "from@example.com",
        "GMAIL_CLIENT_ID": "cid",
        "GMAIL_CLIENT_SECRET": "secret",
        "GMAIL_REFRESH_TOKEN": "refresh",
        "STRIPE_SECRET_KEY": "sk_live_abc",
        "STRIPE_WEBHOOK_SECRET": "whsec_abc",
        "STRIPE_PRICE_PRO_MONTHLY": "price_monthly",
        "STRIPE_PRICE_PRO_YEARLY": "price_yearly",
        "STRIPE_PRICE_REFILL_500": "price_refill",
        "STRIPE_CHECKOUT_SUCCESS_URL": "https://dullypdf.com/account?billing=success",
        "STRIPE_CHECKOUT_CANCEL_URL": "https://dullypdf.com/account?billing=cancel",
        "RECAPTCHA_SITE_KEY": "site",
        "RECAPTCHA_PROJECT_ID": "proj",
        "RECAPTCHA_ALLOWED_HOSTNAMES": "dullypdf.com",
        "DETECTOR_TASKS_PROJECT": "proj",
        "DETECTOR_TASKS_LOCATION": "us-central1",
        "DETECTOR_TASKS_QUEUE": "queue",
        "DETECTOR_SERVICE_URL": "https://detector",
        "DETECTOR_TASKS_SERVICE_ACCOUNT": "sa@example.com",
        "FILL_LINK_REQUIRE_RECAPTCHA": "false",
    }
    mocker.patch.object(app_main, "_is_prod", return_value=True)
    mocker.patch.object(app_main, "_recaptcha_required_any", return_value=True)
    mocker.patch.object(app_main, "_resolve_detection_mode", return_value="tasks")
    mocker.patch.object(app_main, "_env_truthy", return_value=True)
    mocker.patch.object(app_main, "_env_value", side_effect=lambda key: values.get(key, ""))
    with pytest.raises(RuntimeError) as ctx:
        app_main._require_prod_env()
    assert "FILL_LINK_REQUIRE_RECAPTCHA (must be true in prod)" in str(ctx.value)


def test_require_prod_env_rejects_placeholder_fill_link_token_secret(app_main, mocker) -> None:
    values = {
        "SANDBOX_CORS_ORIGINS": "https://app.example.com",
        "SANDBOX_TRUSTED_HOSTS": "app.example.com",
        "FIREBASE_PROJECT_ID": "proj",
        "FIREBASE_USE_ADC": "true",
        "FORMS_BUCKET": "forms",
        "TEMPLATES_BUCKET": "templates",
        "FILL_LINK_TOKEN_SECRET": "change_me_prod_fill_link_token_secret",
        "CONTACT_TO_EMAIL": "to@example.com",
        "CONTACT_FROM_EMAIL": "from@example.com",
        "GMAIL_CLIENT_ID": "cid",
        "GMAIL_CLIENT_SECRET": "secret",
        "GMAIL_REFRESH_TOKEN": "refresh",
        "STRIPE_SECRET_KEY": "sk_live_abc",
        "STRIPE_WEBHOOK_SECRET": "whsec_abc",
        "STRIPE_PRICE_PRO_MONTHLY": "price_monthly",
        "STRIPE_PRICE_PRO_YEARLY": "price_yearly",
        "STRIPE_PRICE_REFILL_500": "price_refill",
        "STRIPE_CHECKOUT_SUCCESS_URL": "https://dullypdf.com/account?billing=success",
        "STRIPE_CHECKOUT_CANCEL_URL": "https://dullypdf.com/account?billing=cancel",
        "RECAPTCHA_SITE_KEY": "site",
        "RECAPTCHA_PROJECT_ID": "proj",
        "RECAPTCHA_ALLOWED_HOSTNAMES": "dullypdf.com",
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
    assert "at least 32 characters" in str(ctx.value)


def test_require_prod_env_rejects_short_fill_link_token_secret(app_main, mocker) -> None:
    values = {
        "SANDBOX_CORS_ORIGINS": "https://app.example.com",
        "SANDBOX_TRUSTED_HOSTS": "app.example.com",
        "FIREBASE_PROJECT_ID": "proj",
        "FIREBASE_USE_ADC": "true",
        "FORMS_BUCKET": "forms",
        "TEMPLATES_BUCKET": "templates",
        "FILL_LINK_TOKEN_SECRET": "short-secret",
        "CONTACT_TO_EMAIL": "to@example.com",
        "CONTACT_FROM_EMAIL": "from@example.com",
        "GMAIL_CLIENT_ID": "cid",
        "GMAIL_CLIENT_SECRET": "secret",
        "GMAIL_REFRESH_TOKEN": "refresh",
        "STRIPE_SECRET_KEY": "sk_live_abc",
        "STRIPE_WEBHOOK_SECRET": "whsec_abc",
        "STRIPE_PRICE_PRO_MONTHLY": "price_monthly",
        "STRIPE_PRICE_PRO_YEARLY": "price_yearly",
        "STRIPE_PRICE_REFILL_500": "price_refill",
        "STRIPE_CHECKOUT_SUCCESS_URL": "https://dullypdf.com/account?billing=success",
        "STRIPE_CHECKOUT_CANCEL_URL": "https://dullypdf.com/account?billing=cancel",
        "RECAPTCHA_SITE_KEY": "site",
        "RECAPTCHA_PROJECT_ID": "proj",
        "RECAPTCHA_ALLOWED_HOSTNAMES": "dullypdf.com",
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
    assert "at least 32 characters" in str(ctx.value)


def test_require_prod_env_rejects_explicit_firebase_credentials_in_prod(app_main, mocker) -> None:
    values = {
        "SANDBOX_CORS_ORIGINS": "https://app.example.com",
        "SANDBOX_TRUSTED_HOSTS": "app.example.com",
        "FIREBASE_PROJECT_ID": "proj",
        "FIREBASE_USE_ADC": "true",
        "FIREBASE_CREDENTIALS": '{"type":"service_account"}',
        "GOOGLE_APPLICATION_CREDENTIALS": "/tmp/firebase.json",
        "FORMS_BUCKET": "forms",
        "TEMPLATES_BUCKET": "templates",
        "FILL_LINK_TOKEN_SECRET": "fill-link-secret-0123456789abcdef",
        "CONTACT_TO_EMAIL": "to@example.com",
        "CONTACT_FROM_EMAIL": "from@example.com",
        "GMAIL_CLIENT_ID": "cid",
        "GMAIL_CLIENT_SECRET": "secret",
        "GMAIL_REFRESH_TOKEN": "refresh",
        "STRIPE_SECRET_KEY": "sk_live_abc",
        "STRIPE_WEBHOOK_SECRET": "whsec_abc",
        "STRIPE_PRICE_PRO_MONTHLY": "price_monthly",
        "STRIPE_PRICE_PRO_YEARLY": "price_yearly",
        "STRIPE_PRICE_REFILL_500": "price_refill",
        "STRIPE_CHECKOUT_SUCCESS_URL": "https://dullypdf.com/account?billing=success",
        "STRIPE_CHECKOUT_CANCEL_URL": "https://dullypdf.com/account?billing=cancel",
        "RECAPTCHA_SITE_KEY": "site",
        "RECAPTCHA_PROJECT_ID": "proj",
        "RECAPTCHA_ALLOWED_HOSTNAMES": "dullypdf.com",
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
    message = str(ctx.value)
    assert "FIREBASE_CREDENTIALS (must be unset in prod; use ADC only)" in message
    assert "GOOGLE_APPLICATION_CREDENTIALS (must be unset in prod; use ADC only)" in message


def test_require_prod_env_rejects_missing_recaptcha_allowed_hostnames(app_main, mocker) -> None:
    values = {
        "SANDBOX_CORS_ORIGINS": "https://app.example.com",
        "SANDBOX_TRUSTED_HOSTS": "app.example.com",
        "FIREBASE_PROJECT_ID": "proj",
        "FIREBASE_USE_ADC": "true",
        "FORMS_BUCKET": "forms",
        "TEMPLATES_BUCKET": "templates",
        "FILL_LINK_TOKEN_SECRET": "fill-link-secret-0123456789abcdef",
        "CONTACT_TO_EMAIL": "to@example.com",
        "CONTACT_FROM_EMAIL": "from@example.com",
        "GMAIL_CLIENT_ID": "cid",
        "GMAIL_CLIENT_SECRET": "secret",
        "GMAIL_REFRESH_TOKEN": "refresh",
        "STRIPE_SECRET_KEY": "sk_live_abc",
        "STRIPE_WEBHOOK_SECRET": "whsec_abc",
        "STRIPE_PRICE_PRO_MONTHLY": "price_monthly",
        "STRIPE_PRICE_PRO_YEARLY": "price_yearly",
        "STRIPE_PRICE_REFILL_500": "price_refill",
        "STRIPE_CHECKOUT_SUCCESS_URL": "https://dullypdf.com/account?billing=success",
        "STRIPE_CHECKOUT_CANCEL_URL": "https://dullypdf.com/account?billing=cancel",
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
    assert "RECAPTCHA_ALLOWED_HOSTNAMES (required in prod when reCAPTCHA is enabled)" in str(ctx.value)


def test_resolve_cors_origins_wildcard_debug_gating(monkeypatch, app_main, mocker) -> None:
    monkeypatch.setenv("SANDBOX_CORS_ORIGINS", "*")
    mocker.patch.object(app_main, "debug_enabled", return_value=True)
    assert app_main._resolve_cors_origins() == ["*"]

    mocker.patch.object(app_main, "debug_enabled", return_value=False)
    mocker.patch.object(app_main, "_is_prod", return_value=False)
    origins = app_main._resolve_cors_origins()
    assert "*" not in origins
    assert "http://localhost:5173" in origins
    assert "http://127.0.0.1:5177" in origins


def test_resolve_cors_origins_dev_defaults_cover_vite_increment_ports(monkeypatch, app_main, mocker) -> None:
    monkeypatch.delenv("SANDBOX_CORS_ORIGINS", raising=False)
    mocker.patch.object(app_main, "_is_prod", return_value=False)

    origins = app_main._resolve_cors_origins()

    assert "http://localhost:5173" in origins
    assert "http://localhost:5189" in origins
    assert "http://127.0.0.1:5177" in origins


def test_resolve_cors_origins_dedupes_and_handles_malformed_values(monkeypatch, app_main, mocker) -> None:
    monkeypatch.setenv("SANDBOX_CORS_ORIGINS", " https://a.example.com , , https://a.example.com ")
    mocker.patch.object(app_main, "_is_prod", return_value=True)
    origins = app_main._resolve_cors_origins()
    assert origins == ["https://a.example.com"]


def test_resolve_trusted_hosts_normalizes_and_dedupes(monkeypatch, app_main, mocker) -> None:
    monkeypatch.setenv(
        "SANDBOX_TRUSTED_HOSTS",
        " https://dullypdf.com , dullypdf.web.app:443 , *.example.com , dullypdf.com ",
    )
    mocker.patch.object(app_main, "_is_prod", return_value=True)

    hosts = app_main._resolve_trusted_hosts()

    assert hosts == ["dullypdf.com", "dullypdf.web.app", "*.example.com"]


def test_resolve_trusted_hosts_adds_dev_defaults(monkeypatch, app_main, mocker) -> None:
    monkeypatch.delenv("SANDBOX_TRUSTED_HOSTS", raising=False)
    mocker.patch.object(app_main, "_is_prod", return_value=False)

    hosts = app_main._resolve_trusted_hosts()

    assert "testserver" in hosts
    assert "localhost" in hosts
    assert "127.0.0.1" in hosts


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


def test_resolve_openai_modes_default_to_local_and_promote_to_tasks(monkeypatch, app_main) -> None:
    monkeypatch.delenv("OPENAI_RENAME_MODE", raising=False)
    monkeypatch.delenv("OPENAI_REMAP_MODE", raising=False)
    monkeypatch.delenv("OPENAI_RENAME_TASKS_QUEUE", raising=False)
    monkeypatch.delenv("OPENAI_REMAP_TASKS_QUEUE", raising=False)
    monkeypatch.delenv("OPENAI_RENAME_TASKS_QUEUE_LIGHT", raising=False)
    monkeypatch.delenv("OPENAI_REMAP_TASKS_QUEUE_LIGHT", raising=False)

    assert app_main.resolve_openai_rename_mode() == "local"
    assert app_main.resolve_openai_remap_mode() == "local"

    monkeypatch.setenv("OPENAI_RENAME_TASKS_QUEUE_LIGHT", "rename-light")
    monkeypatch.setenv("OPENAI_REMAP_TASKS_QUEUE_LIGHT", "remap-light")
    assert app_main.resolve_openai_rename_mode() == "tasks"
    assert app_main.resolve_openai_remap_mode() == "tasks"

    monkeypatch.setenv("OPENAI_RENAME_MODE", "local")
    monkeypatch.setenv("OPENAI_REMAP_MODE", "tasks")
    assert app_main.resolve_openai_rename_mode() == "local"
    assert app_main.resolve_openai_remap_mode() == "tasks"
