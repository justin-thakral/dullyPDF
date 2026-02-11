"""Blueprint for unit tests of `backend/fieldDetecting/rename_pipeline/env_loader.py`.

Required coverage:
- `.env` parsing behavior
- export-line support
- comment/blank-line handling
- no override of pre-existing env vars
- `bootstrap_env` idempotency

Edge cases:
- missing files
- malformed lines without '='

Important context:
- Many rename-pipeline scripts rely on this loader when run directly.
"""
