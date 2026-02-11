"""Blueprint for unit tests of role/limits helpers in `backend/main.py`.

Required coverage:
- `_resolve_detect_max_pages`
- `_resolve_fillable_max_pages`
- `_resolve_saved_forms_limit`
- `_resolve_role_limits`

Edge cases:
- invalid env values
- minimum clamp to at least 1
- god/base branching

Important context:
- Tier limits are part of billing and abuse-prevention behavior.
"""
