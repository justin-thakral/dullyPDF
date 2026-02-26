# DullyPDF

FastAPI + React app for detecting PDF form fields, renaming candidates with OpenAI, and editing fields in a PDF viewer. The main pipeline is CommonForms (by [jbarrow](https://github.com/jbarrow/commonforms)) detection, optional OpenAI rename, and schema-only mapping.

## Getting Started

This guide covers a quick local setup for the main pipeline and points to small, tracked fixtures for manual testing.

### Prereqs

- Node.js (for frontend tooling)
- Python 3.10+ (for backend)

### Run the full stack (dev)

From the repo root:

```bash
npm install
npm run dev
```

This starts the FastAPI backend and Vite frontend together, and also starts Stripe CLI webhook forwarding to the local billing webhook when `STRIPE_SECRET_KEY` is configured.

Notes for Stripe local billing:
- `npm run dev` injects the Stripe CLI session `whsec_...` into the backend process for that run.
- Checkout health enforcement is forced off for local CLI forwarding (`STRIPE_ENFORCE_WEBHOOK_HEALTH=false`) because Stripe CLI forwarding does not create a dashboard webhook endpoint.
- Set `STRIPE_DEV_LISTEN_ENABLED=false` to skip automatic Stripe forwarding.

You can still run frontend/backend separately with `npm run backend:dev` and `npm run frontend:dev`.

Open the UI at `http://localhost:5173`.

### Environment setup

Backend dev env is local-only and created on first run:

- Backend: `env/backend.dev.env` (from `config/backend.dev.env.example`)

Frontend uses committed public env files:

- `config/public/frontend.dev.env`
- `config/public/frontend.stack.env`
- `config/public/frontend.prod.env`

Optional local frontend overrides can be added in ignored files:

- `env/frontend.dev.local.env`
- `env/frontend.stack.local.env`
- `env/frontend.prod.local.env`

`npm run backend:dev` loads `env/backend.dev.env`, then pulls Firebase Admin credentials via Secret Manager if configured.
`npm run frontend:dev` builds `frontend/.env.local` from `config/public/frontend.dev.env` and appends local override files when present.

### OpenAI (optional)

Rename and schema mapping require `OPENAI_API_KEY`. If the key is missing, those actions fail while CommonForms (by [jbarrow](https://github.com/jbarrow/commonforms)) detection still works.

## Quick test files

Use the tracked fixtures in `quickTestFiles/`:

- `quickTestFiles/new_patient_forms_1915ccb015.pdf`
- `quickTestFiles/new_patient_forms_1915ccb015_mock.csv` (Search & Fill rows)
- `quickTestFiles/healthdb_vw_form_fields.csv` (schema headers)

Notes:
- CSV/Excel/JSON rows stay in the browser; only headers/types are sent to the server.
- Do not add PHI/PII to tracked files.

## Cleanup

Use the repo cleanup entrypoint to clear generated artifacts:

```bash
python3 clean.py --mcp --mcp-logs --mcp-screenshots
python3 clean.py --runs --tmp --test-results
python3 clean.py --field-detect-logs --mcp-bug-logs --frontend-tmp
python3 clean.py --outbound-leads
python3 clean.py --bug-reports --mcp-security-logs
python3 clean.py --coverage --pytest-cache --python-cache --frontend-dist --output --repo-logs --pipeline-improve
python3 clean.py --all --dry-run
```

Each directory also ships its own `cleanOutput.py` script (see `mcp/`, `runs/`, `test-results/`, `tmp/`, `backend/fieldDetecting/logs/`, `mcp/codexBugs/logs/`, and `frontend/`). Root-level cleanup also supports bug-report folders and local cache/build artifacts.

## Fullstack Read Audit

Scope: main pipeline only (`backend` + detector + `frontend`), with supporting tooling called out separately. Legacy OpenCV pipeline in `legacy/` is excluded from the runtime path.

### 1) Languages in this stack

- Python (backend API + detector services)
- TypeScript (frontend app + build config)
- JavaScript (Node scripts/tooling + MCP server)
- HTML (frontend entry)
- CSS (frontend styling)
- Bash/Shell (dev/deploy/runtime scripts)
- YAML (container/service config)
- JSON (app/tooling config and manifests)
- Markdown (project docs)

Also present (secondary tooling): PowerShell scripts (`.ps1`).

### 2) Backend API libraries (`backend/requirements.txt`)

- `fastapi==0.128.2`
- `uvicorn==0.30.6`
- `pdfplumber==0.11.9`
- `pymupdf==1.24.9` (`fitz`)
- `opencv-python-headless==4.10.0.84`
- `numpy==1.26.4`
- `pillow==12.0.0`
- `openai==2.11.0`
- `python-multipart==0.0.22`
- `httpx==0.28.1`
- `pypdf==6.6.2`
- `firebase-admin==7.1.0`
- `google-cloud-storage==3.9.0`
- `google-cloud-tasks==2.21.0`
- `protobuf==5.29.6`
- `PyJWT==2.10.1`

### 3) Detector-specific libraries

From `backend/requirements-detector.txt` and `Dockerfile.detector`:

- `commonforms==0.2.1`
- `torch==2.9.1+cpu`
- `torchvision==0.24.1+cpu`

### 4) Backend test libraries (`backend/requirements-dev.txt`)

- `pytest>=8.0,<9`
- `pytest-mock>=3.14,<4`
- `pytest-cov>=5,<7`

### 5) Frontend runtime libraries (`frontend/package.json`)

- `react@^19.2.0`
- `react-dom@^19.2.0`
- `pdfjs-dist@^4.5.136`
- `firebase@^10.11.0`
- `firebaseui@^6.1.0`
- `read-excel-file@^6.0.3`

### 6) Frontend build/test/tooling libraries

- `typescript@~5.9.3`
- `vite@^7.2.4`
- `@vitejs/plugin-react@^5.1.1`
- `vitest@^4.0.18`
- `@testing-library/react@^16.2.0`
- `@testing-library/user-event@^14.6.1`
- `jsdom@^26.1.0`
- `eslint@^9.39.1`
- `@eslint/js@^9.39.1`
- `typescript-eslint@^8.46.4`
- `eslint-plugin-react-hooks@^7.0.1`
- `eslint-plugin-react-refresh@^0.4.24`
- `@types/node@^24.10.1`
- `@types/react@^19.2.5`
- `@types/react-dom@^19.2.3`
- `globals@^16.5.0`
- `undici` override: `6.23.0`

### 7) Root workspace tooling (`package.json`)

- `concurrently@^8.2.2` (run frontend/backend together)
- `@playwright/test@^1.57.0` (E2E tooling)

### 8) MCP server libraries (`mcp/server/package.json`)

- `@modelcontextprotocol/sdk@^1.25.1`
- `axios@^1.6.7`
- `dotenv@^16.4.5`
- `form-data@^4.0.0`

### 9) Platform and service dependencies in the live pipeline

- FastAPI backend service on Cloud Run
- Dedicated detector service on Cloud Run
- Firebase Hosting (SPA + selected `/api` rewrites)
- Firebase Auth / Identity Platform
- Firestore (session/schema/request metadata)
- Google Cloud Storage (forms/templates/artifacts)
- Google Cloud Tasks (detector job queue)
- OpenAI API (rename + schema mapping)
- reCAPTCHA Enterprise (contact/signup risk checks)
- Gmail API (contact form email delivery)

### 10) Not on the main runtime path

- `docker-compose.yml` defines SQL Server (`mcr.microsoft.com/mssql/server:2022-latest`) for local/support scenarios.
- Backend docs explicitly state SQL/Postgres integrations are not part of the current main runtime path (moved to `legacy/`).

### Audit inputs reviewed

- `backend/requirements.txt`
- `backend/requirements-detector.txt`
- `backend/requirements-dev.txt`
- `frontend/package.json`
- `package.json`
- `mcp/server/package.json`
- `Dockerfile`
- `Dockerfile.detector`
- `docker-compose.yml`
- `backend/README.md`
- `backend/fieldDetecting/README.md`
- `backend/fieldDetecting/docs/commonforms.md`
- `backend/fieldDetecting/docs/rename-flow.md`
- `frontend/README.md`
- `frontend/docs/overview.md`
- `frontend/docs/api-routing.md`

## More docs

- `backend/README.md`
- `frontend/README.md`
- `backend/fieldDetecting/docs/README.md`
