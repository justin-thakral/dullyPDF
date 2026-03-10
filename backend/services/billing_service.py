"""Stripe checkout and webhook helpers for sandbox billing flows."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import time
import uuid
from typing import Any, Dict, Iterable, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from backend.env_utils import env_value


CHECKOUT_KIND_PRO_MONTHLY = "pro_monthly"
CHECKOUT_KIND_PRO_YEARLY = "pro_yearly"
CHECKOUT_KIND_REFILL_500 = "refill_500"

SUPPORTED_CHECKOUT_KINDS = {
    CHECKOUT_KIND_PRO_MONTHLY,
    CHECKOUT_KIND_PRO_YEARLY,
    CHECKOUT_KIND_REFILL_500,
}

ACTIVE_SUBSCRIPTION_STATUSES = {"active", "trialing", "past_due"}
REFILL_PRICE_CREDIT_ENV_MAP: tuple[tuple[str, str], ...] = (
    ("STRIPE_PRICE_REFILL_500", "STRIPE_REFILL_CREDITS"),
)
DEFAULT_BILLING_CATALOG_CACHE_TTL_SECONDS = 300
_BILLING_CATALOG_CACHE: Dict[str, Any] = {"expires_at": 0.0, "payload": {}}
DEFAULT_CHECKOUT_IDEMPOTENCY_WINDOW_SECONDS = 300
DEFAULT_WEBHOOK_HEALTH_CACHE_TTL_SECONDS = 60
_WEBHOOK_HEALTH_CACHE: Dict[str, Any] = {"expires_at": 0.0, "payload": {}}
DEFAULT_RECONCILE_CHECKOUT_EVENTS_LIMIT = 100
MAX_RECONCILE_CHECKOUT_EVENTS_LIMIT = 500
REQUIRED_STRIPE_WEBHOOK_EVENTS = {
    "checkout.session.completed",
    "invoice.paid",
    "customer.subscription.updated",
    "customer.subscription.deleted",
}


class BillingConfigError(RuntimeError):
    """Raised when Stripe integration is missing required configuration."""


class BillingCheckoutConflictError(RuntimeError):
    """Raised when checkout cannot proceed due to an existing billing state."""


class BillingCheckoutSessionNotFoundError(RuntimeError):
    """Raised when a targeted Stripe checkout session no longer exists."""


@dataclass(frozen=True)
class CheckoutPlan:
    kind: str
    mode: str
    price_id: str


@dataclass(frozen=True)
class CancelSubscriptionResult:
    status: Optional[str]
    cancel_at_period_end: bool
    cancel_at: Optional[int]
    current_period_end: Optional[int]
    customer_id: Optional[str]
    price_id: Optional[str]


@dataclass(frozen=True)
class CheckoutPlanCatalogItem:
    kind: str
    mode: str
    price_id: str
    label: str
    currency: Optional[str]
    unit_amount: Optional[int]
    interval: Optional[str]
    refill_credits: Optional[int]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "mode": self.mode,
            "priceId": self.price_id,
            "label": self.label,
            "currency": self.currency,
            "unitAmount": self.unit_amount,
            "interval": self.interval,
            "refillCredits": self.refill_credits,
        }


def _is_truthy(value: Optional[str], *, default: bool = False) -> bool:
    if value is None:
        return default
    normalized = value.strip().lower()
    if not normalized:
        return default
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _load_stripe_module():
    try:
        import stripe  # type: ignore
    except Exception as exc:  # pragma: no cover - exercised via API tests
        raise BillingConfigError(
            "Stripe SDK is not installed. Add `stripe` to backend requirements.",
        ) from exc
    return stripe


def billing_enabled() -> bool:
    return bool(env_value("STRIPE_SECRET_KEY") and env_value("STRIPE_WEBHOOK_SECRET"))


def webhook_health_enforced_for_checkout() -> bool:
    raw = env_value("STRIPE_ENFORCE_WEBHOOK_HEALTH")
    if raw is None or not raw.strip():
        return (env_value("ENV") or "").strip().lower() != "test"
    return _is_truthy(raw, default=True)


def _default_success_url() -> str:
    return "http://localhost:5173/?billing=success"


def _default_cancel_url() -> str:
    return "http://localhost:5173/?billing=cancel"


def _resolve_checkout_urls() -> tuple[str, str]:
    success_url = env_value("STRIPE_CHECKOUT_SUCCESS_URL") or _default_success_url()
    cancel_url = env_value("STRIPE_CHECKOUT_CANCEL_URL") or _default_cancel_url()
    return (
        _append_billing_state_param(success_url, state="success"),
        _append_billing_state_param(cancel_url, state="cancel"),
    )


def _append_billing_state_param(url: str, *, state: str) -> str:
    parsed = urlsplit(url)
    query_pairs = parse_qsl(parsed.query, keep_blank_values=True)
    if any((key or "").strip().lower() == "billing" for key, _ in query_pairs):
        return url
    query_pairs.append(("billing", state))
    query = urlencode(query_pairs, doseq=True)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, query, parsed.fragment))


def _stripe_object_to_dict(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        converted = to_dict()
        if isinstance(converted, dict):
            return converted
    return {}


def _safe_positive_int_env(name: str, default: int) -> int:
    raw = (env_value(name) or "").strip()
    if not raw:
        return default
    try:
        parsed = int(raw)
    except ValueError:
        return default
    return parsed if parsed > 0 else default


def _resolve_billing_catalog_cache_ttl_seconds() -> int:
    return _safe_positive_int_env(
        "STRIPE_CATALOG_CACHE_TTL_SECONDS",
        DEFAULT_BILLING_CATALOG_CACHE_TTL_SECONDS,
    )


def _resolve_plan(kind: str) -> CheckoutPlan:
    normalized_kind = (kind or "").strip().lower()
    if normalized_kind == CHECKOUT_KIND_PRO_MONTHLY:
        price_id = env_value("STRIPE_PRICE_PRO_MONTHLY")
        if not price_id:
            raise BillingConfigError("Missing STRIPE_PRICE_PRO_MONTHLY.")
        return CheckoutPlan(kind=normalized_kind, mode="subscription", price_id=price_id)
    if normalized_kind == CHECKOUT_KIND_PRO_YEARLY:
        price_id = env_value("STRIPE_PRICE_PRO_YEARLY")
        if not price_id:
            raise BillingConfigError("Missing STRIPE_PRICE_PRO_YEARLY.")
        return CheckoutPlan(kind=normalized_kind, mode="subscription", price_id=price_id)
    if normalized_kind == CHECKOUT_KIND_REFILL_500:
        price_id = env_value("STRIPE_PRICE_REFILL_500")
        if not price_id:
            raise BillingConfigError("Missing STRIPE_PRICE_REFILL_500.")
        return CheckoutPlan(kind=normalized_kind, mode="payment", price_id=price_id)
    raise BillingConfigError("Unsupported checkout kind.")


def _resolve_checkout_label(kind: str) -> str:
    normalized_kind = (kind or "").strip().lower()
    if normalized_kind == CHECKOUT_KIND_PRO_MONTHLY:
        return "Pro Monthly"
    if normalized_kind == CHECKOUT_KIND_PRO_YEARLY:
        return "Pro Yearly"
    if normalized_kind == CHECKOUT_KIND_REFILL_500:
        return "Refill 500 Credits"
    return "Checkout Plan"


def _coerce_optional_int(value: Any) -> Optional[int]:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed


def _extract_list_data(value: Any) -> list[Dict[str, Any]]:
    payload = _stripe_object_to_dict(value)
    data = payload.get("data")
    if not isinstance(data, list):
        return []
    normalized: list[Dict[str, Any]] = []
    for item in data:
        converted = _stripe_object_to_dict(item)
        if converted:
            normalized.append(converted)
    return normalized


def _resolve_checkout_idempotency_window_seconds() -> int:
    return _safe_positive_int_env(
        "STRIPE_CHECKOUT_IDEMPOTENCY_WINDOW_SECONDS",
        DEFAULT_CHECKOUT_IDEMPOTENCY_WINDOW_SECONDS,
    )


def _resolve_checkout_idempotency_key(
    *,
    user_id: str,
    checkout_kind: str,
    checkout_attempt_id: Optional[str] = None,
) -> str:
    normalized_user_id = (user_id or "").strip()
    normalized_kind = (checkout_kind or "").strip().lower()
    if not normalized_kind:
        normalized_kind = "unknown"
    normalized_attempt_id = (checkout_attempt_id or "").strip()
    if normalized_kind == CHECKOUT_KIND_REFILL_500:
        # Refill purchases must allow immediate back-to-back checkouts. A shared
        # 5-minute idempotency bucket can otherwise reuse a completed Stripe
        # session and redirect users to "all done here". Attempt-scoped keys keep
        # retries deduplicated when a caller supplies an attempt id, while still
        # allowing a fresh checkout for a new refill purchase.
        if normalized_attempt_id:
            digest = hashlib.sha256(
                f"{normalized_kind}:{normalized_user_id}:{normalized_attempt_id}".encode("utf-8")
            ).hexdigest()
            return f"checkout_{digest}"
        return f"checkout_{uuid.uuid4().hex}"
    window_seconds = max(1, _resolve_checkout_idempotency_window_seconds())
    bucket = int(time.time() // window_seconds)
    digest = hashlib.sha256(f"{normalized_kind}:{normalized_user_id}:{bucket}".encode("utf-8")).hexdigest()
    return f"checkout_{digest}"


def _resolve_customer_create_idempotency_key(*, user_id: str) -> str:
    normalized_user_id = (user_id or "").strip()
    digest = hashlib.sha256(normalized_user_id.encode("utf-8")).hexdigest()
    return f"customer_{digest}"


def _list_existing_customer_ids_for_user(
    *,
    stripe: Any,
    user_id: str,
    user_email: Optional[str],
) -> list[str]:
    normalized_email = (user_email or "").strip()
    if not normalized_email:
        return []
    customers = stripe.Customer.list(email=normalized_email, limit=25)
    normalized_user_id = (user_id or "").strip()
    matching_user_ids: list[str] = []
    seen_ids: set[str] = set()
    for customer in _extract_list_data(customers):
        customer_id = str(customer.get("id") or "").strip()
        if not customer_id or customer_id in seen_ids or bool(customer.get("deleted")):
            continue
        seen_ids.add(customer_id)
        metadata = customer.get("metadata") if isinstance(customer.get("metadata"), dict) else {}
        customer_user_id = first_nonempty(
            [
                str(metadata.get("userId") or ""),
                str(metadata.get("user_id") or ""),
            ]
        )
        if customer_user_id and customer_user_id == normalized_user_id:
            matching_user_ids.append(customer_id)
    return matching_user_ids


def _resolve_or_create_customer_id(
    *,
    stripe: Any,
    user_id: str,
    user_email: Optional[str],
    customer_id: Optional[str] = None,
) -> Optional[str]:
    normalized_customer_id = (customer_id or "").strip() or None
    if normalized_customer_id:
        return normalized_customer_id

    normalized_user_id = (user_id or "").strip()
    normalized_email = (user_email or "").strip() or None
    candidate_customer_ids = _list_existing_customer_ids_for_user(
        stripe=stripe,
        user_id=normalized_user_id,
        user_email=normalized_email,
    )
    if candidate_customer_ids:
        return candidate_customer_ids[0]

    create_payload: Dict[str, Any] = {"metadata": {"userId": normalized_user_id}}
    if normalized_email:
        create_payload["email"] = normalized_email
    created = stripe.Customer.create(
        **create_payload,
        idempotency_key=_resolve_customer_create_idempotency_key(user_id=normalized_user_id),
    )
    created_payload = _stripe_object_to_dict(created)
    created_customer_id = first_nonempty(
        [
            str(created_payload.get("id") or ""),
            str(getattr(created, "id", "") or ""),
        ]
    )
    if not created_customer_id:
        raise BillingConfigError("Stripe customer creation failed for checkout session.")
    return created_customer_id


def _find_open_checkout_session(
    *,
    stripe: Any,
    user_id: str,
    customer_id: Optional[str],
    allowed_checkout_kinds: set[str],
    expected_checkout_attempt_id: Optional[str] = None,
    expected_checkout_price_id: Optional[str] = None,
) -> Optional[Dict[str, Optional[str]]]:
    normalized_customer_id = (customer_id or "").strip()
    normalized_user_id = (user_id or "").strip()
    normalized_expected_attempt_id = (expected_checkout_attempt_id or "").strip() or None
    normalized_expected_price_id = (expected_checkout_price_id or "").strip() or None
    if not normalized_customer_id or not normalized_user_id:
        return None
    normalized_allowed_kinds = {(value or "").strip().lower() for value in allowed_checkout_kinds if value}
    if not normalized_allowed_kinds:
        return None
    sessions = stripe.checkout.Session.list(
        customer=normalized_customer_id,
        status="open",
        limit=20,
    )
    for session in _extract_list_data(sessions):
        metadata = session.get("metadata") if isinstance(session.get("metadata"), dict) else {}
        checkout_kind = str(metadata.get("checkoutKind") or "").strip().lower()
        if checkout_kind not in normalized_allowed_kinds:
            continue
        session_user_id = first_nonempty(
            [
                str(metadata.get("userId") or ""),
                str(metadata.get("user_id") or ""),
                str(session.get("client_reference_id") or ""),
            ]
        )
        if session_user_id != normalized_user_id:
            continue
        session_attempt_id = first_nonempty(
            [
                str(metadata.get("checkoutAttemptId") or ""),
                str(metadata.get("checkout_attempt_id") or ""),
            ]
        )
        if normalized_expected_attempt_id and session_attempt_id != normalized_expected_attempt_id:
            continue
        session_price_id = first_nonempty(
            [
                str(metadata.get("checkoutPriceId") or ""),
                str(metadata.get("checkout_price_id") or ""),
            ]
        )
        if normalized_expected_price_id and session_price_id != normalized_expected_price_id:
            continue
        session_id = str(session.get("id") or "").strip()
        session_url = str(session.get("url") or "").strip()
        if not session_id or not session_url:
            continue
        return {
            "sessionId": session_id,
            "url": session_url,
            "customerId": normalized_customer_id,
            "checkoutAttemptId": session_attempt_id,
            "checkoutPriceId": session_price_id,
        }
    return None


def _find_open_pro_checkout_session(
    *,
    stripe: Any,
    user_id: str,
    customer_id: Optional[str],
    checkout_attempt_id: Optional[str] = None,
    checkout_price_id: Optional[str] = None,
) -> Optional[Dict[str, Optional[str]]]:
    return _find_open_checkout_session(
        stripe=stripe,
        user_id=user_id,
        customer_id=customer_id,
        allowed_checkout_kinds={CHECKOUT_KIND_PRO_MONTHLY, CHECKOUT_KIND_PRO_YEARLY},
        expected_checkout_attempt_id=checkout_attempt_id,
        expected_checkout_price_id=checkout_price_id,
    )


def _find_open_refill_checkout_session(
    *,
    stripe: Any,
    user_id: str,
    customer_id: Optional[str],
    checkout_attempt_id: Optional[str] = None,
    checkout_price_id: Optional[str] = None,
) -> Optional[Dict[str, Optional[str]]]:
    return _find_open_checkout_session(
        stripe=stripe,
        user_id=user_id,
        customer_id=customer_id,
        allowed_checkout_kinds={CHECKOUT_KIND_REFILL_500},
        expected_checkout_attempt_id=checkout_attempt_id,
        expected_checkout_price_id=checkout_price_id,
    )


def _extract_subscription_price_ids(subscription_obj: Dict[str, Any]) -> list[str]:
    price_ids: list[str] = []
    items = subscription_obj.get("items") if isinstance(subscription_obj, dict) else None
    data = items.get("data") if isinstance(items, dict) else None
    if not isinstance(data, list):
        return price_ids
    for entry in data:
        if not isinstance(entry, dict):
            continue
        price = entry.get("price")
        if isinstance(price, dict):
            price_id = str(price.get("id") or "").strip()
            if price_id:
                price_ids.append(price_id)
            continue
        direct_price_id = str(price or "").strip()
        if direct_price_id:
            price_ids.append(direct_price_id)
    return price_ids


def _find_active_pro_subscription_for_customer(
    *,
    stripe: Any,
    customer_id: Optional[str],
) -> Optional[str]:
    normalized_customer_id = (customer_id or "").strip()
    if not normalized_customer_id:
        return None
    subscription_api = getattr(stripe, "Subscription", None)
    list_subscriptions = getattr(subscription_api, "list", None)
    if not callable(list_subscriptions):
        return None
    subscriptions = list_subscriptions(
        customer=normalized_customer_id,
        status="all",
        limit=20,
    )
    for subscription in _extract_list_data(subscriptions):
        status = str(subscription.get("status") or "").strip().lower()
        if not is_subscription_active(status):
            continue
        price_ids = _extract_subscription_price_ids(subscription)
        if not any(is_pro_price_id(price_id) for price_id in price_ids):
            continue
        subscription_id = str(subscription.get("id") or "").strip()
        return subscription_id or "active_pro_subscription"
    return None


def _resolve_price_metadata(price_id: str) -> tuple[Optional[str], Optional[int], Optional[str]]:
    secret_key = env_value("STRIPE_SECRET_KEY")
    normalized_price_id = (price_id or "").strip()
    if not secret_key or not normalized_price_id:
        return None, None, None
    try:
        stripe = _load_stripe_module()
        stripe.api_key = secret_key
        stripe_price = stripe.Price.retrieve(normalized_price_id)
        payload = _stripe_object_to_dict(stripe_price)
    except Exception:
        return None, None, None
    currency = (str(payload.get("currency") or "").strip().lower() or None)
    unit_amount = _coerce_optional_int(payload.get("unit_amount"))
    recurring = payload.get("recurring") if isinstance(payload.get("recurring"), dict) else {}
    interval = (str(recurring.get("interval") or "").strip().lower() or None)
    return currency, unit_amount, interval


def _build_checkout_catalog_payload() -> Dict[str, Dict[str, Any]]:
    catalog: Dict[str, Dict[str, Any]] = {}
    for kind in (
        CHECKOUT_KIND_PRO_MONTHLY,
        CHECKOUT_KIND_PRO_YEARLY,
        CHECKOUT_KIND_REFILL_500,
    ):
        try:
            plan = _resolve_plan(kind)
        except BillingConfigError:
            continue
        currency, unit_amount, interval = _resolve_price_metadata(plan.price_id)
        refill_credits: Optional[int] = None
        if kind == CHECKOUT_KIND_REFILL_500:
            refill_credits = resolve_refill_credit_pack_size_for_price(plan.price_id)
            if refill_credits is None:
                refill_credits = resolve_refill_credit_pack_size()
        item = CheckoutPlanCatalogItem(
            kind=plan.kind,
            mode=plan.mode,
            price_id=plan.price_id,
            label=_resolve_checkout_label(plan.kind),
            currency=currency,
            unit_amount=unit_amount,
            interval=interval,
            refill_credits=refill_credits,
        )
        catalog[plan.kind] = item.to_dict()
    return catalog


def resolve_checkout_catalog(*, force_refresh: bool = False) -> Dict[str, Dict[str, Any]]:
    """Return checkout metadata for UI rendering, cached for short intervals."""
    ttl_seconds = _resolve_billing_catalog_cache_ttl_seconds()
    now = time.monotonic()
    if not force_refresh:
        cached_payload = _BILLING_CATALOG_CACHE.get("payload")
        cached_expires_at = float(_BILLING_CATALOG_CACHE.get("expires_at") or 0.0)
        if now < cached_expires_at and isinstance(cached_payload, dict):
            return dict(cached_payload)
    payload = _build_checkout_catalog_payload()
    _BILLING_CATALOG_CACHE["payload"] = dict(payload)
    _BILLING_CATALOG_CACHE["expires_at"] = now + max(1, ttl_seconds)
    return payload


def _resolve_webhook_health_cache_ttl_seconds() -> int:
    return _safe_positive_int_env(
        "STRIPE_WEBHOOK_HEALTH_CACHE_TTL_SECONDS",
        DEFAULT_WEBHOOK_HEALTH_CACHE_TTL_SECONDS,
    )


def _resolve_reconcile_checkout_events_limit(limit: Optional[int]) -> int:
    fallback = _safe_positive_int_env(
        "STRIPE_RECONCILE_CHECKOUT_EVENTS_LIMIT",
        DEFAULT_RECONCILE_CHECKOUT_EVENTS_LIMIT,
    )
    if limit is None:
        return min(fallback, MAX_RECONCILE_CHECKOUT_EVENTS_LIMIT)
    try:
        parsed = int(limit)
    except (TypeError, ValueError):
        parsed = fallback
    parsed = parsed if parsed > 0 else fallback
    return min(parsed, MAX_RECONCILE_CHECKOUT_EVENTS_LIMIT)


def _resolve_required_webhook_events() -> set[str]:
    configured = (env_value("STRIPE_REQUIRED_WEBHOOK_EVENTS") or "").strip()
    if not configured:
        return set(REQUIRED_STRIPE_WEBHOOK_EVENTS)
    resolved: set[str] = set()
    for raw in configured.split(","):
        event_name = raw.strip()
        if event_name:
            resolved.add(event_name)
    return resolved or set(REQUIRED_STRIPE_WEBHOOK_EVENTS)


def _normalize_webhook_endpoint_url(raw_url: Optional[str]) -> str:
    raw = (raw_url or "").strip()
    if not raw:
        return ""
    parsed = urlsplit(raw)
    scheme = parsed.scheme.strip().lower()
    netloc = parsed.netloc.strip().lower()
    path = parsed.path.rstrip("/") or "/"
    query = parsed.query
    return urlunsplit((scheme, netloc, path, query, ""))


def _resolve_expected_webhook_endpoint_url() -> Optional[str]:
    normalized = _normalize_webhook_endpoint_url(env_value("STRIPE_WEBHOOK_ENDPOINT_URL"))
    return normalized or None


def _extract_webhook_endpoint_data(value: Any) -> list[Dict[str, Any]]:
    endpoints = _extract_list_data(value)
    if endpoints:
        return endpoints
    payload = _stripe_object_to_dict(value)
    endpoint_payload = payload.get("data")
    if not isinstance(endpoint_payload, list):
        return []
    normalized: list[Dict[str, Any]] = []
    for item in endpoint_payload:
        converted = _stripe_object_to_dict(item)
        if converted:
            normalized.append(converted)
    return normalized


def _resolve_enabled_endpoint_events(endpoint_payload: Dict[str, Any]) -> set[str]:
    raw = endpoint_payload.get("enabled_events")
    if not isinstance(raw, list):
        return set()
    resolved: set[str] = set()
    for item in raw:
        if item is None:
            continue
        event_name = str(item).strip()
        if event_name:
            resolved.add(event_name)
    return resolved


def resolve_webhook_health(*, force_refresh: bool = False) -> Dict[str, Any]:
    """Return whether Stripe webhook delivery prerequisites are satisfied."""
    now = time.time()
    if not force_refresh:
        cached_payload = _WEBHOOK_HEALTH_CACHE.get("payload")
        cached_expires = float(_WEBHOOK_HEALTH_CACHE.get("expires_at") or 0.0)
        if isinstance(cached_payload, dict) and cached_payload and cached_expires > now:
            return dict(cached_payload)

    checked_at = int(now)
    enforced_for_checkout = webhook_health_enforced_for_checkout()
    expected_endpoint_url = _resolve_expected_webhook_endpoint_url()

    def _build_payload(*, healthy: bool, reason: str, **extra: Any) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "healthy": healthy,
            "reason": reason,
            "checkedAt": checked_at,
            "enforcedForCheckout": enforced_for_checkout,
            "expectedEndpointUrl": expected_endpoint_url,
        }
        payload.update(extra)
        return payload

    if not billing_enabled():
        payload = _build_payload(
            healthy=False,
            reason="Stripe billing is not fully configured (missing STRIPE_SECRET_KEY or STRIPE_WEBHOOK_SECRET).",
        )
    else:
        stripe = _load_stripe_module()
        secret_key = env_value("STRIPE_SECRET_KEY")
        assert secret_key is not None  # guarded by billing_enabled
        stripe.api_key = secret_key

        endpoint_api = getattr(stripe, "WebhookEndpoint", None)
        list_endpoint_fn = getattr(endpoint_api, "list", None)
        if not callable(list_endpoint_fn):
            payload = _build_payload(
                healthy=False,
                reason="Stripe SDK does not expose WebhookEndpoint.list for health checks.",
            )
        else:
            try:
                endpoints_response = list_endpoint_fn(limit=50)
            except Exception as exc:
                payload = _build_payload(
                    healthy=False,
                    reason=f"Unable to query Stripe webhook endpoints: {exc}",
                )
            else:
                required_events = _resolve_required_webhook_events()
                endpoints = _extract_webhook_endpoint_data(endpoints_response)
                enabled_endpoint_count = 0
                fallback_matching_endpoint: Optional[Dict[str, Any]] = None
                fallback_missing_events: Optional[set[str]] = None
                expected_endpoint_seen = False
                expected_endpoint_enabled = False
                expected_matching_endpoint: Optional[Dict[str, Any]] = None
                expected_missing_events: Optional[set[str]] = None
                expected_endpoint_id: Optional[str] = None
                expected_endpoint_raw_url: Optional[str] = None

                for endpoint in endpoints:
                    status = str(endpoint.get("status") or "").strip().lower()
                    endpoint_url = _normalize_webhook_endpoint_url(endpoint.get("url"))
                    enabled_events = _resolve_enabled_endpoint_events(endpoint)
                    missing_events = (
                        set()
                        if "*" in enabled_events
                        else (required_events - enabled_events)
                    )

                    if status != "enabled":
                        if expected_endpoint_url and endpoint_url == expected_endpoint_url:
                            expected_endpoint_seen = True
                            expected_endpoint_id = str(endpoint.get("id") or "").strip() or None
                            expected_endpoint_raw_url = str(endpoint.get("url") or "").strip() or None
                        continue

                    enabled_endpoint_count += 1

                    if not missing_events and fallback_matching_endpoint is None:
                        fallback_matching_endpoint = endpoint
                    elif fallback_missing_events is None or len(missing_events) < len(fallback_missing_events):
                        fallback_missing_events = missing_events

                    if expected_endpoint_url and endpoint_url == expected_endpoint_url:
                        expected_endpoint_seen = True
                        expected_endpoint_enabled = True
                        expected_endpoint_id = str(endpoint.get("id") or "").strip() or None
                        expected_endpoint_raw_url = str(endpoint.get("url") or "").strip() or None
                        if not missing_events and expected_matching_endpoint is None:
                            expected_matching_endpoint = endpoint
                        elif expected_missing_events is None or len(missing_events) < len(expected_missing_events):
                            expected_missing_events = missing_events

                if expected_endpoint_url:
                    if not expected_endpoint_seen:
                        payload = _build_payload(
                            healthy=False,
                            reason=f"Configured Stripe webhook endpoint URL was not found: {expected_endpoint_url}",
                        )
                    elif not expected_endpoint_enabled:
                        payload = _build_payload(
                            healthy=False,
                            reason=(
                                "Configured Stripe webhook endpoint is not enabled. "
                                f"Configure or enable endpoint URL: {expected_endpoint_url}"
                            ),
                            endpointId=expected_endpoint_id,
                            endpointUrl=expected_endpoint_raw_url,
                        )
                    elif expected_matching_endpoint is None:
                        required_csv = ",".join(sorted(required_events))
                        missing_csv = ",".join(sorted(expected_missing_events or required_events))
                        payload = _build_payload(
                            healthy=False,
                            reason=(
                                "Configured Stripe webhook endpoint is missing required event subscriptions. "
                                f"Required={required_csv}; Missing={missing_csv}"
                            ),
                            endpointId=expected_endpoint_id,
                            endpointUrl=expected_endpoint_raw_url,
                        )
                    else:
                        payload = _build_payload(
                            healthy=True,
                            reason="Stripe webhook health check passed.",
                            endpointId=str(expected_matching_endpoint.get("id") or "").strip() or None,
                            endpointUrl=str(expected_matching_endpoint.get("url") or "").strip() or None,
                        )
                else:
                    if enforced_for_checkout:
                        payload = _build_payload(
                            healthy=False,
                            reason=(
                                "Missing STRIPE_WEBHOOK_ENDPOINT_URL. "
                                "Set a specific webhook endpoint URL before enabling checkout."
                            ),
                        )
                    elif fallback_matching_endpoint is None:
                        if enabled_endpoint_count == 0:
                            reason = "No enabled Stripe webhook endpoint is configured for this account."
                        else:
                            required_csv = ",".join(sorted(required_events))
                            missing_csv = ",".join(sorted(fallback_missing_events or required_events))
                            reason = (
                                "Enabled Stripe webhook endpoints are missing required event subscriptions. "
                                f"Required={required_csv}; Missing={missing_csv}"
                            )
                        payload = _build_payload(
                            healthy=False,
                            reason=reason,
                        )
                    else:
                        payload = _build_payload(
                            healthy=True,
                            reason="Stripe webhook health check passed.",
                            endpointId=str(fallback_matching_endpoint.get("id") or "").strip() or None,
                            endpointUrl=str(fallback_matching_endpoint.get("url") or "").strip() or None,
                        )

    ttl_seconds = _resolve_webhook_health_cache_ttl_seconds()
    _WEBHOOK_HEALTH_CACHE["payload"] = dict(payload)
    _WEBHOOK_HEALTH_CACHE["expires_at"] = now + max(1, ttl_seconds)
    return payload


def list_recent_checkout_completion_events(
    *,
    created_gte: Optional[int] = None,
    limit: Optional[int] = None,
) -> list[Dict[str, Any]]:
    """List recent Stripe checkout.session.completed events in reverse chronology."""
    stripe = _load_stripe_module()
    secret_key = env_value("STRIPE_SECRET_KEY")
    if not secret_key:
        raise BillingConfigError("Missing STRIPE_SECRET_KEY.")
    stripe.api_key = secret_key

    event_api = getattr(stripe, "Event", None)
    list_event_fn = getattr(event_api, "list", None)
    if not callable(list_event_fn):
        raise BillingConfigError("Stripe SDK does not expose Event.list for reconciliation.")

    resolved_limit = _resolve_reconcile_checkout_events_limit(limit)
    collected: list[Dict[str, Any]] = []
    starting_after: Optional[str] = None

    while len(collected) < resolved_limit:
        page_limit = min(100, resolved_limit - len(collected))
        query: Dict[str, Any] = {
            "type": "checkout.session.completed",
            "limit": page_limit,
        }
        if created_gte is not None:
            try:
                normalized_created_gte = int(created_gte)
            except (TypeError, ValueError):
                normalized_created_gte = 0
            if normalized_created_gte > 0:
                query["created"] = {"gte": normalized_created_gte}
        if starting_after:
            query["starting_after"] = starting_after

        page = list_event_fn(**query)
        page_payload = _stripe_object_to_dict(page)
        events = _extract_list_data(page)
        if not events:
            break
        collected.extend(events)
        has_more = bool(page_payload.get("has_more"))
        if not has_more:
            break
        starting_after = str(events[-1].get("id") or "").strip() or None
        if not starting_after:
            break

    return collected[:resolved_limit]


def retrieve_checkout_session(*, session_id: str) -> Dict[str, Any]:
    """Fetch a specific Stripe Checkout session for targeted self reconciliation."""
    stripe = _load_stripe_module()
    secret_key = env_value("STRIPE_SECRET_KEY")
    normalized_session_id = (session_id or "").strip()
    if not secret_key:
        raise BillingConfigError("Missing STRIPE_SECRET_KEY.")
    if not normalized_session_id:
        raise BillingConfigError("Missing Stripe checkout session id.")
    stripe.api_key = secret_key

    checkout_api = getattr(stripe, "checkout", None)
    session_api = getattr(checkout_api, "Session", None)
    retrieve_session_fn = getattr(session_api, "retrieve", None)
    if not callable(retrieve_session_fn):
        raise BillingConfigError("Stripe SDK does not expose checkout.Session.retrieve for reconciliation.")

    try:
        session = retrieve_session_fn(normalized_session_id)
    except Exception as exc:
        exc_name = exc.__class__.__name__.strip().lower()
        exc_code = str(getattr(exc, "code", "") or "").strip().lower()
        exc_message = str(exc).strip().lower()
        exc_status = getattr(exc, "http_status", None)
        if (
            exc_name == "invalidrequesterror"
            and (
                exc_code == "resource_missing"
                or exc_status == 404
                or "no such checkout.session" in exc_message
                or "no such checkout session" in exc_message
            )
        ):
            raise BillingCheckoutSessionNotFoundError("Stripe checkout session was not found.") from exc
        raise
    payload = _stripe_object_to_dict(session)
    if not payload:
        raise BillingCheckoutSessionNotFoundError("Stripe checkout session was not found.")
    return payload


def resolve_refill_credit_pack_size() -> int:
    raw = env_value("STRIPE_REFILL_CREDITS")
    if not raw:
        return 500
    try:
        value = int(raw)
    except ValueError:
        return 500
    return value if value > 0 else 500


def resolve_refill_credit_pack_size_for_price(price_id: Optional[str]) -> Optional[int]:
    normalized_price_id = (price_id or "").strip()
    if not normalized_price_id:
        return None
    for price_env, credit_env in REFILL_PRICE_CREDIT_ENV_MAP:
        configured_price_id = (env_value(price_env) or "").strip()
        if not configured_price_id or configured_price_id != normalized_price_id:
            continue
        raw_credits = env_value(credit_env)
        if not raw_credits:
            return 500
        try:
            parsed_credits = int(raw_credits)
        except ValueError:
            return 500
        return parsed_credits if parsed_credits > 0 else 500
    return None


def resolve_price_id_for_checkout_kind(kind: str) -> Optional[str]:
    try:
        return _resolve_plan(kind).price_id
    except BillingConfigError:
        return None


def resolve_pro_price_ids() -> set[str]:
    values = [env_value("STRIPE_PRICE_PRO_MONTHLY"), env_value("STRIPE_PRICE_PRO_YEARLY")]
    return {value for value in values if value}


def is_pro_price_id(price_id: Optional[str]) -> bool:
    normalized = (price_id or "").strip()
    if not normalized:
        return False
    return normalized in resolve_pro_price_ids()


def is_subscription_active(status: Optional[str]) -> bool:
    normalized = (status or "").strip().lower()
    return normalized in ACTIVE_SUBSCRIPTION_STATUSES


def create_checkout_session(
    *,
    user_id: str,
    user_email: Optional[str],
    checkout_kind: str,
    customer_id: Optional[str] = None,
    checkout_attempt_id: Optional[str] = None,
) -> Dict[str, Optional[str]]:
    """Create a Stripe Checkout session and return id/url payload."""
    stripe = _load_stripe_module()
    secret_key = env_value("STRIPE_SECRET_KEY")
    if not secret_key:
        raise BillingConfigError("Missing STRIPE_SECRET_KEY.")

    plan = _resolve_plan(checkout_kind)
    success_url, cancel_url = _resolve_checkout_urls()
    metadata = {
        "userId": (user_id or "").strip(),
        "checkoutKind": plan.kind,
        "checkoutPriceId": plan.price_id,
    }
    normalized_checkout_attempt_id = (checkout_attempt_id or "").strip() or None
    if not metadata["userId"]:
        raise BillingConfigError("Missing user id for checkout session.")
    if normalized_checkout_attempt_id:
        metadata["checkoutAttemptId"] = normalized_checkout_attempt_id
    if plan.kind == CHECKOUT_KIND_REFILL_500:
        refill_credits = resolve_refill_credit_pack_size_for_price(plan.price_id)
        if refill_credits is None:
            raise BillingConfigError("Missing refill credit configuration for STRIPE_PRICE_REFILL_500.")
        metadata["refillCredits"] = str(refill_credits)

    resolved_customer_id: Optional[str] = None

    stripe.api_key = secret_key
    if plan.kind == CHECKOUT_KIND_REFILL_500:
        resolved_customer_id = _resolve_or_create_customer_id(
            stripe=stripe,
            user_id=metadata["userId"],
            user_email=user_email,
            customer_id=customer_id,
        )
        existing_open_refill_checkout = _find_open_refill_checkout_session(
            stripe=stripe,
            user_id=metadata["userId"],
            customer_id=resolved_customer_id,
            checkout_price_id=plan.price_id,
        )
        if existing_open_refill_checkout:
            return existing_open_refill_checkout
    if plan.mode == "subscription":
        resolved_customer_id = _resolve_or_create_customer_id(
            stripe=stripe,
            user_id=metadata["userId"],
            user_email=user_email,
            customer_id=customer_id,
        )
        existing_open_pro_checkout = _find_open_pro_checkout_session(
            stripe=stripe,
            user_id=metadata["userId"],
            customer_id=resolved_customer_id,
            checkout_price_id=plan.price_id,
        )
        if existing_open_pro_checkout:
            return existing_open_pro_checkout
        customer_ids_to_check: list[str] = []
        if resolved_customer_id:
            customer_ids_to_check.append(resolved_customer_id)
        for candidate_customer_id in _list_existing_customer_ids_for_user(
            stripe=stripe,
            user_id=metadata["userId"],
            user_email=user_email,
        ):
            if candidate_customer_id in customer_ids_to_check:
                continue
            customer_ids_to_check.append(candidate_customer_id)
        for existing_customer_id in customer_ids_to_check:
            existing_open_pro_checkout = _find_open_pro_checkout_session(
                stripe=stripe,
                user_id=metadata["userId"],
                customer_id=existing_customer_id,
                checkout_price_id=plan.price_id,
            )
            if existing_open_pro_checkout:
                return existing_open_pro_checkout

        active_subscription_id: Optional[str] = None
        for existing_customer_id in customer_ids_to_check:
            active_subscription_id = _find_active_pro_subscription_for_customer(
                stripe=stripe,
                customer_id=existing_customer_id,
            )
            if active_subscription_id:
                break
        if active_subscription_id:
            raise BillingCheckoutConflictError(
                "An active Pro subscription already exists for this user. Manage the existing subscription or contact support."
            )

    create_payload: Dict[str, Any] = {
        "mode": plan.mode,
        "line_items": [{"price": plan.price_id, "quantity": 1}],
        "success_url": success_url,
        "cancel_url": cancel_url,
        "client_reference_id": metadata["userId"],
        "metadata": metadata,
    }
    if plan.mode == "subscription":
        create_payload["subscription_data"] = {"metadata": metadata}
        if resolved_customer_id:
            create_payload["customer"] = resolved_customer_id
        elif user_email:
            create_payload["customer_email"] = user_email
    elif resolved_customer_id:
        create_payload["customer"] = resolved_customer_id
    elif user_email:
        create_payload["customer_email"] = user_email

    session = stripe.checkout.Session.create(
        **create_payload,
        idempotency_key=_resolve_checkout_idempotency_key(
            user_id=metadata["userId"],
            checkout_kind=plan.kind,
            checkout_attempt_id=normalized_checkout_attempt_id,
        ),
    )
    session_payload = _stripe_object_to_dict(session)
    session_id = str(getattr(session, "id", "") or "")
    session_url = str(getattr(session, "url", "") or "")
    if not session_id or not session_url:
        raise BillingConfigError("Stripe Checkout did not return a redirect URL.")
    resolved_customer_id = first_nonempty(
        [
            str(session_payload.get("customer") or ""),
            str(getattr(session, "customer", "") or ""),
            resolved_customer_id,
        ]
    )
    return {
        "sessionId": session_id,
        "url": session_url,
        "customerId": resolved_customer_id,
        "checkoutAttemptId": normalized_checkout_attempt_id,
        "checkoutPriceId": plan.price_id,
    }


def _extract_subscription_price_id(subscription_obj: Dict[str, Any]) -> Optional[str]:
    items = subscription_obj.get("items") if isinstance(subscription_obj, dict) else None
    data = items.get("data") if isinstance(items, dict) else None
    if not isinstance(data, list) or not data:
        return None
    first_item = data[0]
    if not isinstance(first_item, dict):
        return None
    price = first_item.get("price")
    if not isinstance(price, dict):
        return None
    price_id = str(price.get("id") or "").strip()
    return price_id or None


def cancel_subscription_at_period_end(*, subscription_id: str) -> CancelSubscriptionResult:
    """Mark a subscription to cancel at the end of the current billing period."""
    normalized_subscription_id = (subscription_id or "").strip()
    if not normalized_subscription_id:
        raise BillingConfigError("Missing Stripe subscription id.")

    stripe = _load_stripe_module()
    secret_key = env_value("STRIPE_SECRET_KEY")
    if not secret_key:
        raise BillingConfigError("Missing STRIPE_SECRET_KEY.")

    stripe.api_key = secret_key
    subscription = stripe.Subscription.modify(
        normalized_subscription_id,
        cancel_at_period_end=True,
    )
    payload = _stripe_object_to_dict(subscription)
    status_raw = str(payload.get("status") or "").strip().lower()
    status = status_raw or None
    cancel_at_period_end = bool(payload.get("cancel_at_period_end"))
    cancel_at_raw = payload.get("cancel_at")
    current_period_end_raw = payload.get("current_period_end")
    cancel_at = int(cancel_at_raw) if isinstance(cancel_at_raw, int) else None
    current_period_end = int(current_period_end_raw) if isinstance(current_period_end_raw, int) else None
    customer_id = first_nonempty([str(payload.get("customer") or "")])
    price_id = _extract_subscription_price_id(payload)
    return CancelSubscriptionResult(
        status=status,
        cancel_at_period_end=cancel_at_period_end,
        cancel_at=cancel_at,
        current_period_end=current_period_end,
        customer_id=customer_id,
        price_id=price_id,
    )


def construct_webhook_event(*, payload: bytes, signature: str) -> Dict[str, Any]:
    """Validate and decode a Stripe webhook event."""
    stripe = _load_stripe_module()
    secret_key = env_value("STRIPE_SECRET_KEY")
    webhook_secret = env_value("STRIPE_WEBHOOK_SECRET")
    if not secret_key:
        raise BillingConfigError("Missing STRIPE_SECRET_KEY.")
    if not webhook_secret:
        raise BillingConfigError("Missing STRIPE_WEBHOOK_SECRET.")
    if not signature:
        raise ValueError("Missing Stripe-Signature header.")
    stripe.api_key = secret_key
    event = stripe.Webhook.construct_event(payload, signature, webhook_secret)
    converted = _stripe_object_to_dict(event)
    if converted:
        return converted
    raise ValueError("Unable to parse Stripe webhook event.")


def extract_price_ids_from_invoice(invoice: Dict[str, Any]) -> list[str]:
    """Collect any invoice line price ids from a webhook payload."""
    price_ids: list[str] = []
    lines = invoice.get("lines") if isinstance(invoice, dict) else None
    data = lines.get("data") if isinstance(lines, dict) else None
    if not isinstance(data, list):
        return price_ids
    for entry in data:
        if not isinstance(entry, dict):
            continue
        price = entry.get("price")
        price_id: Optional[str] = None
        if isinstance(price, dict):
            price_id = str(price.get("id") or "").strip() or None
        elif price:
            price_id = str(price).strip() or None
        if not price_id:
            plan = entry.get("plan")
            if isinstance(plan, dict):
                price_id = str(plan.get("id") or "").strip() or None
            elif plan:
                price_id = str(plan).strip() or None
        if price_id:
            price_ids.append(price_id)
    return price_ids


def first_nonempty(values: Iterable[Optional[str]]) -> Optional[str]:
    for value in values:
        normalized = (value or "").strip()
        if normalized:
            return normalized
    return None
