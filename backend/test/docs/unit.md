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

- `backend.main` still triggers app bootstrap on import (prod env checks run via `backend.api.app`). For unit tests, set `ENV=test` before import.
- Prefer patching route/service modules directly (`backend/api/routes/*`, `backend/services/*`) instead of relying only on `backend.main` re-exports.
- Several modules cache global state; clear/reset between tests when needed:
  - `backend.firebaseDB.firebase_service` globals (`_firebase_app`, `_firebase_init_error`, `_firebase_project_id`)
  - `backend.security.rate_limit._RATE_LIMIT_BUCKETS`
  - `backend.sessions.session_store` L1 cache globals
- `backend.fieldDetecting.rename_pipeline.debug_flags` mutates `sys.argv` at import time. Use isolated imports/reloads for those tests.

## Handling Failing Tests

Failing tests are acceptable only as a short-term development signal while debugging. A failing test is not a done state for merge.

When a test fails:

1. First verify the test is correct (assertions, fixtures, mocks, and expected behavior).
2. If the test itself is wrong, fix the test first.
3. If the test is correct and product code is failing, report failing test ids, a brief issue summary, and why it failed (expected vs observed).
4. Write a detailed bug report in `test/bugs/` as `YYYY-MM-DD_<area>_<short-slug>.md`.

Required bug report sections:

- Title + date
- Failing test ids and exact command used
- Reproduction steps
- Expected behavior
- Actual behavior
- Root-cause analysis (or strongest hypothesis)
- Suggested fix options
- Risk/impact assessment
- Follow-up validation plan

If a failure must be kept temporarily, mark it explicitly (for example `xfail`) with a reason and a link/path to its bug report.

## Definition of Done for a Completed Unit File

- All listed scenarios implemented.
- External calls fully mocked.
- Edge cases implemented (not only happy path).
- Tests are deterministic and pass repeatedly.
