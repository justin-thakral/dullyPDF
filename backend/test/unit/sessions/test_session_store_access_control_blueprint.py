"""Blueprint for unit tests of access-control flows in `backend/sessions/session_store.py`.

Required coverage:
- `_require_owner` denial/allow rules
- `get_session_entry` owner enforcement and missing-session handling
- `get_session_entry_if_present` non-raising behavior
- `touch_session_entry` ownership + error mapping

Edge cases:
- legacy sessions missing `user_id`
- owner mismatch
- L2 touch failure path maps to 503

Important context:
- Session ownership is a security boundary for all user data in session cache.
"""
