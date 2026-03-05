# Overview

The frontend is a React + TypeScript app for loading PDFs, editing fields, and filling records from local data sources. It connects to the FastAPI backend for detection, OpenAI rename/mapping, profile data, and saved forms.

## Main workflow

1. Load a PDF (detection upload, fillable upload, or saved form).
2. Detect fields with CommonForms (by [jbarrow](https://github.com/jbarrow/commonforms)) via `/detect-fields`, or import embedded AcroForm widgets.
3. Optionally run OpenAI rename and schema mapping.
4. Edit fields in overlay/list/inspector panels.
5. Run Search & Fill from CSV/Excel/JSON rows.
6. Download a filled PDF or save it to the signed-in profile.
7. Persist and replay deterministic fill rules (`fillRules`) including text split/join transforms.

## Public usage docs

- End-user documentation is available at canonical `/usage-docs/*` URLs.
- Legacy `/docs/*` URLs are compatibility redirects (HTTP 301) to `/usage-docs/*`.
- Canonical style is non-trailing slash for non-root routes; `/path/` should only 301 once to `/path` (never loop).
- The docs include dedicated pages for detection, rename/mapping, editor workflow, Search & Fill, and troubleshooting.
- Route handling lives in `frontend/src/main.tsx` alongside legal page route handling.

## SEO landing routes

- Public intent landing pages cover commercial search intents:
  - `/pdf-to-fillable-form`
  - `/pdf-to-database-template`
  - `/fill-pdf-from-csv`
  - `/fill-information-in-pdf`
  - `/fillable-form-field-name`
- Industry-specific SEO routes are available for:
  - `/healthcare-pdf-automation`
  - `/acord-form-automation`
  - `/insurance-pdf-automation`
  - `/real-estate-pdf-automation`
  - `/government-form-automation`
  - `/finance-loan-pdf-automation`
  - `/hr-pdf-automation`
  - `/legal-pdf-workflow-automation`
  - `/education-form-automation`
  - `/nonprofit-pdf-form-automation`
  - `/logistics-pdf-automation`
- Each route has unique canonical metadata and FAQ structured data.
- Two hub routes aggregate intent pages for cleaner global navigation:
  - `/workflows` lists workflow-intent pages.
  - `/industries` lists industry-intent pages.

## Data source behavior

- CSV/Excel/JSON imports parse schema headers and rows.
- TXT imports are schema-only (headers/types, no rows).
- Schema metadata can be persisted to `/api/schemas` for mapping.
- OpenAI confirmations warn before sending PDF/schema content; row values and field values are not included in OpenAI rename/map requests.

## Auth and profile

- Firebase auth supports email/password, Google, and GitHub.
- Password users must verify email before editor access.
- Profile view shows limits, credits, Stripe billing/subscription status, and saved forms.

## Demo and fixtures

- Demo assets are served from `frontend/public/demo`.
- Demo sessions allow downloading the generated PDF without signing in; saving to profile remains sign-in only.
- Small tracked fixtures live in `quickTestFiles/`; larger local datasets live in `samples/`.
- Regenerate demo rename/remap name maps from the repo root with `npm run demo:generate-name-maps`.

## Out of scope

- Full PDF content editing beyond form fields/overlays.
- Search & Fill from TXT uploads.
- Offline persistence (state is session-scoped unless saved).
