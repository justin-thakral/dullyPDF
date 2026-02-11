"""Blueprint for route-level unit tests of public/profile endpoints in `backend/main.py`.

Endpoints to cover (with patched dependencies):
- `GET /health`, `GET /api/health`
- `GET /api/profile`
- `POST /api/contact`
- `POST /api/recaptcha/assess`
- `POST /api/sessions/{session_id}/touch`

Required scenarios:
- profile response shape for base/god roles
- contact/signup rate-limit handling (global vs per-IP)
- recaptcha required and optional modes
- contact email send success/failure behavior
- session touch ownership and refresh behavior

Edge cases:
- missing recaptcha config in required mode
- invalid/missing contact channels
- unknown client IP fallback behavior

Important context:
- Public routes are abuse targets; tests should preserve strict validation behavior.
"""
