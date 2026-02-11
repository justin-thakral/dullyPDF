"""Blueprint for unit tests of `backend/security/rate_limit.py`.

Required coverage:
- `_memory_rate_limit` sliding-window behavior
- `_rate_limit_doc_id` stability/uniqueness
- `_firestore_rate_limit` transaction behavior
- `check_rate_limit` backend selection + fallback

Edge cases:
- `limit <= 0` behavior
- window rollover
- Firestore failure fallback to memory

Important context:
- This is shared by detect, rename, mapping, contact, and signup flows.
"""
