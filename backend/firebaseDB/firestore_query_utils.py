"""Firestore query helpers that work with both real and fake clients."""

from __future__ import annotations

from typing import Any

from google.cloud.firestore_v1.base_query import FieldFilter


def where_equals(collection: Any, field_path: str, value: Any):
    """Build an equality query using the modern filter API when available.

    The repo's fake Firestore client still exposes the older positional
    ``where(field, op, value)`` signature, so we fall back to that form when
    ``filter=...`` is unsupported.
    """

    try:
        return collection.where(filter=FieldFilter(field_path, "==", value))
    except TypeError:
        return collection.where(field_path, "==", value)
