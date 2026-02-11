"""Blueprint for unit tests of L1 cache behavior in `backend/sessions/session_store.py`.

Required coverage:
- `_prune_session_cache` TTL sweep behavior
- `_trim_session_cache_size` LRU eviction
- `_store_l1_entry` insertion/update ordering
- `_session_last_access` coercion

Edge cases:
- malformed `last_access` values
- sweep interval short-circuit
- max entries = 0 behavior

Important context:
- L1 cache affects performance and cache-consistency during active editor sessions.
"""
