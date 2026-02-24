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

- End-user documentation is available at `/usage-docs/*` (with `/docs/*` aliases).
- The docs include dedicated pages for detection, rename/mapping, editor workflow, Search & Fill, and troubleshooting.
- Route handling lives in `frontend/src/main.tsx` alongside legal page route handling.

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
- Small tracked fixtures live in `quickTestFiles/`; larger local datasets live in `samples/`.
- Regenerate demo rename/remap name maps from the repo root with `npm run demo:generate-name-maps`.

## Out of scope

- Full PDF content editing beyond form fields/overlays.
- Search & Fill from TXT uploads.
- Offline persistence (state is session-scoped unless saved).
