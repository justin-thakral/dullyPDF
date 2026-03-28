from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from backend.firebaseDB.user_database import UserBillingRecord, UserProfileRecord
from backend.services.billing_service import BillingCheckoutSessionNotFoundError


STRIPE_TEST_CARD_SUCCESS = "4242 4242 4242 4242"
STRIPE_TEST_CARD_3DS_REQUIRED = "4000 0025 0000 3155"
STRIPE_TEST_CARD_DECLINED = "4000 0000 0000 0002"
STRIPE_TEST_CARD_INSUFFICIENT_FUNDS = "4000 0000 0000 9995"


@pytest.fixture(autouse=True)
def _allow_billing_rate_limit(mocker, app_main):
    return mocker.patch.object(app_main, "check_rate_limit", return_value=True)


def _patch_auth(mocker, app_main, user) -> None:
    mocker.patch.object(app_main, "_verify_token", return_value={"uid": user.app_user_id})
    mocker.patch.object(app_main, "ensure_user", return_value=user)


def _build_checkout_session_completed_event(
    *,
    event_id: str,
    checkout_kind: str,
    payment_status: str,
    card_number: str,
    user_id: str = "user-1",
    checkout_session_id: str = "cs_test_123",
    checkout_attempt_id: str | None = None,
) -> dict:
    metadata = {
        "userId": user_id,
        "checkoutKind": checkout_kind,
        # Stored for test traceability only.
        "stripeTestCardNumber": card_number,
    }
    if checkout_kind == "refill_500":
        metadata["checkoutPriceId"] = "price_refill_500"
        metadata["refillCredits"] = "500"
    elif checkout_kind == "pro_monthly":
        metadata["checkoutPriceId"] = "price_pro_monthly"
    elif checkout_kind == "pro_yearly":
        metadata["checkoutPriceId"] = "price_pro_yearly"
    if checkout_attempt_id:
        metadata["checkoutAttemptId"] = checkout_attempt_id

    return {
        "id": event_id,
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": checkout_session_id,
                "client_reference_id": user_id,
                "metadata": metadata,
                "subscription": "sub_123",
                "customer": "cus_123",
                "payment_status": payment_status,
            }
        },
    }


def _build_checkout_session_object(**kwargs) -> dict:
    return _build_checkout_session_completed_event(
        event_id="evt_checkout_session_object",
        **kwargs,
    )["data"]["object"]


def test_checkout_session_rejects_refill_for_non_pro_users(
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
        "get_user_profile",
        return_value=UserProfileRecord(
            uid=base_user.app_user_id,
            email=base_user.email,
            display_name=base_user.display_name,
            role="base",
            openai_credits_remaining=2,
        ),
    )
    checkout_mock = mocker.patch.object(app_main, "create_checkout_session")

    response = client.post(
        "/api/billing/checkout-session",
        json={"kind": "refill_500"},
        headers=auth_headers,
    )

    assert response.status_code == 403
    assert "Pro users only" in response.text
    checkout_mock.assert_not_called()


def test_checkout_session_creates_monthly_and_yearly_pro_sessions(
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
        "get_user_profile",
        return_value=UserProfileRecord(
            uid=base_user.app_user_id,
            email=base_user.email,
            display_name=base_user.display_name,
            role="base",
            openai_credits_remaining=2,
        ),
    )
    mocker.patch.object(app_main, "get_user_billing_record", return_value=None)
    checkout_mock = mocker.patch.object(
        app_main,
        "create_checkout_session",
        side_effect=[
            {"sessionId": "cs_monthly", "url": "https://checkout/monthly"},
            {"sessionId": "cs_yearly", "url": "https://checkout/yearly"},
        ],
    )

    monthly = client.post(
        "/api/billing/checkout-session",
        json={"kind": "pro_monthly"},
        headers=auth_headers,
    )
    yearly = client.post(
        "/api/billing/checkout-session",
        json={"kind": "pro_yearly"},
        headers=auth_headers,
    )

    assert monthly.status_code == 200
    assert monthly.json()["checkoutUrl"] == "https://checkout/monthly"
    assert yearly.status_code == 200
    assert yearly.json()["checkoutUrl"] == "https://checkout/yearly"
    assert checkout_mock.call_args_list[0].kwargs["checkout_kind"] == "pro_monthly"
    assert checkout_mock.call_args_list[1].kwargs["checkout_kind"] == "pro_yearly"


def test_checkout_session_persists_resolved_customer_id_for_pro_checkout(
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
        "get_user_profile",
        return_value=UserProfileRecord(
            uid=base_user.app_user_id,
            email=base_user.email,
            display_name=base_user.display_name,
            role="base",
            openai_credits_remaining=2,
        ),
    )
    mocker.patch.object(app_main, "get_user_billing_record", return_value=None)
    mocker.patch.object(
        app_main,
        "create_checkout_session",
        return_value={
            "sessionId": "cs_monthly",
            "url": "https://checkout/monthly",
            "customerId": "cus_new_123",
        },
    )
    persist_customer_mock = mocker.patch.object(app_main, "set_user_billing_subscription", return_value=None)

    response = client.post(
        "/api/billing/checkout-session",
        json={"kind": "pro_monthly"},
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.json()["checkoutUrl"] == "https://checkout/monthly"
    persist_customer_mock.assert_called_once_with(
        base_user.app_user_id,
        customer_id="cus_new_123",
    )


def test_checkout_session_rejects_refill_without_active_subscription_even_for_pro(
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
        "get_user_profile",
        return_value=UserProfileRecord(
            uid=base_user.app_user_id,
            email=base_user.email,
            display_name=base_user.display_name,
            role="pro",
            openai_credits_remaining=500,
        ),
    )
    mocker.patch.object(
        app_main,
        "get_user_billing_record",
        return_value=UserBillingRecord(
            uid=base_user.app_user_id,
            customer_id="cus_123",
            subscription_id="sub_inactive",
            subscription_status="canceled",
            subscription_price_id="price_pro_monthly",
        ),
    )
    mocker.patch.object(app_main, "is_subscription_active", return_value=False)
    checkout_mock = mocker.patch.object(app_main, "create_checkout_session")

    response = client.post(
        "/api/billing/checkout-session",
        json={"kind": "refill_500"},
        headers=auth_headers,
    )

    assert response.status_code == 409
    assert "requires an active Pro subscription" in response.text
    checkout_mock.assert_not_called()


def test_checkout_session_rejects_refill_when_pro_profile_has_no_billing_record(
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
        "get_user_profile",
        return_value=UserProfileRecord(
            uid=base_user.app_user_id,
            email=base_user.email,
            display_name=base_user.display_name,
            role="pro",
            openai_credits_remaining=500,
        ),
    )
    mocker.patch.object(app_main, "get_user_billing_record", return_value=None)
    checkout_mock = mocker.patch.object(app_main, "create_checkout_session")

    response = client.post(
        "/api/billing/checkout-session",
        json={"kind": "refill_500"},
        headers=auth_headers,
    )

    assert response.status_code == 409
    assert "requires an active Pro subscription" in response.text
    checkout_mock.assert_not_called()


def test_checkout_session_creates_refill_session_for_pro_with_active_subscription(
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
        "get_user_profile",
        return_value=UserProfileRecord(
            uid=base_user.app_user_id,
            email=base_user.email,
            display_name=base_user.display_name,
            role="pro",
            openai_credits_remaining=500,
        ),
    )
    mocker.patch.object(
        app_main,
        "get_user_billing_record",
        return_value=UserBillingRecord(
            uid=base_user.app_user_id,
            customer_id="cus_123",
            subscription_id="sub_active",
            subscription_status="active",
            subscription_price_id="price_pro_monthly",
        ),
    )
    mocker.patch.object(app_main, "is_subscription_active", return_value=True)
    checkout_mock = mocker.patch.object(
        app_main,
        "create_checkout_session",
        return_value={
            "sessionId": "cs_refill",
            "url": "https://checkout/refill",
            "checkoutAttemptId": "attempt_refill_123",
            "checkoutPriceId": "price_refill_500",
        },
    )
    persist_customer_mock = mocker.patch.object(app_main, "set_user_billing_subscription")

    response = client.post(
        "/api/billing/checkout-session",
        json={"kind": "refill_500"},
        headers=auth_headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["kind"] == "refill_500"
    assert payload["checkoutUrl"] == "https://checkout/refill"
    assert payload["attemptId"] == "attempt_refill_123"
    assert payload["checkoutPriceId"] == "price_refill_500"
    checkout_mock.assert_called_once_with(
        user_id=base_user.app_user_id,
        user_email=base_user.email,
        checkout_kind="refill_500",
        customer_id=None,
    )
    persist_customer_mock.assert_not_called()


def test_checkout_session_forwards_checkout_attempt_id_for_refill(
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
        "get_user_profile",
        return_value=UserProfileRecord(
            uid=base_user.app_user_id,
            email=base_user.email,
            display_name=base_user.display_name,
            role="pro",
            openai_credits_remaining=500,
        ),
    )
    mocker.patch.object(
        app_main,
        "get_user_billing_record",
        return_value=UserBillingRecord(
            uid=base_user.app_user_id,
            customer_id="cus_123",
            subscription_id="sub_active",
            subscription_status="active",
            subscription_price_id="price_pro_monthly",
        ),
    )
    mocker.patch.object(app_main, "is_subscription_active", return_value=True)
    checkout_mock = mocker.patch.object(
        app_main,
        "create_checkout_session",
        return_value={
            "sessionId": "cs_refill",
            "url": "https://checkout/refill",
            "checkoutAttemptId": "attempt_abc_123",
            "checkoutPriceId": "price_refill_500",
        },
    )

    response = client.post(
        "/api/billing/checkout-session",
        json={"kind": "refill_500", "attemptId": "attempt_abc_123"},
        headers=auth_headers,
    )

    assert response.status_code == 200
    checkout_mock.assert_called_once_with(
        user_id=base_user.app_user_id,
        user_email=base_user.email,
        checkout_kind="refill_500",
        customer_id=None,
        checkout_attempt_id="attempt_abc_123",
    )


def test_checkout_session_rejects_duplicate_active_pro_subscription(
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
        "get_user_profile",
        return_value=UserProfileRecord(
            uid=base_user.app_user_id,
            email=base_user.email,
            display_name=base_user.display_name,
            role="pro",
            openai_credits_remaining=450,
        ),
    )
    mocker.patch.object(
        app_main,
        "get_user_billing_record",
        return_value=UserBillingRecord(
            uid=base_user.app_user_id,
            customer_id="cus_123",
            subscription_id="sub_active",
            subscription_status="active",
            subscription_price_id="price_pro_monthly",
        ),
    )
    mocker.patch.object(app_main, "is_subscription_active", return_value=True)
    checkout_mock = mocker.patch.object(app_main, "create_checkout_session")

    response = client.post(
        "/api/billing/checkout-session",
        json={"kind": "pro_monthly"},
        headers=auth_headers,
    )

    assert response.status_code == 409
    assert "active Pro subscription already exists" in response.text
    checkout_mock.assert_not_called()


def test_checkout_session_surfaces_service_subscription_conflict_as_409(
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
        "get_user_profile",
        return_value=UserProfileRecord(
            uid=base_user.app_user_id,
            email=base_user.email,
            display_name=base_user.display_name,
            role="base",
            openai_credits_remaining=10,
        ),
    )
    mocker.patch.object(
        app_main,
        "get_user_billing_record",
        return_value=UserBillingRecord(
            uid="user-1",
            customer_id="cus_123",
            subscription_id="sub_123",
            subscription_status="active",
            subscription_price_id="price_pro_monthly",
        ),
    )
    mocker.patch.object(
        app_main,
        "create_checkout_session",
        side_effect=app_main.BillingCheckoutConflictError("An active Pro subscription already exists for this customer."),
    )

    response = client.post(
        "/api/billing/checkout-session",
        json={"kind": "pro_monthly"},
        headers=auth_headers,
    )

    assert response.status_code == 409
    assert "active Pro subscription already exists" in response.text


def test_checkout_session_returns_503_when_billing_not_configured(
    client,
    app_main,
    base_user,
    mocker,
    auth_headers,
) -> None:
    _patch_auth(mocker, app_main, base_user)
    mocker.patch.object(app_main, "billing_enabled", return_value=False)

    response = client.post(
        "/api/billing/checkout-session",
        json={"kind": "pro_monthly"},
        headers=auth_headers,
    )

    assert response.status_code == 503
    assert "Stripe billing is not configured" in response.text


def test_checkout_session_returns_503_when_webhook_health_check_fails(
    client,
    app_main,
    base_user,
    mocker,
    auth_headers,
) -> None:
    _patch_auth(mocker, app_main, base_user)
    mocker.patch.object(app_main, "billing_enabled", return_value=True)
    mocker.patch.object(app_main, "webhook_health_enforced_for_checkout", return_value=True)
    mocker.patch.object(
        app_main,
        "resolve_webhook_health",
        return_value={
            "healthy": False,
            "reason": "No enabled Stripe webhook endpoint is configured for this account.",
            "enforcedForCheckout": True,
        },
    )
    checkout_mock = mocker.patch.object(app_main, "create_checkout_session")

    response = client.post(
        "/api/billing/checkout-session",
        json={"kind": "pro_monthly"},
        headers=auth_headers,
    )

    assert response.status_code == 503
    assert "webhook health check failed" in response.text.lower()
    assert "No enabled Stripe webhook endpoint is configured" not in response.text
    checkout_mock.assert_not_called()


def test_checkout_session_rate_limits_authenticated_users(
    client,
    app_main,
    base_user,
    mocker,
    auth_headers,
    _allow_billing_rate_limit,
) -> None:
    _patch_auth(mocker, app_main, base_user)
    _allow_billing_rate_limit.return_value = False
    mocker.patch.object(app_main, "billing_enabled", return_value=True)
    mocker.patch.object(app_main, "webhook_health_enforced_for_checkout", return_value=False)
    mocker.patch.object(
        app_main,
        "get_user_profile",
        return_value=UserProfileRecord(
            uid=base_user.app_user_id,
            email=base_user.email,
            display_name=base_user.display_name,
            role="base",
            openai_credits_remaining=2,
        ),
    )
    checkout_mock = mocker.patch.object(app_main, "create_checkout_session")

    response = client.post(
        "/api/billing/checkout-session",
        json={"kind": "pro_monthly"},
        headers=auth_headers,
    )

    assert response.status_code == 429
    assert "Too many billing requests" in response.text
    checkout_mock.assert_not_called()


def test_checkout_session_rejects_unknown_checkout_kind(
    client,
    app_main,
    base_user,
    mocker,
    auth_headers,
) -> None:
    _patch_auth(mocker, app_main, base_user)
    mocker.patch.object(app_main, "billing_enabled", return_value=True)

    response = client.post(
        "/api/billing/checkout-session",
        json={"kind": "not_a_real_kind"},
        headers=auth_headers,
    )

    assert response.status_code == 422


def test_checkout_session_returns_401_when_auth_fails(client, app_main, mocker) -> None:
    mocker.patch.object(app_main, "_verify_token", side_effect=HTTPException(status_code=401, detail="Unauthorized"))

    response = client.post(
        "/api/billing/checkout-session",
        json={"kind": "pro_monthly"},
    )

    assert response.status_code == 401


def test_cancel_subscription_returns_401_when_auth_fails(client, app_main, mocker) -> None:
    mocker.patch.object(app_main, "_verify_token", side_effect=HTTPException(status_code=401, detail="Unauthorized"))

    response = client.post("/api/billing/subscription/cancel")

    assert response.status_code == 401


def test_cancel_subscription_rate_limits_authenticated_users(
    client,
    app_main,
    base_user,
    mocker,
    auth_headers,
    _allow_billing_rate_limit,
) -> None:
    _patch_auth(mocker, app_main, base_user)
    _allow_billing_rate_limit.return_value = False
    mocker.patch.object(app_main, "billing_enabled", return_value=True)
    mocker.patch.object(
        app_main,
        "get_user_profile",
        return_value=UserProfileRecord(
            uid=base_user.app_user_id,
            email=base_user.email,
            display_name=base_user.display_name,
            role="pro",
            openai_credits_remaining=500,
        ),
    )

    response = client.post("/api/billing/subscription/cancel", headers=auth_headers)

    assert response.status_code == 429
    assert "Too many billing requests" in response.text


def test_cancel_subscription_rejects_non_pro_users(
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
        "get_user_profile",
        return_value=UserProfileRecord(
            uid=base_user.app_user_id,
            email=base_user.email,
            display_name=base_user.display_name,
            role="base",
            openai_credits_remaining=2,
        ),
    )

    response = client.post("/api/billing/subscription/cancel", headers=auth_headers)

    assert response.status_code == 403
    assert "Only Pro users" in response.text


def test_cancel_subscription_allows_non_pro_user_when_subscription_record_exists(
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
        "get_user_profile",
        return_value=UserProfileRecord(
            uid=base_user.app_user_id,
            email=base_user.email,
            display_name=base_user.display_name,
            role="base",
            openai_credits_remaining=2,
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
            subscription_price_id="price_pro_monthly",
        ),
    )
    mocker.patch.object(
        app_main,
        "cancel_subscription_at_period_end",
        return_value=SimpleNamespace(
            status="active",
            cancel_at_period_end=True,
            cancel_at=1775000000,
            current_period_end=1775000000,
            customer_id="cus_123",
            price_id="price_pro_monthly",
        ),
    )
    set_subscription_mock = mocker.patch.object(app_main, "set_user_billing_subscription", return_value=None)
    downgrade_mock = mocker.patch.object(app_main, "downgrade_to_base_membership", return_value=None)

    response = client.post("/api/billing/subscription/cancel", headers=auth_headers)

    assert response.status_code == 200
    assert response.json()["cancelAtPeriodEnd"] is True
    set_subscription_mock.assert_called_once()
    assert set_subscription_mock.call_args.kwargs["cancel_at_period_end"] is True
    assert set_subscription_mock.call_args.kwargs["cancel_at"] == 1775000000
    assert set_subscription_mock.call_args.kwargs["current_period_end"] == 1775000000
    downgrade_mock.assert_not_called()


def test_cancel_subscription_returns_503_when_billing_not_configured(
    client,
    app_main,
    base_user,
    mocker,
    auth_headers,
) -> None:
    _patch_auth(mocker, app_main, base_user)
    mocker.patch.object(app_main, "billing_enabled", return_value=False)

    response = client.post("/api/billing/subscription/cancel", headers=auth_headers)

    assert response.status_code == 503
    assert "Stripe billing is not configured" in response.text


def test_cancel_subscription_returns_conflict_when_subscription_missing(
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
        "get_user_profile",
        return_value=UserProfileRecord(
            uid=base_user.app_user_id,
            email=base_user.email,
            display_name=base_user.display_name,
            role="pro",
            openai_credits_remaining=2,
        ),
    )
    mocker.patch.object(
        app_main,
        "get_user_billing_record",
        return_value=UserBillingRecord(
            uid=base_user.app_user_id,
            customer_id="cus_123",
            subscription_id=None,
            subscription_status="active",
            subscription_price_id="price_pro",
        ),
    )

    response = client.post("/api/billing/subscription/cancel", headers=auth_headers)

    assert response.status_code == 409
    assert "No active subscription" in response.text


def test_cancel_subscription_marks_period_end_and_keeps_pro_role(
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
        "get_user_profile",
        return_value=UserProfileRecord(
            uid=base_user.app_user_id,
            email=base_user.email,
            display_name=base_user.display_name,
            role="pro",
            openai_credits_remaining=2,
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
            subscription_price_id="price_pro_yearly",
        ),
    )
    mocker.patch.object(
        app_main,
        "cancel_subscription_at_period_end",
        return_value=SimpleNamespace(
            status="active",
            cancel_at_period_end=True,
            cancel_at=1775000000,
            current_period_end=1775000000,
            customer_id="cus_123",
            price_id="price_pro_yearly",
        ),
    )
    set_subscription_mock = mocker.patch.object(app_main, "set_user_billing_subscription", return_value=None)
    downgrade_mock = mocker.patch.object(app_main, "downgrade_to_base_membership", return_value=None)

    response = client.post("/api/billing/subscription/cancel", headers=auth_headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["cancelAtPeriodEnd"] is True
    set_subscription_mock.assert_called_once()
    downgrade_mock.assert_not_called()


def test_cancel_subscription_returns_already_canceled_when_period_end_is_already_scheduled(
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
        "get_user_profile",
        return_value=UserProfileRecord(
            uid=base_user.app_user_id,
            email=base_user.email,
            display_name=base_user.display_name,
            role="pro",
            openai_credits_remaining=2,
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
            subscription_price_id="price_pro_yearly",
            cancel_at_period_end=True,
            cancel_at=1775000000,
            current_period_end=1775000000,
        ),
    )
    cancel_mock = mocker.patch.object(app_main, "cancel_subscription_at_period_end")
    set_subscription_mock = mocker.patch.object(app_main, "set_user_billing_subscription")
    downgrade_mock = mocker.patch.object(app_main, "downgrade_to_base_membership")

    response = client.post("/api/billing/subscription/cancel", headers=auth_headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["alreadyCanceled"] is True
    assert payload["cancelAtPeriodEnd"] is True
    cancel_mock.assert_not_called()
    set_subscription_mock.assert_not_called()
    downgrade_mock.assert_not_called()


@pytest.mark.parametrize("subscription_status", ["canceled", "incomplete_expired", "unpaid"])
def test_cancel_subscription_rejects_terminal_subscription_statuses(
    client,
    app_main,
    base_user,
    mocker,
    auth_headers,
    subscription_status,
) -> None:
    _patch_auth(mocker, app_main, base_user)
    mocker.patch.object(app_main, "billing_enabled", return_value=True)
    mocker.patch.object(
        app_main,
        "get_user_profile",
        return_value=UserProfileRecord(
            uid=base_user.app_user_id,
            email=base_user.email,
            display_name=base_user.display_name,
            role="base",
            openai_credits_remaining=2,
        ),
    )
    mocker.patch.object(
        app_main,
        "get_user_billing_record",
        return_value=UserBillingRecord(
            uid=base_user.app_user_id,
            customer_id="cus_123",
            subscription_id="sub_dead",
            subscription_status=subscription_status,
            subscription_price_id="price_pro_monthly",
        ),
    )
    cancel_mock = mocker.patch.object(app_main, "cancel_subscription_at_period_end")

    response = client.post("/api/billing/subscription/cancel", headers=auth_headers)

    assert response.status_code == 409
    assert "already inactive" in response.text
    cancel_mock.assert_not_called()


def test_cancel_subscription_downgrades_immediately_when_status_inactive(
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
        "get_user_profile",
        return_value=UserProfileRecord(
            uid=base_user.app_user_id,
            email=base_user.email,
            display_name=base_user.display_name,
            role="pro",
            openai_credits_remaining=2,
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
            subscription_price_id="price_pro_monthly",
        ),
    )
    mocker.patch.object(
        app_main,
        "cancel_subscription_at_period_end",
        return_value=SimpleNamespace(
            status="canceled",
            cancel_at_period_end=True,
            cancel_at=1775000000,
            current_period_end=1775000000,
            customer_id="cus_123",
            price_id="price_pro_monthly",
        ),
    )
    mocker.patch.object(app_main, "set_user_billing_subscription", return_value=None)
    downgrade_mock = mocker.patch.object(app_main, "downgrade_to_base_membership", return_value=None)
    apply_retention_mock = mocker.patch.object(app_main, "apply_user_downgrade_retention", return_value={"status": "grace_period"})

    response = client.post("/api/billing/subscription/cancel", headers=auth_headers)

    assert response.status_code == 200
    downgrade_mock.assert_called_once_with(base_user.app_user_id)
    apply_retention_mock.assert_called_once_with(base_user.app_user_id)


def test_cancel_subscription_succeeds_when_subscription_state_persistence_fails(
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
        "get_user_profile",
        return_value=UserProfileRecord(
            uid=base_user.app_user_id,
            email=base_user.email,
            display_name=base_user.display_name,
            role="pro",
            openai_credits_remaining=2,
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
            subscription_price_id="price_pro_monthly",
        ),
    )
    mocker.patch.object(
        app_main,
        "cancel_subscription_at_period_end",
        return_value=SimpleNamespace(
            status="active",
            cancel_at_period_end=True,
            cancel_at=1775000000,
            current_period_end=1775000000,
            customer_id="cus_123",
            price_id="price_pro_monthly",
        ),
    )
    mocker.patch.object(
        app_main,
        "set_user_billing_subscription",
        side_effect=RuntimeError("firestore unavailable"),
    )
    downgrade_mock = mocker.patch.object(app_main, "downgrade_to_base_membership", return_value=None)

    response = client.post("/api/billing/subscription/cancel", headers=auth_headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["stateSyncDeferred"] is True
    downgrade_mock.assert_not_called()


def test_cancel_subscription_succeeds_when_role_downgrade_fails_after_stripe_cancel(
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
        "get_user_profile",
        return_value=UserProfileRecord(
            uid=base_user.app_user_id,
            email=base_user.email,
            display_name=base_user.display_name,
            role="pro",
            openai_credits_remaining=2,
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
            subscription_price_id="price_pro_monthly",
        ),
    )
    mocker.patch.object(
        app_main,
        "cancel_subscription_at_period_end",
        return_value=SimpleNamespace(
            status="canceled",
            cancel_at_period_end=True,
            cancel_at=1775000000,
            current_period_end=1775000000,
            customer_id="cus_123",
            price_id="price_pro_monthly",
        ),
    )
    mocker.patch.object(app_main, "set_user_billing_subscription", return_value=None)
    mocker.patch.object(
        app_main,
        "downgrade_to_base_membership",
        side_effect=RuntimeError("firestore unavailable"),
    )

    response = client.post("/api/billing/subscription/cancel", headers=auth_headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["stateSyncDeferred"] is True


def test_cancel_subscription_immediate_downgrade_uses_retention_override_when_billing_persistence_fails(
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
        "get_user_profile",
        return_value=UserProfileRecord(
            uid=base_user.app_user_id,
            email=base_user.email,
            display_name=base_user.display_name,
            role="pro",
            openai_credits_remaining=2,
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
            subscription_price_id="price_pro_monthly",
        ),
    )
    mocker.patch.object(
        app_main,
        "cancel_subscription_at_period_end",
        return_value=SimpleNamespace(
            status="canceled",
            cancel_at_period_end=True,
            cancel_at=1775000000,
            current_period_end=1775000000,
            customer_id="cus_123",
            price_id="price_pro_monthly",
        ),
    )
    mocker.patch.object(
        app_main,
        "set_user_billing_subscription",
        side_effect=RuntimeError("firestore unavailable"),
    )
    downgrade_mock = mocker.patch.object(app_main, "downgrade_to_base_membership", return_value=None)
    apply_retention_mock = mocker.patch.object(app_main, "apply_user_downgrade_retention", return_value={"status": "grace_period"})

    response = client.post("/api/billing/subscription/cancel", headers=auth_headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["stateSyncDeferred"] is True
    downgrade_mock.assert_called_once_with(base_user.app_user_id)
    apply_retention_mock.assert_called_once()
    eligibility_override = apply_retention_mock.call_args.kwargs["eligibility_override"]
    assert eligibility_override.should_apply is True
    assert eligibility_override.role == "base"
    assert eligibility_override.has_active_subscription is False
    assert apply_retention_mock.call_args.kwargs["billing_state_deferred"] is True


def test_cancel_subscription_returns_503_on_billing_config_error(
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
        "get_user_profile",
        return_value=UserProfileRecord(
            uid=base_user.app_user_id,
            email=base_user.email,
            display_name=base_user.display_name,
            role="pro",
            openai_credits_remaining=2,
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
            subscription_price_id="price_pro_monthly",
        ),
    )
    mocker.patch.object(
        app_main,
        "cancel_subscription_at_period_end",
        side_effect=app_main.BillingConfigError("Missing STRIPE_SECRET_KEY."),
    )

    response = client.post("/api/billing/subscription/cancel", headers=auth_headers)

    assert response.status_code == 503
    assert "Missing STRIPE_SECRET_KEY." in response.text


def test_cancel_subscription_returns_500_on_unexpected_error(
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
        "get_user_profile",
        return_value=UserProfileRecord(
            uid=base_user.app_user_id,
            email=base_user.email,
            display_name=base_user.display_name,
            role="pro",
            openai_credits_remaining=2,
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
            subscription_price_id="price_pro_monthly",
        ),
    )
    mocker.patch.object(
        app_main,
        "cancel_subscription_at_period_end",
        side_effect=ValueError("unexpected"),
    )

    response = client.post("/api/billing/subscription/cancel", headers=auth_headers)

    assert response.status_code == 500
    assert "Failed to cancel Stripe subscription." in response.text


def test_billing_webhook_health_endpoint_returns_health_payload(
    client,
    app_main,
    base_user,
    mocker,
    auth_headers,
) -> None:
    _patch_auth(mocker, app_main, base_user)
    mocker.patch.object(
        app_main,
        "get_user_profile",
        return_value=UserProfileRecord(
            uid=base_user.app_user_id,
            email=base_user.email,
            display_name=base_user.display_name,
            role="base",
            openai_credits_remaining=500,
        ),
    )
    mocker.patch.object(
        app_main,
        "resolve_webhook_health",
        return_value={
            "healthy": False,
            "reason": "No enabled Stripe webhook endpoint is configured for this account.",
            "checkedAt": 1771906544,
            "enforcedForCheckout": True,
            "endpointId": "we_123",
            "endpointUrl": "https://billing.example.com/api/billing/webhook",
            "expectedEndpointUrl": "https://billing.example.com/api/billing/webhook",
            "expectedEndpointUrls": ["https://billing.example.com/api/billing/webhook"],
        },
    )

    response = client.get("/api/billing/webhook-health", headers=auth_headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["healthy"] is False
    assert payload["reason"] == (
        "Stripe webhook health check is failing. "
        "Ask an administrator to review billing configuration."
    )
    assert payload["enforcedForCheckout"] is True
    assert "endpointId" not in payload
    assert "endpointUrl" not in payload
    assert "expectedEndpointUrl" not in payload
    assert "expectedEndpointUrls" not in payload
    app_main.resolve_webhook_health.assert_called_once_with(force_refresh=False)


def test_billing_webhook_health_endpoint_includes_endpoint_details_for_god_role(
    client,
    app_main,
    god_user,
    mocker,
    auth_headers,
) -> None:
    _patch_auth(mocker, app_main, god_user)
    mocker.patch.object(
        app_main,
        "get_user_profile",
        return_value=UserProfileRecord(
            uid=god_user.app_user_id,
            email=god_user.email,
            display_name=god_user.display_name,
            role="god",
            openai_credits_remaining=500,
        ),
    )
    mocker.patch.object(
        app_main,
        "resolve_webhook_health",
        return_value={
            "healthy": True,
            "reason": "Stripe webhook health check passed.",
            "checkedAt": 1771906544,
            "enforcedForCheckout": True,
            "endpointId": "we_123",
            "endpointUrl": "https://billing.example.com/api/billing/webhook",
            "expectedEndpointUrl": "https://billing.example.com/api/billing/webhook",
            "expectedEndpointUrls": ["https://billing.example.com/api/billing/webhook"],
        },
    )

    response = client.get("/api/billing/webhook-health", headers=auth_headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["healthy"] is True
    assert payload["endpointId"] == "we_123"
    assert payload["endpointUrl"] == "https://billing.example.com/api/billing/webhook"
    assert payload["expectedEndpointUrl"] == "https://billing.example.com/api/billing/webhook"
    assert payload["expectedEndpointUrls"] == ["https://billing.example.com/api/billing/webhook"]
    app_main.resolve_webhook_health.assert_called_once_with(force_refresh=True)


def test_billing_reconcile_dry_run_reports_missing_checkout_session_without_processing(
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
        "get_user_profile",
        return_value=UserProfileRecord(
            uid=base_user.app_user_id,
            email=base_user.email,
            display_name=base_user.display_name,
            role="pro",
            openai_credits_remaining=500,
        ),
    )
    mocker.patch.object(
        app_main,
        "retrieve_checkout_session",
        return_value=_build_checkout_session_object(
            checkout_kind="refill_500",
            payment_status="paid",
            card_number=STRIPE_TEST_CARD_SUCCESS,
            user_id=base_user.app_user_id,
            checkout_session_id="cs_refill_123",
            checkout_attempt_id="attempt_refill_123",
        ),
    )
    list_mock = mocker.patch.object(app_main, "list_recent_checkout_completion_events")
    mocker.patch.object(app_main, "get_billing_event", return_value=None)
    start_mock = mocker.patch.object(app_main, "start_billing_event")

    response = client.post(
        "/api/billing/reconcile",
        json={
            "dryRun": True,
            "lookbackHours": 24,
            "maxEvents": 20,
            "sessionId": "cs_refill_123",
            "attemptId": "attempt_refill_123",
        },
        headers=auth_headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["dryRun"] is True
    assert payload["candidateEventCount"] == 1
    assert payload["pendingReconciliationCount"] == 1
    assert payload["reconciledCount"] == 0
    assert payload["events"] == [
        {
            "eventId": "checkout_session:cs_refill_123",
            "eventType": "checkout.session.completed",
            "eventUserId": base_user.app_user_id,
            "created": None,
            "checkoutSessionId": "cs_refill_123",
            "checkoutAttemptId": "attempt_refill_123",
            "checkoutKind": "refill_500",
            "checkoutPriceId": "price_refill_500",
            "billingEventStatus": None,
        }
    ]
    start_mock.assert_not_called()
    list_mock.assert_not_called()


def test_billing_reconcile_rate_limits_self_scope_requests(
    client,
    app_main,
    base_user,
    mocker,
    auth_headers,
    _allow_billing_rate_limit,
) -> None:
    _patch_auth(mocker, app_main, base_user)
    _allow_billing_rate_limit.return_value = False
    mocker.patch.object(app_main, "billing_enabled", return_value=True)
    mocker.patch.object(
        app_main,
        "get_user_profile",
        return_value=UserProfileRecord(
            uid=base_user.app_user_id,
            email=base_user.email,
            display_name=base_user.display_name,
            role="pro",
            openai_credits_remaining=500,
        ),
    )
    retrieve_mock = mocker.patch.object(app_main, "retrieve_checkout_session")

    response = client.post(
        "/api/billing/reconcile",
        json={"dryRun": True, "sessionId": "cs_rate_limited_123"},
        headers=auth_headers,
    )

    assert response.status_code == 429
    assert "Too many billing requests" in response.text
    retrieve_mock.assert_not_called()


def test_billing_reconcile_processes_missing_checkout_session(
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
        "get_user_profile",
        return_value=UserProfileRecord(
            uid=base_user.app_user_id,
            email=base_user.email,
            display_name=base_user.display_name,
            role="pro",
            openai_credits_remaining=500,
        ),
    )
    mocker.patch.object(
        app_main,
        "retrieve_checkout_session",
        return_value=_build_checkout_session_object(
            checkout_kind="refill_500",
            payment_status="paid",
            card_number=STRIPE_TEST_CARD_SUCCESS,
            user_id=base_user.app_user_id,
            checkout_session_id="cs_refill_apply",
            checkout_attempt_id="attempt_refill_apply",
        ),
    )
    list_mock = mocker.patch.object(app_main, "list_recent_checkout_completion_events")
    mocker.patch.object(app_main, "get_billing_event", return_value=None)
    mocker.patch.object(app_main, "start_billing_event", return_value=True)
    handle_mock = mocker.patch.object(app_main, "_handle_checkout_session_completed", return_value=None)
    complete_mock = mocker.patch.object(app_main, "complete_billing_event", return_value=None)

    response = client.post(
        "/api/billing/reconcile",
        json={
            "dryRun": False,
            "lookbackHours": 24,
            "maxEvents": 20,
            "sessionId": "cs_refill_apply",
            "attemptId": "attempt_refill_apply",
        },
        headers=auth_headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["candidateEventCount"] == 1
    assert payload["pendingReconciliationCount"] == 1
    assert payload["reconciledCount"] == 1
    assert payload["events"][0]["checkoutSessionId"] == "cs_refill_apply"
    assert payload["events"][0]["checkoutAttemptId"] == "attempt_refill_apply"
    assert payload["events"][0]["checkoutPriceId"] == "price_refill_500"
    handle_mock.assert_called_once()
    complete_mock.assert_called_once_with("checkout_session:cs_refill_apply")
    list_mock.assert_not_called()


def test_billing_reconcile_requires_session_id_for_self_scope(
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
        "get_user_profile",
        return_value=UserProfileRecord(
            uid=base_user.app_user_id,
            email=base_user.email,
            display_name=base_user.display_name,
            role="pro",
            openai_credits_remaining=500,
        ),
    )
    retrieve_mock = mocker.patch.object(app_main, "retrieve_checkout_session")
    list_mock = mocker.patch.object(app_main, "list_recent_checkout_completion_events")

    response = client.post(
        "/api/billing/reconcile",
        json={"dryRun": True, "lookbackHours": 24, "maxEvents": 20},
        headers=auth_headers,
    )

    assert response.status_code == 400
    assert "sessionId is required" in response.text
    retrieve_mock.assert_not_called()
    list_mock.assert_not_called()


def test_billing_reconcile_returns_not_found_for_invalid_self_session_id(
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
        "get_user_profile",
        return_value=UserProfileRecord(
            uid=base_user.app_user_id,
            email=base_user.email,
            display_name=base_user.display_name,
            role="pro",
            openai_credits_remaining=500,
        ),
    )
    retrieve_mock = mocker.patch.object(
        app_main,
        "retrieve_checkout_session",
        side_effect=BillingCheckoutSessionNotFoundError("Stripe checkout session was not found."),
    )

    response = client.post(
        "/api/billing/reconcile",
        json={"dryRun": True, "sessionId": "cs_missing_123"},
        headers=auth_headers,
    )

    assert response.status_code == 404
    assert "Stripe checkout session was not found." in response.text
    retrieve_mock.assert_called_once_with(session_id="cs_missing_123")


def test_billing_reconcile_self_scope_does_not_scan_account_events(
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
        "get_user_profile",
        return_value=UserProfileRecord(
            uid=base_user.app_user_id,
            email=base_user.email,
            display_name=base_user.display_name,
            role="pro",
            openai_credits_remaining=500,
        ),
    )
    mocker.patch.object(
        app_main,
        "retrieve_checkout_session",
        return_value=_build_checkout_session_object(
            checkout_kind="refill_500",
            payment_status="paid",
            card_number=STRIPE_TEST_CARD_SUCCESS,
            user_id=base_user.app_user_id,
            checkout_session_id="cs_self_only",
            checkout_attempt_id="attempt_self_only",
        ),
    )
    list_mock = mocker.patch.object(app_main, "list_recent_checkout_completion_events")
    mocker.patch.object(app_main, "get_billing_event", return_value=None)

    response = client.post(
        "/api/billing/reconcile",
        json={
            "dryRun": True,
            "lookbackHours": 24,
            "maxEvents": 20,
            "sessionId": "cs_self_only",
            "attemptId": "attempt_self_only",
        },
        headers=auth_headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["scope"] == "self"
    assert payload["events"][0]["checkoutSessionId"] == "cs_self_only"
    list_mock.assert_not_called()


def test_billing_reconcile_returns_processed_events_for_frontend_matching(
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
        "get_user_profile",
        return_value=UserProfileRecord(
            uid=base_user.app_user_id,
            email=base_user.email,
            display_name=base_user.display_name,
            role="pro",
            openai_credits_remaining=500,
        ),
    )
    mocker.patch.object(
        app_main,
        "retrieve_checkout_session",
        return_value=_build_checkout_session_object(
            checkout_kind="pro_monthly",
            payment_status="paid",
            card_number=STRIPE_TEST_CARD_SUCCESS,
            user_id=base_user.app_user_id,
            checkout_session_id="cs_processed_123",
            checkout_attempt_id="attempt_processed_123",
        ),
    )
    mocker.patch.object(app_main, "get_billing_event", return_value={"status": "processed"})
    list_mock = mocker.patch.object(app_main, "list_recent_checkout_completion_events")
    start_mock = mocker.patch.object(app_main, "start_billing_event")

    response = client.post(
        "/api/billing/reconcile",
        json={
            "dryRun": False,
            "lookbackHours": 24,
            "maxEvents": 20,
            "sessionId": "cs_processed_123",
            "attemptId": "attempt_processed_123",
        },
        headers=auth_headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["candidateEventCount"] == 0
    assert payload["alreadyProcessedCount"] == 1
    assert payload["events"] == [
        {
            "eventId": "checkout_session:cs_processed_123",
            "eventType": "checkout.session.completed",
            "eventUserId": base_user.app_user_id,
            "created": None,
            "checkoutSessionId": "cs_processed_123",
            "checkoutAttemptId": "attempt_processed_123",
            "checkoutKind": "pro_monthly",
            "checkoutPriceId": "price_pro_monthly",
            "billingEventStatus": "processed",
        }
    ]
    start_mock.assert_not_called()
    list_mock.assert_not_called()


def test_billing_webhook_rejects_invalid_signature(client, app_main, mocker) -> None:
    mocker.patch.object(app_main, "construct_webhook_event", side_effect=ValueError("Missing Stripe-Signature header."))

    response = client.post("/api/billing/webhook", content=b"{}")

    assert response.status_code == 400
    assert "Missing Stripe-Signature header." in response.text


def test_billing_webhook_trailing_slash_remains_public(client, app_main, mocker) -> None:
    verify_mock = mocker.patch.object(app_main, "_verify_token")
    mocker.patch.object(app_main, "construct_webhook_event", side_effect=ValueError("Missing Stripe-Signature header."))

    response = client.post("/api/billing/webhook/", content=b"{}", follow_redirects=True)

    assert response.status_code == 400
    assert "Missing Stripe-Signature header." in response.text
    verify_mock.assert_not_called()


def test_billing_webhook_rejects_missing_event_id_or_type(client, app_main, mocker) -> None:
    mocker.patch.object(
        app_main,
        "construct_webhook_event",
        return_value={
            "id": "",
            "type": "checkout.session.completed",
            "data": {"object": {}},
        },
    )

    response = client.post(
        "/api/billing/webhook",
        content=b"{}",
        headers={"Stripe-Signature": "sig"},
    )

    assert response.status_code == 400
    assert "event id/type is required" in response.text


def test_billing_webhook_short_circuits_duplicate_events(client, app_main, mocker) -> None:
    mocker.patch.object(
        app_main,
        "construct_webhook_event",
        return_value={
            "id": "evt_1",
            "type": "checkout.session.completed",
            "data": {"object": {"metadata": {"userId": "user-1", "checkoutKind": "refill_500"}}},
        },
    )
    start_mock = mocker.patch.object(app_main, "start_billing_event", return_value=False)
    refill_mock = mocker.patch.object(app_main, "add_refill_openai_credits")

    response = client.post(
        "/api/billing/webhook",
        content=b"{}",
        headers={"Stripe-Signature": "sig"},
    )

    assert response.status_code == 200
    assert response.json()["duplicate"] is True
    start_mock.assert_called_once_with("evt_1", "checkout.session.completed")
    refill_mock.assert_not_called()


def test_billing_webhook_returns_503_when_event_is_already_processing(client, app_main, mocker) -> None:
    mocker.patch.object(
        app_main,
        "construct_webhook_event",
        return_value={
            "id": "evt_locked",
            "type": "checkout.session.completed",
            "data": {"object": {"metadata": {"userId": "user-1", "checkoutKind": "refill_500"}}},
        },
    )
    mocker.patch.object(
        app_main,
        "start_billing_event",
        side_effect=app_main.BillingEventInProgressError("lock is currently processing"),
    )

    response = client.post(
        "/api/billing/webhook",
        content=b"{}",
        headers={"Stripe-Signature": "sig"},
    )

    assert response.status_code == 503
    assert "currently processing" in response.text


def test_billing_webhook_unknown_event_type_is_noop_and_completes(client, app_main, mocker) -> None:
    mocker.patch.object(
        app_main,
        "construct_webhook_event",
        return_value={
            "id": "evt_unknown",
            "type": "customer.created",
            "data": {"object": {"id": "cus_1"}},
        },
    )
    mocker.patch.object(app_main, "start_billing_event", return_value=True)
    complete_mock = mocker.patch.object(app_main, "complete_billing_event", return_value=None)
    clear_mock = mocker.patch.object(app_main, "clear_billing_event", return_value=None)

    response = client.post(
        "/api/billing/webhook",
        content=b"{}",
        headers={"Stripe-Signature": "sig"},
    )

    assert response.status_code == 200
    assert response.json() == {"received": True}
    complete_mock.assert_called_once_with("evt_unknown")
    clear_mock.assert_not_called()


def test_billing_webhook_applies_refill_and_marks_complete(client, app_main, mocker) -> None:
    mocker.patch.object(
        app_main,
        "construct_webhook_event",
        return_value={
            "id": "evt_2",
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "client_reference_id": "user-1",
                    "metadata": {"checkoutKind": "refill_500"},
                    "payment_status": "paid",
                }
            },
        },
    )
    mocker.patch.object(app_main, "start_billing_event", return_value=True)
    mocker.patch.object(
        app_main,
        "get_user_profile",
        return_value=UserProfileRecord(
            uid="user-1",
            email="pro@example.com",
            display_name="Pro User",
            role="pro",
            openai_credits_remaining=500,
        ),
    )
    mocker.patch.object(
        app_main,
        "get_user_billing_record",
        return_value=UserBillingRecord(
            uid="user-1",
            customer_id="cus_123",
            subscription_id="sub_123",
            subscription_status="active",
            subscription_price_id="price_pro_monthly",
        ),
    )
    mocker.patch.object(app_main, "resolve_refill_credit_pack_size_for_price", return_value=500)
    refill_mock = mocker.patch.object(app_main, "add_refill_openai_credits", return_value=500)
    complete_mock = mocker.patch.object(app_main, "complete_billing_event", return_value=None)
    clear_mock = mocker.patch.object(app_main, "clear_billing_event", return_value=None)

    response = client.post(
        "/api/billing/webhook",
        content=b"{}",
        headers={"Stripe-Signature": "sig"},
    )

    assert response.status_code == 200
    assert response.json() == {"received": True}
    refill_mock.assert_called_once_with("user-1", credits=500, stripe_event_id="evt_2")
    complete_mock.assert_called_once_with("evt_2")
    clear_mock.assert_not_called()


def test_billing_webhook_refill_ineligible_returns_retryable_and_does_not_complete(client, app_main, mocker) -> None:
    mocker.patch.object(
        app_main,
        "construct_webhook_event",
        return_value={
            "id": "evt_refill_ineligible",
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "client_reference_id": "user-1",
                    "metadata": {"checkoutKind": "refill_500"},
                    "payment_status": "paid",
                }
            },
        },
    )
    mocker.patch.object(app_main, "start_billing_event", return_value=True)
    mocker.patch.object(
        app_main,
        "get_user_profile",
        return_value=UserProfileRecord(
            uid="user-1",
            email="base@example.com",
            display_name="Base User",
            role="base",
            openai_credits_remaining=10,
        ),
    )
    mocker.patch.object(
        app_main,
        "get_user_billing_record",
        return_value=UserBillingRecord(
            uid="user-1",
            customer_id="cus_123",
            subscription_id="sub_123",
            subscription_status="active",
            subscription_price_id="price_pro_monthly",
        ),
    )
    refill_mock = mocker.patch.object(app_main, "add_refill_openai_credits")
    complete_mock = mocker.patch.object(app_main, "complete_billing_event", return_value=None)
    clear_mock = mocker.patch.object(app_main, "clear_billing_event", return_value=None)

    response = client.post(
        "/api/billing/webhook",
        content=b"{}",
        headers={"Stripe-Signature": "sig"},
    )

    assert response.status_code == 503
    assert "active Pro subscription at fulfillment time" in response.text
    refill_mock.assert_not_called()
    complete_mock.assert_not_called()
    clear_mock.assert_called_once_with("evt_refill_ineligible")


def test_billing_webhook_refill_uses_line_items_price_fallback_when_metadata_lacks_price(client, app_main, mocker) -> None:
    mocker.patch.object(
        app_main,
        "construct_webhook_event",
        return_value={
            "id": "evt_refill_line_items_fallback",
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "client_reference_id": "user-1",
                    "metadata": {"checkoutKind": "refill_500"},
                    "line_items": {"data": [{"price": {"id": "price_refill_500"}}]},
                    "payment_status": "paid",
                }
            },
        },
    )
    mocker.patch.object(app_main, "start_billing_event", return_value=True)
    mocker.patch.object(
        app_main,
        "get_user_profile",
        return_value=UserProfileRecord(
            uid="user-1",
            email="pro@example.com",
            display_name="Pro User",
            role="pro",
            openai_credits_remaining=500,
        ),
    )
    mocker.patch.object(
        app_main,
        "get_user_billing_record",
        return_value=UserBillingRecord(
            uid="user-1",
            customer_id="cus_123",
            subscription_id="sub_123",
            subscription_status="active",
            subscription_price_id="price_pro_monthly",
        ),
    )
    mocker.patch.object(app_main, "resolve_refill_credit_pack_size_for_price", return_value=500)
    refill_mock = mocker.patch.object(app_main, "add_refill_openai_credits", return_value=500)
    complete_mock = mocker.patch.object(app_main, "complete_billing_event", return_value=None)
    clear_mock = mocker.patch.object(app_main, "clear_billing_event", return_value=None)

    response = client.post(
        "/api/billing/webhook",
        content=b"{}",
        headers={"Stripe-Signature": "sig"},
    )

    assert response.status_code == 200
    assert response.json() == {"received": True}
    refill_mock.assert_called_once_with("user-1", credits=500, stripe_event_id="evt_refill_line_items_fallback")
    complete_mock.assert_called_once_with("evt_refill_line_items_fallback")
    clear_mock.assert_not_called()


def test_billing_webhook_refill_checkout_skips_on_credit_metadata_mismatch(client, app_main, mocker) -> None:
    mocker.patch.object(
        app_main,
        "construct_webhook_event",
        return_value={
            "id": "evt_refill_credit_mismatch",
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "client_reference_id": "user-1",
                    "metadata": {
                        "checkoutKind": "refill_500",
                        "checkoutPriceId": "price_refill_500",
                        "refillCredits": "500",
                    },
                    "payment_status": "paid",
                }
            },
        },
    )
    mocker.patch.object(app_main, "start_billing_event", return_value=True)
    mocker.patch.object(
        app_main,
        "get_user_profile",
        return_value=UserProfileRecord(
            uid="user-1",
            email="pro@example.com",
            display_name="Pro User",
            role="pro",
            openai_credits_remaining=500,
        ),
    )
    mocker.patch.object(
        app_main,
        "get_user_billing_record",
        return_value=UserBillingRecord(
            uid="user-1",
            customer_id="cus_123",
            subscription_id="sub_123",
            subscription_status="active",
            subscription_price_id="price_pro_monthly",
        ),
    )
    mocker.patch.object(app_main, "resolve_refill_credit_pack_size_for_price", return_value=250)
    refill_mock = mocker.patch.object(app_main, "add_refill_openai_credits", return_value=500)
    complete_mock = mocker.patch.object(app_main, "complete_billing_event", return_value=None)
    clear_mock = mocker.patch.object(app_main, "clear_billing_event", return_value=None)

    response = client.post(
        "/api/billing/webhook",
        content=b"{}",
        headers={"Stripe-Signature": "sig"},
    )

    assert response.status_code == 503
    assert "Unable to resolve refill credits" in response.text
    refill_mock.assert_not_called()
    complete_mock.assert_not_called()
    clear_mock.assert_called_once_with("evt_refill_credit_mismatch")


def test_billing_webhook_refill_checkout_skips_when_credit_mapping_is_missing(client, app_main, mocker) -> None:
    mocker.patch.object(
        app_main,
        "construct_webhook_event",
        return_value={
            "id": "evt_refill_credit_missing",
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "client_reference_id": "user-1",
                    "metadata": {
                        "checkoutKind": "refill_500",
                        "checkoutPriceId": "price_unconfigured_refill",
                    },
                    "payment_status": "paid",
                }
            },
        },
    )
    mocker.patch.object(app_main, "start_billing_event", return_value=True)
    mocker.patch.object(
        app_main,
        "get_user_profile",
        return_value=UserProfileRecord(
            uid="user-1",
            email="pro@example.com",
            display_name="Pro User",
            role="pro",
            openai_credits_remaining=500,
        ),
    )
    mocker.patch.object(
        app_main,
        "get_user_billing_record",
        return_value=UserBillingRecord(
            uid="user-1",
            customer_id="cus_123",
            subscription_id="sub_123",
            subscription_status="active",
            subscription_price_id="price_pro_monthly",
        ),
    )
    mocker.patch.object(app_main, "resolve_refill_credit_pack_size_for_price", return_value=None)
    refill_mock = mocker.patch.object(app_main, "add_refill_openai_credits", return_value=500)
    complete_mock = mocker.patch.object(app_main, "complete_billing_event", return_value=None)
    clear_mock = mocker.patch.object(app_main, "clear_billing_event", return_value=None)

    response = client.post(
        "/api/billing/webhook",
        content=b"{}",
        headers={"Stripe-Signature": "sig"},
    )

    assert response.status_code == 503
    assert "Unable to resolve refill credits" in response.text
    refill_mock.assert_not_called()
    complete_mock.assert_not_called()
    clear_mock.assert_called_once_with("evt_refill_credit_missing")


@pytest.mark.parametrize(
    ("card_number", "payment_status", "expect_refill_applied"),
    [
        (STRIPE_TEST_CARD_SUCCESS, "paid", True),
        (STRIPE_TEST_CARD_SUCCESS, "no_payment_required", True),
        (STRIPE_TEST_CARD_SUCCESS, "", False),
        (STRIPE_TEST_CARD_3DS_REQUIRED, "unpaid", False),
        (STRIPE_TEST_CARD_DECLINED, "unpaid", False),
        (STRIPE_TEST_CARD_INSUFFICIENT_FUNDS, "unpaid", False),
    ],
    ids=[
        "success-4242",
        "success-no-payment-required",
        "missing-payment-status",
        "requires-auth-3155",
        "declined-0002",
        "insufficient-funds-9995",
    ],
)
def test_billing_webhook_refill_card_outcomes_only_fulfill_paid_sessions(
    client,
    app_main,
    mocker,
    card_number,
    payment_status,
    expect_refill_applied,
) -> None:
    event_id = f"evt_refill_{card_number[-4:]}"
    mocker.patch.object(
        app_main,
        "construct_webhook_event",
        return_value=_build_checkout_session_completed_event(
            event_id=event_id,
            checkout_kind="refill_500",
            payment_status=payment_status,
            card_number=card_number,
        ),
    )
    mocker.patch.object(app_main, "start_billing_event", return_value=True)
    mocker.patch.object(
        app_main,
        "get_user_profile",
        return_value=UserProfileRecord(
            uid="user-1",
            email="pro@example.com",
            display_name="Pro User",
            role="pro",
            openai_credits_remaining=500,
        ),
    )
    mocker.patch.object(
        app_main,
        "get_user_billing_record",
        return_value=UserBillingRecord(
            uid="user-1",
            customer_id="cus_123",
            subscription_id="sub_123",
            subscription_status="active",
            subscription_price_id="price_pro_monthly",
        ),
    )
    mocker.patch.object(app_main, "resolve_refill_credit_pack_size_for_price", return_value=500)
    refill_mock = mocker.patch.object(app_main, "add_refill_openai_credits", return_value=500)
    complete_mock = mocker.patch.object(app_main, "complete_billing_event", return_value=None)
    clear_mock = mocker.patch.object(app_main, "clear_billing_event", return_value=None)

    response = client.post(
        "/api/billing/webhook",
        content=b"{}",
        headers={"Stripe-Signature": "sig"},
    )

    assert response.status_code == 200
    assert response.json() == {"received": True}
    if expect_refill_applied:
        refill_mock.assert_called_once_with(
            "user-1",
            credits=500,
            stripe_event_id="checkout_session:cs_test_123",
        )
    else:
        refill_mock.assert_not_called()
    complete_mock.assert_called_once_with(event_id)
    clear_mock.assert_not_called()


def test_billing_webhook_refill_checkout_skips_fulfillment_when_user_is_not_pro(client, app_main, mocker) -> None:
    event_id = "evt_refill_base_user"
    mocker.patch.object(
        app_main,
        "construct_webhook_event",
        return_value=_build_checkout_session_completed_event(
            event_id=event_id,
            checkout_kind="refill_500",
            payment_status="paid",
            card_number=STRIPE_TEST_CARD_SUCCESS,
        ),
    )
    mocker.patch.object(app_main, "start_billing_event", return_value=True)
    mocker.patch.object(
        app_main,
        "get_user_profile",
        return_value=UserProfileRecord(
            uid="user-1",
            email="base@example.com",
            display_name="Base User",
            role="base",
            openai_credits_remaining=2,
        ),
    )
    mocker.patch.object(app_main, "resolve_refill_credit_pack_size_for_price", return_value=500)
    refill_mock = mocker.patch.object(app_main, "add_refill_openai_credits", return_value=500)
    complete_mock = mocker.patch.object(app_main, "complete_billing_event", return_value=None)
    clear_mock = mocker.patch.object(app_main, "clear_billing_event", return_value=None)

    response = client.post(
        "/api/billing/webhook",
        content=b"{}",
        headers={"Stripe-Signature": "sig"},
    )

    assert response.status_code == 503
    assert "active Pro subscription at fulfillment time" in response.text
    refill_mock.assert_not_called()
    complete_mock.assert_not_called()
    clear_mock.assert_called_once_with(event_id)


def test_billing_webhook_refill_checkout_skips_when_subscription_is_inactive(client, app_main, mocker) -> None:
    event_id = "evt_refill_inactive_sub"
    mocker.patch.object(
        app_main,
        "construct_webhook_event",
        return_value=_build_checkout_session_completed_event(
            event_id=event_id,
            checkout_kind="refill_500",
            payment_status="paid",
            card_number=STRIPE_TEST_CARD_SUCCESS,
        ),
    )
    mocker.patch.object(app_main, "start_billing_event", return_value=True)
    mocker.patch.object(
        app_main,
        "get_user_profile",
        return_value=UserProfileRecord(
            uid="user-1",
            email="pro@example.com",
            display_name="Pro User",
            role="pro",
            openai_credits_remaining=500,
        ),
    )
    mocker.patch.object(
        app_main,
        "get_user_billing_record",
        return_value=UserBillingRecord(
            uid="user-1",
            customer_id="cus_1",
            subscription_id="sub_1",
            subscription_status="canceled",
            subscription_price_id="price_pro_monthly",
        ),
    )
    mocker.patch.object(app_main, "is_subscription_active", return_value=False)
    mocker.patch.object(app_main, "resolve_refill_credit_pack_size_for_price", return_value=500)
    refill_mock = mocker.patch.object(app_main, "add_refill_openai_credits", return_value=500)
    complete_mock = mocker.patch.object(app_main, "complete_billing_event", return_value=None)
    clear_mock = mocker.patch.object(app_main, "clear_billing_event", return_value=None)

    response = client.post(
        "/api/billing/webhook",
        content=b"{}",
        headers={"Stripe-Signature": "sig"},
    )

    assert response.status_code == 503
    assert "active Pro subscription at fulfillment time" in response.text
    refill_mock.assert_not_called()
    complete_mock.assert_not_called()
    clear_mock.assert_called_once_with(event_id)


@pytest.mark.parametrize(
    ("card_number", "payment_status", "expect_pro_activation"),
    [
        (STRIPE_TEST_CARD_SUCCESS, "paid", True),
        (STRIPE_TEST_CARD_SUCCESS, "no_payment_required", True),
        (STRIPE_TEST_CARD_SUCCESS, "", False),
        (STRIPE_TEST_CARD_3DS_REQUIRED, "unpaid", False),
        (STRIPE_TEST_CARD_DECLINED, "unpaid", False),
        (STRIPE_TEST_CARD_INSUFFICIENT_FUNDS, "unpaid", False),
    ],
    ids=[
        "success-4242",
        "success-no-payment-required",
        "missing-payment-status",
        "requires-auth-3155",
        "declined-0002",
        "insufficient-funds-9995",
    ],
)
def test_billing_webhook_pro_checkout_card_outcomes_only_promote_paid_sessions(
    client,
    app_main,
    mocker,
    card_number,
    payment_status,
    expect_pro_activation,
) -> None:
    event_id = f"evt_pro_{card_number[-4:]}"
    mocker.patch.object(
        app_main,
        "construct_webhook_event",
        return_value=_build_checkout_session_completed_event(
            event_id=event_id,
            checkout_kind="pro_monthly",
            payment_status=payment_status,
            card_number=card_number,
        ),
    )
    mocker.patch.object(app_main, "start_billing_event", return_value=True)
    mocker.patch.object(app_main, "resolve_price_id_for_checkout_kind", return_value="price_pro_monthly")
    activate_mock = mocker.patch.object(
        app_main,
        "activate_pro_membership_with_subscription",
        return_value=True,
    )
    complete_mock = mocker.patch.object(app_main, "complete_billing_event", return_value=None)
    clear_mock = mocker.patch.object(app_main, "clear_billing_event", return_value=None)

    response = client.post(
        "/api/billing/webhook",
        content=b"{}",
        headers={"Stripe-Signature": "sig"},
    )

    assert response.status_code == 200
    assert response.json() == {"received": True}
    if expect_pro_activation:
        activate_mock.assert_called_once()
        assert activate_mock.call_args.kwargs["stripe_event_id"] == "checkout_session:cs_test_123"
        assert activate_mock.call_args.kwargs["subscription_id"] == "sub_123"
        assert activate_mock.call_args.kwargs["subscription_status"] == "active"
        assert activate_mock.call_args.kwargs["cancel_at_period_end"] is False
        assert activate_mock.call_args.kwargs["cancel_at"] is None
        assert activate_mock.call_args.kwargs["current_period_end"] is None
    else:
        activate_mock.assert_not_called()
    complete_mock.assert_called_once_with(event_id)
    clear_mock.assert_not_called()


def test_billing_webhook_pro_checkout_uses_client_reference_user_when_metadata_missing(client, app_main, mocker) -> None:
    event_id = "evt_pro_client_reference_fallback"
    mocker.patch.object(
        app_main,
        "construct_webhook_event",
        return_value={
            "id": event_id,
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "client_reference_id": "user-1",
                    "metadata": {"checkoutKind": "pro_monthly"},
                    "payment_status": "paid",
                    "subscription": "sub_123",
                    "customer": "cus_123",
                }
            },
        },
    )
    mocker.patch.object(app_main, "start_billing_event", return_value=True)
    mocker.patch.object(app_main, "resolve_price_id_for_checkout_kind", return_value="price_pro_monthly")
    activate_mock = mocker.patch.object(
        app_main,
        "activate_pro_membership_with_subscription",
        return_value=True,
    )
    complete_mock = mocker.patch.object(app_main, "complete_billing_event", return_value=None)
    clear_mock = mocker.patch.object(app_main, "clear_billing_event", return_value=None)

    response = client.post(
        "/api/billing/webhook",
        content=b"{}",
        headers={"Stripe-Signature": "sig"},
    )

    assert response.status_code == 200
    assert response.json() == {"received": True}
    activate_mock.assert_called_once()
    assert activate_mock.call_args.args[0] == "user-1"
    complete_mock.assert_called_once_with(event_id)
    clear_mock.assert_not_called()


def test_billing_webhook_subscription_deletion_downgrades_to_base(client, app_main, mocker) -> None:
    mocker.patch.object(
        app_main,
        "construct_webhook_event",
        return_value={
            "id": "evt_3",
            "type": "customer.subscription.deleted",
            "data": {
                "object": {
                    "id": "sub_1",
                    "status": "canceled",
                    "metadata": {"userId": "user-1"},
                    "customer": "cus_1",
                }
            },
        },
    )
    mocker.patch.object(app_main, "start_billing_event", return_value=True)
    mocker.patch.object(
        app_main,
        "get_user_billing_record",
        return_value=UserBillingRecord(
            uid="user-1",
            customer_id="cus_1",
            subscription_id="sub_1",
            subscription_status="active",
            subscription_price_id="price_pro_monthly",
        ),
    )
    mocker.patch.object(app_main, "is_pro_price_id", side_effect=lambda value: value == "price_pro_monthly")
    mocker.patch.object(app_main, "is_subscription_active", return_value=False)
    mocker.patch.object(app_main, "complete_billing_event", return_value=None)
    mocker.patch.object(app_main, "clear_billing_event", return_value=None)
    set_subscription_mock = mocker.patch.object(app_main, "set_user_billing_subscription", return_value=None)
    downgrade_mock = mocker.patch.object(app_main, "downgrade_to_base_membership", return_value=None)
    apply_retention_mock = mocker.patch.object(app_main, "apply_user_downgrade_retention", return_value={"status": "grace_period"})

    response = client.post(
        "/api/billing/webhook",
        content=b"{}",
        headers={"Stripe-Signature": "sig"},
    )

    assert response.status_code == 200
    set_subscription_mock.assert_called_once()
    downgrade_mock.assert_called_once_with("user-1")
    apply_retention_mock.assert_called_once_with("user-1")


def test_billing_webhook_subscription_updated_cancel_at_period_end_keeps_pro_role(client, app_main, mocker) -> None:
    mocker.patch.object(
        app_main,
        "construct_webhook_event",
        return_value={
            "id": "evt_3b",
            "type": "customer.subscription.updated",
            "data": {
                "object": {
                    "id": "sub_1",
                    "status": "active",
                    "cancel_at_period_end": True,
                    "metadata": {"userId": "user-1"},
                    "customer": "cus_1",
                    "items": {"data": [{"price": {"id": "price_pro_monthly"}}]},
                }
            },
        },
    )
    mocker.patch.object(app_main, "start_billing_event", return_value=True)
    mocker.patch.object(app_main, "is_pro_price_id", side_effect=lambda value: value == "price_pro_monthly")
    set_subscription_mock = mocker.patch.object(app_main, "set_user_billing_subscription", return_value=None)
    set_role_mock = mocker.patch.object(app_main, "set_user_role", return_value=None)
    clear_retention_mock = mocker.patch.object(app_main, "clear_user_downgrade_retention", return_value=None)
    downgrade_mock = mocker.patch.object(app_main, "downgrade_to_base_membership", return_value=None)
    complete_mock = mocker.patch.object(app_main, "complete_billing_event", return_value=None)
    clear_mock = mocker.patch.object(app_main, "clear_billing_event", return_value=None)

    response = client.post(
        "/api/billing/webhook",
        content=b"{}",
        headers={"Stripe-Signature": "sig"},
    )

    assert response.status_code == 200
    assert response.json() == {"received": True}
    set_subscription_mock.assert_called_once()
    assert set_subscription_mock.call_args.kwargs["cancel_at_period_end"] is True
    set_role_mock.assert_called_once_with("user-1", "pro")
    clear_retention_mock.assert_called_once_with("user-1")
    downgrade_mock.assert_not_called()
    complete_mock.assert_called_once_with("evt_3b")
    clear_mock.assert_not_called()


def test_billing_webhook_subscription_lifecycle_ignores_non_pro_subscription_events(client, app_main, mocker) -> None:
    mocker.patch.object(
        app_main,
        "construct_webhook_event",
        return_value={
            "id": "evt_3c",
            "type": "customer.subscription.updated",
            "data": {
                "object": {
                    "id": "sub_non_pro",
                    "status": "active",
                    "metadata": {"userId": "user-1"},
                    "customer": "cus_1",
                    "items": {"data": [{"price": {"id": "price_non_pro"}}]},
                }
            },
        },
    )
    mocker.patch.object(app_main, "start_billing_event", return_value=True)
    mocker.patch.object(app_main, "get_user_billing_record", return_value=None)
    mocker.patch.object(app_main, "is_pro_price_id", return_value=False)
    set_subscription_mock = mocker.patch.object(app_main, "set_user_billing_subscription", return_value=None)
    set_role_mock = mocker.patch.object(app_main, "set_user_role", return_value=None)
    downgrade_mock = mocker.patch.object(app_main, "downgrade_to_base_membership", return_value=None)
    complete_mock = mocker.patch.object(app_main, "complete_billing_event", return_value=None)
    clear_mock = mocker.patch.object(app_main, "clear_billing_event", return_value=None)

    response = client.post(
        "/api/billing/webhook",
        content=b"{}",
        headers={"Stripe-Signature": "sig"},
    )

    assert response.status_code == 200
    assert response.json() == {"received": True}
    set_subscription_mock.assert_not_called()
    set_role_mock.assert_not_called()
    downgrade_mock.assert_not_called()
    complete_mock.assert_called_once_with("evt_3c")
    clear_mock.assert_not_called()


def test_billing_webhook_subscription_lifecycle_uses_stored_pro_record_when_event_price_is_non_pro(
    client,
    app_main,
    mocker,
) -> None:
    mocker.patch.object(
        app_main,
        "construct_webhook_event",
        return_value={
            "id": "evt_3_non_pro_with_pro_record",
            "type": "customer.subscription.updated",
            "data": {
                "object": {
                    "id": "sub_1",
                    "status": "canceled",
                    "metadata": {"userId": "user-1"},
                    "customer": "cus_1",
                    "items": {"data": [{"price": {"id": "price_non_pro"}}]},
                }
            },
        },
    )
    mocker.patch.object(app_main, "start_billing_event", return_value=True)
    mocker.patch.object(
        app_main,
        "get_user_billing_record",
        return_value=UserBillingRecord(
            uid="user-1",
            customer_id="cus_1",
            subscription_id="sub_1",
            subscription_status="active",
            subscription_price_id="price_pro_monthly",
            cancel_at_period_end=False,
            cancel_at=None,
            current_period_end=None,
        ),
    )
    mocker.patch.object(app_main, "is_pro_price_id", side_effect=lambda value: value == "price_pro_monthly")
    set_subscription_mock = mocker.patch.object(app_main, "set_user_billing_subscription", return_value=None)
    set_role_mock = mocker.patch.object(app_main, "set_user_role", return_value=None)
    downgrade_mock = mocker.patch.object(app_main, "downgrade_to_base_membership", return_value=None)
    complete_mock = mocker.patch.object(app_main, "complete_billing_event", return_value=None)
    clear_mock = mocker.patch.object(app_main, "clear_billing_event", return_value=None)

    response = client.post(
        "/api/billing/webhook",
        content=b"{}",
        headers={"Stripe-Signature": "sig"},
    )

    assert response.status_code == 200
    assert response.json() == {"received": True}
    set_subscription_mock.assert_called_once()
    set_role_mock.assert_not_called()
    downgrade_mock.assert_called_once_with("user-1")
    complete_mock.assert_called_once_with("evt_3_non_pro_with_pro_record")
    clear_mock.assert_not_called()


def test_billing_webhook_subscription_lifecycle_missing_user_returns_retryable(client, app_main, mocker) -> None:
    mocker.patch.object(
        app_main,
        "construct_webhook_event",
        return_value={
            "id": "evt_3_missing_user",
            "type": "customer.subscription.updated",
            "data": {
                "object": {
                    "id": "sub_missing_user",
                    "status": "active",
                    "metadata": {},
                    "customer": "cus_1",
                    "items": {"data": [{"price": {"id": "price_pro_monthly"}}]},
                }
            },
        },
    )
    mocker.patch.object(app_main, "start_billing_event", return_value=True)
    mocker.patch.object(app_main, "find_user_id_by_subscription_id", return_value=None)
    mocker.patch.object(app_main, "is_pro_price_id", side_effect=lambda value: value == "price_pro_monthly")
    set_subscription_mock = mocker.patch.object(app_main, "set_user_billing_subscription", return_value=None)
    set_role_mock = mocker.patch.object(app_main, "set_user_role", return_value=None)
    downgrade_mock = mocker.patch.object(app_main, "downgrade_to_base_membership", return_value=None)
    complete_mock = mocker.patch.object(app_main, "complete_billing_event", return_value=None)
    clear_mock = mocker.patch.object(app_main, "clear_billing_event", return_value=None)

    response = client.post(
        "/api/billing/webhook",
        content=b"{}",
        headers={"Stripe-Signature": "sig"},
    )

    assert response.status_code == 503
    assert "awaiting subscription linkage" in response.text
    set_subscription_mock.assert_not_called()
    set_role_mock.assert_not_called()
    downgrade_mock.assert_not_called()
    complete_mock.assert_not_called()
    clear_mock.assert_called_once_with("evt_3_missing_user")


def test_billing_webhook_retryable_failure_deletes_lock_when_clear_fails(client, app_main, mocker) -> None:
    mocker.patch.object(
        app_main,
        "construct_webhook_event",
        return_value={
            "id": "evt_retryable_clear_fail",
            "type": "customer.subscription.updated",
            "data": {
                "object": {
                    "id": "sub_missing_user",
                    "status": "active",
                    "metadata": {},
                    "customer": "cus_1",
                    "items": {"data": [{"price": {"id": "price_pro_monthly"}}]},
                }
            },
        },
    )
    mocker.patch.object(app_main, "start_billing_event", return_value=True)
    mocker.patch.object(app_main, "find_user_id_by_subscription_id", return_value=None)
    mocker.patch.object(app_main, "is_pro_price_id", side_effect=lambda value: value == "price_pro_monthly")
    clear_mock = mocker.patch.object(
        app_main,
        "clear_billing_event",
        side_effect=RuntimeError("clear failed"),
    )
    delete_mock = mocker.patch.object(app_main, "delete_billing_event", return_value=None)

    response = client.post(
        "/api/billing/webhook",
        content=b"{}",
        headers={"Stripe-Signature": "sig"},
    )

    assert response.status_code == 503
    clear_mock.assert_called_once_with("evt_retryable_clear_fail")
    delete_mock.assert_called_once_with("evt_retryable_clear_fail")


def test_billing_webhook_processing_failure_deletes_lock_when_clear_fails(client, app_main, mocker) -> None:
    mocker.patch.object(
        app_main,
        "construct_webhook_event",
        return_value={
            "id": "evt_failure_clear_fail",
            "type": "customer.created",
            "data": {"object": {"id": "cus_1"}},
        },
    )
    mocker.patch.object(app_main, "start_billing_event", return_value=True)
    mocker.patch.object(
        app_main,
        "complete_billing_event",
        side_effect=RuntimeError("complete failed"),
    )
    clear_mock = mocker.patch.object(
        app_main,
        "clear_billing_event",
        side_effect=RuntimeError("clear failed"),
    )
    delete_mock = mocker.patch.object(app_main, "delete_billing_event", return_value=None)

    response = client.post(
        "/api/billing/webhook",
        content=b"{}",
        headers={"Stripe-Signature": "sig"},
    )

    assert response.status_code == 500
    clear_mock.assert_called_once_with("evt_failure_clear_fail")
    delete_mock.assert_called_once_with("evt_failure_clear_fail")


def test_billing_webhook_subscription_lifecycle_non_pro_missing_user_is_noop(client, app_main, mocker) -> None:
    mocker.patch.object(
        app_main,
        "construct_webhook_event",
        return_value={
            "id": "evt_3_non_pro_missing_user",
            "type": "customer.subscription.updated",
            "data": {
                "object": {
                    "id": "sub_non_pro_missing_user",
                    "status": "active",
                    "metadata": {},
                    "customer": "cus_1",
                    "items": {"data": [{"price": {"id": "price_non_pro"}}]},
                }
            },
        },
    )
    mocker.patch.object(app_main, "start_billing_event", return_value=True)
    mocker.patch.object(app_main, "find_user_id_by_subscription_id", return_value=None)
    mocker.patch.object(app_main, "is_pro_price_id", return_value=False)
    set_subscription_mock = mocker.patch.object(app_main, "set_user_billing_subscription", return_value=None)
    complete_mock = mocker.patch.object(app_main, "complete_billing_event", return_value=None)
    clear_mock = mocker.patch.object(app_main, "clear_billing_event", return_value=None)

    response = client.post(
        "/api/billing/webhook",
        content=b"{}",
        headers={"Stripe-Signature": "sig"},
    )

    assert response.status_code == 200
    assert response.json() == {"received": True}
    set_subscription_mock.assert_not_called()
    complete_mock.assert_called_once_with("evt_3_non_pro_missing_user")
    clear_mock.assert_not_called()


def test_billing_webhook_invoice_paid_resets_pro_monthly_pool(client, app_main, mocker) -> None:
    mocker.patch.object(
        app_main,
        "construct_webhook_event",
        return_value={
            "id": "evt_4",
            "type": "invoice.paid",
            "data": {
                "object": {
                    "subscription": "sub_123",
                    "customer": "cus_123",
                    "lines": {"data": [{"price": {"id": "price_pro_monthly"}}]},
                }
            },
        },
    )
    mocker.patch.object(app_main, "start_billing_event", return_value=True)
    mocker.patch.object(app_main, "extract_price_ids_from_invoice", return_value=["price_pro_monthly"])
    mocker.patch.object(app_main, "is_pro_price_id", return_value=True)
    mocker.patch.object(app_main, "find_user_id_by_subscription_id", return_value="user-1")
    mocker.patch.object(app_main, "get_user_billing_record", return_value=None)
    activate_mock = mocker.patch.object(
        app_main,
        "activate_pro_membership_with_subscription",
        return_value=True,
    )
    mocker.patch.object(app_main, "complete_billing_event", return_value=None)
    mocker.patch.object(app_main, "clear_billing_event", return_value=None)

    response = client.post(
        "/api/billing/webhook",
        content=b"{}",
        headers={"Stripe-Signature": "sig"},
    )

    assert response.status_code == 200
    activate_mock.assert_called_once()
    assert activate_mock.call_args.kwargs["stripe_event_id"] == "evt_4"
    assert activate_mock.call_args.kwargs["subscription_id"] == "sub_123"


def test_billing_webhook_invoice_paid_missing_prices_is_noop(client, app_main, mocker) -> None:
    mocker.patch.object(
        app_main,
        "construct_webhook_event",
        return_value={
            "id": "evt_4_no_prices",
            "type": "invoice.paid",
            "data": {
                "object": {
                    "subscription": "sub_456",
                    "customer": "cus_456",
                    "lines": {"data": []},
                }
            },
        },
    )
    mocker.patch.object(app_main, "start_billing_event", return_value=True)
    mocker.patch.object(app_main, "extract_price_ids_from_invoice", return_value=[])
    mocker.patch.object(app_main, "find_user_id_by_subscription_id", return_value="user-1")
    mocker.patch.object(
        app_main,
        "get_user_billing_record",
        return_value=UserBillingRecord(
            uid="user-1",
            customer_id="cus_456",
            subscription_id="sub_456",
            subscription_status="active",
            subscription_price_id="price_not_pro",
        ),
    )
    mocker.patch.object(app_main, "is_pro_price_id", return_value=False)
    activate_mock = mocker.patch.object(
        app_main,
        "activate_pro_membership_with_subscription",
        return_value=True,
    )
    complete_mock = mocker.patch.object(app_main, "complete_billing_event", return_value=None)
    clear_mock = mocker.patch.object(app_main, "clear_billing_event", return_value=None)

    response = client.post(
        "/api/billing/webhook",
        content=b"{}",
        headers={"Stripe-Signature": "sig"},
    )

    assert response.status_code == 200
    assert response.json() == {"received": True}
    activate_mock.assert_not_called()
    complete_mock.assert_called_once_with("evt_4_no_prices")
    clear_mock.assert_not_called()


def test_billing_webhook_invoice_paid_uses_stored_pro_price_when_lines_missing(client, app_main, mocker) -> None:
    mocker.patch.object(
        app_main,
        "construct_webhook_event",
        return_value={
            "id": "evt_4_fallback",
            "type": "invoice.paid",
            "data": {
                "object": {
                    "subscription": "sub_789",
                    "customer": "cus_789",
                    "lines": {"data": []},
                }
            },
        },
    )
    mocker.patch.object(app_main, "start_billing_event", return_value=True)
    mocker.patch.object(app_main, "extract_price_ids_from_invoice", return_value=[])
    mocker.patch.object(app_main, "find_user_id_by_subscription_id", return_value="user-1")
    mocker.patch.object(
        app_main,
        "get_user_billing_record",
        return_value=UserBillingRecord(
            uid="user-1",
            customer_id="cus_789",
            subscription_id="sub_789",
            subscription_status="active",
            subscription_price_id="price_pro_monthly",
        ),
    )
    mocker.patch.object(app_main, "is_pro_price_id", side_effect=lambda value: value == "price_pro_monthly")
    activate_mock = mocker.patch.object(
        app_main,
        "activate_pro_membership_with_subscription",
        return_value=True,
    )
    complete_mock = mocker.patch.object(app_main, "complete_billing_event", return_value=None)
    clear_mock = mocker.patch.object(app_main, "clear_billing_event", return_value=None)

    response = client.post(
        "/api/billing/webhook",
        content=b"{}",
        headers={"Stripe-Signature": "sig"},
    )

    assert response.status_code == 200
    activate_mock.assert_called_once()
    assert activate_mock.call_args.kwargs["stripe_event_id"] == "evt_4_fallback"
    assert activate_mock.call_args.kwargs["subscription_id"] == "sub_789"
    complete_mock.assert_called_once_with("evt_4_fallback")
    clear_mock.assert_not_called()


def test_billing_webhook_invoice_paid_selects_pro_price_from_mixed_invoice_lines(client, app_main, mocker) -> None:
    mocker.patch.object(
        app_main,
        "construct_webhook_event",
        return_value={
            "id": "evt_4_mixed",
            "type": "invoice.paid",
            "data": {
                "object": {
                    "subscription": "sub_654",
                    "customer": "cus_654",
                    "lines": {"data": [{"price": {"id": "price_non_pro"}}, {"price": {"id": "price_pro_monthly"}}]},
                }
            },
        },
    )
    mocker.patch.object(app_main, "start_billing_event", return_value=True)
    mocker.patch.object(app_main, "extract_price_ids_from_invoice", return_value=["price_non_pro", "price_pro_monthly"])
    mocker.patch.object(app_main, "is_pro_price_id", side_effect=lambda value: value == "price_pro_monthly")
    mocker.patch.object(app_main, "find_user_id_by_subscription_id", return_value="user-1")
    mocker.patch.object(app_main, "get_user_billing_record", return_value=None)
    activate_mock = mocker.patch.object(
        app_main,
        "activate_pro_membership_with_subscription",
        return_value=True,
    )
    complete_mock = mocker.patch.object(app_main, "complete_billing_event", return_value=None)
    clear_mock = mocker.patch.object(app_main, "clear_billing_event", return_value=None)

    response = client.post(
        "/api/billing/webhook",
        content=b"{}",
        headers={"Stripe-Signature": "sig"},
    )

    assert response.status_code == 200
    assert response.json() == {"received": True}
    activate_mock.assert_called_once()
    assert activate_mock.call_args.kwargs["subscription_price_id"] == "price_pro_monthly"
    complete_mock.assert_called_once_with("evt_4_mixed")
    clear_mock.assert_not_called()


def test_billing_webhook_invoice_paid_missing_user_returns_retryable(client, app_main, mocker) -> None:
    mocker.patch.object(
        app_main,
        "construct_webhook_event",
        return_value={
            "id": "evt_4_missing_user",
            "type": "invoice.paid",
            "data": {
                "object": {
                    "subscription": "sub_missing_user",
                    "customer": "cus_missing_user",
                    "lines": {"data": [{"price": {"id": "price_pro_monthly"}}]},
                }
            },
        },
    )
    mocker.patch.object(app_main, "start_billing_event", return_value=True)
    mocker.patch.object(app_main, "extract_price_ids_from_invoice", return_value=["price_pro_monthly"])
    mocker.patch.object(app_main, "is_pro_price_id", side_effect=lambda value: value == "price_pro_monthly")
    mocker.patch.object(app_main, "find_user_id_by_subscription_id", return_value=None)
    activate_mock = mocker.patch.object(
        app_main,
        "activate_pro_membership_with_subscription",
        return_value=True,
    )
    complete_mock = mocker.patch.object(app_main, "complete_billing_event", return_value=None)
    clear_mock = mocker.patch.object(app_main, "clear_billing_event", return_value=None)

    response = client.post(
        "/api/billing/webhook",
        content=b"{}",
        headers={"Stripe-Signature": "sig"},
    )

    assert response.status_code == 503
    assert "awaiting subscription linkage" in response.text
    activate_mock.assert_not_called()
    complete_mock.assert_not_called()
    clear_mock.assert_called_once_with("evt_4_missing_user")


def test_billing_webhook_processing_failure_clears_event_lock(client, app_main, mocker) -> None:
    mocker.patch.object(
        app_main,
        "construct_webhook_event",
        return_value={
            "id": "evt_5",
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "metadata": {"checkoutKind": "refill_500", "userId": "user-1"},
                    "payment_status": "paid",
                }
            },
        },
    )
    mocker.patch.object(app_main, "start_billing_event", return_value=True)
    mocker.patch.object(
        app_main,
        "get_user_profile",
        return_value=UserProfileRecord(
            uid="user-1",
            email="pro@example.com",
            display_name="Pro User",
            role="pro",
            openai_credits_remaining=500,
        ),
    )
    mocker.patch.object(
        app_main,
        "get_user_billing_record",
        return_value=UserBillingRecord(
            uid="user-1",
            customer_id="cus_123",
            subscription_id="sub_123",
            subscription_status="active",
            subscription_price_id="price_pro_monthly",
        ),
    )
    mocker.patch.object(app_main, "resolve_refill_credit_pack_size_for_price", return_value=500)
    mocker.patch.object(app_main, "add_refill_openai_credits", side_effect=RuntimeError("db down"))
    clear_mock = mocker.patch.object(app_main, "clear_billing_event", return_value=None)
    complete_mock = mocker.patch.object(app_main, "complete_billing_event", return_value=None)

    response = client.post(
        "/api/billing/webhook",
        content=b"{}",
        headers={"Stripe-Signature": "sig"},
    )

    assert response.status_code == 500
    clear_mock.assert_called_once_with("evt_5")
    complete_mock.assert_not_called()
