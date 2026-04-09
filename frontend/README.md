# Frontend

React + TypeScript UI for viewing PDFs, editing detected fields, organizing saved forms into named groups, running Search & Fill, publishing native Fill By Link forms for either one saved template or an open group, sending PDFs for signature, and saving forms. Saved templates now also expose an `API Fill` manager in the workspace header so owners can publish a template-scoped JSON-to-PDF endpoint, rotate/revoke keys, review recent endpoint activity, and copy server-side examples without leaving the editor. The upload screen includes a compact saved-form browser with group filtering, a stable selected-group label during group refreshes, an `Open groups` toggle, create/delete group actions, and pill-style saved-template chips. Fill By Link now uses a large builder dialog with sticky global settings, searchable question management, live preview, per-question requiredness and text limits, template-only custom web-form questions, and a separate responses tab for Search & Fill handoff. Saved forms now persist versioned editor snapshots so reopen/group-switch flows can hydrate fields and page sizes without re-extracting them on every open. The editor now treats radio fields as first-class single-select groups instead of leaning on legacy checkbox hints, and the frontend talks to the FastAPI backend for detection, OpenAI rename, schema mapping (schema headers only), group management, and owner/respondent workflows, including deterministic `fillRules` for checkbox, radio, and text split/join fill behavior. Workspace navigation is route-driven under `/upload` and `/ui`, with direct routes for the upload shell, profile, saved forms, and saved groups so refresh/bookmark flows reopen the same workspace context instead of dropping back to `/`.
Public product usage documentation is available at canonical `/usage-docs/*` URLs. Legacy `/docs/*` URLs permanently redirect to matching canonical docs routes.
Public intent landing pages are also available for search-oriented entry routes (for example `/pdf-to-fillable-form`, `/pdf-fill-api`, `/pdf-radio-button-editor`, `/pdf-signature-workflow`, and `/fill-pdf-from-csv`) and industry-focused routes (for example `/healthcare-pdf-automation` and `/acord-form-automation`).
Public plan explainer pages are available at `/free-features` and `/premium-features`, and the premium page can launch Stripe Checkout for signed-in users when billing is available.
Profile and public plan messaging now audit the full enforced tier set instead of only Fill By Link copy. Current defaults are: free = 5 saved forms, 5 detect pages, 50 fillable pages, unlimited active Fill By Links with 25 accepted responses/month across the account, 1 API Fill endpoint with 250 fills/month and 25 pages/request, 25 sent signing requests/month, and a base OpenAI pool that tops back up to 10 each month when the balance is below 10; premium = 100 saved forms, 100 detect pages, 1,000 fillable pages, unlimited active Fill By Links with 10,000 accepted responses/month across the account, 20 API Fill endpoints with 10,000 fills/month and 250 pages/request, 10,000 sent signing requests/month, and a 500-credit monthly pool before refill packs.
Completed signing flows now also expose a public `/verify-signing/:token` validation page, and audit receipts point there with a QR-backed validation link so recipients can re-check the retained record later without opening the signer ceremony again. The owner-side audit evidence is broader than the public receipt: it preserves immutable source/signed hashes, sender and signer identity fields, invite delivery metadata, OTP/access-check state, ceremony timestamps, disclosure evidence, retained artifact metadata, and, for company-binding requests, the authority-attestation text/version/hash plus the signer-provided representative title and company name so the owner can export a dispute package later. That evidence model is intended to support the core E-SIGN mechanics around signer intent, association with the exact record, consumer consent where required, and later-reference retention, but it is not a blanket legal determination for every workflow or an independent proof of corporate authority. When no production PKCS#12 or Cloud KMS PDF signing identity is configured, DullyPDF can self-sign the finalized PDF for tamper evidence, but standard PDF viewers may still show that embedded certificate as untrusted because it is not chained to a public CA. In that configuration, the intended verification path is the audit receipt plus the retained validation page rather than a viewer trust badge.
Search & Fill keeps selected row data in the browser. API Fill is different: published API requests send JSON record data to the backend and are governed by server-side rate limits, monthly request caps, and audit logging.
If a paid account downgrades below the saved-form limit, the frontend keeps every saved form visible but only the oldest-created forms inside the base cap stay accessible. The remaining templates are locked in place until the owner upgrades again, and any Fill By Link, signing, group, or API Fill flow tied to a locked template is blocked without deleting the underlying records.

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

To open the internal production stats dashboard locally:

```bash
npm run stats
```

This starts a standalone local server on `http://127.0.0.1:5174`. The dashboard is intentionally outside the shipped frontend/backend bundles, reads the production Firestore project directly, and does not use DullyPDF app sign-in. Use `gcloud auth application-default login` if your local Google credentials are not already configured.

## Environment

The dev scripts source env vars via `scripts/use-frontend-env.sh`. Common entries:
- `VITE_API_URL` / `VITE_DETECTION_API_URL` for backend base URLs.
- `VITE_DETECTION_POLL_TIMEOUT_MS` to cap how long detection polling waits before returning.
- `VITE_BACKEND_READY_MAX_WAIT_MS` to control how long the homepage shell waits for `/api/health` during Cloud Run cold starts before surfacing a retry message.
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

## Workspace routes

- `/` keeps the marketing shell.
- `/upload` opens the signed-in upload shell.
- `/ui` is the generic editor/runtime route for unsaved uploads and in-flight workspace processing.
- `/ui/profile` opens the profile view.
- `/ui/forms/:formId` reopens a saved form directly.
- `/ui/groups/:groupId?template=:formId` reopens a saved group and, when present, prefers the requested template.
- Refresh restore is session-scoped. The browser stores a small resume manifest in `sessionStorage` and uses backend session state for recovery. Saved forms/groups still rehydrate from backend data plus the saved editor snapshot. Ad hoc `/ui` workspaces can also recover after reload when they already have a live detect/mapping session because the runtime re-downloads the source PDF from the backend session and reapplies the server-side field/rule snapshot.
- The resume manifest is not a full offline cache. It still does not persist PDF bytes or unsaved field edits locally, and ad hoc `/ui` recovery only works while the backing session is still alive.

## Detection timeout behavior

- `VITE_DETECTION_POLL_TIMEOUT_MS` only caps how long the foreground upload flow waits before yielding control back to the runtime.
- If backend detection is still running when that timeout expires and there are no usable embedded fields yet, the editor stays in the processing state and continues polling in the background instead of opening a false-empty workspace.
- If usable embedded fields already exist, the runtime can open with those fields while detection continues in the background.

Builds should use an explicit env target so the generated bundle never depends
on whatever stale `.env.local` happens to be in the workspace:

- From the repo root: `npm run frontend:build:dev` or `npm run frontend:build:prod`
- From `frontend/`: `npm run build:dev` or `npm run build:prod`

Production/static deploys then run `node scripts/generate-static-html.mjs`, which emits both the prerendered homepage/public-route HTML and a neutral `frontend/dist/app-shell.html` used only for Firebase rewrite targets like `/respond/:token`, `/sign/:token`, `/upload`, and `/ui/*`.

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
