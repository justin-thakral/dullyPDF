"""Integration tests for Stripe webhook route wiring and security behavior."""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

import backend.main as main
import backend.api.routes.billing as billing_routes
import backend.firebaseDB.billing_database as billing_database
import backend.firebaseDB.user_database as user_database
from backend.test.integration.billing_webhook_test_support import (
    encode_event as _encode_event,
    install_fake_stripe_module as _install_fake_stripe_module,
    sign_stripe_payload as _sign_stripe_payload,
)
from backend.test.unit.firebase._fakes import FakeFirestoreClient


def _active_pro_billing_record(uid: str = "integration-user") -> user_database.UserBillingRecord:
    return user_database.UserBillingRecord(
        uid=uid,
        customer_id="cus_integration",
        subscription_id="sub_integration",
        subscription_status="active",
        subscription_price_id="price_pro_monthly",
    )

@pytest.fixture
def client() -> TestClient:
    return TestClient(main.app)


@pytest.fixture
def webhook_secret(monkeypatch: pytest.MonkeyPatch) -> str:
    _install_fake_stripe_module(monkeypatch)
    # Stripe event construction requires both values to be present.
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_integration")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_integration_test")
    return "whsec_integration_test"


@pytest.fixture(autouse=True)
def allow_webhook_retention_restores(mocker) -> None:
    mocker.patch.object(billing_routes, "restore_user_downgrade_managed_links", return_value=None)
    mocker.patch.object(billing_routes, "apply_user_downgrade_retention", return_value=None)
    mocker.patch.object(billing_routes, "get_user_billing_record", return_value=None)


def test_webhook_accepts_valid_signature_and_dispatches_refill(
    client: TestClient,
    webhook_secret: str,
    mocker,
) -> None:
    event = {
        "id": "evt_integration_refill_paid",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "client_reference_id": "integration-user",
                "metadata": {
                    "userId": "integration-user",
                    "checkoutKind": "refill_500",
                    "checkoutPriceId": "price_refill_500",
                    "refillCredits": "500",
                },
                "payment_status": "paid",
            }
        },
    }
    payload = _encode_event(event)
    signature = _sign_stripe_payload(payload, secret=webhook_secret)

    mocker.patch.object(billing_routes, "start_billing_event", return_value=True)
    mocker.patch.object(
        billing_routes,
        "get_user_profile",
        return_value=user_database.UserProfileRecord(
            uid="integration-user",
            email="integration@example.com",
            display_name="Integration User",
            role=user_database.ROLE_PRO,
            openai_credits_remaining=500,
        ),
    )
    mocker.patch.object(
        billing_routes,
        "get_user_billing_record",
        return_value=_active_pro_billing_record(),
    )
    mocker.patch.object(billing_routes, "resolve_refill_credit_pack_size_for_price", return_value=500)
    refill_mock = mocker.patch.object(billing_routes, "add_refill_openai_credits", return_value=500)
    complete_mock = mocker.patch.object(billing_routes, "complete_billing_event", return_value=None)
    clear_mock = mocker.patch.object(billing_routes, "clear_billing_event", return_value=None)

    response = client.post(
        "/api/billing/webhook",
        content=payload,
        headers={"Stripe-Signature": signature},
    )

    assert response.status_code == 200
    assert response.json() == {"received": True}
    refill_mock.assert_called_once_with(
        "integration-user",
        credits=500,
        stripe_event_id="evt_integration_refill_paid",
    )
    complete_mock.assert_called_once_with("evt_integration_refill_paid")
    clear_mock.assert_not_called()


def test_webhook_rejects_tampered_signature(
    client: TestClient,
    webhook_secret: str,
    mocker,
) -> None:
    event = {
        "id": "evt_integration_bad_sig",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "metadata": {
                    "checkoutKind": "refill_500",
                    "userId": "integration-user",
                    "checkoutPriceId": "price_refill_500",
                    "refillCredits": "500",
                }
            }
        },
    }
    payload = _encode_event(event)
    signature = _sign_stripe_payload(payload, secret=f"{webhook_secret}_wrong")
    start_mock = mocker.patch.object(billing_routes, "start_billing_event")

    response = client.post(
        "/api/billing/webhook",
        content=payload,
        headers={"Stripe-Signature": signature},
    )

    assert response.status_code == 400
    start_mock.assert_not_called()


def test_webhook_rejects_expired_signature_timestamp(
    client: TestClient,
    webhook_secret: str,
    mocker,
) -> None:
    event = {
        "id": "evt_integration_old_timestamp",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "metadata": {
                    "checkoutKind": "refill_500",
                    "userId": "integration-user",
                    "checkoutPriceId": "price_refill_500",
                    "refillCredits": "500",
                }
            }
        },
    }
    payload = _encode_event(event)
    signature = _sign_stripe_payload(payload, secret=webhook_secret, timestamp=int(time.time()) - 1000)
    start_mock = mocker.patch.object(billing_routes, "start_billing_event")

    response = client.post(
        "/api/billing/webhook",
        content=payload,
        headers={"Stripe-Signature": signature},
    )

    assert response.status_code == 400
    start_mock.assert_not_called()


def test_webhook_duplicate_event_short_circuits_with_valid_signature(
    client: TestClient,
    webhook_secret: str,
    mocker,
) -> None:
    event = {
        "id": "evt_integration_duplicate",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "metadata": {
                    "checkoutKind": "refill_500",
                    "userId": "integration-user",
                    "checkoutPriceId": "price_refill_500",
                    "refillCredits": "500",
                }
            }
        },
    }
    payload = _encode_event(event)
    signature = _sign_stripe_payload(payload, secret=webhook_secret)

    start_mock = mocker.patch.object(billing_routes, "start_billing_event", return_value=False)
    refill_mock = mocker.patch.object(billing_routes, "add_refill_openai_credits")

    response = client.post(
        "/api/billing/webhook",
        content=payload,
        headers={"Stripe-Signature": signature},
    )

    assert response.status_code == 200
    assert response.json() == {"received": True, "duplicate": True}
    start_mock.assert_called_once_with("evt_integration_duplicate", "checkout.session.completed")
    refill_mock.assert_not_called()


def test_webhook_returns_503_when_event_lock_is_currently_processing(
    client: TestClient,
    webhook_secret: str,
    mocker,
) -> None:
    fake_client = FakeFirestoreClient()
    fake_client.collection(billing_database.BILLING_EVENTS_COLLECTION).document("evt_integration_locked").seed(
        {
            "event_id": "evt_integration_locked",
            "event_type": "checkout.session.completed",
            "status": billing_database.BILLING_EVENT_STATUS_PROCESSING,
            "created_at": "ts-created",
            "updated_at": "2999-01-01T00:00:00+00:00",
            "attempts": 1,
        }
    )
    mocker.patch.object(billing_database, "get_firestore_client", return_value=fake_client)
    mocker.patch.object(
        billing_database.firebase_firestore,
        "transactional",
        side_effect=lambda fn: fn,
    )

    event = {
        "id": "evt_integration_locked",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "metadata": {
                    "checkoutKind": "refill_500",
                    "userId": "integration-user",
                    "checkoutPriceId": "price_refill_500",
                    "refillCredits": "500",
                }
            }
        },
    }
    payload = _encode_event(event)
    signature = _sign_stripe_payload(payload, secret=webhook_secret)

    response = client.post(
        "/api/billing/webhook",
        content=payload,
        headers={"Stripe-Signature": signature},
    )

    assert response.status_code == 503
    assert "still processing" in response.text


def test_webhook_pro_checkout_unpaid_does_not_activate_membership(
    client: TestClient,
    webhook_secret: str,
    mocker,
) -> None:
    event = {
        "id": "evt_integration_unpaid",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "client_reference_id": "integration-user",
                "metadata": {"userId": "integration-user", "checkoutKind": "pro_monthly"},
                "subscription": "sub_integration",
                "customer": "cus_integration",
                "payment_status": "unpaid",
            }
        },
    }
    payload = _encode_event(event)
    signature = _sign_stripe_payload(payload, secret=webhook_secret)

    mocker.patch.object(billing_routes, "start_billing_event", return_value=True)
    activate_mock = mocker.patch.object(
        billing_routes,
        "activate_pro_membership",
        return_value=True,
    )
    complete_mock = mocker.patch.object(billing_routes, "complete_billing_event", return_value=None)
    clear_mock = mocker.patch.object(billing_routes, "clear_billing_event", return_value=None)

    response = client.post(
        "/api/billing/webhook",
        content=payload,
        headers={"Stripe-Signature": signature},
    )

    assert response.status_code == 200
    assert response.json() == {"received": True}
    activate_mock.assert_not_called()
    complete_mock.assert_called_once_with("evt_integration_unpaid")
    clear_mock.assert_not_called()


def test_webhook_invoice_paid_dispatches_pro_activation(
    client: TestClient,
    webhook_secret: str,
    mocker,
) -> None:
    event = {
        "id": "evt_integration_invoice_paid",
        "type": "invoice.paid",
        "data": {
            "object": {
                "subscription": "sub_integration_invoice",
                "customer": "cus_integration",
                "lines": {"data": [{"price": {"id": "price_non_pro"}}, {"price": {"id": "price_pro_monthly"}}]},
            }
        },
    }
    payload = _encode_event(event)
    signature = _sign_stripe_payload(payload, secret=webhook_secret)

    mocker.patch.object(billing_routes, "start_billing_event", return_value=True)
    mocker.patch.object(
        billing_routes,
        "extract_price_ids_from_invoice",
        return_value=["price_non_pro", "price_pro_monthly"],
    )
    mocker.patch.object(
        billing_routes,
        "is_pro_price_id",
        side_effect=lambda value: value == "price_pro_monthly",
    )
    mocker.patch.object(
        billing_routes,
        "find_user_id_by_subscription_id",
        return_value="integration-user",
    )
    mocker.patch.object(
        billing_routes,
        "get_user_billing_record",
        return_value=_active_pro_billing_record(),
    )
    activate_mock = mocker.patch.object(
        billing_routes,
        "activate_pro_membership",
        return_value=True,
    )
    set_subscription_mock = mocker.patch.object(
        billing_routes,
        "set_user_billing_subscription",
        return_value=None,
    )
    complete_mock = mocker.patch.object(billing_routes, "complete_billing_event", return_value=None)
    clear_mock = mocker.patch.object(billing_routes, "clear_billing_event", return_value=None)

    response = client.post(
        "/api/billing/webhook",
        content=payload,
        headers={"Stripe-Signature": signature},
    )

    assert response.status_code == 200
    assert response.json() == {"received": True}
    activate_mock.assert_called_once()
    assert activate_mock.call_args.kwargs["stripe_event_id"] == "evt_integration_invoice_paid"
    assert activate_mock.call_args.kwargs["reset_monthly_credits"] is False
    set_subscription_mock.assert_called_once()
    assert set_subscription_mock.call_args.kwargs["subscription_id"] == "sub_integration_invoice"
    assert set_subscription_mock.call_args.kwargs["subscription_price_id"] == "price_pro_monthly"
    complete_mock.assert_called_once_with("evt_integration_invoice_paid")
    clear_mock.assert_not_called()


def test_webhook_invoice_paid_does_not_reset_consumed_pro_credits_after_checkout_activation(
    client: TestClient,
    webhook_secret: str,
    mocker,
) -> None:
    fake_client = FakeFirestoreClient()
    fake_client.collection(user_database.USERS_COLLECTION).document("integration-user").seed(
        {
            "email": "integration@example.com",
            "displayName": "Integration User",
            user_database.ROLE_FIELD: user_database.ROLE_BASE,
            user_database.OPENAI_CREDITS_FIELD: user_database.BASE_OPENAI_CREDITS,
            user_database.OPENAI_CREDITS_BASE_CYCLE_FIELD: "2026-03",
            "created_at": "2026-03-01T00:00:00+00:00",
            "updated_at": "2026-03-01T00:00:00+00:00",
        }
    )

    mocker.patch.object(user_database, "get_firestore_client", return_value=fake_client)
    mocker.patch.object(user_database.firebase_firestore, "transactional", side_effect=lambda fn: fn)
    mocker.patch.object(billing_routes, "start_billing_event", return_value=True)
    mocker.patch.object(billing_routes, "complete_billing_event", return_value=None)
    mocker.patch.object(billing_routes, "clear_billing_event", return_value=None)
    mocker.patch.object(
        billing_routes,
        "resolve_price_id_for_checkout_kind",
        return_value="price_pro_monthly",
    )
    mocker.patch.object(
        billing_routes,
        "is_pro_price_id",
        side_effect=lambda value: value == "price_pro_monthly",
    )
    mocker.patch.object(user_database, "_current_month_cycle_key", return_value="2026-03")

    checkout_event = {
        "id": "evt_integration_pro_checkout_paid",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_integration_pro_checkout",
                "client_reference_id": "integration-user",
                "metadata": {
                    "userId": "integration-user",
                    "checkoutKind": "pro_monthly",
                    "checkoutPriceId": "price_pro_monthly",
                },
                "subscription": "sub_integration_pro",
                "customer": "cus_integration",
                "payment_status": "paid",
            }
        },
    }
    invoice_event = {
        "id": "evt_integration_invoice_after_checkout",
        "type": "invoice.paid",
        "data": {
            "object": {
                "subscription": "sub_integration_pro",
                "customer": "cus_integration",
                "lines": {"data": [{"price": {"id": "price_pro_monthly"}}]},
            }
        },
    }

    checkout_response = client.post(
        "/api/billing/webhook",
        content=_encode_event(checkout_event),
        headers={"Stripe-Signature": _sign_stripe_payload(_encode_event(checkout_event), secret=webhook_secret)},
    )

    assert checkout_response.status_code == 200

    remaining_after_consume, allowed = user_database.consume_openai_credits(
        "integration-user",
        credits=137,
    )
    assert allowed is True
    assert remaining_after_consume == 363

    invoice_response = client.post(
        "/api/billing/webhook",
        content=_encode_event(invoice_event),
        headers={"Stripe-Signature": _sign_stripe_payload(_encode_event(invoice_event), secret=webhook_secret)},
    )

    assert invoice_response.status_code == 200

    stored_user = (
        fake_client.collection(user_database.USERS_COLLECTION)
        .document("integration-user")
        .get()
        .to_dict()
    )
    assert stored_user[user_database.ROLE_FIELD] == user_database.ROLE_PRO
    assert stored_user[user_database.OPENAI_CREDITS_MONTHLY_FIELD] == 363
    assert stored_user[user_database.OPENAI_CREDITS_MONTHLY_CYCLE_FIELD] == "2026-03"
    assert stored_user[user_database.STRIPE_SUBSCRIPTION_ID_FIELD] == "sub_integration_pro"


def test_webhook_invoice_paid_missing_user_returns_retryable(
    client: TestClient,
    webhook_secret: str,
    mocker,
) -> None:
    event = {
        "id": "evt_integration_invoice_missing_user",
        "type": "invoice.paid",
        "data": {
            "object": {
                "subscription": "sub_integration_missing_user",
                "customer": "cus_integration",
                "lines": {"data": [{"price": {"id": "price_pro_monthly"}}]},
            }
        },
    }
    payload = _encode_event(event)
    signature = _sign_stripe_payload(payload, secret=webhook_secret)

    mocker.patch.object(billing_routes, "start_billing_event", return_value=True)
    mocker.patch.object(
        billing_routes,
        "extract_price_ids_from_invoice",
        return_value=["price_pro_monthly"],
    )
    mocker.patch.object(
        billing_routes,
        "is_pro_price_id",
        side_effect=lambda value: value == "price_pro_monthly",
    )
    mocker.patch.object(
        billing_routes,
        "find_user_id_by_subscription_id",
        return_value=None,
    )
    activate_mock = mocker.patch.object(
        billing_routes,
        "activate_pro_membership",
        return_value=True,
    )
    set_subscription_mock = mocker.patch.object(
        billing_routes,
        "set_user_billing_subscription",
        return_value=None,
    )
    complete_mock = mocker.patch.object(billing_routes, "complete_billing_event", return_value=None)
    clear_mock = mocker.patch.object(billing_routes, "clear_billing_event", return_value=None)

    response = client.post(
        "/api/billing/webhook",
        content=payload,
        headers={"Stripe-Signature": signature},
    )

    assert response.status_code == 503
    assert "awaiting subscription linkage" in response.text
    activate_mock.assert_not_called()
    set_subscription_mock.assert_not_called()
    complete_mock.assert_not_called()
    clear_mock.assert_called_once_with("evt_integration_invoice_missing_user")


def test_webhook_subscription_deleted_updates_billing_state(
    client: TestClient,
    webhook_secret: str,
    mocker,
) -> None:
    event = {
        "id": "evt_integration_deleted",
        "type": "customer.subscription.deleted",
        "data": {
            "object": {
                "id": "sub_integration_deleted",
                "customer": "cus_integration",
                "status": "canceled",
                "metadata": {"userId": "integration-user"},
                "items": {"data": [{"price": {"id": "price_pro_monthly"}}]},
            }
        },
    }
    payload = _encode_event(event)
    signature = _sign_stripe_payload(payload, secret=webhook_secret)

    mocker.patch.object(billing_routes, "start_billing_event", return_value=True)
    mocker.patch.object(
        billing_routes,
        "is_pro_price_id",
        side_effect=lambda value: value == "price_pro_monthly",
    )
    set_subscription_mock = mocker.patch.object(billing_routes, "set_user_billing_subscription", return_value=None)
    activate_mock = mocker.patch.object(billing_routes, "activate_pro_membership", return_value=True)
    downgrade_mock = mocker.patch.object(billing_routes, "downgrade_to_base_membership", return_value=None)
    complete_mock = mocker.patch.object(billing_routes, "complete_billing_event", return_value=None)
    clear_mock = mocker.patch.object(billing_routes, "clear_billing_event", return_value=None)

    response = client.post(
        "/api/billing/webhook",
        content=payload,
        headers={"Stripe-Signature": signature},
    )

    assert response.status_code == 200
    assert response.json() == {"received": True}
    set_subscription_mock.assert_called_once()
    activate_mock.assert_not_called()
    downgrade_mock.assert_called_once_with("integration-user")
    complete_mock.assert_called_once_with("evt_integration_deleted")
    clear_mock.assert_not_called()

def test_webhook_subscription_updated_ignores_non_pro_price_events(
    client: TestClient,
    webhook_secret: str,
    mocker,
) -> None:
    event = {
        "id": "evt_integration_non_pro_lifecycle",
        "type": "customer.subscription.updated",
        "data": {
            "object": {
                "id": "sub_integration_non_pro",
                "customer": "cus_integration",
                "status": "active",
                "metadata": {"userId": "integration-user"},
                "items": {"data": [{"price": {"id": "price_other_product"}}]},
            }
        },
    }
    payload = _encode_event(event)
    signature = _sign_stripe_payload(payload, secret=webhook_secret)

    mocker.patch.object(billing_routes, "start_billing_event", return_value=True)
    mocker.patch.object(billing_routes, "is_pro_price_id", return_value=False)
    mocker.patch.object(
        billing_routes,
        "get_user_billing_record",
        return_value=_active_pro_billing_record(),
    )
    set_subscription_mock = mocker.patch.object(billing_routes, "set_user_billing_subscription", return_value=None)
    activate_mock = mocker.patch.object(billing_routes, "activate_pro_membership", return_value=True)
    downgrade_mock = mocker.patch.object(billing_routes, "downgrade_to_base_membership", return_value=None)
    complete_mock = mocker.patch.object(billing_routes, "complete_billing_event", return_value=None)
    clear_mock = mocker.patch.object(billing_routes, "clear_billing_event", return_value=None)

    response = client.post(
        "/api/billing/webhook",
        content=payload,
        headers={"Stripe-Signature": signature},
    )

    assert response.status_code == 200
    assert response.json() == {"received": True}
    set_subscription_mock.assert_not_called()
    activate_mock.assert_not_called()
    downgrade_mock.assert_not_called()
    complete_mock.assert_called_once_with("evt_integration_non_pro_lifecycle")
    clear_mock.assert_not_called()


def test_webhook_persists_and_deduplicates_billing_events(
    client: TestClient,
    webhook_secret: str,
    mocker,
) -> None:
    fake_client = FakeFirestoreClient()
    mocker.patch.object(billing_database, "get_firestore_client", return_value=fake_client)
    mocker.patch.object(
        billing_database.firebase_firestore,
        "transactional",
        side_effect=lambda fn: fn,
    )
    mocker.patch.object(
        billing_database,
        "now_iso",
        side_effect=["created-ts", "updated-ts", "processed-ts"],
    )
    mocker.patch.object(billing_database, "log_expires_at", return_value=None)
    mocker.patch.object(
        billing_routes,
        "get_user_profile",
        return_value=user_database.UserProfileRecord(
            uid="integration-user",
            email="integration@example.com",
            display_name="Integration User",
            role=user_database.ROLE_PRO,
            openai_credits_remaining=500,
        ),
    )
    mocker.patch.object(
        billing_routes,
        "get_user_billing_record",
        return_value=_active_pro_billing_record(),
    )
    mocker.patch.object(billing_routes, "resolve_refill_credit_pack_size_for_price", return_value=500)
    refill_mock = mocker.patch.object(billing_routes, "add_refill_openai_credits", return_value=500)

    event = {
        "id": "evt_integration_store_1",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "client_reference_id": "integration-user",
                "metadata": {
                    "userId": "integration-user",
                    "checkoutKind": "refill_500",
                    "checkoutPriceId": "price_refill_500",
                    "refillCredits": "500",
                },
                "payment_status": "paid",
            }
        },
    }
    payload = _encode_event(event)
    signature = _sign_stripe_payload(payload, secret=webhook_secret)

    first = client.post(
        "/api/billing/webhook",
        content=payload,
        headers={"Stripe-Signature": signature},
    )

    assert first.status_code == 200
    assert first.json() == {"received": True}
    refill_mock.assert_called_once_with(
        "integration-user",
        credits=500,
        stripe_event_id="evt_integration_store_1",
    )

    stored = (
        fake_client.collection(billing_database.BILLING_EVENTS_COLLECTION)
        .document("evt_integration_store_1")
        .get()
        .to_dict()
    )
    assert stored["event_id"] == "evt_integration_store_1"
    assert stored["event_type"] == "checkout.session.completed"
    assert stored["status"] == "processed"
    assert stored["created_at"] == "created-ts"
    assert stored["updated_at"] == "processed-ts"

    duplicate = client.post(
        "/api/billing/webhook",
        content=payload,
        headers={"Stripe-Signature": signature},
    )
    assert duplicate.status_code == 200
    assert duplicate.json() == {"received": True, "duplicate": True}
    refill_mock.assert_called_once()


def test_webhook_retry_after_partial_failure_does_not_double_refill_credits(
    client: TestClient,
    webhook_secret: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_client = FakeFirestoreClient()
    fake_client.collection(user_database.USERS_COLLECTION).document("integration-user").seed(
        {
            user_database.ROLE_FIELD: user_database.ROLE_PRO,
            user_database.OPENAI_CREDITS_REFILL_FIELD: 0,
        }
    )

    monkeypatch.setattr(billing_database, "get_firestore_client", lambda: fake_client)
    monkeypatch.setattr(user_database, "get_firestore_client", lambda: fake_client)
    monkeypatch.setattr(
        billing_database.firebase_firestore,
        "transactional",
        lambda fn: fn,
    )
    monkeypatch.setattr(
        user_database.firebase_firestore,
        "transactional",
        lambda fn: fn,
    )
    monkeypatch.setattr(
        billing_routes,
        "get_user_billing_record",
        lambda *_args, **_kwargs: _active_pro_billing_record(),
    )

    complete_calls = {"count": 0}

    def _flaky_complete(event_id: str) -> None:
        complete_calls["count"] += 1
        if complete_calls["count"] == 1:
            raise RuntimeError("simulated completion failure")
        billing_database.complete_billing_event(event_id)

    monkeypatch.setattr(billing_routes, "complete_billing_event", _flaky_complete)
    monkeypatch.setattr(billing_routes, "resolve_refill_credit_pack_size_for_price", lambda *_args, **_kwargs: 500)

    event = {
        "id": "evt_integration_retry_once",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "client_reference_id": "integration-user",
                "metadata": {
                    "userId": "integration-user",
                    "checkoutKind": "refill_500",
                    "checkoutPriceId": "price_refill_500",
                    "refillCredits": "500",
                },
                "payment_status": "paid",
            }
        },
    }
    payload = _encode_event(event)
    signature = _sign_stripe_payload(payload, secret=webhook_secret)

    first = client.post(
        "/api/billing/webhook",
        content=payload,
        headers={"Stripe-Signature": signature},
    )
    second = client.post(
        "/api/billing/webhook",
        content=payload,
        headers={"Stripe-Signature": signature},
    )

    assert first.status_code == 500
    assert second.status_code == 200
    assert second.json() == {"received": True}

    user_doc = fake_client.collection(user_database.USERS_COLLECTION).document("integration-user").get().to_dict()
    assert user_doc[user_database.OPENAI_CREDITS_REFILL_FIELD] == 500

    event_doc = (
        fake_client.collection(billing_database.BILLING_EVENTS_COLLECTION)
        .document("evt_integration_retry_once")
        .get()
        .to_dict()
    )
    assert event_doc["status"] == billing_database.BILLING_EVENT_STATUS_PROCESSED
    assert event_doc["attempts"] == 2
