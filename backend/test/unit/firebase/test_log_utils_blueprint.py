"""Blueprint for unit tests of `backend/firebaseDB/log_utils.py`.

Required coverage:
- `log_ttl_seconds()` parsing and default fallback
- `log_expires_at()` when TTL is positive vs non-positive

Important context:
- TTL behavior controls Firestore cleanup for request logs.
"""
