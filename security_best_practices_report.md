# API Fill Security Audit

## Executive Summary

I audited the DullyPDF API Fill feature across the owner publish/rotate/revoke routes, the public schema/fill routes, the snapshot/materialization services, the Firestore persistence layer, and the React management UI.

The overall design is directionally sound:

- API keys are endpoint-scoped instead of user-global.
- Secrets are stored as hashes, not plaintext.
- Public fills operate on frozen saved-template snapshots instead of client-supplied PDFs.
- The frontend keeps the plaintext secret in component state only and clears it when the dialog closes.

I did not find a direct auth bypass or a plaintext-secret storage bug.

The main problems are in the public fill runtime:

1. the public fill route parses request bodies before auth and rate limiting;
2. monthly usage is double-counted on successful fills;
3. failed fills can still burn monthly quota; and
4. endpoint-local audit counters are race-prone under concurrency.

## Follow-up Status: March 27, 2026

The issues above have since been remediated in the working tree:

- public fill now authenticates and rate-limits before JSON parsing, enforces a streamed body cap, and requires `application/json`;
- monthly quota is reserved once, refunded on downstream failures, and the fake Firestore integration path now supports the transactional helper;
- endpoint-local usage/failure/audit counters now update through transaction-aware helpers instead of plain read-modify-write sequences.

The follow-up review also found and fixed three additional API Fill hardening issues:

1. the public schema route needed an explicit JSON response again and now returns `private, no-store`;
2. large validation failures could produce oversized client/storage error strings and are now summarized and truncated; and
3. browser-originated API Fill `POST`s now enforce the same allowlist guard pattern already used by public signing routes.

The current working tree also tightens two owner-side availability/privacy edges:

- owner API Fill manager routes now return `private, no-store`; and
- recent activity reads are bounded at the query layer instead of loading the full event history before slicing.

The latest cleanup pass also removes one more public runtime inefficiency:

- public auth now verifies against projected endpoint metadata first and only loads the full published snapshot after the key is accepted.

This pass also tightens the request contract:

- unknown top-level request-envelope keys are now rejected instead of ignored; and
- differently spelled input keys that normalize to the same schema key are now rejected as ambiguous instead of silently overwriting each other.

The Basic auth parser is stricter now too:

- only the documented `Basic base64(API_KEY:)` format is accepted, so malformed credentials and nonblank passwords are rejected before endpoint metadata lookup.

The payload-validation audit path is safer too:

- request-envelope validation failures are summarized from `loc`/`msg`/`type` only, so owner-visible failure logs do not persist raw caller input values from Pydantic error payloads.

The schema/request layer also now reflects implicit checkbox groups correctly:

- field-defined checkbox groups without explicit `checkboxRules` are exposed as list-style API Fill keys and accepted under `strict=true` instead of being silently omitted from the schema.

This pass also closes two more contract-drift issues:

- published snapshots now fail closed if two public keys collide after normalization, so a scalar field can no longer silently shadow a checkbox/radio group with the same public key; and
- the owner publish request now rejects unknown top-level fields instead of silently falling back to default publish settings.

The latest follow-up also tightens owner telemetry correctness:

- runtime PDF-generation failures now increment a dedicated endpoint failure counter so the manager no longer underreports real failures; and
- plan-limit blocks are now logged separately from monthly-quota blocks instead of collapsing both outcomes into the same audit label.

The latest follow-up also fixes one more month-boundary correctness edge:

- successful fills now keep the endpoint's monthly usage summary in the originally reserved month bucket, so a request that spans a UTC month rollover cannot bill one month while incrementing the owner-visible endpoint counter in the next.

## High Severity

### APIFILL-001: Public fill requests are parsed before auth, rate limiting, and the body-size guard

- Rule ID: FASTAPI-AUTH-001 / FASTAPI-DEPLOY baseline request-abuse protection
- Severity: High
- Location:
  - `backend/api/middleware/security.py:45-60`
  - `backend/api/routes/template_api_public.py:242-253`
  - `backend/api/schemas/models.py:146-154`
- Evidence:
  - `backend/api/middleware/security.py:52-60` explicitly exempts `/api/v1/fill/` from the preverified-auth middleware path.
  - `backend/api/routes/template_api_public.py:243-249` declares `payload: TemplateApiFillRequest`, so FastAPI/Pydantic must parse the body before the handler runs.
  - The size check is inside the handler at `backend/api/routes/template_api_public.py:250-252`, which is too late to prevent parsing/allocation.
- Reproduction:
  - Local repro on March 27, 2026: `POST /api/v1/fill/tep-any.pdf` with malformed JSON and no `Authorization` header returned `422` instead of `401`, confirming the request body was parsed before auth.
- Impact:
  - An unauthenticated attacker can force JSON decoding and Pydantic validation work before auth or rate limits run.
  - The `_MAX_FILL_REQUEST_BODY_BYTES` check is only advisory for clients that send an honest `Content-Length`; it does not protect the server from already-parsed oversized or malformed bodies.
  - This weakens abuse resistance on a public endpoint.
- Fix:
  - Move auth and request-size enforcement ahead of model parsing.
  - The safest pattern here is to accept `Request` instead of `payload: TemplateApiFillRequest`, verify auth and rate limits first, then read and parse the body manually under an explicit byte cap.
  - Also enforce a body-size limit at the ASGI/edge layer so malformed unauthenticated requests cannot allocate large bodies before app code runs.

## Medium Severity

### APIFILL-002: Successful fills consume the monthly quota twice

- Rule ID: correctness / billing integrity
- Severity: Medium
- Location:
  - `backend/api/routes/template_api_public.py:157-176`
  - `backend/api/routes/template_api_public.py:336`
  - `backend/firebaseDB/template_api_endpoint_database.py:494-540`
  - `backend/firebaseDB/template_api_endpoint_database.py:543-555`
- Evidence:
  - `_enforce_runtime_plan_limits()` calls `increment_and_check_template_api_monthly_usage(...)` at `backend/api/routes/template_api_public.py:171-174`.
  - After a successful fill, the route calls `record_template_api_endpoint_use(record.id)` at `backend/api/routes/template_api_public.py:336`.
  - `record_template_api_endpoint_use()` increments the same monthly usage counter again via `increment_template_api_monthly_usage(...)` at `backend/firebaseDB/template_api_endpoint_database.py:554`.
- Reproduction:
  - I reproduced this with the repo's `FakeFirestoreClient`: after one simulated quota admission the monthly `request_count` was `1`; after `record_template_api_endpoint_use('tep-1')` it became `2`, while the endpoint's `usage_count` was still `1`.
- Impact:
  - Customers lose monthly API Fill quota twice as fast as intended.
  - Owner-visible counters diverge: `request_count` becomes `2` while endpoint-local `usage_count` is `1`.
  - Monthly limit enforcement can trip early.
- Fix:
  - Count quota exactly once per billable request.
  - Either:
    - change `_enforce_runtime_plan_limits()` to check without incrementing and increment only on success, or
    - keep the transactional increment in `_enforce_runtime_plan_limits()` and remove the extra increment from `record_template_api_endpoint_use()`.

### APIFILL-003: Validation failures and unexpected materialization errors still burn quota

- Rule ID: correctness / availability
- Severity: Medium
- Location:
  - `backend/api/routes/template_api_public.py:283-334`
  - `backend/api/routes/template_api_public.py:157-176`
- Evidence:
  - Quota is incremented in `_enforce_runtime_plan_limits()` before request validation or PDF materialization.
  - Validation happens later in `resolve_template_api_request_data(...)` at `backend/api/routes/template_api_public.py:293-299`.
  - Materialization happens later at `backend/api/routes/template_api_public.py:313-319`.
  - Only `FileNotFoundError` and `ValueError` are handled. Any other exception after quota admission will bubble out as a `500` without a compensating quota rollback.
- Impact:
  - Invalid requests consume quota even though they never produce a PDF.
  - Transient server-side failures can also consume quota.
  - A caller with a leaked key can deny service to the owner more cheaply by sending invalid payloads instead of full successful fills.
- Fix:
  - Treat monthly quota as billable usage after the request passes validation and the fill succeeds, or add an explicit refund/rollback path for downstream failures.
  - Catch unexpected materialization exceptions, log a failure event, clean up temp files, and preserve quota consistency.

### APIFILL-004: Endpoint-local usage and failure counters are non-atomic and can undercount under concurrency

- Rule ID: audit integrity
- Severity: Medium
- Location:
  - `backend/firebaseDB/template_api_endpoint_database.py:543-564`
  - `backend/firebaseDB/template_api_endpoint_database.py:567-588`
  - `backend/firebaseDB/template_api_endpoint_database.py:408-418`
- Evidence:
  - `record_template_api_endpoint_use()` reads the current record, computes `+1`, and writes the result back without a transaction.
  - `record_template_api_endpoint_failure()` does the same for auth/validation/suspicious counters.
  - `create_template_api_endpoint_event()` also bumps `audit_event_count` with a read-modify-write sequence.
- Impact:
  - Concurrent traffic can drop increments, making per-endpoint usage, failure counts, and audit-event counts unreliable.
  - This matters most under load or attack, which is exactly when those counters are most valuable.
- Fix:
  - Use Firestore transactions or atomic increment operations for all endpoint-local counters.
  - Keep "last failure" metadata updates in the same transactional write where possible.

## Low Severity / Testing Gap

### APIFILL-005: The integration test for the public fill path currently fails and does not cover the live quota path

- Rule ID: regression coverage
- Severity: Low
- Location:
  - `backend/test/integration/test_template_api_integration.py:233-371`
  - `backend/firebaseDB/template_api_endpoint_database.py:494-540`
- Evidence:
  - Running `pytest -q backend/test/integration/test_template_api_integration.py -q` currently fails in `test_template_api_public_schema_and_fill_use_scoped_basic_auth`.
  - The failure comes from `increment_and_check_template_api_monthly_usage(...)` returning fail-closed when used with `FakeFirestoreClient`, which does not support the transactional quota path.
- Impact:
  - The public fill route is not currently covered end-to-end in the integration suite.
  - Regressions in quota handling or public fill admission can slip through with only the unit tests passing.
- Fix:
  - Patch the quota helper in that test, or extend `FakeFirestoreClient` so the transactional quota path behaves like production.

## Positive Controls Observed

- `backend/services/template_api_service.py` uses PBKDF2-HMAC with `hmac.compare_digest` for secret verification.
- `backend/api/routes/template_api.py` returns the plaintext API key only on initial publish or rotation.
- `frontend/src/hooks/useWorkspaceTemplateApi.ts:157`, `frontend/src/hooks/useWorkspaceTemplateApi.ts:183`, and `frontend/src/hooks/useWorkspaceTemplateApi.ts:230-233` keep the latest secret only in component state and clear it on dialog close/reset.
- `frontend/src/components/features/ApiFillManagerDialog.tsx:268-287` clearly labels the key as shown once and intended for server-side storage.
- `backend/services/fill_link_download_service.py` sanitizes response filenames before download and only materializes from allowlisted GCS paths.

## Recommended Tightening Order

1. Fix request admission on the public fill route so auth, rate limits, and body-size enforcement happen before JSON parsing.
2. Fix quota accounting so a successful fill counts once and failed fills do not silently burn quota.
3. Make endpoint-local counters transactional or atomic.
4. Repair the failing public-fill integration test so the full path is covered in CI.
