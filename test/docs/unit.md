# Unit Testing Guide (Backend + Frontend)

Canonical unit-testing docs:

- Backend: `backend/test/docs/unit.md`
- Frontend: `frontend/test/docs/unit.md`

This file is a top-level index for the requested `test/docs` location.

## Backend Overview

- Scope: deterministic backend logic in isolation (helpers, validation, env-driven behavior, small orchestrators).
- Location: `backend/test/unit/`
- Naming: `test_*.py` grouped by area (`api/`, `firebase/`, `sessions/`, `fieldDetecting/`, etc.)
- Run:

```bash
backend/.venv/bin/pytest backend/test/unit
```

Quick backend pass (unit + integration):

```bash
backend/.venv/bin/pytest backend/test/unit backend/test/integration
```

For full backend conventions, mocking notes, and bug-report requirements, read `backend/test/docs/unit.md`.

## Frontend Overview

- Scope: utility logic, service adapters, and component interaction behavior in isolation.
- Location: `frontend/test/unit/`
- Naming: executable tests use `.test.ts` / `.test.tsx` and area-based grouping.
- Stack: Vitest + React Testing Library.
- Run:

```bash
cd frontend && npm run test
```

For frontend-specific guidance (browser API mocking, async UI testing), read `frontend/test/docs/unit.md`.

## Failing Tests Policy

Failing tests are acceptable only as short-term debugging signals. If product behavior is wrong, report:

- failing test ids
- expected vs actual behavior

Then write a bug report in `test/bugs/` as `YYYY-MM-DD_<area>_<short-slug>.md`.
