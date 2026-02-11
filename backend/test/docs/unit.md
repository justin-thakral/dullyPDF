# Unit Testing Guide (Backend)

This folder uses comment-first test blueprints in `backend/test/unit/`.
Each blueprint file lists what to implement and why, with project-specific edge cases.

## Scope

Unit tests should validate deterministic logic in isolation:

- payload normalization/sanitization
- allowlist/validation logic
- env-driven behavior
- helper functions and small orchestrators

Keep real network/services out of unit tests.

## Test Dependencies

Install backend test tooling from `backend/requirements-dev.txt` (includes `pytest`, `pytest-mock`, and `pytest-cov`).

## Location and Naming

- Unit tests live under `backend/test/unit/`
- Use `test_*.py` filenames
- Keep area-based grouping (`ai/`, `firebase/`, `sessions/`, `fieldDetecting/`, etc.)

## Run Unit Tests

```bash
pytest backend/test/unit
```

If you use the project venv:

```bash
backend/.venv/bin/pytest backend/test/unit
```

Run with coverage (`pytest-cov`):

```bash
backend/.venv/bin/pytest backend/test/unit --cov=backend --cov-config=.coveragerc --cov-report=term-missing
```

## How To Complete a Blueprint File

1. Read the file-level docstring and copy each listed scenario into concrete tests.
2. Add one test per behavior branch/edge case.
3. Patch external boundaries (`Firestore`, `GCS`, `OpenAI`, `httpx`, `google-auth`).
4. Keep assertions focused on behavior and side effects.
5. Avoid broad snapshot assertions for dynamic payloads.

## Standard Test Pattern

```python
import pytest

def test_branch(mocker):
    dep = mocker.patch('backend.some_module.some_dependency')
    dep.return_value = ...
    ...
    assert ...
```

## Important Backend-Specific Notes

- `backend.main` has import-time env checks (`_require_prod_env`). For unit tests, set `ENV=test` before import.
- Several modules cache global state; clear/reset between tests when needed:
  - `backend.main` token caches
  - `backend.security.rate_limit._RATE_LIMIT_BUCKETS`
  - `backend.sessions.session_store` L1 cache globals
- `debug_flags.py` mutates `sys.argv` at import time. Use isolated imports/reloads for those tests.

## Definition of Done for a Completed Unit File

- All listed scenarios implemented.
- External calls fully mocked.
- Edge cases implemented (not only happy path).
- Tests are deterministic and pass repeatedly.
