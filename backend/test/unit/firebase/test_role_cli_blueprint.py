"""Unit tests for `backend/firebaseDB/role_cli.py`."""

import sys
from types import SimpleNamespace

import pytest

from backend.firebaseDB import role_cli
from backend.test.unit.firebase._fakes import FakeFirestoreClient


def test_main_requires_email_or_uid(monkeypatch) -> None:
    monkeypatch.setattr(sys, "argv", ["role_cli.py"])

    with pytest.raises(SystemExit, match="Provide --email or --uid"):
        role_cli.main()


def test_main_updates_claims_and_firestore_using_email(monkeypatch, mocker) -> None:
    user = SimpleNamespace(uid="uid-1", email="user@example.com", custom_claims={"existing": "claim"})
    client = FakeFirestoreClient()
    set_claims = mocker.patch("backend.firebaseDB.role_cli.firebase_auth.set_custom_user_claims")
    mocker.patch("backend.firebaseDB.role_cli.init_firebase")
    mocker.patch("backend.firebaseDB.role_cli.firebase_auth.get_user_by_email", return_value=user)
    get_user = mocker.patch("backend.firebaseDB.role_cli.firebase_auth.get_user")
    mocker.patch("backend.firebaseDB.role_cli.get_firestore_client", return_value=client)
    mocker.patch("backend.firebaseDB.role_cli.now_iso", return_value="ts-updated")
    monkeypatch.setattr(
        sys,
        "argv",
        ["role_cli.py", "--email", "user@example.com", "--role", role_cli.ROLE_GOD],
    )

    role_cli.main()

    get_user.assert_not_called()
    set_claims.assert_called_once_with(
        "uid-1",
        {"existing": "claim", role_cli.ROLE_FIELD: role_cli.ROLE_GOD},
    )

    doc = client.collection(role_cli.USERS_COLLECTION).document("uid-1")
    assert doc.set_calls[-1]["merge"] is True
    assert doc.get().to_dict() == {
        role_cli.ROLE_FIELD: role_cli.ROLE_GOD,
        "updated_at": "ts-updated",
        "firebase_uid": "uid-1",
        "email": "user@example.com",
    }


def test_main_uses_uid_lookup_and_can_reset_rename_count(monkeypatch, mocker) -> None:
    user = SimpleNamespace(uid="uid-2", email="uid@example.com", custom_claims=None)
    client = FakeFirestoreClient()
    set_claims = mocker.patch("backend.firebaseDB.role_cli.firebase_auth.set_custom_user_claims")
    get_user = mocker.patch("backend.firebaseDB.role_cli.firebase_auth.get_user", return_value=user)
    get_user_by_email = mocker.patch("backend.firebaseDB.role_cli.firebase_auth.get_user_by_email")
    mocker.patch("backend.firebaseDB.role_cli.init_firebase")
    mocker.patch("backend.firebaseDB.role_cli.get_firestore_client", return_value=client)
    mocker.patch("backend.firebaseDB.role_cli.now_iso", return_value="ts-updated")
    monkeypatch.setattr(
        sys,
        "argv",
        ["role_cli.py", "--uid", "uid-2", "--reset-rename-count"],
    )

    role_cli.main()

    get_user.assert_called_once_with("uid-2")
    get_user_by_email.assert_not_called()
    set_claims.assert_called_once_with("uid-2", {role_cli.ROLE_FIELD: role_cli.ROLE_BASE})

    doc = client.collection(role_cli.USERS_COLLECTION).document("uid-2")
    assert doc.get().to_dict() == {
        role_cli.ROLE_FIELD: role_cli.ROLE_BASE,
        "updated_at": "ts-updated",
        "firebase_uid": "uid-2",
        "email": "uid@example.com",
        role_cli.RENAME_COUNT_FIELD: 0,
    }


def test_main_propagates_lookup_error(monkeypatch, mocker) -> None:
    mocker.patch("backend.firebaseDB.role_cli.init_firebase")
    mocker.patch(
        "backend.firebaseDB.role_cli.firebase_auth.get_user_by_email",
        side_effect=LookupError("missing user"),
    )
    monkeypatch.setattr(sys, "argv", ["role_cli.py", "--email", "missing@example.com"])

    with pytest.raises(LookupError, match="missing user"):
        role_cli.main()
