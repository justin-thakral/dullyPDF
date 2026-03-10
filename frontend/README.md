# Frontend

React + TypeScript UI for viewing PDFs, editing detected fields, organizing saved forms into named groups, running Search & Fill, publishing native Fill By Link forms for either one saved template or an open group, and saving forms. The upload screen includes a compact saved-form browser with group filtering, a stable selected-group label during group refreshes, an `Open groups` toggle, create/delete group actions, and pill-style saved-template chips. Saved forms now persist versioned editor snapshots so reopen/group-switch flows can hydrate fields and page sizes without re-extracting them on every open. The frontend talks to the FastAPI backend for detection, OpenAI rename, schema mapping (schema headers only), group management, and owner/respondent workflows, including deterministic `fillRules` for checkbox and text split/join fill behavior.
Public product usage documentation is available at canonical `/usage-docs/*` URLs. Legacy `/docs/*` URLs permanently redirect to matching canonical docs routes.
Public intent landing pages are also available for search-oriented entry routes (for example `/pdf-to-fillable-form`, `/pdf-to-database-template`, and `/fill-pdf-from-csv`) and industry-focused routes (for example `/healthcare-pdf-automation` and `/acord-form-automation`).
Public plan explainer pages are available at `/free-features` and `/premium-features`, and the premium page can launch Stripe Checkout for signed-in users when billing is available.
Native Fill By Link marketing surfaces advertise the current tiering: free users get 1 active link with 5 responses, and premium users can publish a shareable link for every saved template with up to 10,000 responses per link.
If a paid account downgrades below the saved-form limit, the frontend shows a downgrade-retention dialog on each site visit, lets the owner choose which saved forms stay within the free cap, and exposes delete-now/reactivate-Pro actions during the 30-day grace period.

## Quick start

From the repo root (recommended):

```bash
npm run frontend:dev
```

Or run it directly:

```bash
cd frontend
npm install
npm run dev
```

Vite will pick the next available port (typically `http://localhost:5173`).

To run the full local stack (frontend + backend) from the repo root:

```bash
npm run dev
```

To run the prod-like dev stack (backend container + Cloud Tasks + Cloud Run detector):

```bash
npm run dev:stack
```

Stop the dev stack cleanly:

```bash
npm run dev:stack:stop
```

## Environment

The dev scripts source env vars via `scripts/use-frontend-env.sh`. Common entries:
- `VITE_API_URL` / `VITE_DETECTION_API_URL` for backend base URLs.
- `VITE_DETECTION_POLL_TIMEOUT_MS` to cap how long detection polling waits before returning.
- Firebase Identity Platform keys (`VITE_FIREBASE_*`).
- `VITE_GOOGLE_ADS_TAG_ID` to inject the Google Ads `gtag.js` base tag in prod builds.
- `VITE_GOOGLE_ADS_SIGNUP_LABEL`, `VITE_GOOGLE_ADS_PRO_PURCHASE_LABEL`, and `VITE_GOOGLE_ADS_REFILL_PURCHASE_LABEL` for native Google Ads conversion events.
- `VITE_DISABLE_ADMIN_OVERRIDE=1` to force-disable admin overrides in dev (prod-like runs).

Committed frontend env sources live in:
- `config/public/frontend.dev.env`
- `config/public/frontend.stack.env`
- `config/public/frontend.prod.env`

Optional local-only overrides live in ignored files:
- `env/frontend.dev.local.env`
- `env/frontend.stack.local.env`
- `env/frontend.prod.local.env`

Legacy local override files (`env/frontend.dev.env`, `env/frontend.stack.env`, `env/frontend.prod.env`) are still loaded when present to avoid breaking existing local setups.

The dev stack runs the backend in prod mode (revocation checks on, legacy
endpoints disabled) while targeting dev resources. It reads
`config/public/frontend.stack.env` so admin override headers stay disabled for
prod-like testing.

Builds should use an explicit env target so the generated bundle never depends
on whatever stale `.env.local` happens to be in the workspace:

- From the repo root: `npm run frontend:build:dev` or `npm run frontend:build:prod`
- From `frontend/`: `npm run build:dev` or `npm run build:prod`

CSV/XLSX/JSON/TXT schema imports are capped at 10MB in the browser so oversized
files fail fast instead of freezing the editor tab.

## Cleanup

```bash
python3 frontend/cleanOutput.py --tmp
```

Or from the repo root:

```bash
python3 clean.py --frontend-tmp
```

Add `--dry-run` to preview.

## WebP Assets

Use the open-source ImageMagick CLI (`convert`) to refresh `.webp` mirrors for files in
`frontend/public`:

```bash
npm run frontend:webp
```

You can tune conversion settings with:
- `WEBP_QUALITY` (default `82`)
- `WEBP_METHOD` (default `6`)

## Docs

See `frontend/docs/README.md` for architecture and workflow notes.
See `frontend/docs/seo-operations.md` for weekly Search Console and authority growth workflow.
See `frontend/test/docs/unit.md` for frontend unit test implementation guidance.
See `../GIT_WORKFLOW.md` for the repo-level documentation and pricing-copy update checklist that should ship with customer-facing features.
