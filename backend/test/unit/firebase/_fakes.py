from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from firebase_admin import firestore as firebase_firestore


def _resolve_nested(data: dict[str, Any], field: str) -> Any:
    current: Any = data
    for segment in field.split("."):
        if not isinstance(current, dict) or segment not in current:
            return None
        current = current.get(segment)
    return current


def _assign_nested(target: dict[str, Any], field: str, value: Any) -> None:
    current = target
    segments = field.split(".")
    for segment in segments[:-1]:
        next_value = current.get(segment)
        if not isinstance(next_value, dict):
            next_value = {}
            current[segment] = next_value
        current = next_value
    current[segments[-1]] = deepcopy(value)


def _project_dict(data: dict[str, Any], field_paths: list[str] | None) -> dict[str, Any]:
    if not field_paths:
        return deepcopy(data)
    projected: dict[str, Any] = {}
    for field in field_paths:
        resolved = _resolve_nested(data, field)
        if resolved is None:
            continue
        _assign_nested(projected, field, resolved)
    return projected


def _is_delete_field(value: Any) -> bool:
    return value is firebase_firestore.DELETE_FIELD or repr(value) == repr(firebase_firestore.DELETE_FIELD)


def _merge_with_delete_fields(current: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(current)
    for key, value in payload.items():
        if _is_delete_field(value):
            merged.pop(key, None)
            continue
        merged[key] = deepcopy(value)
    return merged


@dataclass
class FakeSnapshot:
    id: str
    _data: dict[str, Any]
    exists: bool = True
    reference: Any = None

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

    def get(self, field_paths: list[str] | None = None, transaction: Any = None) -> FakeSnapshot:
        return FakeSnapshot(self.id, _project_dict(self._data, field_paths), exists=self._exists, reference=self)

    def set(self, payload: dict[str, Any], merge: bool = False) -> None:
        payload_copy = deepcopy(payload)
        self.set_calls.append({"payload": payload_copy, "merge": merge})
        if merge and self._exists:
            self._data = _merge_with_delete_fields(self._data, payload_copy)
        else:
            self._data = payload_copy
        self._exists = True

    def create(self, payload: dict[str, Any]) -> None:
        if self._exists:
            raise RuntimeError(f"Document already exists: {self.id}")
        self.set(payload, merge=False)

    def update(self, payload: dict[str, Any]) -> None:
        payload_copy = deepcopy(payload)
        self.update_calls.append(payload_copy)
        current = deepcopy(self._data) if self._exists else {}
        self._data = _merge_with_delete_fields(current, payload_copy)
        self._exists = True

    def delete(self) -> None:
        self.delete_calls += 1
        self._exists = False
        self._data = {}


class FakeQuery:
    def __init__(
        self,
        docs: list[FakeDocumentRef],
        *,
        order_field: str | None = None,
        order_direction: str = "ASCENDING",
        limit_count: int | None = None,
    ):
        self._docs = docs
        self._order_field = order_field
        self._order_direction = order_direction
        self._limit_count = limit_count

    def order_by(self, field_path: str, direction: str = "ASCENDING") -> "FakeQuery":
        return FakeQuery(
            self._docs,
            order_field=field_path,
            order_direction=direction,
            limit_count=self._limit_count,
        )

    def limit(self, count: int) -> "FakeQuery":
        return FakeQuery(
            self._docs,
            order_field=self._order_field,
            order_direction=self._order_direction,
            limit_count=max(0, int(count)),
        )

    def get(self, transaction: Any = None) -> list[FakeSnapshot]:
        docs = [doc for doc in self._docs if doc.get().exists]
        if self._order_field:
            reverse = str(self._order_direction or "").upper() == "DESCENDING"
            docs.sort(
                key=lambda doc: (_resolve_nested(doc.get().to_dict(), self._order_field) or "", doc.id),
                reverse=reverse,
            )
        if self._limit_count is not None:
            docs = docs[: self._limit_count]
        return [doc.get() for doc in docs]


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
            if _resolve_nested(data, field) == value:
                matches.append(doc)
        return FakeQuery(matches)


class FakeTransaction:
    def __init__(self):
        self._read_only = False
        self.set_calls: list[dict[str, Any]] = []
        self.delete_calls: list[str] = []

    def set(self, doc_ref: FakeDocumentRef, payload: dict[str, Any], merge: bool = False) -> None:
        payload_copy = deepcopy(payload)
        self.set_calls.append({"doc_id": doc_ref.id, "payload": payload_copy, "merge": merge})
        doc_ref.set(payload_copy, merge=merge)

    def delete(self, doc_ref: FakeDocumentRef) -> None:
        self.delete_calls.append(doc_ref.id)
        doc_ref.delete()


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
