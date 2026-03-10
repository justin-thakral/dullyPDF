# Fill By Link Integration Plan

## Executive Recommendation

Build **DullyPDF-native link forms** as the primary implementation.

Do **not** make Google Forms or "send the real PDF and scrape it later" the core architecture.

Use this product shape:

1. A signed-in owner starts from an existing DullyPDF saved form/template.
2. DullyPDF generates a **public respondent link** backed by a mobile-friendly HTML form, not a PDF.
3. Respondent answers are stored as **normalized structured data** in Firestore under the template owner's account.
4. In the workspace, the owner picks a respondent from a response list.
5. The existing DullyPDF Search & Fill and download/materialize flow fills the template and generates the final PDF only when needed.

This fits the current repo far better than the alternatives because the codebase already has:

- durable template storage in `backend/api/routes/saved_forms.py`
- download-time PDF materialization in `backend/api/routes/forms.py`
- client-side record selection/fill behavior in `frontend/src/components/features/SearchFillModal.tsx`
- existing saved-form/session/template concepts

The correct canonical object to store is **response data**, not response PDFs.

## Free Tier Product Rule

For the initial product offer:

- free/basic users can have **1 active published Fill By Link template**
- that published link can accept **at most 5 successful responses**
- once response 5 is accepted, the link must automatically stop accepting more submissions
- the public page should show a clean closed state when the cap is reached

This must be enforced on the backend, not only in the UI.

## Premium Tier Product Rule

For paid users, the plan should support a clearly stronger offer:

- premium/pro users can publish a shareable Fill By Link for **every saved template they have**
- each premium/pro link can accept up to **10,000 successful responses**
- this should be advertised clearly in product, docs, homepage messaging, and SEO pages

Important implementation note:

- if you want to advertise `send to 10,000 users`, the backend should enforce a concrete response-cap rule
- unless you also build invitation tracking, market this as `up to 10,000 responses/respondents per link`
- that is measurable and technically honest

## Naming Recommendation

Do not label the phase-1 feature internally as only a `PDF link`.

Reason:

- in phase 1 the respondent is filling a structured web form, not editing the actual PDF
- calling it a `PDF link` can create the wrong expectation

Recommended product naming:

- `Fill By Link`
- `Response Link`
- `Send as Link`

Then describe the outcome as:

- `collect responses and generate the final PDF`

## Main Product Decision

### What I would ship first

Ship one new feature called **Fill By Link** with one canonical backend model:

- `link template`: a respondent-facing schema generated from one saved DullyPDF template
- `link response`: one normalized answer record tied to that link template and owner

The owner's PDF template remains the source PDF.
The respondent never edits that PDF in phase 1.

### What I would explicitly avoid in phase 1

- storing one PDF per respondent response
- scraping Google Forms HTML
- scraping email attachments without a controlled upload/webhook path
- treating signature capture as solved if you only have typed text fields
- storing volatile response arrays inside the existing `user_templates` document metadata

## Why This Is The Best Fit For The Current Repo

The current code already separates these concerns well:

- template/saved-form persistence: `backend/api/routes/saved_forms.py`
- PDF materialization: `backend/api/routes/forms.py`
- field extraction from fillable PDFs in the browser: `frontend/src/utils/pdf.ts`
- record search and one-row fill behavior: `frontend/src/components/features/SearchFillModal.tsx`
- save/download orchestration: `frontend/src/hooks/useSaveDownload.ts`

That means the lowest-risk architecture is:

- keep the PDF template exactly where it already lives
- add a new response-data source
- reuse the existing fill/download path

The repo already proves the final step:

- DullyPDF can take a template PDF plus field/value payload and generate the final output on download

So the new feature only needs to solve:

- respondent data capture
- response storage
- response selection in the owner UI

## Non-Negotiable Architecture Decisions

### 1. Firestore, not GCS, should store normal responses

Use Firestore for structured respondent answers.

Reason:

- responses are small JSON-like records, not binary assets
- Firestore makes list/filter/select/update/delete much easier
- GCS is a poor fit for small mutable records and query-driven UI
- mixing response JSON into `TEMPLATES_BUCKET` would make storage semantics messy

Recommendation:

- **No new bucket for phase 1**
- keep using existing template/form buckets for PDFs only
- add a dedicated bucket only later if you introduce raw response artifacts like uploaded PDFs

### 2. Responses must be their own collection, not embedded in template metadata

Do not append respondent records into `user_templates.metadata`.

Reason:

- Firestore document size limit
- poor concurrent write behavior
- hard pagination and filtering
- impossible to scale response counts cleanly

Recommendation:

- keep `user_templates` for durable template metadata
- add separate collections for link configs and responses

### 3. Public links need tokenized access, not authenticated respondent accounts

Respondents should not need DullyPDF accounts in the default path.

Use:

- a high-entropy public token
- optional expiration
- optional response limits
- rate limiting and reCAPTCHA on submit

### 3.1. Free-tier limits must be hard backend rules

For free/basic users:

- maximum active published fill links: `1`
- maximum accepted responses per published link: `5`

For premium/pro users:

- maximum active published fill links: one for every saved template they are allowed to store
- maximum accepted responses per published link: `10,000`

When the fifth response is accepted:

- update the link status to closed
- persist `closed_reason = response_cap_reached`
- persist `closed_at`
- reject later submits

When the ten-thousandth premium/pro response is accepted:

- apply the same close-on-cap behavior
- persist the same closure reason and timestamps

### 3.2. The response cap must be atomic

Do not enforce the 5-response cap with a naive read-then-write path.

Use a Firestore transaction or equivalent atomic update so two simultaneous submissions cannot both become responses 5 and 6.

### 4. The canonical internal output must be a row-shaped record

Every response should normalize into the same shape the app already understands for Search & Fill:

- keys
- values
- display label
- identifier/search tokens

That avoids creating a second fill engine.

## Recommended Data Model

### Collection 1: `fill_link_templates`

One document per owner-configured respondent form.

Suggested shape:

```json
{
  "owner_user_id": "uid",
  "source_template_id": "user_template_id",
  "source_template_name": "New Patient Intake",
  "status": "draft",
  "accepted_response_count": 0,
  "max_responses": 5,
  "tier_snapshot": "basic",
  "name": "Patient Intake Link",
  "public_token_hash": "sha256(...)",
  "public_token_prefix": "abc123",
  "public_slug": null,
  "question_schema_version": 1,
  "questions": [
    {
      "id": "q_full_name",
      "field_name": "full_name",
      "label": "Full legal name",
      "help_text": "",
      "input_kind": "text",
      "required": true,
      "section": "Patient",
      "sort_order": 10,
      "include_in_response_record": true
    }
  ],
  "identifier_fields": ["full_name", "email"],
  "settings": {
    "allow_multiple_submissions": true,
    "latest_response_wins": true,
    "collect_email": true,
    "require_recaptcha": true,
    "response_retention_days": null,
    "expires_at": null
  },
  "provider": {
    "type": "native"
  },
  "created_at": "ISO",
  "updated_at": "ISO",
  "published_at": null,
  "closed_at": null,
  "closed_reason": null,
  "archived_at": null
}
```

### Collection 2: `fill_link_responses`

One document per submitted respondent record.

Suggested shape:

```json
{
  "owner_user_id": "uid",
  "fill_link_template_id": "link_template_id",
  "source_template_id": "user_template_id",
  "provider_type": "native",
  "provider_response_id": null,
  "status": "submitted",
  "respondent_display_name": "Jane Doe",
  "respondent_lookup_tokens": ["jane doe", "jane@example.com"],
  "identifier_values": {
    "full_name": "Jane Doe",
    "email": "jane@example.com"
  },
  "answers": {
    "full_name": "Jane Doe",
    "dob": "1990-01-15",
    "email": "jane@example.com"
  },
  "normalized_row": {
    "full_name": "Jane Doe",
    "dob": "1990-01-15",
    "email": "jane@example.com"
  },
  "submitted_at": "ISO",
  "updated_at": "ISO",
  "source_ip_hash": "optional",
  "source_user_agent": "optional truncated"
}
```

### Optional later collection: `fill_link_invites`

Only add this if you ship email invitation tracking.
Do not add it in MVP unless you truly need send-state analytics.

## Storage Recommendation

### Phase 1

- Firestore stores link templates and responses
- existing `FORMS_BUCKET` and `TEMPLATES_BUCKET` continue to store PDFs only
- no response PDFs are stored

### Phase 2 or 3 only

If you add uploaded response PDFs or vendor webhook artifacts, create:

- `FILL_LINK_ARTIFACTS_BUCKET`

Use it only for:

- temporary uploaded PDFs
- optional audit artifacts
- short-lived import payloads

Add lifecycle deletion. Do not put those artifacts in `TEMPLATES_BUCKET`.

## Tier Limits And Closure Behavior

### Basic/free tier

- `fillLinksMax = 1`
- `fillLinkResponsesPerLinkMax = 5`

I recommend treating this as:

- **1 active published link at a time** for basic users
- archived or draft links do not count toward the active published cap

That keeps the offer usable while still enforcing the commercial boundary.

### Premium/pro tier recommendation

For the premium/pro offer, the plan should explicitly support:

- one shareable link for every saved template the user has
- `10,000` accepted responses per link

Implementation guidance:

- keep the limits env/config-driven even if the launch copy advertises these exact numbers
- backend role naming can remain `pro`, but marketing copy can say `Premium` if that is the preferred commercial label

Recommended backend interpretation:

- `fillLinksMax = savedFormsMax` for premium/pro users
- `fillLinkResponsesPerLinkMax = 10_000`

If product wants this uncoupled from saved-form count later, expose it separately.

Still do this:

- make them env/config-driven
- expose them through `/api/profile`

### Closed-link UX recommendation

When a link is closed because it reached 5 responses:

- `GET /api/public/fill-links/{token}` should still render a friendly closed-state payload when safe to do so
- `POST /api/public/fill-links/{token}/submit` should reject the submit
- the public page should show a message like `This form is no longer accepting responses`

That is better than a silent failure or confusing 404.

### Suggested closure reasons

- `response_cap_reached`
- `expired`
- `archived`
- `token_rotated`

## Public Link UX Recommendation

### Owner UX

From the workspace:

1. User opens or saves a template as they do today.
2. User clicks new CTA: `Fill by Link`.
3. User configures the respondent form:
   - link name
   - question labels
   - required fields
   - hidden fields
   - identifier fields for later lookup
   - expiration / submission settings
4. User publishes the link.
5. If the user is basic/free, the publish UI clearly says:
   - only 1 active published Fill By Link template is allowed
   - only 5 responses are included
6. If the user is premium/pro, the publish UI clearly says:
   - every saved template can have a shareable link
   - each link supports up to 10,000 responses
7. User copies link or optionally emails it.

### Respondent UX

Respondent lands on a public route such as:

- `/respond/<token>`

The page should:

- be mobile-first
- avoid loading the full workspace runtime
- show the template title and owner branding if configured
- render only the allowed respondent questions
- validate required fields client-side and server-side
- show a simple success state, not a PDF editor
- show a clear closed state when the link hit its response cap

### Owner response-selection UX

Inside the workspace, add a response picker that lets the owner:

- select a link template
- see submitted respondents
- filter by name/email/date
- choose one response
- apply it to the current field list

Do not make the owner type raw response IDs.
Use a human list with search.

## Question Generation Rules

Do not expose raw PDF field names directly to respondents unless they are already clean.

### Recommended derivation flow

When creating a link template:

1. Start from the current saved form fields.
2. Prefer the cleaned field names already present after rename/manual editing.
3. Convert those into human labels using a simple humanizer.
4. Let the owner edit labels and required flags before publish.

### Default field mapping rules

- text field -> single-line text input
- date field -> date input
- checkbox group with shared `groupKey` -> checkbox set or radio/select based on question config
- standalone checkbox -> yes/no checkbox
- signature field -> excluded by default in phase 1

### Signature recommendation

Do not pretend a typed text box is a full e-signature workflow.

For phase 1:

- exclude signature widgets by default
- allow owner override to collect signer name/date as plain text only if they explicitly want that

If customers need legal signature workflows, that is a separate product decision and likely a vendor integration.

## Backend Design Plan

### New route module

Add:

- `backend/api/routes/fill_links.py`

This module should contain both authenticated owner endpoints and public token endpoints.

### New database helpers

Add:

- `backend/firebaseDB/fill_link_template_database.py`
- `backend/firebaseDB/fill_link_response_database.py`

Keep them consistent with the existing `template_database.py` style.

### New service helper

Add:

- `backend/services/fill_link_service.py`

This service should own:

- token generation and hashing
- manifest generation for public page rendering
- response normalization
- respondent display-name construction
- provider mapping logic
- tier-limit checks
- automatic close-on-cap logic
- premium/pro plan-claim messaging inputs

### Suggested request models

Add Pydantic models for:

- `FillLinkCreateRequest`
- `FillLinkUpdateRequest`
- `FillLinkPublishRequest`
- `FillLinkPublicSubmitRequest`
- `FillLinkResponseListRequest` if you want server-side filtering later

Suggested create payload:

```json
{
  "sourceTemplateId": "saved_form_id",
  "name": "Patient Intake Link",
  "identifierFields": ["full_name", "email"],
  "settings": {
    "allowMultipleSubmissions": true,
    "requireRecaptcha": true,
    "collectEmail": true,
    "expiresAt": null
  },
  "questionOverrides": [
    {
      "fieldName": "full_name",
      "label": "Full legal name",
      "required": true,
      "section": "Patient",
      "sortOrder": 10,
      "hidden": false
    }
  ]
}
```

Suggested public submit payload:

```json
{
  "answers": {
    "full_name": "Jane Doe",
    "dob": "1990-01-15",
    "email": "jane@example.com"
  },
  "recaptchaToken": "token",
  "clientContext": {
    "timezone": "America/New_York"
  }
}
```

### Suggested owner-auth endpoints

- `POST /api/fill-links`
  - create draft fill-link config from an existing saved form
- `GET /api/fill-links`
  - list owner's fill-link configs
- `GET /api/fill-links/{link_id}`
  - return config + response summary
- `PATCH /api/fill-links/{link_id}`
  - update labels/settings/order/visibility
- `POST /api/fill-links/{link_id}/publish`
  - generate token and publish
  - enforce max active published links for the owner's tier
- `POST /api/fill-links/{link_id}/rotate-token`
  - invalidate old link and generate a new one
- `POST /api/fill-links/{link_id}/archive`
  - stop future public submissions
- `GET /api/fill-links/{link_id}/responses`
  - list responses
- `GET /api/fill-links/{link_id}/responses/{response_id}`
  - fetch one response
- `DELETE /api/fill-links/{link_id}/responses/{response_id}`
  - delete one response

### Suggested public endpoints

- `GET /api/public/fill-links/{token}`
  - return public form manifest
  - if link is closed, optionally return a closed-state manifest instead of a hard 404
- `POST /api/public/fill-links/{token}/submit`
  - validate and store response
  - enforce atomic response-count cap

### Public manifest response shape

Keep the public payload intentionally narrow.
Do not leak owner internals or template metadata that respondents do not need.

Suggested response:

```json
{
  "title": "Patient Intake Link",
  "description": null,
  "acceptingResponses": true,
  "closedReason": null,
  "acceptedResponseCount": 0,
  "maxResponses": 5,
  "questions": [
    {
      "id": "q_full_name",
      "fieldName": "full_name",
      "label": "Full legal name",
      "helpText": "",
      "inputKind": "text",
      "required": true,
      "options": []
    }
  ],
  "settings": {
    "requireRecaptcha": true
  }
}
```

### Why not overload the existing `public.py`

`backend/api/routes/public.py` currently contains generic public endpoints like contact and reCAPTCHA.
`Fill by Link` is large enough to deserve its own route module.

### Config and env additions

Add dedicated config instead of piggybacking on contact-form settings:

- `FILL_LINK_REQUIRE_RECAPTCHA`
- `RECAPTCHA_FILL_LINK_ACTION`
- `FILL_LINK_RATE_LIMIT_WINDOW_SECONDS`
- `FILL_LINK_RATE_LIMIT_PER_IP`
- `FILL_LINK_RATE_LIMIT_GLOBAL`
- `FILL_LINK_RESPONSE_RETENTION_DAYS`
- `FILL_LINK_MAX_ACTIVE_LINKS_PER_USER`
- `SANDBOX_FILL_LINK_TEMPLATES_MAX_BASE`
- `SANDBOX_FILL_LINK_TEMPLATES_MAX_PRO`
- `SANDBOX_FILL_LINK_TEMPLATES_MAX_GOD`
- `SANDBOX_FILL_LINK_RESPONSES_PER_LINK_MAX_BASE`
- `SANDBOX_FILL_LINK_RESPONSES_PER_LINK_MAX_PRO`
- `SANDBOX_FILL_LINK_RESPONSES_PER_LINK_MAX_GOD`

Reason:

- this public surface has very different abuse patterns than contact/signup
- separate knobs prevent accidental coupling

### Limits service integration

Extend the existing limits pattern in `backend/services/limits_service.py`.

Add:

- `resolve_fill_link_templates_limit(role)`
- `resolve_fill_link_responses_per_link_limit(role)`
- include both in `resolve_role_limits(role)`

Then update:

- `backend/api/routes/profile.py`
- frontend profile types and UI

So the owner can see the actual Fill By Link limits in Profile.

### Question derivation algorithm

Implement derivation from saved-form fields in deterministic steps:

1. Read source fields from the saved form.
2. Sort by page, then `y`, then `x`, then stable field name.
3. Collapse checkbox options by `groupKey` when present.
4. Skip duplicate field names after normalization.
5. Exclude signature widgets by default.
6. Humanize labels from field names.
7. Apply owner overrides.
8. Persist the resolved question list so public rendering is stable even if the workspace copy changes later.

## Frontend Design Plan

### Public route

Add a new public route in `frontend/src/main.tsx`:

- `/respond/:token`

Create:

- `frontend/src/components/pages/FillLinkPublicPage.tsx`
- `frontend/src/components/pages/FillLinkPublicPage.css`

This page should not mount the workspace.

Important repo constraint:

- mobile widths currently disable the main DullyPDF UI and pipeline
- this public respondent route must stay available on mobile because it is not the editor
- therefore the route must live in the public-page path handling in `frontend/src/main.tsx`, not inside the workspace runtime shell

### Workspace feature UI

Add:

- `frontend/src/components/features/FillByLinkDialog.tsx`
- `frontend/src/components/features/FillByLinkResponsesDialog.tsx`
- `frontend/src/hooks/useFillLinks.ts`

Use the same pattern as other extracted feature hooks.

Also update the workspace surface to show:

- current response count for each published link
- closed status
- free-tier quota message when user is at the publish limit
- explanation when a link auto-closed at 5 accepted responses
- premium/pro upsell messaging that every saved template can have a shareable link and each link supports up to 10,000 responses

### API client changes

Extend `frontend/src/services/api.ts` with:

- create/list/update/publish/rotate/archive fill links
- fetch public manifest
- submit public response
- list responses

Also add types in:

- `frontend/src/types/index.ts`

### Profile and billing UI updates

Update:

- `frontend/src/services/api.ts`
- `frontend/src/components/pages/ProfilePage.tsx`

So Profile shows:

- max active Fill By Link templates
- max responses per link
- whether the user is on the free/basic tier with the 1-link/5-response cap
- whether the user is on the premium/pro tier with per-template shareable links and 10,000-response capacity

### Reuse the existing fill behavior by refactoring, not copy-pasting

`SearchFillModal.tsx` currently owns a lot of row-application logic internally.
Do not duplicate that logic in the Fill By Link response picker.

Recommended refactor:

1. Extract the pure row-to-fields application logic into a shared helper in:
   - `frontend/src/utils/searchFill.ts`
   - or a new utility such as `frontend/src/utils/applyRecordToFields.ts`
2. Keep `SearchFillModal.tsx` as the UI wrapper around that shared logic.
3. Call the same helper from the Fill By Link response picker.

That gives you one deterministic fill engine instead of two similar implementations that drift.

### API routing recommendation

Because these are lightweight JSON endpoints, route public fill-link API calls as same-origin `/api/...` requests through the existing frontend/backend pattern.

Update:

- `frontend/docs/api-routing.md`

Reason:

- public respondent pages benefit from avoiding extra CORS friction
- these requests are short and fit the existing rewrite strategy better than long-running upload flows

### Where the "apply response" logic should live

Do not write a second field-filling algorithm.

Instead:

1. Fetch `normalized_row` from the response.
2. Convert it into the same row shape used by Search & Fill.
3. Reuse the existing fill behavior already used for CSV/Excel/JSON records.

That means the long-term clean model is:

- `Search & Fill` becomes a generic record-application engine
- `Fill by Link responses` become one more data source

## Exact Integration With Existing Code

### Reuse as-is

- `backend/api/routes/forms.py`
  - keep using `/api/forms/materialize` for final PDF generation
- `backend/api/routes/saved_forms.py`
  - keep using saved forms as the source template objects
- `frontend/src/components/features/SearchFillModal.tsx`
  - reuse record search/fill behavior
- `frontend/src/hooks/useSaveDownload.ts`
  - keep current save/download workflow

### New glue

The new feature only needs to hand the workspace a selected response row.

That means the end-to-end fill path becomes:

1. response submitted
2. response normalized into `normalized_row`
3. owner selects response in UI
4. app injects that row into existing Search & Fill behavior
5. owner clicks existing download button
6. existing materialize endpoint generates the PDF

## Recommended Firestore Indexes

Add indexes for:

- `fill_link_templates`
  - `owner_user_id ASC, updated_at DESC`
- `fill_link_responses`
  - `owner_user_id ASC, fill_link_template_id ASC, submitted_at DESC`
  - `owner_user_id ASC, fill_link_template_id ASC, respondent_display_name ASC`
  - `owner_user_id ASC, fill_link_template_id ASC, status ASC, submitted_at DESC`

If you store status filtering:

- `owner_user_id ASC, fill_link_template_id ASC, status ASC, submitted_at DESC`

## Security And Abuse Controls

### Token design

- generate at least 32 bytes of randomness
- encode as URL-safe base64
- store only the SHA-256 hash in Firestore
- optionally keep only a short prefix for debugging

### Public response protections

- rate-limit the public manifest GET route
- rate-limit the public submit route more aggressively
- require reCAPTCHA on submit by default
- add link expiry support
- add archive support
- log minimal abuse signals
- enforce the 5-response cap transactionally for free users

### PII handling

- never send respondent values to OpenAI
- never include response data in rename/map payloads
- only show responses to the template owner
- support response deletion
- keep tokenized routes `noindex`

### File upload hard line

If later you support response-PDF upload, do not keep raw PDFs forever by default.

Recommended default:

- process upload
- extract values
- store normalized answers
- delete raw artifact immediately unless the owner explicitly enables audit retention

## Google Forms Option

## Recommendation

Treat Google Forms as an **optional adapter**, not the primary product.

If you want the fastest validation path before building native UI, it can work.
If you want the best long-term product and data ownership, it is the wrong center of gravity.

### How to do it correctly if you choose it

Use the official Google Forms API, not scraping.

Recommended approach:

1. DullyPDF creates a Google Form under a DullyPDF-controlled Google account or Workspace tenant.
2. Store the external `formId`, responder URL, and mapping metadata on the DullyPDF side.
3. Ingest responses using `forms.responses.list`.
4. If scale demands it, use `forms.watches` plus Cloud Pub/Sub for push notifications.
5. Normalize each Google response into the same `fill_link_responses` collection shape.

### Do not scrape Google Forms HTML

That is brittle, unnecessary, and the official API already covers structure and response retrieval.

### Pros

- fastest low-build pilot
- good mobile UX out of the box
- familiar to many respondents
- official response retrieval API exists
- push notification support exists

### Cons

- Google controls branding and public UX
- access/publish behavior is controlled by Google settings, not DullyPDF
- not a clean 1:1 mapping from arbitrary PDF field sets to respondent-friendly questions
- external provider dependency for a core feature
- Google auth/account ownership complexity if you do this per customer or per tenant
- hard to make it feel like a first-class DullyPDF feature

### Pricing and operational notes

- Google states the Forms API has **no additional cost**
- the current Forms API limits page lists 450 read requests per minute per project and 180 write requests per minute per project
- the Google Workspace pricing page currently lists Business Starter at $7/user/month with annual commitment, Business Standard at $14, and Business Plus at $22, with current promotional pricing also shown on the page
- Google also documents Forms API publish/access-control changes around March 31, 2026, which is another reason not to make Google-managed behavior the center of this feature
- if you use push notifications, Pub/Sub billing enters the picture

### My recommendation on Google Forms

If you want a 1-2 week pilot:

- acceptable as a temporary adapter

If you want the permanent architecture:

- do not choose it as the main implementation

## "Send The Actual PDF And Scrape It" Option

## Recommendation

Do **not** define this as "send PDF and scrape it somehow later."

That is not a real transport design.
You only get reliable structured data back if one of these is true:

- the respondent uploads the completed PDF back to DullyPDF
- a vendor posts structured completion data to DullyPDF via webhook/API

### Why this should not be phase 1

- browser/mobile PDF filling is inconsistent
- many PDFs are not true AcroForms
- XFA and flattened PDFs complicate extraction
- signatures and handwritten marks are a separate problem
- you do not control the return path if you only email out a PDF

## Recommended phase-2 version of this feature

Implement **PDF import as an adapter**:

1. Owner optionally enables `PDF response upload`.
2. Respondent can download the source PDF and upload the completed PDF through a controlled public link.
3. Backend extracts AcroForm values using existing PDF tooling already in the repo.
4. Backend stores only normalized answers.
5. Raw uploaded PDF is discarded by default.

### Import outcomes

- `imported_clean`
  - field extraction succeeded
- `imported_partial`
  - some fields missing or ambiguous
- `review_required`
  - non-interactive or unsupported structure

### Why this is a good secondary path

- keeps your canonical internal model unchanged
- avoids storing large piles of response PDFs
- lets you support respondents who insist on filling the real PDF
- does not contaminate the MVP

## Vendor / E-Sign Platform Option

If customers need real signature workflows, audit trails, identity features, or vendor-hosted respondent experiences, use a vendor as an adapter.

### Best-fit role for vendors

Not your default path.
Use them only for:

- real e-signature requirements
- compliance-heavy customers
- cases where respondent must work directly from a vendor workflow

### Pros

- mature respondent flow
- signature/legal workflow support
- reminders, audits, identity options

### Cons

- expensive for this use case
- vendor lock-in
- response data and template flow live partly outside DullyPDF
- implementation complexity rises because webhooks and provider field maps enter the system

### Pricing examples from current official pages

- DocuSign eSignature Standard: $25/user/month
- DocuSign Business Pro: $40/user/month
- DocuSign IAM Standard: $45/user/month
- DocuSign IAM Professional: $75/user/month

Those prices are far above the cost of building the native data-capture path you actually need.

## Implementation Plan By Phase

## Phase 0: Design Lock

Goal:

- finalize the canonical data model and route names before coding

Tasks:

1. Confirm source object for fill links is always a saved form in `user_templates`.
2. Confirm phase 1 excludes signatures as true e-signature workflows.
3. Confirm phase 1 stores structured answers only, not PDFs.
4. Confirm public route naming.
5. Confirm whether invitations are in MVP or deferred.
6. Lock the free-tier policy: 1 active published link, 5 accepted responses, auto-close at cap.
7. Lock the premium/pro policy: shareable link on every saved template, up to 10,000 accepted responses per link.

Output:

- approved schema for `fill_link_templates`
- approved schema for `fill_link_responses`
- approved API surface

## Phase 1: Native Fill By Link MVP

Goal:

- owner can publish a public response form from a saved template
- respondent can submit answers
- owner can apply a response and download the filled PDF

Backend tasks:

1. Add Firestore database helpers.
2. Add request/response models to `backend/api/schemas/models.py`.
3. Add `backend/api/routes/fill_links.py`.
4. Register the router in `backend/api/app.py` and `backend/api/routes/__init__.py`.
5. Implement token hashing and lookup.
6. Implement response normalization.
7. Add rate limiting and reCAPTCHA checks on public submit.
8. Add role-limit helpers for Fill By Link in `backend/services/limits_service.py`.
9. Update `/api/profile` to expose Fill By Link limits.
10. Enforce 1 active published link for free/basic users.
11. Enforce 5 accepted responses max for free/basic published links.
12. Auto-close the link when the fifth response is accepted.
13. Return a friendly closed-state manifest for capped/archived/expired links.
14. Enforce premium/pro publish capacity consistent with saved-template limits.
15. Enforce premium/pro response cap at 10,000 per link.

Frontend tasks:

1. Add public route in `frontend/src/main.tsx`.
2. Add `FillLinkPublicPage`.
3. Add owner dialog for creating and publishing links.
4. Add owner response picker dialog.
5. Add API client methods.
6. Reuse Search & Fill application logic for selected responses.
7. Update Profile to display Fill By Link quotas.
8. Add workspace badges/counters for response count and closed-state messaging.

Acceptance criteria:

- owner can create a link from an existing saved template
- respondent can submit on mobile
- response appears in owner workspace
- owner can select response and generate final PDF via current download flow
- no response PDFs are stored
- free/basic users cannot publish a second active link
- the sixth response is rejected
- the public link shows closed once the cap is reached
- premium/pro users can publish shareable links across all saved templates allowed by their tier
- premium/pro links expose and enforce the 10,000-response cap

## Phase 1.1: Usability Hardening

Goal:

- make the feature safe and pleasant enough for real use

Tasks:

1. Add label editing, section ordering, required flags.
2. Add archive and token rotation.
3. Add response deletion.
4. Add pagination and search in response picker.
5. Add owner copy-link UI and submission count summary.
6. Add explicit closed-state reasons in owner UI and public UI.

## Phase 2: Optional PDF Upload Import

Goal:

- support respondents who insist on filling the original PDF

Tasks:

1. Add optional public upload flow tied to the same fill-link template.
2. Extract AcroForm values with backend PDF tooling.
3. Normalize extracted values into `fill_link_responses`.
4. Delete raw PDFs by default after extraction.
5. Add `review_required` handling for unsupported imports.

Acceptance criteria:

- uploaded AcroForm PDF can produce a response row without keeping a permanent response PDF
- failures are surfaced cleanly to owner

## Phase 3: External Provider Adapters

Goal:

- allow Google Forms or vendor workflows without changing the canonical DullyPDF response model

Tasks:

1. Add provider-type field to fill-link template config.
2. Add adapter-specific mapping layer.
3. Normalize external responses into `fill_link_responses`.
4. Keep DullyPDF as the system of record for response rows used by Search & Fill.

## File-Level Build Plan

### Backend files to add

- `backend/api/routes/fill_links.py`
- `backend/firebaseDB/fill_link_template_database.py`
- `backend/firebaseDB/fill_link_response_database.py`
- `backend/services/fill_link_service.py`

### Backend files to update

- `backend/api/app.py`
- `backend/api/routes/__init__.py`
- `backend/api/schemas/models.py`
- `backend/README.md`
- `backend/services/limits_service.py`
- `backend/api/routes/profile.py`

### Frontend files to add

- `frontend/src/components/pages/FillLinkPublicPage.tsx`
- `frontend/src/components/pages/FillLinkPublicPage.css`
- `frontend/src/components/features/FillByLinkDialog.tsx`
- `frontend/src/components/features/FillByLinkResponsesDialog.tsx`
- `frontend/src/hooks/useFillLinks.ts`

### Repo/root files to add

- `GIT_WORKFLOW.md`

### Demo assets to add

- `frontend/public/demo/mobile-link-publish.png`
- `frontend/public/demo/mobile-link-publish.webp`
- `frontend/public/demo/mobile-link-form.png`
- `frontend/public/demo/mobile-link-form.webp`
- `frontend/public/demo/mobile-link-response-list.png`
- `frontend/public/demo/mobile-link-response-list.webp`
- `frontend/public/demo/mobile-link-final-output.png`
- `frontend/public/demo/mobile-link-final-output.webp`

### Test files to add/update

- backend unit tests for fill-link routes, limits, and closure behavior under `backend/test/unit/api/`
- backend integration tests for publish/submit/close flows under `backend/test/integration/`
- frontend unit tests for public route, publish UI, profile limits, and response picker under `frontend/test/unit/`

### Frontend files to update

- `frontend/src/main.tsx`
- `frontend/src/services/api.ts`
- `frontend/src/types/index.ts`
- `frontend/src/WorkspaceRuntime.tsx`
- `frontend/src/components/pages/ProfilePage.tsx`
- `frontend/src/components/pages/Homepage.tsx`
- `frontend/src/components/pages/Homepage.css`
- `frontend/src/components/pages/usageDocsContent.tsx`
- `frontend/src/config/appConstants.tsx`
- `frontend/src/hooks/useDemo.ts`
- `frontend/docs/overview.md`
- `frontend/docs/structure.md`
- `frontend/docs/api-routing.md`
- `frontend/docs/usage-docs.md`
- `frontend/docs/seo-operations.md`
- `frontend/README.md`
- `frontend/src/config/routeSeo.ts`
- `frontend/src/config/intentPages.ts`
- `scripts/seo-route-data.mjs`
- `README.md`

## Proper Test Plan

This feature needs more than lightweight happy-path tests.
It introduces public submission, tier limits, closed states, docs, and SEO surfaces.

### Backend unit tests

Add tests for:

- token generation and hash lookup
- owner authorization checks
- public manifest lookup
- response validation
- response normalization
- archive / expiry behavior
- response deletion
- rate-limit and reCAPTCHA enforcement
- free/basic tier publish limit of 1 active link
- response-cap enforcement at 5
- premium/pro publish capacity aligned to saved-template allowance
- premium/pro response-cap enforcement at 10,000
- automatic `closed_reason = response_cap_reached`
- concurrent submission protection around the fifth response
- concurrent submission protection around the ten-thousandth response

### Backend integration tests

Add end-to-end API tests covering:

1. basic user publishes first link successfully
2. basic user cannot publish second active link
3. five public submissions succeed
4. fifth submission closes the link
5. sixth submission fails
6. owner can still read prior responses after closure
7. archived and expired links reject submit differently from active links
8. premium/pro user can publish multiple links up to their allowed template count
9. a premium/pro link seeded to 9,999 accepted responses accepts exactly one more and then closes

### Frontend unit tests

Add tests for:

- route resolution for `/respond/:token`
- public submit validation states
- closed-state rendering on the public page
- owner link-creation UI
- free-tier quota messaging in publish UI
- premium/pro plan messaging in publish UI
- response-picker filtering
- selected response flowing into existing fill behavior
- Profile rendering of Fill By Link limits

### SEO/static-generation tests

Add tests or release checks for:

- new intent route metadata exists in `routeSeo.ts`
- `scripts/seo-route-data.mjs` includes the route
- sitemap generation includes the new route
- slash canonicalization works for the new public marketing pages
- docs route metadata stays valid if a new usage-doc page is added

### E2E / browser tests

Use Playwright for at least one real browser path:

1. owner opens workspace
2. creates/publishes link
3. public respondent route loads
4. respondent submits answers
5. owner sees response and applies it
6. closed-state is shown after response cap in a seeded/basic test case
7. premium/pro plan messaging is visible in owner-facing UI

### Demo and marketing regression checks

Add verification for:

- homepage CTA still works on desktop and mobile
- mobile walkthrough images fit without overflow
- interactive demo still runs after adding Fill By Link messaging
- public `/respond/:token` page is usable below 900px

### Manual verification

1. Create saved form.
2. Publish fill link as a basic/free user.
3. Confirm Profile and publish UI show the 1-link/5-response limit.
4. Submit response from desktop.
5. Submit response from mobile width.
6. Submit responses 3, 4, and 5.
7. Confirm the link auto-closes after response 5.
8. Confirm response 6 is rejected.
9. Open workspace and select respondent.
10. Download filled PDF.
11. Rotate token and confirm old link fails.
12. Archive link and confirm public submit fails.
13. Switch to a premium/pro test user and confirm multiple templates can publish links.
14. Confirm premium/pro UI copy advertises shareable links on every template and up to 10,000 responses per link.

## Homepage, SEO, And Demo Plan

## Homepage updates

The homepage currently emphasizes detection, rename/remap, and Search & Fill.
Update it so Fill By Link becomes a visible first-class workflow.

Recommended updates:

1. Add one homepage value section for:
   - `Send a form as a link, collect responses, then generate the final PDF`
2. Add one CTA near the existing workflow/demo CTAs:
   - `See Fill By Link`
3. Add one concise free-tier message:
   - `Free includes 1 active link and up to 5 responses`
4. Add one premium/pro plan message and treat it as a real selling point:
   - `Premium: shareable links for every template, up to 10,000 responses per link`
5. Add one proof point explaining:
   - responses are stored as structured data, not piles of response PDFs

Files to update:

- `frontend/src/components/pages/Homepage.tsx`
- `frontend/src/components/pages/Homepage.css`
- `frontend/src/config/routeSeo.ts`

## SEO updates

Do not rely only on the homepage copy.
Add a dedicated search target for the new workflow.

Recommendation:

- add one new workflow intent page focused on terms like:
  - `fill pdf by link`
  - `send pdf form as link`
  - `collect pdf form responses`

That page should clearly advertise:

- free: 1 active link, 5 responses
- premium/pro: shareable links for every template, up to 10,000 responses per link

Suggested route:

- `/fill-pdf-by-link`

Update:

- `frontend/src/config/intentPages.ts`
- `frontend/src/config/routeSeo.ts`
- `scripts/seo-route-data.mjs`
- generated sitemap/static HTML flow
- `frontend/docs/seo-operations.md`

Also add internal links between:

- homepage -> new intent page
- usage docs -> new intent page
- related intent pages -> new Fill By Link page

## Mobile landing demo updates

The current homepage mobile walkthrough is a static story in `Homepage.tsx`.
Extend it with Fill By Link-specific cards.

Add at least these new mobile demo cards:

1. publish link from template
2. respondent fills public form on phone
3. owner selects response in workspace
4. final PDF generated from that response

Add new assets under:

- `frontend/public/demo/mobile-link-publish.png|webp`
- `frontend/public/demo/mobile-link-form.png|webp`
- `frontend/public/demo/mobile-link-response-list.png|webp`
- `frontend/public/demo/mobile-link-final-output.png|webp`

## Interactive demo recommendation

Do **not** simply keep appending unrelated steps onto the existing editor demo forever.
That demo is already centered on detection -> rename -> map -> Search & Fill.

Best recommendation:

- add a **second dedicated demo path** for Fill By Link rather than bloating the current demo sequence

Why:

- the existing interactive demo is editor-centric
- Fill By Link introduces a public respondent page and owner response-selection flow
- a separate demo stays easier to understand and maintain

Suggested implementation:

1. Keep the current demo as the template-building demo.
2. Add a second demo entry such as `Fill By Link demo`.
3. Drive it with a separate step array in:
   - `frontend/src/config/appConstants.tsx`
4. Add a dedicated hook path or mode in:
   - `frontend/src/hooks/useDemo.ts`
5. Reuse `DemoTour.tsx` but with a second scenario.

Suggested interactive demo steps:

1. start from an already-saved template
2. publish link
3. open public respondent form
4. submit respondent answers
5. return to workspace response list
6. select response and generate final PDF

This gives you both:

- template-building demo
- link-based collection demo

without turning one walkthrough into a confusing omnibus.

## Documentation Plan

This feature changes public behavior, workspace behavior, profile limits, and SEO pages.
It needs docs in multiple places.

### Public usage docs

Add a dedicated usage-docs page:

- `/usage-docs/fill-by-link`

Update:

- `frontend/src/components/pages/usageDocsContent.tsx`
- `frontend/src/main.tsx` route resolution
- `frontend/src/config/routeSeo.ts`
- `frontend/docs/usage-docs.md`

Content should cover:

- when to use Fill By Link vs Search & Fill
- free-tier limit: 1 active link, 5 responses
- premium/pro value: shareable links for every template and up to 10,000 responses per link
- public respondent behavior
- closed-state behavior
- how owner selects a response and downloads the PDF

### Frontend architecture docs

Update:

- `frontend/README.md`
- `frontend/docs/overview.md`
- `frontend/docs/structure.md`
- `frontend/docs/usage-docs.md`
- `frontend/docs/seo-operations.md`

### Backend docs

Update:

- `backend/README.md`

Add:

- route list for Fill By Link endpoints
- limit/config env vars
- explanation that responses are stored as structured data, not response PDFs

### Root/product docs

Update:

- `README.md`

Add:

- one short section describing Fill By Link
- free-tier limit summary
- premium/pro summary: shareable links for every template and up to 10,000 responses per link
- link to the new usage docs page

## Git Documentation Plan

I did not find an obvious in-repo git workflow document.
Because you explicitly want this updated, the plan should assume we create one.

Recommendation:

- create `GIT_WORKFLOW.md` in the repo root

Purpose:

- record the required git/release checklist for this feature family

Contents should include:

1. required tests before merge
2. docs that must be updated when Fill By Link changes
3. SEO/static generation checks
4. demo asset update checklist
5. Firestore index/config rollout checklist
6. homepage/usage-doc/intent-page update checklist when limits or messaging change

Also update:

- `README.md`

to link to `GIT_WORKFLOW.md`.

## Recommended Engineering Order

Build in this order:

1. Firestore models
2. owner-auth API
3. public manifest/submit API
4. public respondent page
5. owner response-picker UI
6. reuse Search & Fill application path
7. polish and security hardening

This order minimizes wasted UI work because the canonical backend objects exist first.

## Final Recommendation

If I were implementing this for the repo right now, I would do this:

1. Ship **native DullyPDF Fill By Link** first.
2. Enforce the free/basic offer in code: 1 active published link, 5 accepted responses, auto-close at cap.
3. Store responses in Firestore as normalized row data.
4. Reuse current saved-form and download/materialize pipeline.
5. Defer PDF-response import until phase 2.
6. Treat Google Forms as an optional pilot adapter only.
7. Treat DocuSign/Adobe-style products as premium adapter paths for signature/compliance use cases, not the baseline architecture.

That gives you the cleanest long-term system, the lowest storage waste, the best UX control, and the strongest fit with the codebase that already exists.

## Sources

- DullyPDF repo architecture:
  - `backend/README.md`
  - `frontend/README.md`
  - `frontend/docs/overview.md`
  - `frontend/docs/structure.md`
  - `frontend/docs/field-editing.md`
  - `backend/api/routes/forms.py`
  - `backend/api/routes/saved_forms.py`
  - `frontend/src/components/features/SearchFillModal.tsx`
  - `frontend/src/hooks/useSaveDownload.ts`
  - `frontend/src/utils/pdf.ts`

- Google Forms official sources:
  - https://developers.google.com/workspace/forms/api/reference/rest/v1/forms.responses/list
  - https://developers.google.com/workspace/forms/api/guides/push-notifications
  - https://developers.google.com/workspace/forms/api/limits
  - https://workspace.google.com/pricing.html
  - https://workspace.google.com/products/forms/

- PDF library / form behavior sources:
  - https://pypdf.readthedocs.io/en/stable/user/forms.html
  - https://pypdf.readthedocs.io/en/stable/user/xfa.html

- Vendor pricing / capability references:
  - https://ecom.docusign.com/plans-and-pricing/esignature
  - https://ecom.docusign.com/plans-and-pricing/iam
  - https://www.docusign.com/products/web-forms
