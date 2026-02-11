"""Blueprint for unit tests of `backend/firebaseDB/schema_database.py`.

Required coverage:
- schema create/list/get ownership and TTL filtering
- `_schema_expires_at` and `_is_expired`
- `record_openai_request` and `record_openai_rename_request`

Edge cases:
- TTL disabled (`<=0`)
- ISO-string vs datetime expiration parsing
- missing required logging metadata

Important context:
- Schema metadata and request logs are the persistent audit trail for AI operations.
"""
