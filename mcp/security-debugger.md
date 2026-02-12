# Security Validation Guide (Codex + MCP)

This document teaches a Codex terminal how to act as a security-focused tester for DullyPDF.
It prioritizes data minimization, access control validation, and evidence capture while avoiding PHI/PII exposure.

## Scope

- Use the dev environment by default.
- Validate auth, role, and credit enforcement for OpenAI endpoints.
- Verify that only schema metadata and template overlay tags ever reach OpenAI.
- Capture evidence for every security-relevant finding.

## Prerequisites

- Backend and frontend are running locally.
- MCP server is configured as described in `mcp/README.md`.
- Chrome remote debugging is available per `mcp/devtools.md`.
- Test credentials live in `mcp/.env.local` (git-ignored).

## Safety rails

- Keep prod read-only by default.
- Only enable mutating calls if explicitly approved (`DULLY_MCP_ALLOW_WRITE=1`).
- Use synthetic data and de-identified PDFs unless asked otherwise.
- Never log secrets, access tokens, or PHI/PII in reports or screenshots.

## Baseline test data

- PDF: `quickTestFiles/new_patient_forms_1915ccb015.pdf`
- CSV (local parsing only): `quickTestFiles/new_patient_forms_1915ccb015_mock.csv`
- Schema text: `frontend/public/sample-data/new_patient_forms_1915ccb015_schema.txt`

Always note which PDF/CSV/schema you used in the final report.

## Standard security smoke flow (UI)

Run this end-to-end to validate guardrails.

1. Open the UI and sign in with the configured user.
2. Upload the baseline PDF for detection.
3. Ensure OpenAI toggles are unchecked by default; only enable when testing.
4. Attach a CSV/Excel/TXT schema source and confirm no row data is uploaded.
5. Trigger OpenAI rename and mapping separately, then together, to validate:
   - Auth required.
   - Credits decrement per OpenAI action for base role users.
   - Combined rename + map consumes 2 credits total (rename 1 + map 1).
6. Attempt to submit a PDF with filled form values and confirm the client blocks or the server rejects (attestation required).

Expected signals:
- Network: `/api/renames/ai` and `/api/schema-mappings/ai` return 200 when authorized.
- Credits: base users receive 10 lifetime credits; 402 when insufficient.
- UI: clear warnings on OpenAI submission and attestation of empty fields.

## API checks (non-UI)

Use MCP API tooling to validate security boundaries:

- Without auth: `/api/renames/ai`, `/api/schema-mappings/ai`, `/api/schemas` return 401/403.
- With auth: endpoints return 200 and include request ids.
- Credits: exceed base credits and confirm 402 with remaining/required details.
- Rate limits: exceed per-user limits and confirm 429.

Keep calls read-only unless explicitly approved.

## Data minimization checks

Verify that only schema metadata reaches the server and OpenAI:

- Confirm CSV/Excel uploads are parsed client-side and only headers/types are sent.
- Verify no CSV rows appear in network payloads.
- Validate OpenAI payloads are allowlisted via `backend/ai/schema_mapping.py` and contain only:
  - `schemaFields` with `name` and `type`.
  - `templateTags` with overlay metadata (tag, type, page, rect, groupKey, optionKey).

## OpenAI guardrail checks

Confirm DLP and payload enforcement:

- DLP blocks email addresses, phone numbers, DOB/SSN patterns, and long digit runs.
- Oversized payloads are rejected before OpenAI calls.
- OpenAI receives schema metadata and overlay tags only; no PHI/PII values.

Reference implementation:
- `backend/ai/schema_mapping.py` (`build_allowlist_payload`, `validate_dlp_payload`)
- `backend/api/routes/ai.py` (OpenAI rename/mapping auth, rate-limit, and credit checks)

## Logging and audit checks

Verify that logs and stored records contain only minimal metadata:

- OpenAI request logs store request id, user id, schema id, template id, session id, and timestamp only.
- No CSV rows or field values are persisted.
- Use `backend/firebaseDB/schema_database.py` and `backend/firebaseDB/detection_database.py` as references.

## Evidence capture

Always capture proof when a security-relevant issue occurs.

- Screenshots: `mcp/debugging/mcp-screenshots/`
- Console errors: capture message text and time.
- Network details: record endpoint, status, and response body when possible.

If you trigger dialogs, handle them so the page does not block.

## Finding classification and logging

Every issue must be recorded as a markdown report. Choose one:

1. Easy fix and obvious solution. Implement the fix and record it.
2. Hard fix or unclear solution. Record the finding and list ideas.
3. Easy fix but needs feedback. Record the finding and ask for guidance before changing.

Security categories:
- `auth` (authn/authz failures)
- `data-exposure` (PHI/PII risk)
- `logging` (sensitive data logged or stored)
- `rate-limit` (missing or bypassed limits)
- `credits` (billing enforcement errors)
- `other`

Where to write reports:

- Type 1: `mcp/security-docs/type-1-fixed/`
- Type 2: `mcp/security-docs/type-2-notfixed/`
- Type 3: `mcp/security-docs/type-3-needs-feedback/`

## Bug report template

Use this template for every security report:

```
# Security Finding: <short title>

## Classification
- Type: <1|2|3>
- Category: <auth|data-exposure|logging|rate-limit|credits|other>

## Context
- Environment: dev/prod
- User: <email or role>
- PDF: <path or name>
- Schema source: <csv/xls/txt path or name>
- Time: <ISO 8601>

## Steps to reproduce
1. ...
2. ...

## Expected
...

## Actual
...

## Evidence
- Screenshot: <path>
- Console: <message>
- Network: <method> <url> <status>

## Suggested fix
- ...

## Status
- Fixed: yes/no
- Notes: <summary or follow-up needed>
```

## Session master report

At the end of each session, write a master report that lists every report created.
Save it to `mcp/security-docs/logs/` and include links to each report.
If no issues were found, create a log that states "No findings" and note the run context.

Suggested filename: `session-YYYYMMDD-HHMM-security.md`.

## Stop conditions

Stop and ask for guidance if:

- You discover sensitive data exposure.
- A change would require destructive actions in prod.
- The backend is down or returns repeated 5xx errors.
