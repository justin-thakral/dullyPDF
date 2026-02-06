"""Rate limiting helpers with a Firestore backend and in-memory fallback."""

from collections import deque
from datetime import datetime, timezone
import hashlib
import os
import time
from typing import Deque, Dict

from firebase_admin import firestore as firebase_firestore

from ..fieldDetecting.rename_pipeline.combinedSrc.config import get_logger
from ..firebaseDB.firebase_service import get_firestore_client


logger = get_logger(__name__)

_RATE_LIMIT_BUCKETS: Dict[str, Deque[float]] = {}
_RATE_LIMIT_COLLECTION = os.getenv("SANDBOX_RATE_LIMIT_COLLECTION", "rate_limits")
_RATE_LIMIT_BACKEND = os.getenv("SANDBOX_RATE_LIMIT_BACKEND", "firestore").strip().lower()


def _memory_rate_limit(key: str, *, limit: int, window_seconds: int) -> bool:
    """Apply an in-memory sliding window limit. Complexity: O(k) per request."""
    if limit <= 0:
        return True
    now = time.monotonic()
    bucket = _RATE_LIMIT_BUCKETS.get(key)
    if bucket is None:
        bucket = deque()
        _RATE_LIMIT_BUCKETS[key] = bucket
    while bucket and (now - bucket[0]) > window_seconds:
        bucket.popleft()
    if len(bucket) >= limit:
        return False
    bucket.append(now)
    return True


def _rate_limit_doc_id(key: str) -> str:
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return f"rl_{digest}"


def _firestore_rate_limit(key: str, *, limit: int, window_seconds: int) -> bool:
    """Apply a distributed rate limit using a Firestore transaction. Complexity: O(1) per request."""
    if limit <= 0:
        return True
    if window_seconds <= 0:
        return True
    client = get_firestore_client()
    doc_ref = client.collection(_RATE_LIMIT_COLLECTION).document(_rate_limit_doc_id(key))
    now = time.time()
    transaction = client.transaction()

    @firebase_firestore.transactional
    def _update(txn: firebase_firestore.Transaction) -> bool:
        snapshot = doc_ref.get(transaction=txn)
        data = snapshot.to_dict() or {}
        try:
            window_start = float(data.get("window_start") or 0.0)
        except (TypeError, ValueError):
            window_start = 0.0
        try:
            count = int(data.get("count") or 0)
        except (TypeError, ValueError):
            count = 0

        if (now - window_start) >= window_seconds:
            window_start = now
            count = 0

        expires_at = datetime.fromtimestamp(window_start + window_seconds, tz=timezone.utc)
        if count >= limit:
            txn.set(
                doc_ref,
                {
                    "window_start": window_start,
                    "count": count,
                    "updated_at": firebase_firestore.SERVER_TIMESTAMP,
                    "expires_at": expires_at,
                },
                merge=True,
            )
            return False

        count += 1
        txn.set(
            doc_ref,
            {
                "window_start": window_start,
                "count": count,
                "updated_at": firebase_firestore.SERVER_TIMESTAMP,
                "expires_at": expires_at,
            },
            merge=True,
        )
        return True

    return _update(transaction)


def check_rate_limit(key: str, *, limit: int, window_seconds: int) -> bool:
    """
    Return True when the key is within the configured rate limit.

    Firestore-backed rate limiting keeps counters shared across instances. We fall back
    to in-memory limits on backend errors to avoid blocking requests unnecessarily.
    """
    if _RATE_LIMIT_BACKEND == "memory":
        return _memory_rate_limit(key, limit=limit, window_seconds=window_seconds)
    try:
        return _firestore_rate_limit(key, limit=limit, window_seconds=window_seconds)
    except Exception as exc:
        logger.warning("Rate limit fallback to memory: %s", exc)
        return _memory_rate_limit(key, limit=limit, window_seconds=window_seconds)
