# API Fill Guide

This document describes the implemented Anvil-style template fill API in DullyPDF, the request contract it exposes, and the product guardrails around it.

The target user flow is:

1. A user saves a PDF template in DullyPDF.
2. The user clicks `API Fill`.
3. DullyPDF publishes a frozen API snapshot for that saved template and generates a scoped secret key.
4. The user sends JSON data to a server-side API endpoint.
5. DullyPDF returns a final PDF binary response.

Example target contract:

```http
POST /api/v1/fill/{endpointId}.pdf
Authorization: Basic base64(API_KEY:)
Content-Type: application/json

{
  "data": {
    "patient_name": "Ada Lovelace",
    "marital_status": "married",
    "consent_signed": true
  },
  "filename": "patient-intake.pdf",
  "exportMode": "flat",
  "strict": true
}
```

Request-envelope validation errors are summarized in owner audit history without storing raw caller input values.

The API key must be the Basic username and the Basic password must be blank. Noncanonical Basic auth headers are rejected.

Response:

- `200 application/pdf` with PDF bytes on success.
- `4xx application/json` for invalid auth, invalid payload, invalid option values, or unpublished endpoints.

## Product position

This feature should be built as `API Fill`, not as a public wrapper around the existing generic materialize endpoint.

That distinction matters:

- `POST /api/forms/materialize` currently trusts a client-supplied PDF upload plus a client-supplied field payload.
- A proper API fill product should trust only a server-owned published snapshot of a saved template.
- The public API should fill one saved template at a time from JSON values, not accept arbitrary PDFs per request.

This is intentionally similar to Anvil's PDF fill model:

- template-first workflow
- server-side API key usage
- JSON data payload
- binary PDF response

References:

- Anvil PDF Filling API: https://www.useanvil.com/docs/api/fill-pdf/
- Anvil API auth/getting started: https://www.useanvil.com/docs/api/getting-started/

## Current status

- Milestone 1 is implemented on the backend: owner publish/list/rotate/revoke/schema routes plus frozen snapshot persistence.
- Milestone 2 is implemented end-to-end: public `GET /api/v1/fill/{endpointId}/schema`, public `POST /api/v1/fill/{endpointId}.pdf`, and a workspace `API Fill` manager button/dialog for saved templates.
- Milestone 3 is implemented: endpoint audit events, account monthly usage counters, per-endpoint/public rate limits, owner plan/page enforcement, and a hardened manager dialog that surfaces limits plus recent activity.

## Non-goals for v1

- No org-wide master API key.
- No browser-side long-lived API key usage.
- No direct public use of `POST /api/forms/materialize`.
- No arbitrary unsaved editor-state filling.
- No packet/group API filling in v1.
- No customer-managed API Fill webhooks in v1. Signing lifecycle webhooks now exist as backend-configured server-to-server delivery and stay separate from the API Fill surface.
- No async job model unless page counts or latency force it later.

## Core design decisions

### Template-scoped key, not user-scoped key

The correct security model is one API endpoint per published saved template, with a secret key scoped to that endpoint.

Do not use one master key per user account.

Why:

- Least privilege: a leaked key only affects one template.
- Safer rotation: one integration can rotate without breaking others.
- Better auditability: usage is attributable to one template endpoint.
- Better product UX: `Publish API for this template` is simple and clear.

### Frozen publish snapshot

Every API endpoint must fill from a frozen template snapshot taken at publish time.

The snapshot should include:

- source PDF storage path
- normalized fields
- page sizes
- radio groups
- checkbox rules
- text transform rules
- export defaults
- snapshot version metadata

If the user edits the saved form later, the API output must not silently change. The user should explicitly republish to update the API snapshot.

### Reuse existing backend primitives

The implementation should build on current repo seams:

- [forms.py](/home/dully/projects/dullyPDF/backend/api/routes/forms.py)
- [fill_link_download_service.py](/home/dully/projects/dullyPDF/backend/services/fill_link_download_service.py)
- [saved_form_snapshot_service.py](/home/dully/projects/dullyPDF/backend/services/saved_form_snapshot_service.py)
- [saved_forms.py](/home/dully/projects/dullyPDF/backend/api/routes/saved_forms.py)
- [rate_limit.py](/home/dully/projects/dullyPDF/backend/security/rate_limit.py)

The existing Fill By Link respondent download path is the closest architectural match because it already materializes PDFs from a frozen publish-time snapshot instead of trusting client-provided field geometry.

## Milestone 1: Published Snapshot and Fill Engine

Goal: create a deterministic backend fill core that can fill one saved template from a frozen publish snapshot and JSON data.

### Backend scope

Add a new persistence model for API fill endpoints, for example `template_api_endpoints`.

Suggested record shape:

```json
{
  "id": "tep_123",
  "user_id": "user_123",
  "template_id": "form_123",
  "template_name": "Patient Intake",
  "status": "active",
  "snapshot_version": 1,
  "key_prefix": "dpa_live_abc",
  "secret_hash": "hash",
  "created_at": "ISO8601",
  "published_at": "ISO8601",
  "updated_at": "ISO8601",
  "last_used_at": null,
  "usage_count": 0,
  "snapshot": {
    "sourcePdfPath": "gs://...",
    "fields": [],
    "pageSizes": {},
    "radioGroups": [],
    "checkboxRules": [],
    "textTransformRules": [],
    "defaultExportMode": "flat"
  }
}
```

Add a shared service, for example `backend/services/template_api_service.py`, responsible for:

- building the publish snapshot from a saved form
- generating one-time high-entropy API secrets
- hashing and verifying secrets
- materializing a PDF from `snapshot + data`

Add a dedicated fill application service, for example `backend/services/template_fill_service.py`.

This service should:

- normalize incoming data keys
- resolve radio groups deterministically
- apply checkbox rules deterministically
- apply text transform rules deterministically
- produce final field payloads for `inject_fields(...)`

The service should absorb the logic currently split across:

- [fill_link_download_service.py](/home/dully/projects/dullyPDF/backend/services/fill_link_download_service.py)
- [forms.py](/home/dully/projects/dullyPDF/backend/api/routes/forms.py)
- frontend Search & Fill runtime behavior that must eventually match backend output

### Initial owner endpoints

Add authenticated owner endpoints only:

- `GET /api/template-api-endpoints?templateId={id}`
- `POST /api/template-api-endpoints`
- `POST /api/template-api-endpoints/{id}/rotate`
- `POST /api/template-api-endpoints/{id}/revoke`
- `GET /api/template-api-endpoints/{id}/schema`

These routes should remain signed-in owner routes only in Milestone 1. The public fill route belongs in Milestone 2.

### Data contract rules

Define the fill contract now so all later layers are built against it:

- text/date: scalar values
- checkbox boolean field: `true` or `false`
- checkbox group with `enum` rule: one selected option key string
- checkbox group with `list` rule: array of option keys
- radio group: one selected option key string
- signature widgets are excluded from the API Fill schema; use the signing workflow for signature capture instead of the generic fill API

Fail closed when the selected option key is invalid.

Do not use `checkboxHints` in the API path.

### Tests for Milestone 1

Backend unit tests:

- publish snapshot generation
- key generation and hash verification
- fill service for text, checkbox, radio, and transform cases
- invalid option handling
- republish snapshot replacement behavior

Backend integration tests:

- saved form -> publish snapshot -> internal fill -> PDF bytes
- rotate/revoke lifecycle

### Milestone 1 exit criteria

- Backend can fill one saved template from a publish snapshot and JSON values.
- Output is deterministic and independent from client-side field payloads.
- Secrets are stored as hashes only and shown in plaintext exactly once.

## Milestone 2: Public API and Professional Workspace UI

Goal: expose a stable public fill endpoint and a clean owner UI for publishing and managing it.

### Public API routes

Add the public route:

- `POST /api/v1/fill/{endpointId}.pdf`

Recommended auth:

- `Authorization: Basic base64(API_KEY:)`

This mirrors Anvil's ergonomics while still keeping DullyPDF keys scoped per endpoint rather than org-wide. The same Basic auth header is required for the public schema route too.

Recommended supporting route:

- `GET /api/v1/fill/{endpointId}/schema`

This schema route should return:

- endpoint id
- template name
- available field keys
- field types
- radio options
- checkbox group metadata
- default export mode
- example payload

### Request behavior

The public fill route should:

- verify endpoint existence
- verify the API secret against the stored hash
- enforce endpoint status = active
- rate-limit by endpoint and IP
- materialize the PDF from the frozen snapshot
- return `application/pdf`

Required request field:

- `data`

Optional request fields:
- `filename` optional
- `exportMode` optional
- `strict` optional

Top-level request fields must match those names exactly. Unknown top-level keys are rejected instead of being ignored.

The owner publish route follows the same fail-closed rule for its top-level request fields, so misspelled publish options do not silently republish the endpoint with default settings.

Suggested default behavior:

- omitted keys: ignored
- null values: treated as unset
- blank strings: preserved for scalar fields so callers can intentionally clear a text/date-like value
- unknown keys: ignored when `strict=false`
- unknown keys: `400` when `strict=true`
- differently spelled aliases that normalize to the same schema key are rejected as ambiguous
- field-defined checkbox groups without explicit `checkboxRules` are exposed as list-style group keys in the schema
- published snapshots are rejected if two public keys collide after normalization, and older bad snapshots now fail closed instead of silently shadowing one schema entry with another
- owner activity distinguishes monthly quota blocks from broader plan-limit blocks, and tracked failure counts now include runtime PDF-generation failures in addition to auth/validation failures
- endpoint monthly usage summaries stay tied to the reserved request month, so a fill that finishes after a UTC month rollover does not drift into the wrong owner-side month bucket
- recommended first smoke test: send `strict=true` so schema typos fail closed

### Workspace UI

Add a new `API Fill` button in the header, immediately to the left of `Download`.

Professional UI requirements:

- If no saved template is active, the button is disabled with a concise explanation: `Save template first`.
- If a saved template is active, clicking `API Fill` opens a clean management dialog.
- The dialog should visually match the existing Fill By Link quality level, but be simpler.

Suggested dialog sections:

1. Published status
   - active / revoked
   - last published at
   - last used at
   - usage count

2. Endpoint
   - endpoint URL
   - endpoint id
   - environment label if needed later

3. Secret key
   - generate key
   - show once warning
   - rotate key
   - revoke endpoint

4. Usage examples
   - `curl`
   - Node
   - Python

5. Schema
   - field list
   - radio option keys
   - checkbox guidance

6. Notes
   - keys are for server use only
   - republish is required after template edits

The dialog should avoid a cluttered “developer console” look. This should feel like a normal DullyPDF product surface, not an internal tools modal.

### Frontend implementation shape

Likely additions:

- new header action in [HeaderBar.tsx](/home/dully/projects/dullyPDF/frontend/src/components/layout/HeaderBar.tsx)
- new dialog component, for example `ApiFillManagerDialog.tsx`
- new hook, for example `useTemplateApiEndpoints.ts`
- new API client helpers in `frontend/src/services/api.ts`

### Tests for Milestone 2

Frontend unit tests:

- button visibility and disabled state
- dialog open/close behavior
- create/rotate/revoke actions
- example rendering
- saved-template-only guardrails

Backend integration tests:

- authenticated owner publish lifecycle
- public fill endpoint with valid secret
- public fill endpoint with invalid secret
- strict vs non-strict payload handling

Playwright integration tests:

- save template
- open `API Fill`
- publish endpoint
- reveal/copy secret
- verify example payload is shown
- rotate key
- revoke endpoint

### Milestone 2 exit criteria

- A signed-in user can save a template, publish an API endpoint, and fill it from a server request.
- The UI is clean, minimal, and consistent with the rest of the workspace.
- Public API consumers can get a PDF back with a simple JSON request.

## Milestone 3: Hardening, Billing, and Full Release QA

Goal: make the API Fill feature safe and production-ready.

### Security and abuse controls

Add:

- per-endpoint rate limits
- global API fill rate limits
- fail-closed limiter behavior
- auth and rate-limit admission before request-body parsing
- metadata-first secret verification so wrong-key traffic does not load the full published snapshot
- hard request-body size enforcement on the public fill route
- `application/json` required on the public fill route
- `private, no-store` responses on the owner endpoint manager routes
- `private, no-store` responses on the public schema and PDF routes
- browser-origin allowlist enforcement on public fill `POST`s when an `Origin` header is present
- usage logging without storing raw field values by default
- quota accounting that counts each successful fill once and refunds reserved usage when PDF generation fails downstream
- summarized validation failure reasons so large bad payloads do not create oversized audit entries
- bounded recent-activity reads so owner refreshes do not scan the full audit history under abuse traffic
- endpoint-activity query fallback so owner detail refreshes still work when the Firestore `endpoint_id + created_at` composite index is missing
- endpoint-level revoke and rotation audit history
- suspicious failure counters

Do not allow:

- browser-only usage as the recommended path
- arbitrary PDF uploads to the public fill route
- one secret to access every template in an account

### Billing and product limits

Add profile/plan controls such as:

- max active API endpoints
- max fill requests per month
- max pages per request
- premium-only gating if desired

This feature is operationally more expensive than local Search & Fill because it turns DullyPDF into a hosted runtime service for repeated PDF generation.

### Documentation and customer-facing guidance

Update:

- homepage product copy if API Fill is marketed publicly
- usage docs
- backend README
- frontend README

Important messaging distinction:

- Search & Fill keeps row data local in the browser
- API Fill sends record data to DullyPDF backend services

That difference must be explicit in docs and product copy.

### Full QA requirements

Backend unit and integration:

- snapshot generation
- fill engine behavior
- endpoint lifecycle
- public fill auth before body parsing
- public fill browser-origin blocking for disallowed origins
- rate-limit behavior
- usage logging and single-count quota behavior
- quota refund on downstream materialization failures
- bounded validation failure summaries
- bounded recent-activity event reads
- republish behavior
- revoked endpoint behavior

Frontend unit:

- header button placement
- dialog state
- key generation UX
- examples and schema sections

Playwright integration:

- full owner publish lifecycle
- save template -> publish -> fill -> revoke
- visual regressions on the API dialog

Chrome DevTools MCP E2E:

- verify header placement with `API Fill` left of `Download`
- verify dialog layout, spacing, and copy
- verify no console errors on publish/open/rotate/revoke flows
- verify successful binary response path via live UI-backed owner flow where applicable
- capture screenshots under `mcp/debugging/mcp-screenshots`

### Milestone 3 exit criteria

- API Fill is safe, rate-limited, and auditable.
- The UI looks like a finished product surface.
- Backend, frontend, Playwright, and Chrome DevTools E2E checks are all green.
- The feature is ready for a real customer integration.

## Suggested implementation order inside each milestone

1. Backend service/model changes
2. Route contract and tests
3. Frontend service/hook wiring
4. Dialog and header UI
5. Playwright coverage
6. Chrome DevTools E2E proof
7. Docs and release checklist

## What not to do

- Do not expose a user-wide master API key in v1.
- Do not publish the current generic materialize route as the API product.
- Do not let API behavior depend on frontend-only fill logic.
- Do not ship the feature without snapshot versioning.
- Do not hide the data-handling distinction between local Search & Fill and hosted API Fill.
