"""Blueprint for route-level unit tests of detection endpoints in `backend/main.py`.

Endpoints to cover (with patched dependencies):
- `POST /detect-fields`
- `GET /detect-fields/{session_id}`
- legacy: `POST /api/process-pdf`, `GET /api/detected-fields`

Required scenarios:
- auth required vs admin override behavior
- non-PDF and empty upload validation
- page-limit enforcement by role
- local-mode successful detection path
- tasks-mode enqueue path
- unsupported pipeline selection
- detection status endpoint ownership checks and status transitions

Edge cases:
- queue enqueue failure finalizes status as failed
- missing session metadata / missing fields artifacts
- legacy endpoints hidden when disabled

Important context:
- This is the primary pipeline entrypoint and must preserve strict auth/rate/limit behavior.
"""
