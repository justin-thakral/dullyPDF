from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any


@dataclass
class FakeSnapshot:
    id: str
    _data: dict[str, Any]
    exists: bool = True

    def to_dict(self) -> dict[str, Any]:
        return deepcopy(self._data)


class FakeDocumentRef:
    def __init__(self, doc_id: str):
        self.id = doc_id
        self._data: dict[str, Any] = {}
        self._exists = False
        self.set_calls: list[dict[str, Any]] = []
        self.update_calls: list[dict[str, Any]] = []
        self.delete_calls = 0

    def seed(self, data: dict[str, Any], *, exists: bool = True) -> "FakeDocumentRef":
        self._data = deepcopy(data)
        self._exists = exists
        return self

    def get(self, transaction: Any = None) -> FakeSnapshot:
        return FakeSnapshot(self.id, deepcopy(self._data), exists=self._exists)

    def set(self, payload: dict[str, Any], merge: bool = False) -> None:
        payload_copy = deepcopy(payload)
        self.set_calls.append({"payload": payload_copy, "merge": merge})
        if merge and self._exists:
            merged = deepcopy(self._data)
            merged.update(payload_copy)
            self._data = merged
        else:
            self._data = payload_copy
        self._exists = True

    def update(self, payload: dict[str, Any]) -> None:
        payload_copy = deepcopy(payload)
        self.update_calls.append(payload_copy)
        merged = deepcopy(self._data) if self._exists else {}
        merged.update(payload_copy)
        self._data = merged
        self._exists = True

    def delete(self) -> None:
        self.delete_calls += 1
        self._exists = False
        self._data = {}


class FakeQuery:
    def __init__(self, docs: list[FakeDocumentRef]):
        self._docs = docs

    def get(self) -> list[FakeSnapshot]:
        return [doc.get() for doc in self._docs if doc.get().exists]


class FakeCollection:
    def __init__(self, name: str):
        self.name = name
        self._docs: dict[str, FakeDocumentRef] = {}
        self._auto_id = 0

    def document(self, doc_id: str | None = None) -> FakeDocumentRef:
        if doc_id is None:
            doc_id = f"auto_{self._auto_id}"
            self._auto_id += 1
        if doc_id not in self._docs:
            self._docs[doc_id] = FakeDocumentRef(doc_id)
        return self._docs[doc_id]

    def where(self, field: str, op: str, value: Any) -> FakeQuery:
        if op != "==":
            raise ValueError("Only == is supported in FakeCollection")
        matches: list[FakeDocumentRef] = []
        for doc in self._docs.values():
            if not doc.get().exists:
                continue
            data = doc.get().to_dict()
            if data.get(field) == value:
                matches.append(doc)
        return FakeQuery(matches)


class FakeTransaction:
    def __init__(self):
        self.set_calls: list[dict[str, Any]] = []

    def set(self, doc_ref: FakeDocumentRef, payload: dict[str, Any], merge: bool = False) -> None:
        payload_copy = deepcopy(payload)
        self.set_calls.append({"doc_id": doc_ref.id, "payload": payload_copy, "merge": merge})
        doc_ref.set(payload_copy, merge=merge)


class FakeFirestoreClient:
    def __init__(self):
        self._collections: dict[str, FakeCollection] = {}
        self.transactions: list[FakeTransaction] = []

    def collection(self, name: str) -> FakeCollection:
        if name not in self._collections:
            self._collections[name] = FakeCollection(name)
        return self._collections[name]

    def transaction(self) -> FakeTransaction:
        txn = FakeTransaction()
        self.transactions.append(txn)
        return txn
