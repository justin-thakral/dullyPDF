"""Blueprint for unit tests of `backend/firebaseDB/session_database.py`.

Required coverage:
- `get_session_metadata`
- `upsert_session_metadata`
- `delete_session_metadata`

Edge cases:
- missing session id handling
- auto `updated_at` insertion when omitted
- missing document behavior

Important context:
- Session metadata is the L2 index used by API and detector processes.
"""
