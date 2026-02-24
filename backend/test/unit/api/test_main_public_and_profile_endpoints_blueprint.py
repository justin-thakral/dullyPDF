from fastapi import HTTPException
from starlette import status

from backend.firebaseDB.user_database import UserBillingRecord, UserProfileRecord


def _contact_payload(**overrides) -> dict:
    payload = {
        "issueType": "question",
        "summary": "Need help",
        "message": "Hello",
        "contactEmail": "user@example.com",
    }
    payload.update(overrides)
    return payload


def _patch_auth(mocker, app_main, user) -> None:
    mocker.patch.object(app_main, "_verify_token", return_value={"uid": user.app_user_id})
    mocker.patch.object(app_main, "ensure_user", return_value=user)


def test_health_endpoints(client) -> None:
    assert client.get("/health").status_code == 200
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/health").json() == {"status": "ok"}


def test_profile_response_shape_for_base_and_god(
    client,
    app_main,
    base_user,
    god_user,
    mocker,
    auth_headers,
) -> None:
    _patch_auth(mocker, app_main, base_user)
    mocker.patch.object(app_main, "billing_enabled", return_value=False)
    mocker.patch.object(
        app_main,
        "get_user_profile",
        return_value=UserProfileRecord(
            uid=base_user.app_user_id,
            email=base_user.email,
            display_name=base_user.display_name,
            role="base",
            openai_credits_remaining=7,
            openai_credits_monthly_remaining=None,
            openai_credits_refill_remaining=3,
            openai_credits_available=7,
            refill_credits_locked=True,
        ),
    )
    mocker.patch.object(app_main, "_resolve_role_limits", return_value={"detectMaxPages": 5, "fillableMaxPages": 50, "savedFormsMax": 3})
    response = client.get("/api/profile", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["creditsRemaining"] == 7
    assert response.json()["availableCredits"] == 7
    assert response.json()["monthlyCreditsRemaining"] is None
    assert response.json()["refillCreditsRemaining"] == 3
    assert response.json()["refillCreditsLocked"] is True
    assert response.json()["role"] == "base"
    assert response.json()["billing"] == {
        "enabled": False,
        "plans": {},
        "hasSubscription": False,
        "subscriptionStatus": None,
        "cancelAtPeriodEnd": None,
        "cancelAt": None,
        "currentPeriodEnd": None,
    }
    assert response.json()["creditPricing"]["pageBucketSize"] >= 1

    _patch_auth(mocker, app_main, god_user)
    mocker.patch.object(
        app_main,
        "get_user_profile",
        return_value=UserProfileRecord(
            uid=god_user.app_user_id,
            email=god_user.email,
            display_name=god_user.display_name,
            role="god",
            openai_credits_remaining=100,
        ),
    )
    response = client.get("/api/profile", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["creditsRemaining"] is None
    assert response.json()["availableCredits"] is None
    assert response.json()["monthlyCreditsRemaining"] is None
    assert response.json()["refillCreditsRemaining"] is None
    assert response.json()["refillCreditsLocked"] is False
    assert response.json()["role"] == "god"


def test_profile_includes_billing_catalog_when_enabled(
    client,
    app_main,
    base_user,
    mocker,
    auth_headers,
) -> None:
    _patch_auth(mocker, app_main, base_user)
    mocker.patch.object(app_main, "billing_enabled", return_value=True)
    mocker.patch.object(
        app_main,
        "resolve_checkout_catalog",
        return_value={
            "pro_monthly": {
                "kind": "pro_monthly",
                "mode": "subscription",
                "priceId": "price_monthly",
                "label": "Pro Monthly",
                "currency": "usd",
                "unitAmount": 1000,
                "interval": "month",
                "refillCredits": None,
            }
        },
    )
    mocker.patch.object(
        app_main,
        "get_user_profile",
        return_value=UserProfileRecord(
            uid=base_user.app_user_id,
            email=base_user.email,
            display_name=base_user.display_name,
            role="base",
            openai_credits_remaining=7,
            openai_credits_monthly_remaining=None,
            openai_credits_refill_remaining=3,
            openai_credits_available=7,
            refill_credits_locked=True,
        ),
    )
    mocker.patch.object(
        app_main,
        "get_user_billing_record",
        return_value=UserBillingRecord(
            uid=base_user.app_user_id,
            customer_id="cus_123",
            subscription_id="sub_123",
            subscription_status="active",
            subscription_price_id="price_monthly",
        ),
    )

    response = client.get("/api/profile", headers=auth_headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["billing"]["enabled"] is True
    assert payload["billing"]["hasSubscription"] is True
    assert payload["billing"]["subscriptionStatus"] == "active"
    assert payload["billing"]["cancelAtPeriodEnd"] is None
    assert payload["billing"]["cancelAt"] is None
    assert payload["billing"]["currentPeriodEnd"] is None
    assert payload["billing"]["plans"]["pro_monthly"]["unitAmount"] == 1000
    assert payload["creditPricing"]["renameBaseCost"] >= 1


def test_contact_endpoint_rate_limit_global_and_per_ip(client, app_main, mocker) -> None:
    check_rate_limit = mocker.patch.object(app_main, "check_rate_limit", return_value=False)
    mocker.patch.object(app_main, "_resolve_contact_rate_limits", return_value=(60, 5, 1))
    response = client.post("/api/contact", json=_contact_payload())
    assert response.status_code == 429
    assert check_rate_limit.call_args.args[0] == "contact:global"
    assert check_rate_limit.call_args.kwargs["fail_closed"] is True

    check_rate_limit.reset_mock(return_value=True)
    check_rate_limit.return_value = True
    mocker.patch.object(app_main, "_resolve_contact_rate_limits", return_value=(60, 5, 0))
    mocker.patch.object(app_main, "_resolve_client_ip", return_value="unknown")
    mocker.patch.object(app_main, "_verify_contact_recaptcha", return_value=None)
    mocker.patch.object(app_main, "_send_contact_email", return_value=None)
    response = client.post("/api/contact", json=_contact_payload())
    assert response.status_code == 200
    assert check_rate_limit.call_args.args[0] == "contact:unknown"
    assert check_rate_limit.call_args.kwargs["fail_closed"] is True


def test_contact_endpoint_recaptcha_required_optional_and_email_failure(client, app_main, mocker) -> None:
    mocker.patch.object(app_main, "_resolve_contact_rate_limits", return_value=(60, 5, 0))
    mocker.patch.object(app_main, "check_rate_limit", return_value=True)

    # Required mode with missing token -> 400
    mocker.patch.object(app_main, "_verify_contact_recaptcha", side_effect=HTTPException(status_code=400, detail="Recaptcha token missing"))
    response = client.post("/api/contact", json=_contact_payload(recaptchaToken=None))
    assert response.status_code == 400

    # Optional mode -> success
    mocker.patch.object(app_main, "_verify_contact_recaptcha", return_value=None)
    mocker.patch.object(app_main, "_send_contact_email", return_value=None)
    response = client.post("/api/contact", json=_contact_payload(recaptchaToken=None))
    assert response.status_code == 200
    assert response.json() == {"success": True}

    # Missing recaptcha config in required mode
    mocker.patch.object(app_main, "_verify_contact_recaptcha", side_effect=HTTPException(status_code=500, detail="Recaptcha is not configured"))
    response = client.post("/api/contact", json=_contact_payload(recaptchaToken="abc"))
    assert response.status_code == 500

    # Email send failure bubbles up
    mocker.patch.object(app_main, "_verify_contact_recaptcha", return_value=None)
    mocker.patch.object(app_main, "_send_contact_email", side_effect=HTTPException(status_code=502, detail="Failed to send contact email"))
    response = client.post("/api/contact", json=_contact_payload())
    assert response.status_code == 502


def test_contact_endpoint_rejects_invalid_contact_channels(client) -> None:
    response = client.post(
        "/api/contact",
        json={
            "issueType": "question",
            "summary": "Need help",
            "message": "Hello",
            "contactEmail": None,
            "contactPhone": None,
        },
    )
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


def test_recaptcha_assess_endpoint_rate_limit_and_required_flag(client, app_main, mocker) -> None:
    check_rate_limit = mocker.patch.object(app_main, "check_rate_limit", return_value=False)
    mocker.patch.object(app_main, "_resolve_signup_rate_limits", return_value=(60, 5, 3))
    mocker.patch.object(app_main, "_resolve_signup_recaptcha_action", return_value="signup")
    response = client.post("/api/recaptcha/assess", json={"token": "tok", "action": "signup"})
    assert response.status_code == 429
    assert check_rate_limit.call_args.args[0] == "recaptcha:signup:global"
    assert check_rate_limit.call_args.kwargs["fail_closed"] is True

    check_rate_limit.return_value = True
    mocker.patch.object(app_main, "_resolve_signup_rate_limits", return_value=(60, 5, 0))
    mocker.patch.object(app_main, "_resolve_client_ip", return_value="198.51.100.1")
    verify_mock = mocker.patch.object(app_main, "_verify_recaptcha_token", return_value=None)
    mocker.patch.object(app_main, "_recaptcha_required_for_signup", return_value=False)
    response = client.post("/api/recaptcha/assess", json={"token": "tok", "action": "signup"})
    assert response.status_code == 200
    assert response.json() == {"success": True}
    assert verify_mock.call_args.kwargs["required"] is False
    assert check_rate_limit.call_args.kwargs["fail_closed"] is True


def test_touch_session_endpoint_ownership_and_refresh(
    client,
    app_main,
    base_user,
    mocker,
    auth_headers,
) -> None:
    _patch_auth(mocker, app_main, base_user)
    mocker.patch.object(app_main, "_touch_session_entry", return_value=None)
    response = client.post("/api/sessions/sess-1/touch", headers=auth_headers)
    assert response.status_code == 200
    assert response.json() == {"success": True, "sessionId": "sess-1"}

    mocker.patch.object(
        app_main,
        "_touch_session_entry",
        side_effect=HTTPException(status_code=403, detail="Session access denied"),
    )
    response = client.post("/api/sessions/sess-1/touch", headers=auth_headers)
    assert response.status_code == 403
