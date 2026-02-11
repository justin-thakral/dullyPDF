"""Unit tests for credit and quota logic in `backend/firebaseDB/app_database.py`."""

import pytest

from backend.firebaseDB import app_database as adb
from backend.test.unit.firebase._fakes import FakeFirestoreClient


@pytest.fixture(autouse=True)
def _no_transaction_wrapper(mocker):
    mocker.patch(
        "backend.firebaseDB.app_database.firebase_firestore.transactional",
        side_effect=lambda fn: fn,
    )


def test_resolve_openai_credits_remaining_handles_zero_missing_and_invalid() -> None:
    assert adb._resolve_openai_credits_remaining({adb.OPENAI_CREDITS_FIELD: 0}) == 0
    assert adb._resolve_openai_credits_remaining({}) == adb.BASE_OPENAI_CREDITS
    assert adb._resolve_openai_credits_remaining({adb.OPENAI_CREDITS_FIELD: "not-int"}) == adb.BASE_OPENAI_CREDITS


def test_consume_openai_credits_rejects_missing_uid() -> None:
    with pytest.raises(ValueError, match="Missing firebase uid"):
        adb.consume_openai_credits("", credits=1)


def test_consume_openai_credits_god_role_bypasses_storage(mocker) -> None:
    get_client = mocker.patch("backend.firebaseDB.app_database.get_firestore_client")

    remaining, allowed = adb.consume_openai_credits("uid-1", credits=5, role=adb.ROLE_GOD)

    assert (remaining, allowed) == (-1, True)
    get_client.assert_not_called()


def test_consume_openai_credits_returns_false_when_insufficient(mocker) -> None:
    client = FakeFirestoreClient()
    client.collection(adb.USERS_COLLECTION).document("uid-1").seed({adb.OPENAI_CREDITS_FIELD: 1})
    mocker.patch("backend.firebaseDB.app_database.get_firestore_client", return_value=client)

    remaining, allowed = adb.consume_openai_credits("uid-1", credits=2, role=adb.ROLE_BASE)

    assert remaining == 1
    assert allowed is False
    txn = client.transactions[0]
    assert txn.set_calls == []


def test_consume_openai_credits_coerces_invalid_credit_count_to_one(mocker) -> None:
    client = FakeFirestoreClient()
    doc = client.collection(adb.USERS_COLLECTION).document("uid-1").seed({adb.OPENAI_CREDITS_FIELD: "5"})
    mocker.patch("backend.firebaseDB.app_database.get_firestore_client", return_value=client)
    mocker.patch("backend.firebaseDB.app_database.now_iso", return_value="ts-updated")

    remaining, allowed = adb.consume_openai_credits("uid-1", credits="bad", role=adb.ROLE_BASE)

    assert (remaining, allowed) == (4, True)
    assert doc.get().to_dict()[adb.OPENAI_CREDITS_FIELD] == 4
    assert doc.get().to_dict()["updated_at"] == "ts-updated"
    assert client.transactions[0].set_calls[-1]["merge"] is True


def test_consume_openai_credits_coerces_non_positive_credit_count_to_one(mocker) -> None:
    client = FakeFirestoreClient()
    doc = client.collection(adb.USERS_COLLECTION).document("uid-1").seed({adb.OPENAI_CREDITS_FIELD: 5})
    mocker.patch("backend.firebaseDB.app_database.get_firestore_client", return_value=client)
    mocker.patch("backend.firebaseDB.app_database.now_iso", return_value="ts-updated")

    remaining, allowed = adb.consume_openai_credits("uid-1", credits=0, role=adb.ROLE_BASE)

    assert (remaining, allowed) == (4, True)
    assert doc.get().to_dict()[adb.OPENAI_CREDITS_FIELD] == 4


def test_refund_openai_credits_rejects_missing_uid() -> None:
    with pytest.raises(ValueError, match="Missing firebase uid"):
        adb.refund_openai_credits("", credits=1)


def test_refund_openai_credits_god_role_bypasses_storage(mocker) -> None:
    get_client = mocker.patch("backend.firebaseDB.app_database.get_firestore_client")

    remaining = adb.refund_openai_credits("uid-1", credits=3, role=adb.ROLE_GOD)

    assert remaining == -1
    get_client.assert_not_called()


def test_refund_openai_credits_coerces_invalid_refund_count_to_one(mocker) -> None:
    client = FakeFirestoreClient()
    doc = client.collection(adb.USERS_COLLECTION).document("uid-1").seed({adb.OPENAI_CREDITS_FIELD: 2})
    mocker.patch("backend.firebaseDB.app_database.get_firestore_client", return_value=client)
    mocker.patch("backend.firebaseDB.app_database.now_iso", return_value="ts-refund")

    remaining = adb.refund_openai_credits("uid-1", credits="bad", role=adb.ROLE_BASE)

    assert remaining == 3
    assert doc.get().to_dict()[adb.OPENAI_CREDITS_FIELD] == 3
    assert doc.get().to_dict()["updated_at"] == "ts-refund"
    assert client.transactions[0].set_calls[-1]["merge"] is True


def test_refund_openai_credits_coerces_non_positive_refund_count_to_one(mocker) -> None:
    client = FakeFirestoreClient()
    doc = client.collection(adb.USERS_COLLECTION).document("uid-1").seed({adb.OPENAI_CREDITS_FIELD: 2})
    mocker.patch("backend.firebaseDB.app_database.get_firestore_client", return_value=client)
    mocker.patch("backend.firebaseDB.app_database.now_iso", return_value="ts-refund")

    remaining = adb.refund_openai_credits("uid-1", credits=-5, role=adb.ROLE_BASE)

    assert remaining == 3
    assert doc.get().to_dict()[adb.OPENAI_CREDITS_FIELD] == 3


def test_consume_rename_quota_rejects_missing_uid() -> None:
    with pytest.raises(ValueError, match="Missing firebase uid"):
        adb.consume_rename_quota("")


def test_consume_rename_quota_coerces_invalid_count_and_increments(mocker) -> None:
    client = FakeFirestoreClient()
    doc = client.collection(adb.USERS_COLLECTION).document("uid-1").seed({adb.RENAME_COUNT_FIELD: "bad"})
    mocker.patch("backend.firebaseDB.app_database.get_firestore_client", return_value=client)
    mocker.patch("backend.firebaseDB.app_database.now_iso", return_value="ts-rename")

    count, allowed = adb.consume_rename_quota("uid-1", limit=2)

    assert (count, allowed) == (1, True)
    assert doc.get().to_dict()[adb.RENAME_COUNT_FIELD] == 1
    assert doc.get().to_dict()["updated_at"] == "ts-rename"


def test_consume_rename_quota_blocks_when_limit_reached(mocker) -> None:
    client = FakeFirestoreClient()
    client.collection(adb.USERS_COLLECTION).document("uid-1").seed({adb.RENAME_COUNT_FIELD: 2})
    mocker.patch("backend.firebaseDB.app_database.get_firestore_client", return_value=client)

    count, allowed = adb.consume_rename_quota("uid-1", limit=2)

    assert (count, allowed) == (2, False)
    assert client.transactions[0].set_calls == []


def test_consume_rename_quota_backfills_create_fields_when_doc_missing(mocker) -> None:
    client = FakeFirestoreClient()
    doc = client.collection(adb.USERS_COLLECTION).document("uid-1")
    mocker.patch("backend.firebaseDB.app_database.get_firestore_client", return_value=client)
    mocker.patch("backend.firebaseDB.app_database.now_iso", return_value="ts-created")

    count, allowed = adb.consume_rename_quota("uid-1", limit=3)

    assert (count, allowed) == (1, True)
    payload = doc.get().to_dict()
    assert payload[adb.RENAME_COUNT_FIELD] == 1
    assert payload["firebase_uid"] == "uid-1"
    assert payload["created_at"] == "ts-created"


def test_get_user_profile_handles_missing_uid_and_missing_doc(mocker) -> None:
    client = FakeFirestoreClient()
    mocker.patch("backend.firebaseDB.app_database.get_firestore_client", return_value=client)

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
    mocker.patch("backend.firebaseDB.app_database.get_firestore_client", return_value=client)

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
    mocker.patch("backend.firebaseDB.app_database.get_firestore_client", return_value=client)

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
    mocker.patch("backend.firebaseDB.app_database.get_firestore_client", return_value=client)
    mocker.patch("backend.firebaseDB.app_database.now_iso", return_value="ts-consume")

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
    mocker.patch("backend.firebaseDB.app_database.get_firestore_client", return_value=client)
    mocker.patch("backend.firebaseDB.app_database.now_iso", return_value="ts-refund")

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
