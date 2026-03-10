import base64
import math

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from starlette.requests import Request


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None, text: str = "") -> None:
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self) -> dict:
        return self._payload


class _FakeAsyncClient:
    def __init__(self, response: _FakeResponse) -> None:
        self._response = response
        self.calls: list[dict] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def post(self, url: str, headers=None, json=None, data=None):
        self.calls.append({"url": url, "headers": headers, "json": json, "data": data})
        return self._response


def _build_contact_payload(**overrides):
    payload = {
        "issueType": "question",
        "summary": "  Need help  ",
        "message": "  Hello world  ",
        "contactEmail": "user@example.com",
        "contactPhone": None,
    }
    payload.update(overrides)
    return payload


def test_contact_request_and_recaptcha_request_validators(app_main) -> None:
    contact = app_main.ContactRequest(**_build_contact_payload())
    assert contact.summary == "Need help"
    assert contact.message == "Hello world"
    assert contact.issueType == "question"

    with pytest.raises(ValidationError):
        app_main.ContactRequest(**_build_contact_payload(issueType="not-supported"))
    with pytest.raises(ValidationError):
        app_main.ContactRequest(**_build_contact_payload(contactEmail=None, contactPhone=None))

    recaptcha = app_main.RecaptchaAssessmentRequest(token=" token ", action=" signup ")
    assert recaptcha.token == "token"
    assert recaptcha.action == "signup"
    with pytest.raises(ValidationError):
        app_main.RecaptchaAssessmentRequest(token="   ")


def test_resolve_client_ip_and_is_public_ip(app_main, mocker, scope_builder) -> None:
    mocker.patch.object(app_main, "_trust_proxy_headers", return_value=True)
    request = Request(scope_builder(headers={"x-forwarded-for": "198.51.100.9, 10.0.0.1"}, client_ip="10.0.0.9"))
    assert app_main._resolve_client_ip(request) == "198.51.100.9"

    mocker.patch.object(app_main, "_trust_proxy_headers", return_value=False)
    assert app_main._resolve_client_ip(request) == "10.0.0.9"

    request_no_client = Request(scope_builder(client_ip=None))
    assert app_main._resolve_client_ip(request_no_client) == "unknown"

    assert app_main._is_public_ip("198.51.100.12") is False  # TEST-NET is reserved
    assert app_main._is_public_ip("8.8.8.8") is True
    assert app_main._is_public_ip("10.0.0.2") is False
    assert app_main._is_public_ip("bad-ip") is False


def test_recaptcha_hostname_allowed(app_main) -> None:
    allowed = ["example.com", "*.trusted.com"]
    assert app_main._recaptcha_hostname_allowed("example.com", allowed) is True
    assert app_main._recaptcha_hostname_allowed("api.trusted.com", allowed) is True
    assert app_main._recaptcha_hostname_allowed("trusted.com", allowed) is False
    assert app_main._recaptcha_hostname_allowed("", allowed) is False


def test_rate_limit_resolvers_reject_negative_env_values(app_main, monkeypatch) -> None:
    monkeypatch.setenv("CONTACT_RATE_LIMIT_WINDOW_SECONDS", "-1")
    monkeypatch.setenv("CONTACT_RATE_LIMIT_PER_IP", "-5")
    monkeypatch.setenv("CONTACT_RATE_LIMIT_GLOBAL", "-9")
    monkeypatch.setenv("SIGNUP_RATE_LIMIT_WINDOW_SECONDS", "-2")
    monkeypatch.setenv("SIGNUP_RATE_LIMIT_PER_IP", "-6")
    monkeypatch.setenv("SIGNUP_RATE_LIMIT_GLOBAL", "-10")

    assert app_main._resolve_contact_rate_limits() == (600, 6, 0)
    assert app_main._resolve_signup_rate_limits() == (600, 8, 0)


@pytest.mark.anyio
async def test_verify_recaptcha_token_missing_token_handling(app_main, scope_builder) -> None:
    request = Request(scope_builder())
    with pytest.raises(HTTPException) as ctx:
        await app_main._verify_recaptcha_token(None, "signup", request, required=True)
    assert ctx.value.status_code == 400

    await app_main._verify_recaptcha_token(None, "signup", request, required=False)


@pytest.mark.anyio
async def test_verify_recaptcha_token_missing_config_required_vs_optional(app_main, mocker, scope_builder) -> None:
    request = Request(scope_builder())
    mocker.patch.object(app_main, "_env_value", return_value="")
    mocker.patch.object(app_main, "_resolve_recaptcha_project_id", return_value="")

    with pytest.raises(HTTPException) as ctx:
        await app_main._verify_recaptcha_token("tok", "signup", request, required=True)
    assert ctx.value.status_code == 500

    await app_main._verify_recaptcha_token("tok", "signup", request, required=False)


@pytest.mark.anyio
async def test_verify_recaptcha_token_requires_hostname_allowlist_for_prod_required_checks(
    app_main,
    mocker,
    scope_builder,
) -> None:
    request = Request(scope_builder())
    mocker.patch.object(app_main, "_env_value", side_effect=lambda key: "site" if key == "RECAPTCHA_SITE_KEY" else "")
    mocker.patch.object(app_main, "_resolve_recaptcha_project_id", return_value="proj")
    mocker.patch.object(app_main, "_is_prod", return_value=True)
    mocker.patch.object(app_main, "_resolve_recaptcha_allowed_hostnames", return_value=[])

    with pytest.raises(HTTPException) as ctx:
        await app_main._verify_recaptcha_token("tok", "signup", request, required=True)
    assert ctx.value.status_code == 500
    assert "allowed hostnames" in str(ctx.value.detail).lower()


@pytest.mark.anyio
async def test_verify_recaptcha_token_requires_hostname_allowlist_for_prod_optional_checks_when_token_present(
    app_main,
    mocker,
    scope_builder,
) -> None:
    request = Request(scope_builder())
    mocker.patch.object(app_main, "_env_value", side_effect=lambda key: "site" if key == "RECAPTCHA_SITE_KEY" else "")
    mocker.patch.object(app_main, "_resolve_recaptcha_project_id", return_value="proj")
    mocker.patch.object(app_main, "_is_prod", return_value=True)
    mocker.patch.object(app_main, "_resolve_recaptcha_allowed_hostnames", return_value=[])

    with pytest.raises(HTTPException) as ctx:
        await app_main._verify_recaptcha_token("tok", "signup", request, required=False)
    assert ctx.value.status_code == 500
    assert "allowed hostnames" in str(ctx.value.detail).lower()


@pytest.mark.anyio
async def test_verify_recaptcha_token_error_paths(app_main, mocker, scope_builder) -> None:
    request = Request(scope_builder())
    mocker.patch.object(app_main, "_env_value", side_effect=lambda key: "site" if key == "RECAPTCHA_SITE_KEY" else "")
    mocker.patch.object(app_main, "_resolve_recaptcha_project_id", return_value="proj")
    mocker.patch.object(app_main, "_is_prod", return_value=False)
    mocker.patch.object(app_main, "_resolve_recaptcha_allowed_hostnames", return_value=[])
    mocker.patch.object(app_main, "_resolve_recaptcha_min_score", return_value=0.5)
    mocker.patch.object(app_main, "_get_google_access_token", return_value="access-token")
    mocker.patch.object(app_main, "_resolve_client_ip", return_value="8.8.8.8")
    mocker.patch.object(app_main, "_is_public_ip", return_value=True)

    # Upstream failure -> 502
    client_1 = _FakeAsyncClient(_FakeResponse(500, text="upstream fail"))
    mocker.patch.object(app_main.httpx, "AsyncClient", return_value=client_1)
    with pytest.raises(HTTPException) as ctx:
        await app_main._verify_recaptcha_token("tok", "signup", request, required=True)
    assert ctx.value.status_code == 502

    # Invalid token
    client_2 = _FakeAsyncClient(
        _FakeResponse(
            200,
            payload={"tokenProperties": {"valid": False, "invalidReason": "MALFORMED"}},
        )
    )
    mocker.patch.object(app_main.httpx, "AsyncClient", return_value=client_2)
    with pytest.raises(HTTPException) as ctx:
        await app_main._verify_recaptcha_token("tok", "signup", request, required=True)
    assert ctx.value.status_code == 400
    assert "MALFORMED" in str(ctx.value.detail)

    # Action mismatch
    client_3 = _FakeAsyncClient(
        _FakeResponse(
            200,
            payload={"tokenProperties": {"valid": True, "action": "other"}, "riskAnalysis": {"score": 0.9}},
        )
    )
    mocker.patch.object(app_main.httpx, "AsyncClient", return_value=client_3)
    with pytest.raises(HTTPException) as ctx:
        await app_main._verify_recaptcha_token("tok", "signup", request, required=True)
    assert ctx.value.status_code == 400
    assert "action mismatch" in str(ctx.value.detail).lower()

    # Score too low
    client_4 = _FakeAsyncClient(
        _FakeResponse(
            200,
            payload={"tokenProperties": {"valid": True, "action": "signup"}, "riskAnalysis": {"score": 0.2}},
        )
    )
    mocker.patch.object(app_main.httpx, "AsyncClient", return_value=client_4)
    with pytest.raises(HTTPException) as ctx:
        await app_main._verify_recaptcha_token("tok", "signup", request, required=True)
    assert ctx.value.status_code == 400
    assert "score too low" in str(ctx.value.detail).lower()


@pytest.mark.anyio
async def test_verify_recaptcha_token_success_includes_public_ip(app_main, mocker, scope_builder) -> None:
    request = Request(scope_builder(headers={"user-agent": "pytest-agent"}))
    mocker.patch.object(app_main, "_env_value", side_effect=lambda key: "site" if key == "RECAPTCHA_SITE_KEY" else "")
    mocker.patch.object(app_main, "_resolve_recaptcha_project_id", return_value="proj")
    mocker.patch.object(app_main, "_is_prod", return_value=True)
    mocker.patch.object(app_main, "_resolve_recaptcha_allowed_hostnames", return_value=["example.com"])
    mocker.patch.object(app_main, "_resolve_recaptcha_min_score", return_value=0.5)
    mocker.patch.object(app_main, "_get_google_access_token", return_value="access-token")
    mocker.patch.object(app_main, "_resolve_client_ip", return_value="8.8.8.8")
    mocker.patch.object(app_main, "_is_public_ip", return_value=True)

    response = _FakeResponse(
        200,
        payload={
            "tokenProperties": {"valid": True, "action": "signup", "hostname": "example.com"},
            "riskAnalysis": {"score": 0.9},
        },
    )
    client = _FakeAsyncClient(response)
    mocker.patch.object(app_main.httpx, "AsyncClient", return_value=client)
    await app_main._verify_recaptcha_token("tok", "signup", request, required=True)
    event_payload = client.calls[0]["json"]["event"]
    assert event_payload["userIpAddress"] == "8.8.8.8"
    assert event_payload["userAgent"] == "pytest-agent"


def test_contact_subject_body_and_header_sanitization(app_main, scope_builder) -> None:
    payload = app_main.ContactRequest(
        **_build_contact_payload(
            includeContactInSubject=True,
            contactName="Name\r\nInjected",
            contactPhone="(555) 222-3333",
            pageUrl="https://example.com/form",
        )
    )
    request = Request(scope_builder(headers={"user-agent": "pytest-agent"}))
    subject = app_main._resolve_contact_subject(payload)
    body = app_main._resolve_contact_body(payload, request)
    assert "\n" not in subject
    assert subject.startswith("[DullyPDF][Question]")
    assert "Contact:" in subject
    assert "Issue type: Question" in body
    assert "User-Agent: pytest-agent" in body

    assert app_main._sanitize_email_header_value("A\r\nB") == "A B"
    assert app_main._sanitize_email_header_value("   ") is None
    assert app_main._format_reply_to_header({"email": "User <u@example.com>", "name": "Test\r\nName"}) == "Test Name <u@example.com>"
    assert app_main._format_reply_to_header({"email": "", "name": "Nope"}) is None


@pytest.mark.anyio
async def test_send_contact_email_paths(app_main, mocker) -> None:
    # Missing routing config
    mocker.patch.object(app_main, "_env_value", return_value="")
    with pytest.raises(HTTPException) as ctx:
        await app_main._send_contact_email("subject", "body", None)
    assert ctx.value.status_code == 500

    # Dev fallback when Gmail token is unavailable
    env_values = {"CONTACT_TO_EMAIL": "to@example.com", "CONTACT_FROM_EMAIL": "from@example.com"}
    mocker.patch.object(app_main, "_env_value", side_effect=lambda key: env_values.get(key, ""))
    mocker.patch.object(app_main, "_get_gmail_access_token", side_effect=RuntimeError("missing creds"))
    mocker.patch.object(app_main, "_is_prod", return_value=False)
    await app_main._send_contact_email("subject", "body", None)

    # Prod should fail when Gmail token missing
    mocker.patch.object(app_main, "_is_prod", return_value=True)
    with pytest.raises(HTTPException) as ctx:
        await app_main._send_contact_email("subject", "body", None)
    assert ctx.value.status_code == 500

    # Upstream send failure -> 502
    mocker.patch.object(app_main, "_is_prod", return_value=False)
    mocker.patch.object(app_main, "_get_gmail_access_token", return_value="token")
    mocker.patch.object(app_main, "_resolve_gmail_user_id", return_value="me")
    fail_client = _FakeAsyncClient(_FakeResponse(500, text="gmail fail"))
    mocker.patch.object(app_main.httpx, "AsyncClient", return_value=fail_client)
    with pytest.raises(HTTPException) as ctx:
        await app_main._send_contact_email("subject", "body", {"email": "reply@example.com", "name": "Reply"})
    assert ctx.value.status_code == 502

    # Success path
    ok_client = _FakeAsyncClient(_FakeResponse(200, payload={"id": "ok"}))
    mocker.patch.object(app_main.httpx, "AsyncClient", return_value=ok_client)
    await app_main._send_contact_email("subject", "body", {"email": "reply@example.com", "name": "Reply"})
    payload = ok_client.calls[0]["json"]
    raw = base64.urlsafe_b64decode(payload["raw"]).decode("utf-8")
    assert "Subject: subject" in raw
    assert "Reply-To: Reply <reply@example.com>" in raw


# ---------------------------------------------------------------------------
# Edge-case: is_public_ip with IPv6 addresses
# ---------------------------------------------------------------------------
# The helper uses ipaddress.ip_address which handles both IPv4 and IPv6.
# Verify that public IPv6 addresses are correctly identified, while loopback
# and link-local IPv6 addresses are rejected.
def test_is_public_ip_with_ipv6_addresses(app_main) -> None:
    # Google public DNS IPv6 address is public.
    assert app_main._is_public_ip("2001:4860:4860::8888") is True

    # IPv6 loopback (::1) is not public.
    assert app_main._is_public_ip("::1") is False

    # IPv6 link-local (fe80::) is not public.
    assert app_main._is_public_ip("fe80::1") is False

    # IPv6 unique-local (fc00::/7) is private.
    assert app_main._is_public_ip("fd00::1") is False

    # IPv6 multicast (ff00::/8) is not public.
    assert app_main._is_public_ip("ff02::1") is False

    # IPv6 unspecified (::) is not public.
    assert app_main._is_public_ip("::") is False


# ---------------------------------------------------------------------------
# Edge-case: non-finite RECAPTCHA_MIN_SCORE should not disable score checks
# ---------------------------------------------------------------------------
# float("nan") and float("inf") parse successfully, but they do not represent
# usable score thresholds. The resolver should clamp/fallback to the default
# score instead of returning non-finite values.
@pytest.mark.parametrize("raw_value", ["nan", "NaN", "inf", "-inf"])
def test_resolve_recaptcha_min_score_rejects_non_finite_env_values(
    app_main,
    monkeypatch,
    raw_value: str,
) -> None:
    monkeypatch.setenv("RECAPTCHA_MIN_SCORE", raw_value)

    value = app_main._resolve_recaptcha_min_score()

    assert math.isfinite(value)
    assert value == 0.5


# ---------------------------------------------------------------------------
# Edge-case: out-of-range RECAPTCHA_MIN_SCORE should not weaken validation
# ---------------------------------------------------------------------------
# reCAPTCHA risk scores are defined in the [0, 1] range. Out-of-range values
# indicate misconfiguration and should fall back to the secure default.
@pytest.mark.parametrize("raw_value", ["-0.1", "1.5"])
def test_resolve_recaptcha_min_score_rejects_out_of_range_values(
    app_main,
    monkeypatch,
    raw_value: str,
) -> None:
    monkeypatch.setenv("RECAPTCHA_MIN_SCORE", raw_value)

    value = app_main._resolve_recaptcha_min_score()

    assert value == 0.5
