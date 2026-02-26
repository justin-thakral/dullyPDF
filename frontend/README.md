# Frontend

React + TypeScript UI for viewing PDFs, editing detected fields, running Search & Fill, and saving forms. The frontend talks to the FastAPI backend for detection, OpenAI rename, and schema mapping (schema headers only), including deterministic `fillRules` for checkbox and text split/join fill behavior.
Public product usage documentation is available at canonical `/usage-docs/*` URLs. Legacy `/docs/*` URLs permanently redirect to matching canonical docs routes.
Public intent landing pages are also available for search-oriented entry routes (for example `/pdf-to-fillable-form`, `/pdf-to-database-template`, and `/fill-pdf-from-csv`) and industry-focused routes (for example `/healthcare-pdf-automation` and `/acord-form-automation`).

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
- `VITE_ADMIN_TOKEN` (dev-only; never use in production builds).
- `VITE_DISABLE_ADMIN_OVERRIDE=1` to force-disable admin overrides in dev (prod-like runs).

The dev stack runs the backend in prod mode (revocation checks on, legacy
endpoints disabled) while targeting dev resources. It reads
`env/frontend.stack.env` (from `config/frontend.stack.env.example`) so admin
override headers stay disabled for
prod-like testing.

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
