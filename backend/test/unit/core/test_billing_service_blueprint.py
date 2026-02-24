"""Unit tests for billing service helpers and Stripe webhook validation."""

from __future__ import annotations

import hashlib
import hmac
import json
import time

import pytest

import backend.services.billing_service as billing_service


def _sign_stripe_payload(payload: bytes, *, secret: str, timestamp: int | None = None) -> str:
    signed_timestamp = int(timestamp or time.time())
    signed_payload = f"{signed_timestamp}.".encode("utf-8") + payload
    digest = hmac.new(secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
    return f"t={signed_timestamp},v1={digest}"


def _install_fake_stripe_module(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeWebhook:
        @staticmethod
        def construct_event(payload: bytes, signature: str, secret: str):
            try:
                parts = dict(item.split("=", 1) for item in signature.split(","))
                timestamp = int(parts["t"])
                provided_digest = parts["v1"]
            except Exception as exc:  # pragma: no cover - defensive parsing path
                raise ValueError("Malformed Stripe-Signature header.") from exc

            signed_payload = f"{timestamp}.".encode("utf-8") + payload
            expected_digest = hmac.new(secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
            if not hmac.compare_digest(expected_digest, provided_digest):
                raise ValueError("Webhook signature verification failed.")
            if abs(int(time.time()) - timestamp) > 300:
                raise ValueError("Webhook signature timestamp is outside the tolerance zone.")
            return json.loads(payload.decode("utf-8"))

    class _FakeStripe:
        api_key = None
        Webhook = _FakeWebhook

    monkeypatch.setattr(billing_service, "_load_stripe_module", lambda: _FakeStripe)


def test_resolve_refill_credit_pack_size_defaults_for_missing_invalid_and_non_positive_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("STRIPE_REFILL_CREDITS", raising=False)
    assert billing_service.resolve_refill_credit_pack_size() == 500

    monkeypatch.setenv("STRIPE_REFILL_CREDITS", "not-an-int")
    assert billing_service.resolve_refill_credit_pack_size() == 500

    monkeypatch.setenv("STRIPE_REFILL_CREDITS", "0")
    assert billing_service.resolve_refill_credit_pack_size() == 500

    monkeypatch.setenv("STRIPE_REFILL_CREDITS", "-10")
    assert billing_service.resolve_refill_credit_pack_size() == 500

    monkeypatch.setenv("STRIPE_REFILL_CREDITS", "750")
    assert billing_service.resolve_refill_credit_pack_size() == 750


def test_resolve_refill_credit_pack_size_for_price_uses_price_mapping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("STRIPE_PRICE_REFILL_500", "price_refill_500")
    monkeypatch.setenv("STRIPE_REFILL_CREDITS", "700")

    assert billing_service.resolve_refill_credit_pack_size_for_price("price_refill_500") == 700
    assert billing_service.resolve_refill_credit_pack_size_for_price("price_other") is None
    assert billing_service.resolve_refill_credit_pack_size_for_price("") is None


def test_is_subscription_active_handles_expected_statuses() -> None:
    assert billing_service.is_subscription_active("active") is True
    assert billing_service.is_subscription_active("trialing") is True
    assert billing_service.is_subscription_active("past_due") is True
    assert billing_service.is_subscription_active("canceled") is False
    assert billing_service.is_subscription_active("") is False


def test_billing_enabled_requires_secret_key_and_webhook_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    monkeypatch.delenv("STRIPE_WEBHOOK_SECRET", raising=False)
    assert billing_service.billing_enabled() is False

    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_only")
    monkeypatch.delenv("STRIPE_WEBHOOK_SECRET", raising=False)
    assert billing_service.billing_enabled() is False

    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_only")
    assert billing_service.billing_enabled() is False

    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_billing")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_billing")
    assert billing_service.billing_enabled() is True


def test_resolve_webhook_health_returns_healthy_when_enabled_endpoint_has_required_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_health")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_health")
    monkeypatch.setenv("STRIPE_WEBHOOK_ENDPOINT_URL", "https://billing.example.com/api/billing/webhook")

    class _FakeWebhookEndpoint:
        @staticmethod
        def list(**kwargs):
            assert kwargs == {"limit": 50}
            return {
                "data": [
                    {
                        "id": "we_123",
                        "url": "https://billing.example.com/api/billing/webhook",
                        "status": "enabled",
                        "enabled_events": ["checkout.session.completed", "invoice.paid", "customer.subscription.updated", "customer.subscription.deleted"],
                    }
                ]
            }

    class _FakeStripe:
        api_key = None
        WebhookEndpoint = _FakeWebhookEndpoint

    monkeypatch.setattr(billing_service, "_load_stripe_module", lambda: _FakeStripe)

    payload = billing_service.resolve_webhook_health(force_refresh=True)

    assert payload["healthy"] is True
    assert payload["endpointId"] == "we_123"
    assert payload["endpointUrl"] == "https://billing.example.com/api/billing/webhook"
    assert payload["expectedEndpointUrl"] == "https://billing.example.com/api/billing/webhook"


def test_resolve_webhook_health_returns_unhealthy_when_enabled_endpoint_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_health")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_health")

    class _FakeWebhookEndpoint:
        @staticmethod
        def list(**kwargs):
            assert kwargs == {"limit": 50}
            return {"data": []}

    class _FakeStripe:
        api_key = None
        WebhookEndpoint = _FakeWebhookEndpoint

    monkeypatch.setattr(billing_service, "_load_stripe_module", lambda: _FakeStripe)

    payload = billing_service.resolve_webhook_health(force_refresh=True)

    assert payload["healthy"] is False
    assert "No enabled Stripe webhook endpoint" in payload["reason"]


def test_resolve_webhook_health_returns_unhealthy_when_expected_endpoint_url_missing_with_enforcement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_health")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_health")
    monkeypatch.setenv("STRIPE_ENFORCE_WEBHOOK_HEALTH", "true")
    monkeypatch.delenv("STRIPE_WEBHOOK_ENDPOINT_URL", raising=False)

    class _FakeWebhookEndpoint:
        @staticmethod
        def list(**kwargs):
            assert kwargs == {"limit": 50}
            return {
                "data": [
                    {
                        "id": "we_any",
                        "url": "https://other.example.com/api/billing/webhook",
                        "status": "enabled",
                        "enabled_events": ["*"],
                    }
                ]
            }

    class _FakeStripe:
        api_key = None
        WebhookEndpoint = _FakeWebhookEndpoint

    monkeypatch.setattr(billing_service, "_load_stripe_module", lambda: _FakeStripe)

    payload = billing_service.resolve_webhook_health(force_refresh=True)

    assert payload["healthy"] is False
    assert "Missing STRIPE_WEBHOOK_ENDPOINT_URL" in payload["reason"]
    assert payload["enforcedForCheckout"] is True


def test_resolve_webhook_health_returns_unhealthy_when_only_different_endpoint_matches_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_health")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_health")
    monkeypatch.setenv("STRIPE_WEBHOOK_ENDPOINT_URL", "https://billing.example.com/api/billing/webhook")

    class _FakeWebhookEndpoint:
        @staticmethod
        def list(**kwargs):
            assert kwargs == {"limit": 50}
            return {
                "data": [
                    {
                        "id": "we_other",
                        "url": "https://other.example.com/api/billing/webhook",
                        "status": "enabled",
                        "enabled_events": ["*"],
                    }
                ]
            }

    class _FakeStripe:
        api_key = None
        WebhookEndpoint = _FakeWebhookEndpoint

    monkeypatch.setattr(billing_service, "_load_stripe_module", lambda: _FakeStripe)

    payload = billing_service.resolve_webhook_health(force_refresh=True)

    assert payload["healthy"] is False
    assert "Configured Stripe webhook endpoint URL was not found" in payload["reason"]
    assert payload["expectedEndpointUrl"] == "https://billing.example.com/api/billing/webhook"


def test_resolve_webhook_health_allows_fallback_endpoint_matching_when_enforcement_disabled_and_expected_url_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_health")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_health")
    monkeypatch.setenv("STRIPE_ENFORCE_WEBHOOK_HEALTH", "false")
    monkeypatch.delenv("STRIPE_WEBHOOK_ENDPOINT_URL", raising=False)

    class _FakeWebhookEndpoint:
        @staticmethod
        def list(**kwargs):
            assert kwargs == {"limit": 50}
            return {
                "data": [
                    {
                        "id": "we_any",
                        "url": "https://other.example.com/api/billing/webhook",
                        "status": "enabled",
                        "enabled_events": ["checkout.session.completed", "invoice.paid", "customer.subscription.updated", "customer.subscription.deleted"],
                    }
                ]
            }

    class _FakeStripe:
        api_key = None
        WebhookEndpoint = _FakeWebhookEndpoint

    monkeypatch.setattr(billing_service, "_load_stripe_module", lambda: _FakeStripe)

    payload = billing_service.resolve_webhook_health(force_refresh=True)

    assert payload["healthy"] is True
    assert payload["endpointId"] == "we_any"
    assert payload["expectedEndpointUrl"] is None


def test_list_recent_checkout_completion_events_paginates_until_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_reconcile_events")
    calls: list[dict[str, object]] = []

    class _FakeEvent:
        @staticmethod
        def list(**kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                assert kwargs["type"] == "checkout.session.completed"
                assert kwargs["limit"] == 3
                return {
                    "has_more": True,
                    "data": [
                        {"id": "evt_2", "type": "checkout.session.completed"},
                        {"id": "evt_1", "type": "checkout.session.completed"},
                    ],
                }
            assert kwargs["starting_after"] == "evt_1"
            assert kwargs["limit"] == 1
            return {
                "has_more": False,
                "data": [
                    {"id": "evt_0", "type": "checkout.session.completed"},
                ],
            }

    class _FakeStripe:
        api_key = None
        Event = _FakeEvent

    monkeypatch.setattr(billing_service, "_load_stripe_module", lambda: _FakeStripe)

    events = billing_service.list_recent_checkout_completion_events(limit=3)

    assert [event["id"] for event in events] == ["evt_2", "evt_1", "evt_0"]
    assert len(calls) == 2


def test_extract_price_ids_from_invoice_ignores_malformed_entries() -> None:
    invoice = {
        "lines": {
            "data": [
                {"price": {"id": "price_1"}},
                {"price": {"id": ""}},
                {"price": "price_2"},
                {"not_price": {"id": "ignored"}},
                {"plan": {"id": "price_3"}},
                {"plan": "price_4"},
                "bad-entry",
                {"price": {"id": "price_5"}},
            ]
        }
    }

    assert billing_service.extract_price_ids_from_invoice(invoice) == [
        "price_1",
        "price_2",
        "price_3",
        "price_4",
        "price_5",
    ]


def test_first_nonempty_returns_first_trimmed_value() -> None:
    assert billing_service.first_nonempty(["", None, "   ", " abc ", "def"]) == "abc"
    assert billing_service.first_nonempty(["", None, "  "]) is None


def test_resolve_pro_price_ids_filters_empty_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STRIPE_PRICE_PRO_MONTHLY", "price_monthly")
    monkeypatch.setenv("STRIPE_PRICE_PRO_YEARLY", "")

    assert billing_service.resolve_pro_price_ids() == {"price_monthly"}
    assert billing_service.is_pro_price_id("price_monthly") is True
    assert billing_service.is_pro_price_id("price_yearly") is False


def test_resolve_price_id_for_checkout_kind_returns_none_when_not_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("STRIPE_PRICE_PRO_MONTHLY", raising=False)
    monkeypatch.delenv("STRIPE_PRICE_PRO_YEARLY", raising=False)
    monkeypatch.delenv("STRIPE_PRICE_REFILL_500", raising=False)

    assert billing_service.resolve_price_id_for_checkout_kind("pro_monthly") is None
    assert billing_service.resolve_price_id_for_checkout_kind("pro_yearly") is None
    assert billing_service.resolve_price_id_for_checkout_kind("refill_500") is None
    assert billing_service.resolve_price_id_for_checkout_kind("nope") is None


def test_resolve_checkout_catalog_includes_stripe_price_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_catalog")
    monkeypatch.setenv("STRIPE_PRICE_PRO_MONTHLY", "price_monthly_123")
    monkeypatch.setenv("STRIPE_PRICE_PRO_YEARLY", "price_yearly_123")
    monkeypatch.setenv("STRIPE_PRICE_REFILL_500", "price_refill_123")
    monkeypatch.setenv("STRIPE_REFILL_CREDITS", "500")

    class _FakePrice:
        @staticmethod
        def retrieve(price_id: str):
            if price_id == "price_monthly_123":
                return {
                    "id": price_id,
                    "currency": "usd",
                    "unit_amount": 1000,
                    "recurring": {"interval": "month"},
                }
            if price_id == "price_yearly_123":
                return {
                    "id": price_id,
                    "currency": "usd",
                    "unit_amount": 7500,
                    "recurring": {"interval": "year"},
                }
            return {
                "id": price_id,
                "currency": "usd",
                "unit_amount": 900,
            }

    class _FakeStripe:
        api_key = None
        Price = _FakePrice

    monkeypatch.setattr(billing_service, "_load_stripe_module", lambda: _FakeStripe)

    catalog = billing_service.resolve_checkout_catalog(force_refresh=True)

    assert catalog["pro_monthly"]["unitAmount"] == 1000
    assert catalog["pro_monthly"]["currency"] == "usd"
    assert catalog["pro_monthly"]["interval"] == "month"
    assert catalog["pro_yearly"]["unitAmount"] == 7500
    assert catalog["pro_yearly"]["interval"] == "year"
    assert catalog["refill_500"]["refillCredits"] == 500


def test_create_checkout_session_builds_subscription_payload_with_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_checkout")
    monkeypatch.setenv("STRIPE_PRICE_PRO_MONTHLY", "price_monthly_123")
    monkeypatch.setenv("STRIPE_CHECKOUT_SUCCESS_URL", "https://app.example.com/success")
    monkeypatch.setenv("STRIPE_CHECKOUT_CANCEL_URL", "https://app.example.com/cancel")
    captured: dict[str, object] = {}
    list_captured: dict[str, object] = {}

    class _FakeCheckoutSession:
        @staticmethod
        def list(**kwargs):
            list_captured.update(kwargs)
            return {"data": []}

        @staticmethod
        def create(**kwargs):
            captured.update(kwargs)

            class _Session:
                id = "cs_test_123"
                url = "https://checkout.stripe.test/session"

            return _Session()

    class _FakeCustomer:
        @staticmethod
        def list(email: str, limit: int):
            assert email == "user@example.com"
            assert limit == 25
            return {
                "data": [
                    {
                        "id": "cus_existing_123",
                        "email": "user@example.com",
                        "metadata": {"userId": "user_123"},
                    }
                ]
            }

        @staticmethod
        def create(**kwargs):
            raise AssertionError("Customer.create should not be called when an existing customer already matches.")

    class _FakeCheckout:
        Session = _FakeCheckoutSession

    class _FakeStripe:
        api_key = None
        checkout = _FakeCheckout
        Customer = _FakeCustomer

    monkeypatch.setattr(billing_service, "_load_stripe_module", lambda: _FakeStripe)

    session = billing_service.create_checkout_session(
        user_id="user_123",
        user_email="user@example.com",
        checkout_kind="pro_monthly",
    )

    assert session == {
        "sessionId": "cs_test_123",
        "url": "https://checkout.stripe.test/session",
        "customerId": "cus_existing_123",
    }
    assert _FakeStripe.api_key == "sk_test_checkout"
    assert list_captured == {
        "customer": "cus_existing_123",
        "status": "open",
        "limit": 20,
    }
    assert captured["mode"] == "subscription"
    assert captured["line_items"] == [{"price": "price_monthly_123", "quantity": 1}]
    assert captured["success_url"] == "https://app.example.com/success?billing=success"
    assert captured["cancel_url"] == "https://app.example.com/cancel?billing=cancel"
    assert captured["client_reference_id"] == "user_123"
    assert captured["customer"] == "cus_existing_123"
    assert captured["metadata"] == {
        "userId": "user_123",
        "checkoutKind": "pro_monthly",
        "checkoutPriceId": "price_monthly_123",
    }
    assert captured["subscription_data"] == {
        "metadata": {
            "userId": "user_123",
            "checkoutKind": "pro_monthly",
            "checkoutPriceId": "price_monthly_123",
        }
    }
    assert isinstance(captured.get("idempotency_key"), str) and bool(captured.get("idempotency_key"))
    assert "customer_email" not in captured


def test_create_checkout_session_builds_refill_payment_payload_without_subscription_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_checkout")
    monkeypatch.setenv("STRIPE_PRICE_REFILL_500", "price_refill_123")
    monkeypatch.setenv("STRIPE_REFILL_CREDITS", "650")
    monkeypatch.delenv("STRIPE_CHECKOUT_SUCCESS_URL", raising=False)
    monkeypatch.delenv("STRIPE_CHECKOUT_CANCEL_URL", raising=False)
    captured: dict[str, object] = {}

    class _FakeCheckoutSession:
        @staticmethod
        def list(**kwargs):
            assert kwargs == {"customer": "cus_refill_123", "status": "open", "limit": 20}
            return {"data": []}

        @staticmethod
        def create(**kwargs):
            captured.update(kwargs)

            class _Session:
                id = "cs_test_refill"
                url = "https://checkout.stripe.test/refill"

            return _Session()

    class _FakeCheckout:
        Session = _FakeCheckoutSession

    class _FakeCustomer:
        @staticmethod
        def list(email: str, limit: int):
            # Refill checkout now resolves a stable customer so open sessions can
            # be reused and duplicate API retries do not create extra sessions.
            assert email == ""
            assert limit == 25
            return {"data": []}

        @staticmethod
        def create(**kwargs):
            assert kwargs["metadata"] == {"userId": "user_123"}
            assert kwargs["idempotency_key"]

            class _Customer:
                id = "cus_refill_123"

            return _Customer()

    class _FakeStripe:
        api_key = None
        checkout = _FakeCheckout
        Customer = _FakeCustomer

    monkeypatch.setattr(billing_service, "_load_stripe_module", lambda: _FakeStripe)

    session = billing_service.create_checkout_session(
        user_id="user_123",
        user_email=None,
        checkout_kind="refill_500",
    )

    assert session == {
        "sessionId": "cs_test_refill",
        "url": "https://checkout.stripe.test/refill",
        "customerId": "cus_refill_123",
    }
    assert captured["mode"] == "payment"
    assert captured["line_items"] == [{"price": "price_refill_123", "quantity": 1}]
    assert captured["success_url"] == "http://localhost:5173/?billing=success"
    assert captured["cancel_url"] == "http://localhost:5173/?billing=cancel"
    assert captured["metadata"] == {
        "userId": "user_123",
        "checkoutKind": "refill_500",
        "checkoutPriceId": "price_refill_123",
        "refillCredits": "650",
    }
    assert captured["customer"] == "cus_refill_123"
    assert "subscription_data" not in captured
    assert "customer_email" not in captured


def test_create_checkout_session_preserves_existing_billing_query_params(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_checkout")
    monkeypatch.setenv("STRIPE_PRICE_PRO_MONTHLY", "price_monthly_123")
    monkeypatch.setenv("STRIPE_CHECKOUT_SUCCESS_URL", "https://app.example.com/success?billing=done")
    monkeypatch.setenv("STRIPE_CHECKOUT_CANCEL_URL", "https://app.example.com/cancel?foo=1&billing=cancel")
    captured: dict[str, object] = {}

    class _FakeCheckoutSession:
        @staticmethod
        def list(**kwargs):
            assert kwargs == {"customer": "cus_123", "status": "open", "limit": 20}
            return {"data": []}

        @staticmethod
        def create(**kwargs):
            captured.update(kwargs)

            class _Session:
                id = "cs_test_123"
                url = "https://checkout.stripe.test/session"

            return _Session()

    class _FakeCustomer:
        @staticmethod
        def list(email: str, limit: int):
            assert email == "user@example.com"
            assert limit == 25
            return {"data": [{"id": "cus_123", "metadata": {"userId": "user_123"}}]}

    class _FakeCheckout:
        Session = _FakeCheckoutSession

    class _FakeStripe:
        api_key = None
        checkout = _FakeCheckout
        Customer = _FakeCustomer

    monkeypatch.setattr(billing_service, "_load_stripe_module", lambda: _FakeStripe)

    billing_service.create_checkout_session(
        user_id="user_123",
        user_email="user@example.com",
        checkout_kind="pro_monthly",
    )

    assert captured["success_url"] == "https://app.example.com/success?billing=done"
    assert captured["cancel_url"] == "https://app.example.com/cancel?foo=1&billing=cancel"


def test_create_checkout_session_reuses_existing_open_pro_checkout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_checkout")
    monkeypatch.setenv("STRIPE_PRICE_PRO_MONTHLY", "price_monthly_123")

    create_calls: list[dict[str, object]] = []

    class _FakeCheckoutSession:
        @staticmethod
        def list(**kwargs):
            assert kwargs == {"customer": "cus_123", "status": "open", "limit": 20}
            return {
                "data": [
                    {
                        "id": "cs_open_existing",
                        "url": "https://checkout.stripe.test/open-existing",
                        "client_reference_id": "user_123",
                        "metadata": {
                            "userId": "user_123",
                            "checkoutKind": "pro_monthly",
                        },
                    }
                ]
            }

        @staticmethod
        def create(**kwargs):
            create_calls.append(kwargs)
            raise AssertionError("Session.create should not run when an open Pro checkout already exists.")

    class _FakeCustomer:
        @staticmethod
        def list(email: str, limit: int):
            assert email == "user@example.com"
            assert limit == 25
            return {"data": [{"id": "cus_123", "metadata": {"userId": "user_123"}}]}

    class _FakeCheckout:
        Session = _FakeCheckoutSession

    class _FakeStripe:
        api_key = None
        checkout = _FakeCheckout
        Customer = _FakeCustomer

    monkeypatch.setattr(billing_service, "_load_stripe_module", lambda: _FakeStripe)

    session = billing_service.create_checkout_session(
        user_id="user_123",
        user_email="user@example.com",
        checkout_kind="pro_monthly",
    )

    assert session == {
        "sessionId": "cs_open_existing",
        "url": "https://checkout.stripe.test/open-existing",
        "customerId": "cus_123",
    }
    assert create_calls == []


def test_create_checkout_session_uses_distinct_idempotency_keys_per_pro_plan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_checkout")
    monkeypatch.setenv("STRIPE_PRICE_PRO_MONTHLY", "price_monthly_123")
    monkeypatch.setenv("STRIPE_PRICE_PRO_YEARLY", "price_yearly_123")
    monkeypatch.setenv("STRIPE_CHECKOUT_IDEMPOTENCY_WINDOW_SECONDS", "300")
    monkeypatch.setattr(billing_service.time, "time", lambda: 1700000000.0)

    create_calls: list[dict[str, object]] = []

    class _FakeCheckoutSession:
        @staticmethod
        def list(**kwargs):
            assert kwargs == {"customer": "cus_123", "status": "open", "limit": 20}
            return {"data": []}

        @staticmethod
        def create(**kwargs):
            create_calls.append(kwargs)

            class _Session:
                id = f"cs_test_{len(create_calls)}"
                url = f"https://checkout.stripe.test/{len(create_calls)}"

            return _Session()

    class _FakeCustomer:
        @staticmethod
        def list(email: str, limit: int):
            assert email == "user@example.com"
            assert limit == 25
            return {"data": [{"id": "cus_123", "metadata": {"userId": "user_123"}}]}

    class _FakeCheckout:
        Session = _FakeCheckoutSession

    class _FakeStripe:
        api_key = None
        checkout = _FakeCheckout
        Customer = _FakeCustomer

    monkeypatch.setattr(billing_service, "_load_stripe_module", lambda: _FakeStripe)

    monthly = billing_service.create_checkout_session(
        user_id="user_123",
        user_email="user@example.com",
        checkout_kind="pro_monthly",
    )
    yearly = billing_service.create_checkout_session(
        user_id="user_123",
        user_email="user@example.com",
        checkout_kind="pro_yearly",
    )

    assert monthly["sessionId"] == "cs_test_1"
    assert yearly["sessionId"] == "cs_test_2"
    assert len(create_calls) == 2
    assert create_calls[0]["idempotency_key"] != create_calls[1]["idempotency_key"]
    assert create_calls[0]["line_items"] == [{"price": "price_monthly_123", "quantity": 1}]
    assert create_calls[1]["line_items"] == [{"price": "price_yearly_123", "quantity": 1}]


def test_create_checkout_session_uses_new_idempotency_key_for_each_refill_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_checkout")
    monkeypatch.setenv("STRIPE_PRICE_REFILL_500", "price_refill_123")
    monkeypatch.setenv("STRIPE_REFILL_CREDITS", "500")
    monkeypatch.setenv("STRIPE_CHECKOUT_IDEMPOTENCY_WINDOW_SECONDS", "300")
    monkeypatch.setattr(billing_service.time, "time", lambda: 1700000000.0)

    seen_sessions_by_idempotency_key: dict[str, tuple[str, str]] = {}
    create_calls: list[dict[str, object]] = []

    class _FakeCheckoutSession:
        @staticmethod
        def list(**kwargs):
            assert kwargs == {"customer": "cus_123", "status": "open", "limit": 20}
            return {"data": []}

        @staticmethod
        def create(**kwargs):
            create_calls.append(kwargs)
            key = str(kwargs["idempotency_key"])
            if key not in seen_sessions_by_idempotency_key:
                index = len(seen_sessions_by_idempotency_key) + 1
                seen_sessions_by_idempotency_key[key] = (
                    f"cs_refill_{index}",
                    f"https://checkout.stripe.test/refill-{index}",
                )
            session_id, session_url = seen_sessions_by_idempotency_key[key]

            class _Session:
                id = session_id
                url = session_url

            return _Session()

    class _FakeCustomer:
        @staticmethod
        def list(email: str, limit: int):
            assert email == "user@example.com"
            assert limit == 25
            return {"data": [{"id": "cus_123", "metadata": {"userId": "user_123"}}]}

    class _FakeCheckout:
        Session = _FakeCheckoutSession

    class _FakeStripe:
        api_key = None
        checkout = _FakeCheckout
        Customer = _FakeCustomer

    monkeypatch.setattr(billing_service, "_load_stripe_module", lambda: _FakeStripe)

    first = billing_service.create_checkout_session(
        user_id="user_123",
        user_email="user@example.com",
        checkout_kind="refill_500",
    )
    second = billing_service.create_checkout_session(
        user_id="user_123",
        user_email="user@example.com",
        checkout_kind="refill_500",
    )

    assert first["sessionId"] == "cs_refill_1"
    assert second["sessionId"] == "cs_refill_2"
    assert len(create_calls) == 2
    assert create_calls[0]["idempotency_key"] != create_calls[1]["idempotency_key"]


def test_create_checkout_session_rejects_when_customer_has_active_pro_subscription(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_checkout")
    monkeypatch.setenv("STRIPE_PRICE_PRO_MONTHLY", "price_monthly_123")
    monkeypatch.setenv("STRIPE_PRICE_PRO_YEARLY", "price_yearly_123")

    class _FakeCheckoutSession:
        @staticmethod
        def list(**kwargs):
            assert kwargs == {"customer": "cus_123", "status": "open", "limit": 20}
            return {"data": []}

        @staticmethod
        def create(**kwargs):
            raise AssertionError("Session.create should not run when active Pro subscription already exists.")

    class _FakeCustomer:
        @staticmethod
        def list(email: str, limit: int):
            assert email == "user@example.com"
            assert limit == 25
            return {"data": [{"id": "cus_123", "metadata": {"userId": "user_123"}}]}

    class _FakeSubscription:
        @staticmethod
        def list(**kwargs):
            assert kwargs == {"customer": "cus_123", "status": "all", "limit": 20}
            return {
                "data": [
                    {
                        "id": "sub_existing_active",
                        "status": "active",
                        "items": {"data": [{"price": {"id": "price_yearly_123"}}]},
                    }
                ]
            }

    class _FakeCheckout:
        Session = _FakeCheckoutSession

    class _FakeStripe:
        api_key = None
        checkout = _FakeCheckout
        Customer = _FakeCustomer
        Subscription = _FakeSubscription

    monkeypatch.setattr(billing_service, "_load_stripe_module", lambda: _FakeStripe)

    with pytest.raises(billing_service.BillingCheckoutConflictError, match="active Pro subscription"):
        billing_service.create_checkout_session(
            user_id="user_123",
            user_email="user@example.com",
            checkout_kind="pro_monthly",
        )


def test_create_checkout_session_checks_all_email_matched_customers_for_active_pro_subscription(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_checkout")
    monkeypatch.setenv("STRIPE_PRICE_PRO_MONTHLY", "price_monthly_123")
    monkeypatch.setenv("STRIPE_PRICE_PRO_YEARLY", "price_yearly_123")

    class _FakeCheckoutSession:
        @staticmethod
        def list(**kwargs):
            customer_id = kwargs.get("customer")
            assert kwargs == {"customer": customer_id, "status": "open", "limit": 20}
            return {"data": []}

        @staticmethod
        def create(**kwargs):
            raise AssertionError("Session.create should not run when a linked customer already has active Pro subscription.")

    class _FakeCustomer:
        @staticmethod
        def list(email: str, limit: int):
            assert email == "user@example.com"
            assert limit == 25
            # First customer is the one selected for new checkout, second is a historical
            # customer for the same email with an active Pro subscription.
            return {
                "data": [
                    {"id": "cus_selected", "metadata": {"userId": "user_123"}},
                    {"id": "cus_historical", "email": "user@example.com"},
                ]
            }

    class _FakeSubscription:
        @staticmethod
        def list(**kwargs):
            customer_id = kwargs.get("customer")
            assert kwargs == {"customer": customer_id, "status": "all", "limit": 20}
            if customer_id == "cus_historical":
                return {
                    "data": [
                        {
                            "id": "sub_historical_active",
                            "status": "active",
                            "items": {"data": [{"price": {"id": "price_monthly_123"}}]},
                        }
                    ]
                }
            return {"data": []}

    class _FakeCheckout:
        Session = _FakeCheckoutSession

    class _FakeStripe:
        api_key = None
        checkout = _FakeCheckout
        Customer = _FakeCustomer
        Subscription = _FakeSubscription

    monkeypatch.setattr(billing_service, "_load_stripe_module", lambda: _FakeStripe)

    with pytest.raises(billing_service.BillingCheckoutConflictError, match="sub_historical_active"):
        billing_service.create_checkout_session(
            user_id="user_123",
            user_email="user@example.com",
            checkout_kind="pro_monthly",
        )


def test_create_checkout_session_requires_user_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_checkout")
    monkeypatch.setenv("STRIPE_PRICE_PRO_MONTHLY", "price_monthly_123")

    class _FakeCheckoutSession:
        @staticmethod
        def create(**kwargs):
            raise AssertionError("Stripe checkout should not be called when user_id is empty.")

    class _FakeCheckout:
        Session = _FakeCheckoutSession

    class _FakeStripe:
        api_key = None
        checkout = _FakeCheckout

    monkeypatch.setattr(billing_service, "_load_stripe_module", lambda: _FakeStripe)

    with pytest.raises(billing_service.BillingConfigError, match="Missing user id"):
        billing_service.create_checkout_session(
            user_id="",
            user_email="user@example.com",
            checkout_kind="pro_monthly",
        )


def test_create_checkout_session_rejects_missing_checkout_redirect_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_checkout")
    monkeypatch.setenv("STRIPE_PRICE_PRO_MONTHLY", "price_monthly_123")

    class _FakeCheckoutSession:
        @staticmethod
        def list(**kwargs):
            assert kwargs == {"customer": "cus_123", "status": "open", "limit": 20}
            return {"data": []}

        @staticmethod
        def create(**kwargs):
            class _Session:
                id = "cs_test_missing_url"
                url = ""

            return _Session()

    class _FakeCheckout:
        Session = _FakeCheckoutSession

    class _FakeCustomer:
        @staticmethod
        def list(email: str, limit: int):
            assert email == "user@example.com"
            assert limit == 25
            return {"data": [{"id": "cus_123", "metadata": {"userId": "user_123"}}]}

    class _FakeStripe:
        api_key = None
        checkout = _FakeCheckout
        Customer = _FakeCustomer

    monkeypatch.setattr(billing_service, "_load_stripe_module", lambda: _FakeStripe)

    with pytest.raises(
        billing_service.BillingConfigError,
        match="did not return a redirect URL",
    ):
        billing_service.create_checkout_session(
            user_id="user_123",
            user_email="user@example.com",
            checkout_kind="pro_monthly",
        )


def test_construct_webhook_event_accepts_valid_signature(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_stripe_module(monkeypatch)
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_construct")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_construct")
    event = {
        "id": "evt_service_ok",
        "type": "checkout.session.completed",
        "data": {"object": {"metadata": {"checkoutKind": "refill_500", "userId": "service-user"}}},
    }
    payload = json.dumps(event, separators=(",", ":"), sort_keys=True).encode("utf-8")
    signature = _sign_stripe_payload(payload, secret="whsec_construct")

    parsed = billing_service.construct_webhook_event(payload=payload, signature=signature)

    assert parsed["id"] == "evt_service_ok"
    assert parsed["type"] == "checkout.session.completed"


def test_construct_webhook_event_rejects_missing_signature(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_stripe_module(monkeypatch)
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_construct")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_construct")

    with pytest.raises(ValueError, match="Missing Stripe-Signature header"):
        billing_service.construct_webhook_event(payload=b"{}", signature="")


def test_construct_webhook_event_rejects_invalid_signature(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_stripe_module(monkeypatch)
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_construct")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_construct")
    event = {
        "id": "evt_service_bad_sig",
        "type": "checkout.session.completed",
        "data": {"object": {}},
    }
    payload = json.dumps(event, separators=(",", ":"), sort_keys=True).encode("utf-8")
    signature = _sign_stripe_payload(payload, secret="whsec_wrong")

    with pytest.raises(Exception):
        billing_service.construct_webhook_event(payload=payload, signature=signature)


def test_construct_webhook_event_requires_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_stripe_module(monkeypatch)
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_construct")
    with pytest.raises(billing_service.BillingConfigError, match="Missing STRIPE_SECRET_KEY"):
        billing_service.construct_webhook_event(payload=b"{}", signature="sig")

    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_construct")
    monkeypatch.delenv("STRIPE_WEBHOOK_SECRET", raising=False)
    with pytest.raises(billing_service.BillingConfigError, match="Missing STRIPE_WEBHOOK_SECRET"):
        billing_service.construct_webhook_event(payload=b"{}", signature="sig")


def test_cancel_subscription_at_period_end_requires_subscription_id() -> None:
    with pytest.raises(billing_service.BillingConfigError, match="Missing Stripe subscription id"):
        billing_service.cancel_subscription_at_period_end(subscription_id="")


def test_cancel_subscription_at_period_end_parses_stripe_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_cancel")

    class _FakeSubscription:
        @staticmethod
        def modify(subscription_id: str, cancel_at_period_end: bool):
            assert subscription_id == "sub_test_123"
            assert cancel_at_period_end is True
            return {
                "status": "active",
                "cancel_at_period_end": True,
                "cancel_at": 1775000000,
                "current_period_end": 1775000001,
                "customer": "cus_123",
                "items": {"data": [{"price": {"id": "price_monthly"}}]},
            }

    class _FakeStripe:
        api_key = None
        Subscription = _FakeSubscription

    monkeypatch.setattr(billing_service, "_load_stripe_module", lambda: _FakeStripe)

    result = billing_service.cancel_subscription_at_period_end(subscription_id="sub_test_123")

    assert result.status == "active"
    assert result.cancel_at_period_end is True
    assert result.cancel_at == 1775000000
    assert result.current_period_end == 1775000001
    assert result.customer_id == "cus_123"
    assert result.price_id == "price_monthly"
