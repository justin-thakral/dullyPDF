# Fill By API Audit Report

## Executive Summary

The `API Fill` feature is architecturally pointed in the right direction: it uses template-scoped secrets, frozen publish snapshots, server-side materialization, and avoids exposing raw secrets back after publish/rotate. The main problems are in quota accounting, concurrency safety, and a few runtime/UX mismatches. The most important correctness bug is that successful fills currently increment the monthly usage counter twice, which can exhaust customer quota early.

## Follow-up Status: March 27, 2026

The original issues in this report have been remediated in the working tree. In particular:

- monthly quota is now reserved exactly once per successful fill and refunded on downstream failures;
- auth and rate limiting now run before JSON parsing, with a streamed request-body cap and `application/json` enforcement on the public fill route;
- endpoint-local usage/failure/audit counters now use transaction-aware helpers instead of plain read-modify-write updates;
- public schema/PDF responses and owner manager routes now return `private, no-store`;
- owner recent-activity reads are bounded at the query layer; and
- public auth now verifies against projected endpoint metadata first, so wrong-key traffic no longer loads the full published snapshot.

The current request contract is also stricter than the original audit baseline:

- unknown top-level request-envelope keys are rejected instead of being ignored; and
- ambiguous key aliases that collapse to the same normalized schema key now fail closed instead of silently taking the last value.

The auth parser is stricter too:

- only the documented `Basic base64(API_KEY:)` format is accepted, so malformed credentials and nonblank passwords are rejected before endpoint lookup.

The validation audit path is safer too:

- request-envelope validation failures are summarized without raw `input` values, so owner-facing failure history does not capture caller payload contents through Pydantic error serialization.

The schema layer is more complete too:

- field-defined checkbox groups without explicit `checkboxRules` are now surfaced as list-style schema keys and accepted by API Fill instead of being silently omitted.

The latest pass also hardens two more fail-closed edges:

- published snapshots now reject conflicting normalized public keys, so one API key can no longer map to both a scalar field and a checkbox/radio group at the same time; and
- the owner publish request now rejects unknown top-level fields instead of silently ignoring misspelled options.

The latest telemetry pass also fixes two owner-observability gaps:

- runtime PDF-generation failures now increment a dedicated endpoint counter so the manager no longer understates real failures; and
- monthly quota blocks are now logged separately from broader plan-limit blocks, so recent activity better reflects what actually denied the request.

The latest pass also fixes one more usage-accounting drift:

- endpoint monthly usage summaries now stay tied to the month where quota was reserved, so a request that completes after a UTC month rollover cannot increment the wrong owner-visible month bucket.

The findings below are kept as the historical audit record that drove those fixes. I do not currently see an open high- or medium-severity issue in the API Fill path after the follow-up remediation pass.

## High Severity

### API-001: Successful fills are charged twice against the monthly quota

- Rule ID: API-001
- Severity: High
- Location: [backend/api/routes/template_api_public.py](/home/dully/projects/dullyPDF/backend/api/routes/template_api_public.py#L283), [backend/firebaseDB/template_api_endpoint_database.py](/home/dully/projects/dullyPDF/backend/firebaseDB/template_api_endpoint_database.py#L494), [backend/firebaseDB/template_api_endpoint_database.py](/home/dully/projects/dullyPDF/backend/firebaseDB/template_api_endpoint_database.py#L543)
- Evidence:
  - `_enforce_runtime_plan_limits(...)` calls `increment_and_check_template_api_monthly_usage(...)` before validation/materialization.
  - The success path later calls `record_template_api_endpoint_use(...)`, which calls `increment_template_api_monthly_usage(...)` again.
- Impact: one successful PDF generation can count as two monthly requests, exhausting plan quota early and making owner-visible limits inaccurate.
- Fix: decide whether monthly quota counts authenticated attempts or successful PDFs, then increment exactly once. If you want both metrics, store them separately.
- Mitigation: until fixed, compare the monthly counter against successful fill events when investigating customer quota complaints.
- False positive notes: none. Both code paths write to the same monthly usage collection.

## Medium Severity

### API-002: The request body size guard is ineffective for oversized JSON

- Rule ID: API-002
- Severity: Medium
- Location: [backend/api/routes/template_api_public.py](/home/dully/projects/dullyPDF/backend/api/routes/template_api_public.py#L242)
- Evidence:
  - The route signature parses `payload: TemplateApiFillRequest` before the function body runs.
  - The `content-length` check happens afterward and trusts a client-provided header.
- Impact: a public caller can still force FastAPI/Pydantic to read and parse a large JSON body before the route returns `413`, so the current guard is not a real DoS control by itself.
- Fix: enforce a real body-size cap before model parsing, or enforce it at the ASGI/ingress layer and document that as the source of truth.
- Mitigation: verify Cloud Run / load balancer / proxy body limits in production.
- False positive notes: if infra already rejects oversized bodies upstream, the practical exposure is reduced, but that protection is not visible in app code.

### API-003: Endpoint-local usage and failure counters are lossy under concurrency

- Rule ID: API-003
- Severity: Medium
- Location: [backend/firebaseDB/template_api_endpoint_database.py](/home/dully/projects/dullyPDF/backend/firebaseDB/template_api_endpoint_database.py#L411), [backend/firebaseDB/template_api_endpoint_database.py](/home/dully/projects/dullyPDF/backend/firebaseDB/template_api_endpoint_database.py#L543), [backend/firebaseDB/template_api_endpoint_database.py](/home/dully/projects/dullyPDF/backend/firebaseDB/template_api_endpoint_database.py#L567)
- Evidence:
  - `create_template_api_endpoint_event(...)`, `record_template_api_endpoint_use(...)`, and `record_template_api_endpoint_failure(...)` all do read-modify-write updates without a transaction or atomic increment.
- Impact: concurrent fills can undercount `usage_count`, `current_month_usage_count`, failure counters, and `audit_event_count`, which weakens the owner dashboard and recent-activity summaries.
- Fix: move these updates to Firestore transactions or atomic increment operations.
- Mitigation: treat the append-only event log and the transactional monthly counter as the more trustworthy sources until fixed.
- False positive notes: low-volume endpoints may not show this often, but the public API path is inherently concurrent.

### API-004: Broken snapshots can be published, then consume quota without producing a failure audit trail

- Rule ID: API-004
- Severity: Medium
- Location: [backend/services/template_api_service.py](/home/dully/projects/dullyPDF/backend/services/template_api_service.py#L218), [backend/services/fill_link_download_service.py](/home/dully/projects/dullyPDF/backend/services/fill_link_download_service.py#L67), [backend/api/routes/template_api_public.py](/home/dully/projects/dullyPDF/backend/api/routes/template_api_public.py#L283)
- Evidence:
  - `build_template_api_snapshot(...)` only checks that `pdf_bucket_path` exists.
  - The analogous Fill By Link snapshot builder rejects non-GCS paths up front.
  - The public fill route increments quota before materialization, and its `FileNotFoundError` branch returns `404` without `record_template_api_endpoint_failure(...)` or an audit event.
- Impact: an owner can publish an endpoint that looks valid but fails at runtime, and those failed requests can burn monthly quota while leaving recent activity incomplete.
- Fix: validate the storage path during publish and log storage/materialization failures before returning an error.
- Mitigation: smoke-test every newly published endpoint before treating it as live.
- False positive notes: even if saved forms normally use valid GCS paths, deleted/missing bucket objects can still hit this runtime branch.

### API-005: Active-endpoint limits are raceable

- Rule ID: API-005
- Severity: Medium
- Location: [backend/api/routes/template_api.py](/home/dully/projects/dullyPDF/backend/api/routes/template_api.py#L183), [backend/api/routes/template_api.py](/home/dully/projects/dullyPDF/backend/api/routes/template_api.py#L229)
- Evidence:
  - The code checks for an existing active endpoint and the current active-endpoint count before creating a new endpoint.
  - The actual `create_template_api_endpoint(...)` call happens outside any transaction.
- Impact: concurrent publish requests can create duplicate active endpoints for one template or temporarily bypass the plan cap.
- Fix: enforce the limit and per-template active uniqueness inside a Firestore transaction or other server-side idempotent guard.
- Mitigation: client-side button disabling helps UX but does not solve the server race.
- False positive notes: normal single-click flows are less likely to hit this, but it is a real server-side race.

## Low Severity

### API-006: Manager UX and docs are internally inconsistent

- Rule ID: API-006
- Severity: Low
- Location: [frontend/src/components/features/ApiFillManagerDialog.tsx](/home/dully/projects/dullyPDF/frontend/src/components/features/ApiFillManagerDialog.tsx#L154), [frontend/src/components/features/ApiFillManagerDialog.tsx](/home/dully/projects/dullyPDF/frontend/src/components/features/ApiFillManagerDialog.tsx#L188), [frontend/src/components/pages/usageDocsContent.tsx](/home/dully/projects/dullyPDF/frontend/src/components/pages/usageDocsContent.tsx#L736), [frontend/docs/api.md](/home/dully/projects/dullyPDF/frontend/docs/api.md#L277)
- Evidence:
  - The dialog says `API Fill always uses the last saved template snapshot`, which conflicts with the frozen publish-snapshot model described elsewhere.
  - The docs tell the owner to copy the schema URL, but the dialog only surfaces the fill URL and example snippets.
  - The snippets omit `strict`, while the docs explicitly note that unknown keys are silently ignored unless `strict=true`.
- Impact: operators can misunderstand when republish is required and may miss typoed keys during integration.
- Fix: change the copy to `published snapshot`, expose the schema URL, and show at least one `strict=true` smoke-test example.
- Mitigation: document `strict=true` as the recommended first integration step.
- False positive notes: this is primarily an operational/UX issue rather than a backend correctness flaw.

## Testing Gaps

- The targeted frontend tests passed:
  - `npm test -- test/unit/components/features/test_api_fill_manager_dialog.test.tsx test/unit/hooks/test_use_workspace_template_api.test.tsx`
- The targeted backend database unit tests passed:
  - `pytest -q backend/test/unit/firebase/test_template_api_endpoint_database_blueprint.py`
- The targeted backend API/integration set was not fully green:
  - `pytest -q backend/test/unit/services/test_template_api_service_blueprint.py backend/test/unit/api/test_main_template_api_public_blueprint.py backend/test/integration/test_template_api_integration.py`
  - Current result: `13 passed, 1 failed`
  - Failing test: `test_template_api_public_schema_and_fill_use_scoped_basic_auth`
  - Failure mode: the fake Firestore transaction path makes the quota check fail closed with `429`, so the successful public fill path is not currently verified end-to-end in that integration test.

## Expected Workflow

### Owner setup flow

1. Open a PDF in the workspace and save it as a template.
2. Make sure the saved template has a valid editor snapshot, stable field names, and correct checkbox/radio behavior.
3. Click `API Fill` in the `/ui` header while a saved template is active.
4. Choose the default export mode:
   - `flat` for a non-editable final PDF
   - `editable` to preserve form fields in the response
5. Click `Generate key` to publish the current saved-template snapshot as a frozen API endpoint.
6. Copy the one-time secret and store it on a server, not in browser code.
7. Use the schema and example payload to build an integration.
8. If the template changes later, click `Republish snapshot` so the endpoint uses the new frozen snapshot.
9. If a credential is exposed, click `Rotate key`.
10. If the integration should stop working entirely, click `Revoke`.

### Runtime fill flow

1. A server-side caller sends `POST /api/v1/fill/{endpointId}.pdf`.
2. The caller authenticates with Basic auth using the endpoint key as the username and a blank password.
3. The request body includes:
   - `data`: JSON object with normalized template keys
   - `filename` optional
   - `exportMode` optional override
   - `strict` optional
4. The backend:
   - parses Basic auth and resolves the endpoint by `endpointId + key_prefix`
   - verifies the hashed secret
   - confirms the endpoint is active and the snapshot exists
   - enforces public rate limits
   - enforces plan limits
   - normalizes/validates keys against the frozen published schema
   - materializes the PDF from the frozen snapshot plus submitted data
5. On success, the API returns `200 application/pdf`.
6. On failure, the API returns JSON `4xx` errors for auth, validation, rate-limit, or quota problems.

### Data-shape rules

- Text/date fields expect scalar values.
- Standalone checkbox fields expect boolean-style values.
- Checkbox groups follow the published rule:
  - `yes_no` expects boolean-like input
  - `enum` expects exactly one option key
  - `list` expects an array or comma-delimited set of option keys
- Radio groups expect exactly one option key.
- Unknown keys are ignored by default and rejected only when `strict=true`.
