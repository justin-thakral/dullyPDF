"""Integration tests for free-trial checkout and lifecycle events."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import backend.main as main
import backend.api.middleware.security as security_middleware
import backend.api.routes.billing as billing_routes
import backend.api.routes.profile as profile_routes
import backend.firebaseDB.billing_database as billing_database
import backend.firebaseDB.fill_link_database as fill_link_database
import backend.firebaseDB.user_database as user_database
from backend.test.integration.billing_webhook_test_support import (
    encode_event,
    install_fake_stripe_module,
    sign_stripe_payload,
)
from backend.test.integration.downgrade_test_support import (
    build_request_user,
    seed_downgrade_ready_pro_profile,
)
from backend.test.unit.firebase._fakes import FakeFirestoreClient


def _authenticated_user(uid: str = "trial-user"):
    return build_request_user(
        uid=f"firebase-{uid}",
        app_user_id=uid,
        email="trial@example.com",
        display_name="Trial User",
        role=user_database.ROLE_BASE,
    )


def _seed_base_profile(
    firestore_client: FakeFirestoreClient,
    *,
    user_id: str,
    trial_used: bool = False,
) -> None:
    data = {
        "email": "trial@example.com",
        "displayName": "Trial User",
        user_database.ROLE_FIELD: user_database.ROLE_BASE,
        user_database.OPENAI_CREDITS_FIELD: user_database.BASE_OPENAI_CREDITS,
        user_database.OPENAI_CREDITS_BASE_CYCLE_FIELD: "2026-03",
        "created_at": "2026-03-01T00:00:00+00:00",
        "updated_at": "2026-03-27T00:00:00+00:00",
    }
    if trial_used:
        data[user_database.TRIAL_USED_FIELD] = True
    firestore_client.collection(user_database.USERS_COLLECTION).document(user_id).seed(data)


@pytest.fixture
def client() -> TestClient:
    return TestClient(main.app)


@pytest.fixture
def webhook_secret(monkeypatch: pytest.MonkeyPatch) -> str:
    install_fake_stripe_module(monkeypatch)
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_trial_integration")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_trial_integration")
    return "whsec_trial_integration"


@pytest.fixture(autouse=True)
def _no_transaction_wrapper(mocker):
    mocker.patch.object(user_database.firebase_firestore, "transactional", side_effect=lambda fn: fn)
    mocker.patch.object(billing_database.firebase_firestore, "transactional", side_effect=lambda fn: fn)
    mocker.patch.object(billing_routes, "restore_user_downgrade_managed_links", return_value=None)
    mocker.patch.object(billing_routes, "apply_user_downgrade_retention", return_value=None)


def test_trial_checkout_and_activation(
    client: TestClient,
    webhook_secret: str,
    mocker,
) -> None:
    """Base user → free_trial checkout → webhook checkout.session.completed → pro + trialing."""
    firestore_client = FakeFirestoreClient()
    request_user = _authenticated_user()
    _seed_base_profile(firestore_client, user_id=request_user.app_user_id)

    checkout_event = {
        "id": "evt_trial_checkout_completed",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_trial_123",
                "created": 1711584000,
                "client_reference_id": request_user.app_user_id,
                "metadata": {
                    "userId": request_user.app_user_id,
                    "checkoutKind": "free_trial",
                    "checkoutPriceId": "price_pro_monthly",
                    "checkoutAttemptId": "attempt_trial_123",
                },
                "payment_status": "no_payment_required",
                "subscription": "sub_trial_123",
                "customer": "cus_trial_123",
            }
        },
    }
    payload = encode_event(checkout_event)
    signature = sign_stripe_payload(payload, secret=webhook_secret)

    mocker.patch.object(billing_routes, "start_billing_event", return_value=True)
    mocker.patch.object(
        billing_routes,
        "is_pro_price_id",
        side_effect=lambda value: value == "price_pro_monthly",
    )
    mocker.patch.object(billing_routes, "complete_billing_event", return_value=None)
    mocker.patch.object(billing_routes, "clear_billing_event", return_value=None)
    mocker.patch.object(security_middleware, "verify_token", return_value={"uid": request_user.uid})
    mocker.patch.object(profile_routes, "require_user", return_value=request_user)
    mocker.patch.object(profile_routes, "billing_enabled", return_value=True)
    mocker.patch.object(profile_routes, "resolve_checkout_catalog", return_value={})
    for module in (billing_database, user_database, fill_link_database):
        mocker.patch.object(module, "get_firestore_client", return_value=firestore_client)

    webhook_response = client.post(
        "/api/billing/webhook",
        content=payload,
        headers={"Stripe-Signature": signature},
    )
    assert webhook_response.status_code == 200
    assert webhook_response.json() == {"received": True}

    stored_user = (
        firestore_client.collection(user_database.USERS_COLLECTION)
        .document(request_user.app_user_id)
        .get()
        .to_dict()
    )
    assert stored_user[user_database.ROLE_FIELD] == user_database.ROLE_PRO
    assert stored_user[user_database.TRIAL_USED_FIELD] is True
    assert stored_user[user_database.STRIPE_CUSTOMER_ID_FIELD] == "cus_trial_123"
    assert stored_user[user_database.STRIPE_SUBSCRIPTION_ID_FIELD] == "sub_trial_123"

    profile_response = client.get(
        "/api/profile",
        headers={"Authorization": "Bearer trial-token"},
    )
    assert profile_response.status_code == 200
    profile_data = profile_response.json()
    assert profile_data["role"] == user_database.ROLE_PRO
    assert profile_data["billing"]["trialUsed"] is True


def test_trial_expiry_downgrades(
    client: TestClient,
    webhook_secret: str,
    mocker,
) -> None:
    """Pro-trialing user → subscription deleted → role=base, trial_used still True."""
    firestore_client = FakeFirestoreClient()
    request_user = _authenticated_user()
    seed_downgrade_ready_pro_profile(
        firestore_client,
        user_id=request_user.app_user_id,
        email="trial@example.com",
        display_name="Trial User",
        subscription_id="sub_trial_expire",
    )
    firestore_client.collection(user_database.USERS_COLLECTION).document(
        request_user.app_user_id
    ).set({user_database.TRIAL_USED_FIELD: True}, merge=True)

    deleted_event = {
        "id": "evt_trial_expired",
        "type": "customer.subscription.deleted",
        "data": {
            "object": {
                "id": "sub_trial_expire",
                "customer": "cus_integration",
                "status": "canceled",
                "metadata": {"userId": request_user.app_user_id},
                "items": {"data": [{"price": {"id": "price_pro_monthly"}}]},
            }
        },
    }
    payload = encode_event(deleted_event)
    signature = sign_stripe_payload(payload, secret=webhook_secret)

    mocker.patch.object(billing_routes, "start_billing_event", return_value=True)
    mocker.patch.object(
        billing_routes,
        "is_pro_price_id",
        side_effect=lambda value: value == "price_pro_monthly",
    )
    mocker.patch.object(billing_routes, "complete_billing_event", return_value=None)
    mocker.patch.object(billing_routes, "clear_billing_event", return_value=None)
    for module in (user_database, fill_link_database):
        mocker.patch.object(module, "get_firestore_client", return_value=firestore_client)

    response = client.post(
        "/api/billing/webhook",
        content=payload,
        headers={"Stripe-Signature": signature},
    )
    assert response.status_code == 200

    stored_user = (
        firestore_client.collection(user_database.USERS_COLLECTION)
        .document(request_user.app_user_id)
        .get()
        .to_dict()
    )
    assert stored_user[user_database.ROLE_FIELD] == user_database.ROLE_BASE
    assert stored_user[user_database.TRIAL_USED_FIELD] is True
    assert stored_user[user_database.STRIPE_SUBSCRIPTION_STATUS_FIELD] == "canceled"


def test_trial_to_paid_preserves_pro(
    client: TestClient,
    webhook_secret: str,
    mocker,
) -> None:
    """Pro-trialing user → subscription updated to active → remains pro."""
    firestore_client = FakeFirestoreClient()
    request_user = _authenticated_user()
    seed_downgrade_ready_pro_profile(
        firestore_client,
        user_id=request_user.app_user_id,
        email="trial@example.com",
        display_name="Trial User",
        subscription_id="sub_trial_convert",
    )
    firestore_client.collection(user_database.USERS_COLLECTION).document(
        request_user.app_user_id
    ).set({
        user_database.TRIAL_USED_FIELD: True,
        user_database.STRIPE_SUBSCRIPTION_STATUS_FIELD: "trialing",
    }, merge=True)

    updated_event = {
        "id": "evt_trial_to_paid",
        "type": "customer.subscription.updated",
        "data": {
            "object": {
                "id": "sub_trial_convert",
                "customer": "cus_integration",
                "status": "active",
                "metadata": {"userId": request_user.app_user_id},
                "items": {"data": [{"price": {"id": "price_pro_monthly"}}]},
            }
        },
    }
    payload = encode_event(updated_event)
    signature = sign_stripe_payload(payload, secret=webhook_secret)

    mocker.patch.object(billing_routes, "start_billing_event", return_value=True)
    mocker.patch.object(
        billing_routes,
        "is_pro_price_id",
        side_effect=lambda value: value == "price_pro_monthly",
    )
    mocker.patch.object(billing_routes, "complete_billing_event", return_value=None)
    mocker.patch.object(billing_routes, "clear_billing_event", return_value=None)
    for module in (user_database, fill_link_database):
        mocker.patch.object(module, "get_firestore_client", return_value=firestore_client)

    response = client.post(
        "/api/billing/webhook",
        content=payload,
        headers={"Stripe-Signature": signature},
    )
    assert response.status_code == 200

    stored_user = (
        firestore_client.collection(user_database.USERS_COLLECTION)
        .document(request_user.app_user_id)
        .get()
        .to_dict()
    )
    assert stored_user[user_database.ROLE_FIELD] == user_database.ROLE_PRO
    assert stored_user[user_database.TRIAL_USED_FIELD] is True
    assert stored_user[user_database.STRIPE_SUBSCRIPTION_STATUS_FIELD] == "active"


def test_trial_blocked_after_previous_use(
    client: TestClient,
    mocker,
) -> None:
    """Base user with trial_used=True → checkout POST → 409."""
    firestore_client = FakeFirestoreClient()
    request_user = _authenticated_user()
    _seed_base_profile(firestore_client, user_id=request_user.app_user_id, trial_used=True)

    mocker.patch.object(user_database.firebase_firestore, "transactional", side_effect=lambda fn: fn)
    mocker.patch.object(billing_database.firebase_firestore, "transactional", side_effect=lambda fn: fn)
    mocker.patch.object(security_middleware, "verify_token", return_value={"uid": request_user.uid})
    mocker.patch.object(billing_routes, "ensure_user", return_value=request_user)
    mocker.patch.object(billing_routes, "require_user", return_value=request_user)
    mocker.patch.object(billing_routes, "billing_enabled", return_value=True)
    mocker.patch.object(billing_routes, "check_rate_limit", return_value=True)
    mocker.patch.object(billing_routes, "webhook_health_enforced_for_checkout", return_value=False)
    mocker.patch.object(billing_routes, "resolve_price_id_for_checkout_kind", return_value="price_pro_monthly")
    for module in (billing_database, user_database):
        mocker.patch.object(module, "get_firestore_client", return_value=firestore_client)

    checkout_mock = mocker.patch.object(billing_routes, "create_checkout_session")

    response = client.post(
        "/api/billing/checkout-session",
        json={"kind": "free_trial"},
        headers={"Authorization": "Bearer trial-token"},
    )

    assert response.status_code == 409
    assert "already been used" in response.text
    checkout_mock.assert_not_called()


def test_trial_blocked_for_ex_pro_user(
    client: TestClient,
    mocker,
) -> None:
    """User who was pro and downgraded (trial_used=True) → trial blocked."""
    firestore_client = FakeFirestoreClient()
    request_user = _authenticated_user()
    _seed_base_profile(firestore_client, user_id=request_user.app_user_id, trial_used=True)
    firestore_client.collection(user_database.USERS_COLLECTION).document(
        request_user.app_user_id
    ).set({user_database.STRIPE_SUBSCRIPTION_STATUS_FIELD: "canceled"}, merge=True)

    mocker.patch.object(user_database.firebase_firestore, "transactional", side_effect=lambda fn: fn)
    mocker.patch.object(billing_database.firebase_firestore, "transactional", side_effect=lambda fn: fn)
    mocker.patch.object(security_middleware, "verify_token", return_value={"uid": request_user.uid})
    mocker.patch.object(billing_routes, "ensure_user", return_value=request_user)
    mocker.patch.object(billing_routes, "require_user", return_value=request_user)
    mocker.patch.object(billing_routes, "billing_enabled", return_value=True)
    mocker.patch.object(billing_routes, "check_rate_limit", return_value=True)
    mocker.patch.object(billing_routes, "webhook_health_enforced_for_checkout", return_value=False)
    mocker.patch.object(billing_routes, "resolve_price_id_for_checkout_kind", return_value="price_pro_monthly")
    for module in (billing_database, user_database):
        mocker.patch.object(module, "get_firestore_client", return_value=firestore_client)

    checkout_mock = mocker.patch.object(billing_routes, "create_checkout_session")

    response = client.post(
        "/api/billing/checkout-session",
        json={"kind": "free_trial"},
        headers={"Authorization": "Bearer trial-token"},
    )

    assert response.status_code == 409
    assert "already been used" in response.text
    checkout_mock.assert_not_called()
