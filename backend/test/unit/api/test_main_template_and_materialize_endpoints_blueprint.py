"""Blueprint for route-level unit tests of template/materialize routes in `backend/main.py`.

Endpoints to cover (with patched dependencies):
- `POST /api/templates/session`
- `POST /api/forms/materialize`
- `POST /api/register-fillable`
- `GET /download/{session_id}` (legacy)

Required scenarios:
- fields JSON validation and coercion
- fillable page-limit enforcement
- materialize empty-fields fast path (returns original)
- materialize inject-fields path and output filename sanitation
- streaming CORS header behavior on download responses

Edge cases:
- invalid PDF upload
- temporary file cleanup on failures
- session lookup with missing pdf_path

Important context:
- These routes directly produce user-facing PDF output and must remain robust.
"""
