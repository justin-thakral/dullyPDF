# Integration Testing Guide (Backend)

Integration tests should validate route wiring, middleware behavior, auth gating,
and module-to-module behavior across complete endpoint flows.

## Scope

Integration tests should cover:

- FastAPI endpoints (`backend.main.app`, `backend.detector_main.app`)
- request/response schemas and status codes
- role/auth/rate-limit enforcement
- session lifecycle and pipeline transitions

Integration tests should still stub external systems.

## Location and Naming

- Integration tests live under `backend/test/integration/`
- Use `test_*.py`

## Run Integration Tests

```bash
pytest backend/test/integration
```

Run with coverage (`pytest-cov`):

```bash
backend/.venv/bin/pytest backend/test/integration --cov=backend --cov-config=.coveragerc --cov-report=term-missing
```

## How To Complete an Integration Test File

1. Use `fastapi.testclient.TestClient` against the app module.
2. Patch external boundaries only (Firebase, Storage, OpenAI, Google APIs).
3. Verify status code + response payload + key side effects.
4. Include unhappy paths and permission errors.

## Recommended Boundary Patches

- auth/user:
  - `backend.main._verify_token`
  - `backend.main.ensure_user`
- session/storage:
  - `backend.main._get_session_entry`
  - `backend.main._update_session_entry`
  - storage helper functions in `backend.main`
- OpenAI flows:
  - `backend.main.run_openai_rename_on_pdf`
  - `backend.main.call_openai_schema_mapping_chunked`
- detection queue:
  - `backend.main.enqueue_detection_task`

## Test Priorities for This Project

1. Detection pipeline (`/detect-fields`, `/detect-fields/{sessionId}`)
2. Rename + schema mapping credit behavior
3. Saved forms/template session lifecycle
4. Materialize PDF flow
5. Public contact + reCAPTCHA routes
6. Detector service retry/finalization behavior

## Definition of Done for a Completed Integration File

- Includes happy path + edge/error paths.
- Asserts response and persistence/update side effects.
- No real external network/service calls.
