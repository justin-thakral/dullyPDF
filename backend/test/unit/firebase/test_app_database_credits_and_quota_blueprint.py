"""Unit tests for credit and quota logic in `backend/firebaseDB/app_database.py`."""

import pytest

from backend.firebaseDB import user_database as adb
from backend.test.unit.firebase._fakes import FakeFirestoreClient


@pytest.fixture(autouse=True)
def _no_transaction_wrapper(mocker):
    mocker.patch(
        "backend.firebaseDB.user_database.firebase_firestore.transactional",
        side_effect=lambda fn: fn,
    )


def test_resolve_openai_credits_remaining_handles_zero_missing_and_invalid() -> None:
    assert adb._resolve_openai_credits_remaining({adb.OPENAI_CREDITS_FIELD: 0}) == 0
    assert adb._resolve_openai_credits_remaining({}) == adb.BASE_OPENAI_CREDITS
    assert adb._resolve_openai_credits_remaining({adb.OPENAI_CREDITS_FIELD: "not-int"}) == adb.BASE_OPENAI_CREDITS


def test_apply_processed_stripe_event_id_does_not_trim_when_max_is_zero(mocker) -> None:
    mocker.patch("backend.firebaseDB.user_database.STRIPE_MAX_PROCESSED_EVENTS", 0)

    processed, duplicate = adb._apply_processed_stripe_event_id(["evt_1", "evt_2"], "evt_3")

    assert duplicate is False
    assert processed == ["evt_1", "evt_2", "evt_3"]


def test_consume_openai_credits_rejects_missing_uid() -> None:
    with pytest.raises(ValueError, match="Missing firebase uid"):
        adb.consume_openai_credits("", credits=1)


def test_consume_openai_credits_god_role_bypasses_storage(mocker) -> None:
    client = FakeFirestoreClient()
    client.collection(adb.USERS_COLLECTION).document("uid-1").seed({adb.ROLE_FIELD: adb.ROLE_GOD})
    mocker.patch("backend.firebaseDB.user_database.get_firestore_client", return_value=client)
    remaining, allowed = adb.consume_openai_credits("uid-1", credits=5, role=adb.ROLE_GOD)
    assert (remaining, allowed) == (-1, True)
    assert client.transactions[0].set_calls == []


def test_consume_openai_credits_returns_false_when_insufficient(mocker) -> None:
    client = FakeFirestoreClient()
    client.collection(adb.USERS_COLLECTION).document("uid-1").seed({adb.OPENAI_CREDITS_FIELD: 1})
    mocker.patch("backend.firebaseDB.user_database.get_firestore_client", return_value=client)

    remaining, allowed = adb.consume_openai_credits("uid-1", credits=2, role=adb.ROLE_BASE)

    assert remaining == 1
    assert allowed is False
    txn = client.transactions[0]
    assert txn.set_calls == []


def test_consume_openai_credits_coerces_invalid_credit_count_to_one(mocker) -> None:
    client = FakeFirestoreClient()
    doc = client.collection(adb.USERS_COLLECTION).document("uid-1").seed({adb.OPENAI_CREDITS_FIELD: "5"})
    mocker.patch("backend.firebaseDB.user_database.get_firestore_client", return_value=client)
    mocker.patch("backend.firebaseDB.user_database.now_iso", return_value="ts-updated")

    remaining, allowed = adb.consume_openai_credits("uid-1", credits="bad", role=adb.ROLE_BASE)

    assert (remaining, allowed) == (4, True)
    assert doc.get().to_dict()[adb.OPENAI_CREDITS_FIELD] == 4
    assert doc.get().to_dict()["updated_at"] == "ts-updated"
    assert client.transactions[0].set_calls[-1]["merge"] is True


def test_consume_openai_credits_coerces_non_positive_credit_count_to_one(mocker) -> None:
    client = FakeFirestoreClient()
    doc = client.collection(adb.USERS_COLLECTION).document("uid-1").seed({adb.OPENAI_CREDITS_FIELD: 5})
    mocker.patch("backend.firebaseDB.user_database.get_firestore_client", return_value=client)
    mocker.patch("backend.firebaseDB.user_database.now_iso", return_value="ts-updated")

    remaining, allowed = adb.consume_openai_credits("uid-1", credits=0, role=adb.ROLE_BASE)

    assert (remaining, allowed) == (4, True)
    assert doc.get().to_dict()[adb.OPENAI_CREDITS_FIELD] == 4


def test_refund_openai_credits_rejects_missing_uid() -> None:
    with pytest.raises(ValueError, match="Missing firebase uid"):
        adb.refund_openai_credits("", credits=1)


def test_refund_openai_credits_god_role_bypasses_storage(mocker) -> None:
    client = FakeFirestoreClient()
    client.collection(adb.USERS_COLLECTION).document("uid-1").seed({adb.ROLE_FIELD: adb.ROLE_GOD})
    mocker.patch("backend.firebaseDB.user_database.get_firestore_client", return_value=client)
    remaining = adb.refund_openai_credits("uid-1", credits=3, role=adb.ROLE_GOD)
    assert remaining == -1
    assert client.transactions[0].set_calls == []


def test_consume_openai_credits_ignores_requested_pro_role_when_stored_base(mocker) -> None:
    client = FakeFirestoreClient()
    client.collection(adb.USERS_COLLECTION).document("uid-base").seed(
        {
            adb.ROLE_FIELD: adb.ROLE_BASE,
            adb.OPENAI_CREDITS_FIELD: 2,
            adb.OPENAI_CREDITS_MONTHLY_FIELD: 500,
            adb.OPENAI_CREDITS_REFILL_FIELD: 500,
            adb.OPENAI_CREDITS_MONTHLY_CYCLE_FIELD: adb._current_month_cycle_key(),
        }
    )
    mocker.patch("backend.firebaseDB.user_database.get_firestore_client", return_value=client)

    remaining, allowed, breakdown = adb.consume_openai_credits(
        "uid-base",
        credits=3,
        role=adb.ROLE_PRO,
        include_breakdown=True,
    )

    assert (remaining, allowed) == (2, False)
    assert breakdown == {"base": 0, "monthly": 0, "refill": 0}


def test_consume_openai_credits_ignores_requested_god_role_when_stored_base(mocker) -> None:
    client = FakeFirestoreClient()
    doc = client.collection(adb.USERS_COLLECTION).document("uid-base").seed(
        {
            adb.ROLE_FIELD: adb.ROLE_BASE,
            adb.OPENAI_CREDITS_FIELD: 2,
        }
    )
    mocker.patch("backend.firebaseDB.user_database.get_firestore_client", return_value=client)
    mocker.patch("backend.firebaseDB.user_database.now_iso", return_value="ts-base-consume")

    remaining, allowed = adb.consume_openai_credits("uid-base", credits=1, role=adb.ROLE_GOD)

    assert (remaining, allowed) == (1, True)
    assert doc.get().to_dict()[adb.OPENAI_CREDITS_FIELD] == 1


def test_refund_openai_credits_coerces_invalid_refund_count_to_one(mocker) -> None:
    client = FakeFirestoreClient()
    doc = client.collection(adb.USERS_COLLECTION).document("uid-1").seed({adb.OPENAI_CREDITS_FIELD: 2})
    mocker.patch("backend.firebaseDB.user_database.get_firestore_client", return_value=client)
    mocker.patch("backend.firebaseDB.user_database.now_iso", return_value="ts-refund")

    remaining = adb.refund_openai_credits("uid-1", credits="bad", role=adb.ROLE_BASE)

    assert remaining == 3
    assert doc.get().to_dict()[adb.OPENAI_CREDITS_FIELD] == 3
    assert doc.get().to_dict()["updated_at"] == "ts-refund"
    assert client.transactions[0].set_calls[-1]["merge"] is True


def test_refund_openai_credits_coerces_non_positive_refund_count_to_one(mocker) -> None:
    client = FakeFirestoreClient()
    doc = client.collection(adb.USERS_COLLECTION).document("uid-1").seed({adb.OPENAI_CREDITS_FIELD: 2})
    mocker.patch("backend.firebaseDB.user_database.get_firestore_client", return_value=client)
    mocker.patch("backend.firebaseDB.user_database.now_iso", return_value="ts-refund")

    remaining = adb.refund_openai_credits("uid-1", credits=-5, role=adb.ROLE_BASE)

    assert remaining == 3
    assert doc.get().to_dict()[adb.OPENAI_CREDITS_FIELD] == 3


def test_consume_rename_quota_rejects_missing_uid() -> None:
    with pytest.raises(ValueError, match="Missing firebase uid"):
        adb.consume_rename_quota("")


def test_consume_rename_quota_coerces_invalid_count_and_increments(mocker) -> None:
    client = FakeFirestoreClient()
    doc = client.collection(adb.USERS_COLLECTION).document("uid-1").seed({adb.RENAME_COUNT_FIELD: "bad"})
    mocker.patch("backend.firebaseDB.user_database.get_firestore_client", return_value=client)
    mocker.patch("backend.firebaseDB.user_database.now_iso", return_value="ts-rename")

    count, allowed = adb.consume_rename_quota("uid-1", limit=2)

    assert (count, allowed) == (1, True)
    assert doc.get().to_dict()[adb.RENAME_COUNT_FIELD] == 1
    assert doc.get().to_dict()["updated_at"] == "ts-rename"


def test_consume_rename_quota_blocks_when_limit_reached(mocker) -> None:
    client = FakeFirestoreClient()
    client.collection(adb.USERS_COLLECTION).document("uid-1").seed({adb.RENAME_COUNT_FIELD: 2})
    mocker.patch("backend.firebaseDB.user_database.get_firestore_client", return_value=client)

    count, allowed = adb.consume_rename_quota("uid-1", limit=2)

    assert (count, allowed) == (2, False)
    assert client.transactions[0].set_calls == []


def test_consume_rename_quota_backfills_create_fields_when_doc_missing(mocker) -> None:
    client = FakeFirestoreClient()
    doc = client.collection(adb.USERS_COLLECTION).document("uid-1")
    mocker.patch("backend.firebaseDB.user_database.get_firestore_client", return_value=client)
    mocker.patch("backend.firebaseDB.user_database.now_iso", return_value="ts-created")

    count, allowed = adb.consume_rename_quota("uid-1", limit=3)

    assert (count, allowed) == (1, True)
    payload = doc.get().to_dict()
    assert payload[adb.RENAME_COUNT_FIELD] == 1
    assert payload["firebase_uid"] == "uid-1"
    assert payload["created_at"] == "ts-created"


def test_get_user_profile_handles_missing_uid_and_missing_doc(mocker) -> None:
    client = FakeFirestoreClient()
    mocker.patch("backend.firebaseDB.user_database.get_firestore_client", return_value=client)

    assert adb.get_user_profile("") is None
    assert adb.get_user_profile("uid-missing") is None


def test_get_user_profile_returns_none_credits_for_god_role(mocker) -> None:
    client = FakeFirestoreClient()
    client.collection(adb.USERS_COLLECTION).document("uid-1").seed(
        {
            "email": "god@example.com",
            "displayName": "God",
            adb.ROLE_FIELD: adb.ROLE_GOD,
            adb.OPENAI_CREDITS_FIELD: 99,
        }
    )
    mocker.patch("backend.firebaseDB.user_database.get_firestore_client", return_value=client)

    profile = adb.get_user_profile("uid-1")

    assert profile is not None
    assert profile.role == adb.ROLE_GOD
    assert profile.openai_credits_remaining is None


def test_get_user_profile_resolves_invalid_credit_to_base_for_base_role(mocker) -> None:
    client = FakeFirestoreClient()
    client.collection(adb.USERS_COLLECTION).document("uid-1").seed(
        {
            "email": "base@example.com",
            "displayName": "Base",
            adb.ROLE_FIELD: adb.ROLE_BASE,
            adb.OPENAI_CREDITS_FIELD: "bad-value",
        }
    )
    mocker.patch("backend.firebaseDB.user_database.get_firestore_client", return_value=client)

    profile = adb.get_user_profile("uid-1")

    assert profile is not None
    assert profile.role == adb.ROLE_BASE
    assert profile.openai_credits_remaining == adb.BASE_OPENAI_CREDITS


# ---------------------------------------------------------------------------
# Edge-case: consume_openai_credits happy path with valid integer credits
# ---------------------------------------------------------------------------
# When credits=2 and the user has 5 remaining, the transaction should deduct
# exactly 2 and return (3, True).
def test_consume_openai_credits_happy_path_deducts_valid_integer(mocker) -> None:
    client = FakeFirestoreClient()
    doc = client.collection(adb.USERS_COLLECTION).document("uid-1").seed(
        {adb.OPENAI_CREDITS_FIELD: 5}
    )
    mocker.patch("backend.firebaseDB.user_database.get_firestore_client", return_value=client)
    mocker.patch("backend.firebaseDB.user_database.now_iso", return_value="ts-consume")

    remaining, allowed = adb.consume_openai_credits("uid-1", credits=2, role=adb.ROLE_BASE)

    assert remaining == 3
    assert allowed is True
    stored = doc.get().to_dict()
    assert stored[adb.OPENAI_CREDITS_FIELD] == 3
    assert stored["updated_at"] == "ts-consume"
    # The transaction should have used merge=True
    assert client.transactions[0].set_calls[-1]["merge"] is True


# ---------------------------------------------------------------------------
# Edge-case: refund_openai_credits happy path with valid integer refund
# ---------------------------------------------------------------------------
# When credits=3 and the user has 2 remaining, the refund should yield 5.
def test_refund_openai_credits_happy_path_adds_valid_integer(mocker) -> None:
    client = FakeFirestoreClient()
    doc = client.collection(adb.USERS_COLLECTION).document("uid-1").seed(
        {adb.OPENAI_CREDITS_FIELD: 2}
    )
    mocker.patch("backend.firebaseDB.user_database.get_firestore_client", return_value=client)
    mocker.patch("backend.firebaseDB.user_database.now_iso", return_value="ts-refund")

    remaining = adb.refund_openai_credits("uid-1", credits=3, role=adb.ROLE_BASE)

    assert remaining == 5
    stored = doc.get().to_dict()
    assert stored[adb.OPENAI_CREDITS_FIELD] == 5
    assert stored["updated_at"] == "ts-refund"
    assert client.transactions[0].set_calls[-1]["merge"] is True


# ---------------------------------------------------------------------------
# Edge-case: _resolve_openai_credits_remaining with non-numeric stored value
# ---------------------------------------------------------------------------
# When the stored value is a type that cannot be converted to int (e.g. a list),
# the function should catch TypeError and fall back to BASE_OPENAI_CREDITS.
def test_resolve_openai_credits_remaining_with_non_numeric_type_falls_back(mocker) -> None:
    # A list triggers TypeError in int() -- distinct from the "not-int" string
    # tested above which triggers ValueError.
    result = adb._resolve_openai_credits_remaining({adb.OPENAI_CREDITS_FIELD: [1, 2]})
    assert result == adb.BASE_OPENAI_CREDITS

    # A dict also triggers TypeError
    result_dict = adb._resolve_openai_credits_remaining({adb.OPENAI_CREDITS_FIELD: {"nested": True}})
    assert result_dict == adb.BASE_OPENAI_CREDITS

    # None stored explicitly should fall back via the `raw is None` path
    result_none = adb._resolve_openai_credits_remaining({adb.OPENAI_CREDITS_FIELD: None})
    assert result_none == adb.BASE_OPENAI_CREDITS


def test_consume_openai_credits_pro_uses_monthly_then_refill_with_breakdown(mocker) -> None:
    client = FakeFirestoreClient()
    doc = client.collection(adb.USERS_COLLECTION).document("uid-pro").seed(
        {
            adb.ROLE_FIELD: adb.ROLE_PRO,
            adb.OPENAI_CREDITS_MONTHLY_FIELD: 3,
            adb.OPENAI_CREDITS_REFILL_FIELD: 2,
            adb.OPENAI_CREDITS_MONTHLY_CYCLE_FIELD: adb._current_month_cycle_key(),
        }
    )
    mocker.patch("backend.firebaseDB.user_database.get_firestore_client", return_value=client)
    mocker.patch("backend.firebaseDB.user_database.now_iso", return_value="ts-consume-pro")

    remaining, allowed, breakdown = adb.consume_openai_credits(
        "uid-pro",
        credits=4,
        role=adb.ROLE_PRO,
        include_breakdown=True,
    )

    assert (remaining, allowed) == (1, True)
    assert breakdown == {"base": 0, "monthly": 3, "refill": 1}
    stored = doc.get().to_dict()
    assert stored[adb.OPENAI_CREDITS_MONTHLY_FIELD] == 0
    assert stored[adb.OPENAI_CREDITS_REFILL_FIELD] == 1
    assert stored["updated_at"] == "ts-consume-pro"


def test_consume_openai_credits_pro_returns_false_when_combined_pools_insufficient(mocker) -> None:
    client = FakeFirestoreClient()
    client.collection(adb.USERS_COLLECTION).document("uid-pro").seed(
        {
            adb.ROLE_FIELD: adb.ROLE_PRO,
            adb.OPENAI_CREDITS_MONTHLY_FIELD: 1,
            adb.OPENAI_CREDITS_REFILL_FIELD: 1,
            adb.OPENAI_CREDITS_MONTHLY_CYCLE_FIELD: adb._current_month_cycle_key(),
        }
    )
    mocker.patch("backend.firebaseDB.user_database.get_firestore_client", return_value=client)

    remaining, allowed, breakdown = adb.consume_openai_credits(
        "uid-pro",
        credits=3,
        role=adb.ROLE_PRO,
        include_breakdown=True,
    )

    assert (remaining, allowed) == (2, False)
    assert breakdown == {"base": 0, "monthly": 0, "refill": 0}
    assert client.transactions[0].set_calls == []


def test_consume_openai_credits_base_cannot_spend_refill_pool(mocker) -> None:
    client = FakeFirestoreClient()
    client.collection(adb.USERS_COLLECTION).document("uid-base").seed(
        {
            adb.ROLE_FIELD: adb.ROLE_BASE,
            adb.OPENAI_CREDITS_FIELD: 0,
            adb.OPENAI_CREDITS_REFILL_FIELD: 99,
        }
    )
    mocker.patch("backend.firebaseDB.user_database.get_firestore_client", return_value=client)

    remaining, allowed, breakdown = adb.consume_openai_credits(
        "uid-base",
        credits=1,
        role=adb.ROLE_BASE,
        include_breakdown=True,
    )

    assert (remaining, allowed) == (0, False)
    assert breakdown == {"base": 0, "monthly": 0, "refill": 0}


def test_refund_openai_credits_pro_restores_specific_pools_from_breakdown(mocker) -> None:
    client = FakeFirestoreClient()
    doc = client.collection(adb.USERS_COLLECTION).document("uid-pro").seed(
        {
            adb.ROLE_FIELD: adb.ROLE_PRO,
            adb.OPENAI_CREDITS_MONTHLY_FIELD: 0,
            adb.OPENAI_CREDITS_REFILL_FIELD: 1,
            adb.OPENAI_CREDITS_MONTHLY_CYCLE_FIELD: adb._current_month_cycle_key(),
        }
    )
    mocker.patch("backend.firebaseDB.user_database.get_firestore_client", return_value=client)
    mocker.patch("backend.firebaseDB.user_database.now_iso", return_value="ts-refund-pro")

    available = adb.refund_openai_credits(
        "uid-pro",
        credits=4,
        role=adb.ROLE_PRO,
        credit_breakdown={"monthly": 3, "refill": 1},
    )

    assert available == 5
    stored = doc.get().to_dict()
    assert stored[adb.OPENAI_CREDITS_MONTHLY_FIELD] == 3
    assert stored[adb.OPENAI_CREDITS_REFILL_FIELD] == 2
    assert stored["updated_at"] == "ts-refund-pro"


def test_get_user_profile_base_role_reports_locked_refill_credits(mocker) -> None:
    client = FakeFirestoreClient()
    client.collection(adb.USERS_COLLECTION).document("uid-base").seed(
        {
            adb.ROLE_FIELD: adb.ROLE_BASE,
            adb.OPENAI_CREDITS_FIELD: 2,
            adb.OPENAI_CREDITS_REFILL_FIELD: 5,
            "email": "base@example.com",
            "displayName": "Base",
        }
    )
    mocker.patch("backend.firebaseDB.user_database.get_firestore_client", return_value=client)

    profile = adb.get_user_profile("uid-base")

    assert profile is not None
    assert profile.role == adb.ROLE_BASE
    assert profile.openai_credits_remaining == 2
    assert profile.openai_credits_refill_remaining == 5
    assert profile.openai_credits_available == 2
    assert profile.refill_credits_locked is True


def test_consume_openai_credits_pro_resets_monthly_pool_when_cycle_stale(mocker) -> None:
    client = FakeFirestoreClient()
    doc = client.collection(adb.USERS_COLLECTION).document("uid-pro").seed(
        {
            adb.ROLE_FIELD: adb.ROLE_PRO,
            adb.OPENAI_CREDITS_MONTHLY_FIELD: 12,
            adb.OPENAI_CREDITS_REFILL_FIELD: 20,
            adb.OPENAI_CREDITS_MONTHLY_CYCLE_FIELD: "2026-01",
        }
    )
    mocker.patch("backend.firebaseDB.user_database.get_firestore_client", return_value=client)
    mocker.patch("backend.firebaseDB.user_database._current_month_cycle_key", return_value="2026-02")
    mocker.patch("backend.firebaseDB.user_database.now_iso", return_value="ts-cycle-reset")

    remaining, allowed, breakdown = adb.consume_openai_credits(
        "uid-pro",
        credits=15,
        role=adb.ROLE_PRO,
        include_breakdown=True,
    )

    assert (remaining, allowed) == (505, True)
    assert breakdown == {"base": 0, "monthly": 15, "refill": 0}
    stored = doc.get().to_dict()
    assert stored[adb.OPENAI_CREDITS_MONTHLY_FIELD] == adb.PRO_MONTHLY_OPENAI_CREDITS - 15
    assert stored[adb.OPENAI_CREDITS_REFILL_FIELD] == 20
    assert stored[adb.OPENAI_CREDITS_MONTHLY_CYCLE_FIELD] == "2026-02"
    assert stored["updated_at"] == "ts-cycle-reset"


def test_refund_openai_credits_pro_legacy_refund_goes_to_refill_pool(mocker) -> None:
    client = FakeFirestoreClient()
    doc = client.collection(adb.USERS_COLLECTION).document("uid-pro").seed(
        {
            adb.ROLE_FIELD: adb.ROLE_PRO,
            adb.OPENAI_CREDITS_MONTHLY_FIELD: 0,
            adb.OPENAI_CREDITS_REFILL_FIELD: 2,
            adb.OPENAI_CREDITS_MONTHLY_CYCLE_FIELD: "2026-01",
        }
    )
    mocker.patch("backend.firebaseDB.user_database.get_firestore_client", return_value=client)
    mocker.patch("backend.firebaseDB.user_database._current_month_cycle_key", return_value="2026-02")
    mocker.patch("backend.firebaseDB.user_database.now_iso", return_value="ts-refund-legacy")

    available = adb.refund_openai_credits(
        "uid-pro",
        credits=3,
        role=adb.ROLE_PRO,
        credit_breakdown=None,
    )

    assert available == adb.PRO_MONTHLY_OPENAI_CREDITS + 5
    stored = doc.get().to_dict()
    assert stored[adb.OPENAI_CREDITS_MONTHLY_FIELD] == adb.PRO_MONTHLY_OPENAI_CREDITS
    assert stored[adb.OPENAI_CREDITS_REFILL_FIELD] == 5
    assert stored[adb.OPENAI_CREDITS_MONTHLY_CYCLE_FIELD] == "2026-02"
    assert stored["updated_at"] == "ts-refund-legacy"


def test_get_user_profile_pro_resets_stale_cycle_and_preserves_refill_pool(mocker) -> None:
    client = FakeFirestoreClient()
    doc = client.collection(adb.USERS_COLLECTION).document("uid-pro").seed(
        {
            adb.ROLE_FIELD: adb.ROLE_PRO,
            adb.OPENAI_CREDITS_MONTHLY_FIELD: 1,
            adb.OPENAI_CREDITS_REFILL_FIELD: 9,
            adb.OPENAI_CREDITS_MONTHLY_CYCLE_FIELD: "2026-01",
            "email": "pro@example.com",
            "displayName": "Pro User",
        }
    )
    mocker.patch("backend.firebaseDB.user_database.get_firestore_client", return_value=client)
    mocker.patch("backend.firebaseDB.user_database._current_month_cycle_key", return_value="2026-02")
    mocker.patch("backend.firebaseDB.user_database.now_iso", return_value="ts-profile-reset")

    profile = adb.get_user_profile("uid-pro")

    assert profile is not None
    assert profile.role == adb.ROLE_PRO
    assert profile.openai_credits_monthly_remaining == adb.PRO_MONTHLY_OPENAI_CREDITS
    assert profile.openai_credits_refill_remaining == 9
    assert profile.openai_credits_available == adb.PRO_MONTHLY_OPENAI_CREDITS + 9
    assert profile.openai_credits_remaining == adb.PRO_MONTHLY_OPENAI_CREDITS + 9
    assert doc.set_calls[-1]["merge"] is True
    assert doc.get().to_dict()[adb.OPENAI_CREDITS_MONTHLY_CYCLE_FIELD] == "2026-02"
    assert doc.get().to_dict()[adb.OPENAI_CREDITS_REFILL_FIELD] == 9


def test_activate_pro_membership_resets_monthly_credits_and_keeps_refill_pool(mocker) -> None:
    client = FakeFirestoreClient()
    doc = client.collection(adb.USERS_COLLECTION).document("uid-pro").seed(
        {
            adb.ROLE_FIELD: adb.ROLE_BASE,
            adb.OPENAI_CREDITS_REFILL_FIELD: 37,
        }
    )
    mocker.patch("backend.firebaseDB.user_database.get_firestore_client", return_value=client)
    mocker.patch("backend.firebaseDB.user_database._current_month_cycle_key", return_value="2026-02")
    mocker.patch("backend.firebaseDB.user_database.now_iso", return_value="ts-pro-activate")

    adb.activate_pro_membership("uid-pro")

    stored = doc.get().to_dict()
    assert stored[adb.ROLE_FIELD] == adb.ROLE_PRO
    assert stored[adb.OPENAI_CREDITS_MONTHLY_FIELD] == adb.PRO_MONTHLY_OPENAI_CREDITS
    assert stored[adb.OPENAI_CREDITS_MONTHLY_CYCLE_FIELD] == "2026-02"
    assert stored[adb.OPENAI_CREDITS_REFILL_FIELD] == 37
    assert stored["updated_at"] == "ts-pro-activate"
    assert doc.set_calls[-1]["merge"] is True


def test_activate_pro_membership_is_idempotent_for_same_stripe_event_id(mocker) -> None:
    client = FakeFirestoreClient()
    doc = client.collection(adb.USERS_COLLECTION).document("uid-pro").seed(
        {
            adb.ROLE_FIELD: adb.ROLE_PRO,
            adb.OPENAI_CREDITS_MONTHLY_FIELD: 123,
            adb.OPENAI_CREDITS_REFILL_FIELD: 7,
            adb.OPENAI_CREDITS_MONTHLY_CYCLE_FIELD: "2026-02",
        }
    )
    mocker.patch("backend.firebaseDB.user_database.get_firestore_client", return_value=client)
    mocker.patch("backend.firebaseDB.user_database._current_month_cycle_key", return_value="2026-02")
    mocker.patch("backend.firebaseDB.user_database.now_iso", return_value="ts-pro-idempotent")

    first_applied = adb.activate_pro_membership("uid-pro", stripe_event_id="evt_pro_1")
    assert first_applied is True
    doc.update({adb.OPENAI_CREDITS_MONTHLY_FIELD: 101})

    second_applied = adb.activate_pro_membership("uid-pro", stripe_event_id="evt_pro_1")
    assert second_applied is False

    stored = doc.get().to_dict()
    assert stored[adb.OPENAI_CREDITS_MONTHLY_FIELD] == 101
    assert stored[adb.STRIPE_PROCESSED_EVENT_IDS_FIELD] == ["evt_pro_1"]


def test_activate_pro_membership_with_subscription_writes_membership_and_billing_metadata(mocker) -> None:
    client = FakeFirestoreClient()
    doc = client.collection(adb.USERS_COLLECTION).document("uid-pro").seed(
        {
            adb.ROLE_FIELD: adb.ROLE_BASE,
            adb.OPENAI_CREDITS_REFILL_FIELD: 9,
        }
    )
    mocker.patch("backend.firebaseDB.user_database.get_firestore_client", return_value=client)
    mocker.patch("backend.firebaseDB.user_database._current_month_cycle_key", return_value="2026-02")
    mocker.patch("backend.firebaseDB.user_database.now_iso", return_value="ts-pro-subscription")

    applied = adb.activate_pro_membership_with_subscription(
        "uid-pro",
        stripe_event_id="evt_pro_checkout_1",
        customer_id="cus_123",
        subscription_id="sub_123",
        subscription_status="active",
        subscription_price_id="price_monthly",
    )

    assert applied is True
    stored = doc.get().to_dict()
    assert stored[adb.ROLE_FIELD] == adb.ROLE_PRO
    assert stored[adb.OPENAI_CREDITS_MONTHLY_FIELD] == adb.PRO_MONTHLY_OPENAI_CREDITS
    assert stored[adb.OPENAI_CREDITS_REFILL_FIELD] == 9
    assert stored[adb.STRIPE_CUSTOMER_ID_FIELD] == "cus_123"
    assert stored[adb.STRIPE_SUBSCRIPTION_ID_FIELD] == "sub_123"
    assert stored[adb.STRIPE_SUBSCRIPTION_STATUS_FIELD] == "active"
    assert stored[adb.STRIPE_SUBSCRIPTION_PRICE_ID_FIELD] == "price_monthly"
    assert stored[adb.STRIPE_PROCESSED_EVENT_IDS_FIELD] == ["evt_pro_checkout_1"]


def test_activate_pro_membership_with_subscription_can_backfill_metadata_for_duplicate_event(mocker) -> None:
    client = FakeFirestoreClient()
    doc = client.collection(adb.USERS_COLLECTION).document("uid-pro").seed(
        {
            adb.ROLE_FIELD: adb.ROLE_PRO,
            adb.OPENAI_CREDITS_MONTHLY_FIELD: adb.PRO_MONTHLY_OPENAI_CREDITS,
            adb.OPENAI_CREDITS_REFILL_FIELD: 0,
            adb.OPENAI_CREDITS_MONTHLY_CYCLE_FIELD: "2026-02",
            adb.STRIPE_PROCESSED_EVENT_IDS_FIELD: ["evt_repeat"],
        }
    )
    mocker.patch("backend.firebaseDB.user_database.get_firestore_client", return_value=client)
    mocker.patch("backend.firebaseDB.user_database.now_iso", return_value="ts-backfill")

    applied = adb.activate_pro_membership_with_subscription(
        "uid-pro",
        stripe_event_id="evt_repeat",
        customer_id="cus_backfill",
        subscription_id="sub_backfill",
        subscription_status="active",
        subscription_price_id="price_backfill",
    )

    assert applied is False
    stored = doc.get().to_dict()
    assert stored[adb.STRIPE_CUSTOMER_ID_FIELD] == "cus_backfill"
    assert stored[adb.STRIPE_SUBSCRIPTION_ID_FIELD] == "sub_backfill"
    assert stored[adb.STRIPE_SUBSCRIPTION_STATUS_FIELD] == "active"
    assert stored[adb.STRIPE_SUBSCRIPTION_PRICE_ID_FIELD] == "price_backfill"
    assert stored[adb.STRIPE_PROCESSED_EVENT_IDS_FIELD] == ["evt_repeat"]


def test_add_refill_openai_credits_requires_positive_integer(mocker) -> None:
    get_client = mocker.patch("backend.firebaseDB.user_database.get_firestore_client")

    with pytest.raises(ValueError, match="credits must be a positive integer"):
        adb.add_refill_openai_credits("uid-pro", credits=0)

    with pytest.raises(ValueError, match="credits must be a positive integer"):
        adb.add_refill_openai_credits("uid-pro", credits=-1)

    get_client.assert_not_called()


def test_add_refill_openai_credits_increments_balance(mocker) -> None:
    client = FakeFirestoreClient()
    doc = client.collection(adb.USERS_COLLECTION).document("uid-pro").seed(
        {
            adb.ROLE_FIELD: adb.ROLE_PRO,
            adb.OPENAI_CREDITS_REFILL_FIELD: 3,
        }
    )
    mocker.patch("backend.firebaseDB.user_database.get_firestore_client", return_value=client)
    mocker.patch("backend.firebaseDB.user_database.now_iso", return_value="ts-refill")

    refill_remaining = adb.add_refill_openai_credits("uid-pro", credits=7)

    assert refill_remaining == 10
    assert doc.get().to_dict()[adb.OPENAI_CREDITS_REFILL_FIELD] == 10
    assert doc.get().to_dict()["updated_at"] == "ts-refill"
    assert client.transactions[0].set_calls[-1]["merge"] is True


def test_add_refill_openai_credits_is_idempotent_for_same_stripe_event_id(mocker) -> None:
    client = FakeFirestoreClient()
    doc = client.collection(adb.USERS_COLLECTION).document("uid-pro").seed(
        {
            adb.ROLE_FIELD: adb.ROLE_PRO,
            adb.OPENAI_CREDITS_REFILL_FIELD: 4,
        }
    )
    mocker.patch("backend.firebaseDB.user_database.get_firestore_client", return_value=client)
    mocker.patch("backend.firebaseDB.user_database.now_iso", return_value="ts-refill-idempotent")

    first = adb.add_refill_openai_credits("uid-pro", credits=6, stripe_event_id="evt_refill_1")
    second = adb.add_refill_openai_credits("uid-pro", credits=6, stripe_event_id="evt_refill_1")

    assert first == 10
    assert second == 10
    stored = doc.get().to_dict()
    assert stored[adb.OPENAI_CREDITS_REFILL_FIELD] == 10
    assert stored[adb.STRIPE_PROCESSED_EVENT_IDS_FIELD] == ["evt_refill_1"]


def test_set_and_lookup_user_billing_subscription_fields(mocker) -> None:
    client = FakeFirestoreClient()
    mocker.patch("backend.firebaseDB.user_database.get_firestore_client", return_value=client)
    mocker.patch("backend.firebaseDB.user_database.now_iso", return_value="ts-billing")

    adb.set_user_billing_subscription(
        "uid-billing",
        customer_id=" cus_123 ",
        subscription_id=" sub_123 ",
        subscription_status=" active ",
        subscription_price_id=" price_monthly ",
        cancel_at_period_end=True,
        cancel_at=1775000000,
        current_period_end=1775000000,
    )

    record = adb.get_user_billing_record("uid-billing")
    assert record is not None
    assert record.uid == "uid-billing"
    assert record.customer_id == "cus_123"
    assert record.subscription_id == "sub_123"
    assert record.subscription_status == "active"
    assert record.subscription_price_id == "price_monthly"
    assert record.cancel_at_period_end is True
    assert record.cancel_at == 1775000000
    assert record.current_period_end == 1775000000
    assert adb.find_user_id_by_subscription_id(" sub_123 ") == "uid-billing"
