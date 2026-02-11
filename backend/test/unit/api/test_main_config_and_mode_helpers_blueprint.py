"""Blueprint for unit tests of environment/config helpers in `backend/main.py`.

Required coverage:
- `_is_prod`, `_docs_enabled`, `_legacy_endpoints_enabled`
- `_resolve_detection_mode` local/tasks fallback behavior
- `_require_prod_env` validation matrix for required prod variables
- `_resolve_cors_origins` and wildcard debug gating
- `_resolve_stream_cors_headers`

Edge cases:
- malformed env values
- duplicate CORS origins and dedupe behavior
- `DETECTOR_MODE=local` but CommonForms missing with task queue present

Important context:
- Import-time startup safety depends on these helpers.
"""
