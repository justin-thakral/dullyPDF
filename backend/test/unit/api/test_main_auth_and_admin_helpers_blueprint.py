"""Blueprint for unit tests of auth/admin helpers in `backend/main.py`.

Required coverage:
- `_is_password_sign_in`
- `_enforce_email_verification`
- `_verify_token` exception mapping to HTTP statuses
- `_require_user` ensure_user failure mapping
- `_has_admin_override` behavior by ENV and token sources

Edge cases:
- revoked token path
- missing/empty bearer token
- debug password fallback path

Important context:
- Endpoint middleware and role enforcement depend on these paths.
"""
