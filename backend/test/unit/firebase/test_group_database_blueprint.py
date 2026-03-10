from backend.firebaseDB import group_database as gdb
from backend.test.unit.firebase._fakes import FakeFirestoreClient


def test_remove_template_from_all_groups_updates_non_empty_groups(mocker) -> None:
    client = FakeFirestoreClient()
    doc = client.collection(gdb.GROUPS_COLLECTION).document("group-1").seed(
        {
          "user_id": "user-1",
          "name": "Admissions",
          "normalized_name": "admissions",
          "template_ids": ["tpl-a", "tpl-b"],
        }
    )
    mocker.patch("backend.firebaseDB.group_database.get_firestore_client", return_value=client)
    mocker.patch("backend.firebaseDB.group_database.now_iso", return_value="ts-updated")

    removed_count = gdb.remove_template_from_all_groups("tpl-a", "user-1")

    assert removed_count == 1
    assert doc.get().exists is True
    assert doc.get().to_dict()["template_ids"] == ["tpl-b"]
    assert doc.get().to_dict()["updated_at"] == "ts-updated"
    assert doc.delete_calls == 0


def test_remove_template_from_all_groups_deletes_empty_groups(mocker) -> None:
    client = FakeFirestoreClient()
    doc = client.collection(gdb.GROUPS_COLLECTION).document("group-1").seed(
        {
          "user_id": "user-1",
          "name": "Admissions",
          "normalized_name": "admissions",
          "template_ids": ["tpl-a"],
        }
    )
    mocker.patch("backend.firebaseDB.group_database.get_firestore_client", return_value=client)

    removed_count = gdb.remove_template_from_all_groups("tpl-a", "user-1")

    assert removed_count == 1
    assert doc.get().exists is False
    assert doc.delete_calls == 1
