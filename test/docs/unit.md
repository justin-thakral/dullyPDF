# Unit Testing Guide (Backend)

Canonical docs live in `backend/test/docs/unit.md`.
This mirror exists to satisfy the requested `test/docs` location.

Use this command to run backend unit tests:

```bash
backend/.venv/bin/pytest backend/test/unit
```

Failing tests are allowed only as short-term debugging signals. If a test failure is caused by product code (not a bad test), report:

- failing test id(s)
- brief issue summary
- expected vs actual behavior

Then write a detailed bug report in `test/bugs/` named `YYYY-MM-DD_<area>_<short-slug>.md`.
