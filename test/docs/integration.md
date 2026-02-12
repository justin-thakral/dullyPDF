# Integration Testing Guide (Backend)

Canonical docs live in `backend/test/docs/integration.md`.
This mirror exists to satisfy the requested `test/docs` location and is backend-only.
Frontend tests are documented in `frontend/test/docs/`.

Use this command to run backend integration tests:

```bash
backend/.venv/bin/pytest backend/test/integration
```

Run backend unit + integration together:

```bash
backend/.venv/bin/pytest backend/test/unit backend/test/integration
```
