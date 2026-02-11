"""Blueprint for unit tests of `backend/time_utils.py`.

Required coverage:
- `now_iso()` returns ISO-8601 string
- Value is parseable with timezone info
- Offset is UTC (`+00:00`)

Important context:
- Timestamp strings are used in Firestore metadata and logs across the backend.
"""
