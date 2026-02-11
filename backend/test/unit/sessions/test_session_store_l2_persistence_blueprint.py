"""Blueprint for unit tests of L2 persistence in `backend/sessions/session_store.py`.

Required coverage:
- `_persist_session_entry` artifact persistence flags
- `_hydrate_from_l2` include-flag hydration behavior
- `_missing_required_data` logic
- `_touch_l2_session` touch throttling

Edge cases:
- `persist_pdf=True` with missing `pdf_bytes` -> error
- missing metadata/document path conditions
- TTL-enabled metadata includes `expires_at`

Important context:
- L2 consistency is required for multi-instance Cloud Run behavior.
"""
