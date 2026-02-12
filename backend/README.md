## Backend

FastAPI service for PDF field detection, schema-only OpenAI mapping, and saved-form storage. Runtime entrypoint remains `backend/main.py`, while app construction and routing now live under `backend/api/`:

- `backend/api/app.py`: app factory + middleware + router registration
- `backend/api/routes/`: endpoint modules grouped by domain
- `backend/api/schemas/`: request model definitions
- `backend/services/`: shared business/helpers used by routes

Detection is executed by the dedicated detector service (`backend/detection/detector_app.py`) which runs CommonForms (by [jbarrow](https://github.com/jbarrow/commonforms)) under `backend/fieldDetecting/commonforms/`. The legacy OpenCV pipeline lives in `legacy/fieldDetecting/` and is not part of the main pipeline.

### Core flows

- Detection: `POST /detect-fields` queues CommonForms (by [jbarrow](https://github.com/jbarrow/commonforms)) detection and returns a `sessionId`.
- Detection status: `GET /detect-fields/{sessionId}` returns status + fields when ready.
- CommonForms-only (by [jbarrow](https://github.com/jbarrow/commonforms)): `POST /api/process-pdf` (legacy upload helper; dev-only; auth required; no rename/mapping).
- Register fillable: `POST /api/register-fillable` (dev-only; auth required; store PDF bytes without running detection).
- OpenAI rename (overlay tags + PDF pages; schema headers included for combined rename+map): `POST /api/renames/ai`.
- OpenAI rename job status (task mode): `GET /api/renames/ai/{jobId}`.
- Schema metadata: `POST /api/schemas`, `GET /api/schemas`.
- Schema mapping (OpenAI): `POST /api/schema-mappings/ai` (results returned only; not persisted).
- Schema mapping job status (task mode): `GET /api/schema-mappings/ai/{jobId}`.
- Saved forms: `GET /api/saved-forms`, `POST /api/saved-forms` (supports `overwriteFormId` to replace an existing saved form), `GET /api/saved-forms/{id}`, `GET /api/saved-forms/{id}/download`, `POST /api/saved-forms/{id}/session`, `DELETE /api/saved-forms/{id}`.
- Template session (fillable upload): `POST /api/templates/session` (stores PDF bytes + fields so rename/mapping can run).
- Materialize fillable: `POST /api/forms/materialize` (auth required; injects fields into a PDF upload and enforces fillable page limits).
- Profile summary: `GET /api/profile` (tier info, credits, and limits).
- Contact form: `POST /api/contact` (public; reCAPTCHA required; sends email via Gmail API).
- reCAPTCHA verify: `POST /api/recaptcha/assess` (public; used for account creation checks).

### Production API routing (Firebase Hosting rewrites)

In production, the SPA is served from Firebase Hosting and a subset of backend endpoints are proxied
through Hosting rewrites so the browser can call them as same-origin `/api/...` requests. This is
primarily to remove CORS preflights (OPTIONS) from fast JSON endpoints (notably reCAPTCHA verification
and profile fetches) so Cloud Run scale-to-zero cold starts feel less blocking.

Some endpoints are intentionally not proxied (OpenAI routes, detection routes, and large upload/stream
routes) to avoid Firebase Hosting's Cloud Run rewrite timeout (approximately 60 seconds) and to keep
large transfers direct-to-Cloud-Run.

See `frontend/docs/api-routing.md` for the current rewrite list and frontend call rules.

### Runtime requirements

- Main API: Cloud Tasks client + Firebase Admin + OpenAI (optional).
- Detector service: CommonForms (by [jbarrow](https://github.com/jbarrow/commonforms)) + PyTorch for detection.
- Rename worker service: OpenAI rename execution (`backend/ai/rename_worker_app.py`).
- Remap worker service: OpenAI schema mapping execution (`backend/ai/remap_worker_app.py`).
- OpenAI API key for rename + schema mapping (schema metadata only).
- Firebase Admin for auth and role claims.
- GCS buckets for saved forms and templates.

### Minimum env (dev)

- `FIREBASE_PROJECT_ID`
- `FIREBASE_CREDENTIALS` (JSON string), `GOOGLE_APPLICATION_CREDENTIALS` (path), or
  `FIREBASE_USE_ADC=true` on GCP (recommended for prod).
- `FIREBASE_CREDENTIALS_SECRET` (Secret Manager name loaded by `scripts/*backend*.sh`)
- `FIREBASE_CREDENTIALS_PROJECT` (Secret Manager project, if different from `FIREBASE_PROJECT_ID`)
- `FORMS_BUCKET`, `TEMPLATES_BUCKET`
- `OPENAI_API_KEY` (only if schema mapping enabled)
- `CONTACT_TO_EMAIL`, `CONTACT_FROM_EMAIL`
- `GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET`, `GMAIL_REFRESH_TOKEN`
- `GMAIL_USER_ID` (optional; defaults to `me`)
- `RECAPTCHA_SITE_KEY`
- `RECAPTCHA_PROJECT_ID` (or `FIREBASE_PROJECT_ID` / `GCP_PROJECT_ID`)
- `RECAPTCHA_CONTACT_ACTION` (default `contact`; overrides legacy `RECAPTCHA_EXPECTED_ACTION`)
- `RECAPTCHA_SIGNUP_ACTION` (default `signup`; overrides legacy `RECAPTCHA_EXPECTED_ACTION`)
- `RECAPTCHA_ALLOWED_HOSTNAMES` (optional comma-separated allowlist; supports `*.example.com`)
- `RECAPTCHA_MIN_SCORE` (default 0.5)
- `CONTACT_REQUIRE_RECAPTCHA` (default true)
- `CONTACT_RATE_LIMIT_WINDOW_SECONDS`, `CONTACT_RATE_LIMIT_PER_IP`
- `CONTACT_RATE_LIMIT_GLOBAL` (optional; global cap for `/api/contact` regardless of caller IP)
- `SIGNUP_REQUIRE_RECAPTCHA` (default true)
- `SIGNUP_RATE_LIMIT_WINDOW_SECONDS`, `SIGNUP_RATE_LIMIT_PER_IP`
- `SIGNUP_RATE_LIMIT_GLOBAL` (optional; global cap for `/api/recaptcha/assess` regardless of caller IP)
- `SANDBOX_TRUST_PROXY_HEADERS` (default false; only enable when Cloud Run is reachable *only* via a trusted proxy that strips spoofed headers)
- `SANDBOX_CORS_ORIGINS` (comma-separated list)
- `SANDBOX_ENABLE_LEGACY_ENDPOINTS` (dev-only; defaults to true; ignored in prod)
- `ADMIN_TOKEN` (dev-only override; ignored when `ENV=prod` or `SANDBOX_ALLOW_ADMIN_OVERRIDE=false`)
- `SANDBOX_DETECT_MAX_PAGES_BASE`, `SANDBOX_DETECT_MAX_PAGES_GOD`
- `SANDBOX_FILLABLE_MAX_PAGES_BASE`, `SANDBOX_FILLABLE_MAX_PAGES_GOD`
- `SANDBOX_SAVED_FORMS_MAX_BASE`, `SANDBOX_SAVED_FORMS_MAX_GOD`
- `SANDBOX_SCHEMA_TTL_SECONDS`
- `SANDBOX_OPENAI_LOG_TTL_SECONDS`
- `SANDBOX_ENABLE_DOCS` (optional; allow OpenAPI/docs in dev only; ignored in prod)
- `DETECTOR_MODE` (`tasks` for production)
- `DETECTOR_TASKS_PROJECT`, `DETECTOR_TASKS_LOCATION`
- `DETECTOR_TASKS_QUEUE` or `DETECTOR_TASKS_QUEUE_LIGHT`
- `DETECTOR_SERVICE_URL` or `DETECTOR_SERVICE_URL_LIGHT`
- `DETECTOR_TASKS_QUEUE_HEAVY`, `DETECTOR_SERVICE_URL_HEAVY` (optional; for 10+ page PDFs)
- `DETECTOR_TASKS_HEAVY_PAGE_THRESHOLD` (default 10)
- `DETECTOR_TASKS_SERVICE_ACCOUNT`
- `DETECTOR_TASKS_AUDIENCE`, `DETECTOR_TASKS_AUDIENCE_LIGHT`, `DETECTOR_TASKS_AUDIENCE_HEAVY` (optional)
- `DETECTOR_TASKS_DISPATCH_DEADLINE_SECONDS_LIGHT`, `DETECTOR_TASKS_DISPATCH_DEADLINE_SECONDS_HEAVY` (optional)
- `DETECTOR_TASKS_FORCE_IMMEDIATE` (optional; schedule tasks in the past to bypass host clock skew)
- `OPENAI_RENAME_MODE` (`tasks` for production async rename workers)
- `OPENAI_RENAME_TASKS_PROJECT`, `OPENAI_RENAME_TASKS_LOCATION`
- `OPENAI_RENAME_TASKS_QUEUE` or `OPENAI_RENAME_TASKS_QUEUE_LIGHT`
- `OPENAI_RENAME_SERVICE_URL` or `OPENAI_RENAME_SERVICE_URL_LIGHT`
- `OPENAI_RENAME_TASKS_QUEUE_HEAVY`, `OPENAI_RENAME_SERVICE_URL_HEAVY` (optional; for larger PDFs)
- `OPENAI_RENAME_TASKS_HEAVY_PAGE_THRESHOLD` (default 10)
- `OPENAI_RENAME_TASKS_SERVICE_ACCOUNT`
- `OPENAI_RENAME_TASKS_AUDIENCE`, `OPENAI_RENAME_TASKS_AUDIENCE_LIGHT`, `OPENAI_RENAME_TASKS_AUDIENCE_HEAVY` (optional)
- `OPENAI_RENAME_TASKS_DISPATCH_DEADLINE_SECONDS_LIGHT`, `OPENAI_RENAME_TASKS_DISPATCH_DEADLINE_SECONDS_HEAVY` (optional)
- `OPENAI_REMAP_MODE` (`tasks` for production async remap workers)
- `OPENAI_REMAP_TASKS_PROJECT`, `OPENAI_REMAP_TASKS_LOCATION`
- `OPENAI_REMAP_TASKS_QUEUE` or `OPENAI_REMAP_TASKS_QUEUE_LIGHT`
- `OPENAI_REMAP_SERVICE_URL` or `OPENAI_REMAP_SERVICE_URL_LIGHT`
- `OPENAI_REMAP_TASKS_QUEUE_HEAVY`, `OPENAI_REMAP_SERVICE_URL_HEAVY` (optional; for large template tag sets)
- `OPENAI_REMAP_TASKS_HEAVY_TAG_THRESHOLD` (default 120)
- `OPENAI_REMAP_TASKS_SERVICE_ACCOUNT`
- `OPENAI_REMAP_TASKS_AUDIENCE`, `OPENAI_REMAP_TASKS_AUDIENCE_LIGHT`, `OPENAI_REMAP_TASKS_AUDIENCE_HEAVY` (optional)
- `OPENAI_REMAP_TASKS_DISPATCH_DEADLINE_SECONDS_LIGHT`, `OPENAI_REMAP_TASKS_DISPATCH_DEADLINE_SECONDS_HEAVY` (optional)
- `OPENAI_REQUEST_TIMEOUT_SECONDS` (default 75; bounds each OpenAI request to avoid long UI stalls)
- `OPENAI_MAX_RETRIES` (default 1; OpenAI SDK retry count for rename/remap calls)
- `OPENAI_WORKER_MAX_RETRIES` (default 0; worker-only OpenAI SDK retries to avoid multiplying Cloud Tasks retries)
- `OPENAI_PRICE_INPUT_PER_1M_USD`, `OPENAI_PRICE_OUTPUT_PER_1M_USD` (optional; enables per-job USD estimates)
- `OPENAI_PRICE_CACHED_INPUT_PER_1M_USD`, `OPENAI_PRICE_REASONING_OUTPUT_PER_1M_USD` (optional; refine USD estimates when token subclasses are available)
- `OPENAI_PREWARM_ENABLED` (default false; best-effort worker warmup during detection)
- `OPENAI_PREWARM_REMAINING_PAGES` (default 3; trigger point for prewarm)
- `OPENAI_PREWARM_TIMEOUT_SECONDS` (default 2; health check timeout)

Detector env examples:
- `config/detector.dev.env.example`
- `config/detector.prod.env.example`

### Notes

- Session entries are cached in-process (L1) and persisted in Firestore + GCS (L2) for multi-instance access.
- L1 uses TTL/LRU via `SANDBOX_SESSION_TTL_SECONDS`, `SANDBOX_SESSION_SWEEP_INTERVAL_SECONDS`, and `SANDBOX_SESSION_MAX_ENTRIES`.
- L2 expiry should be aligned to `SANDBOX_SESSION_TTL_SECONDS` with Firestore TTL plus a scheduled cleanup job for GCS session artifacts (`scripts/cleanup_sessions.py`).
- L2 touch throttling uses `SANDBOX_SESSION_L2_TOUCH_SECONDS` (default 300 seconds).
- Editor clients should call `/api/sessions/{sessionId}/touch` about once per minute to keep active sessions from expiring.
- `SANDBOX_SESSION_BUCKET` can override the default session bucket (falls back to `FORMS_BUCKET`).
- Schema metadata TTL uses `SANDBOX_SCHEMA_TTL_SECONDS` (default 3600) with Firestore TTL on `schema_metadata.expires_at`.
- Detector jobs are queued via Cloud Tasks; the detector service writes fields/results to GCS + Firestore.
- Detector routing picks the heavy queue when `page_count >= DETECTOR_TASKS_HEAVY_PAGE_THRESHOLD` and the heavy service URLs are configured.
- Rename/remap jobs can run in `tasks` mode and are persisted in Firestore (`openai_jobs`) with pollable status.
- Async rename/remap jobs store OpenAI usage summaries (`openai_usage_summary`, `openai_usage_events`) so status polling can report token usage (and optional USD estimates when pricing env vars are set).
- Rename/remap task workers refund consumed credits on terminal failures.
- Detection can emit best-effort OpenAI worker prewarm requests when `OPENAI_PREWARM_ENABLED=true` and remaining pages are below `OPENAI_PREWARM_REMAINING_PAGES`.
- Encrypted PDFs are rejected before detection to avoid repeated task retries.
- `DETECTOR_TASKS_MAX_ATTEMPTS` on the detector service should match the Cloud Tasks queue max attempts to finalize failures on the last retry.
- Session ownership guards can be sanity-checked with `python -m backend.scripts.verify_session_owner`.
- Base users start with 10 lifetime OpenAI credits; credits are consumed per OpenAI action: Rename (1), Remap (1), Rename + Remap (2). God role bypasses credits.
- Email/password logins must be email-verified; OAuth providers are treated as verified.
- Schema metadata (headers/types) is stored in Firestore; CSV/Excel/JSON rows and field values never reach the server.
- Postgres/SQL integrations are not part of the runtime path (moved to `legacy/`).
- OpenAI rate limiting uses Firestore (`SANDBOX_RATE_LIMIT_BACKEND=firestore`) with the `rate_limits` collection by default.
- Detection rate limiting uses `SANDBOX_DETECT_RATE_LIMIT_WINDOW_SECONDS` and `SANDBOX_DETECT_RATE_LIMIT_PER_USER`.
- Public `/api/contact` and `/api/recaptcha/assess` rate limits fail closed when the Firestore limiter is unavailable.
- Enable Firestore TTL on `rate_limits.expires_at` to auto-expire rate limit counters.
- OpenAI and detection request logs use `SANDBOX_OPENAI_LOG_TTL_SECONDS` with Firestore TTL on `openai_requests.expires_at`,
  `openai_rename_requests.expires_at`, and `detection_requests.expires_at`.
- One-time cleanup tasks (schema TTL backfill, template mapping purge) live in `scripts/cleanup_firestore_artifacts.py`.
- OpenAPI/Docs routes are disabled in prod unless `SANDBOX_ENABLE_DOCS=true`.

### Local test files

- Small, tracked fixtures live in `quickTestFiles/` for quick manual testing.
- Large datasets remain in `samples/` and are ignored by git.

### More docs

- `backend/fieldDetecting/README.md`
- `backend/fieldDetecting/docs/README.md`
- `backend/fieldDetecting/docs/commonforms.md`
- `backend/fieldDetecting/docs/rename-flow.md`
- `backend/fieldDetecting/docs/security.md`

### Running locally

Prefer the repo scripts so the backend uses `backend/.venv` (CommonForms (by [jbarrow](https://github.com/jbarrow/commonforms)) requires
NumPy 1.x and will fail under NumPy 2.x if you run with a system Python). For local dev, prefer Python 3.11+
to match Docker and avoid future dependency support warnings (Google libs warn on Python 3.10):

```bash
python3.11 -m venv backend/.venv
backend/.venv/bin/python -m pip install -r backend/requirements.txt
```

Then run:

```
./scripts/run-backend-dev.sh env/backend.dev.env
```

For the fast local path (frontend + backend together), run:

```
npm run dev
```

If you keep `DETECTOR_MODE=local`, install `backend/requirements-detector.txt` so
CommonForms (by [jbarrow](https://github.com/jbarrow/commonforms)) is available. For the production-style flow, use the dev stack:

```
npm run dev:stack
```

The dev stack expects `env/backend.dev.stack.env` (created from
`config/backend.dev.stack.env.example`) and uses Cloud Tasks + the Cloud Run
detector in `dullypdf-dev`. The stack forces prod-mode backend behavior
(`ENV=prod`, revocation checks on, legacy endpoints disabled) while still using
dev resources. It only reads the stack env file, so export `OPENAI_API_KEY`
separately if you want rename/mapping enabled. In task mode, it also resolves
OpenAI rename/remap worker URLs (`dullypdf-openai-rename-*`, `dullypdf-openai-remap-*`).
When `DEV_STACK_BUILD=1` is set, `npm run dev:stack` now rebuilds the local
backend image and redeploys detector + OpenAI worker Cloud Run services using
`scripts/deploy-detector-services.sh` and `scripts/deploy-openai-workers.sh`
before starting the local stack.
To clean up lingering processes,
run:

```
npm run dev:stack:stop
```

Detector service entrypoint (for Cloud Run or local dev):

```
uvicorn backend.detection.detector_app:app --host 0.0.0.0 --port 8000
```

Rename worker service entrypoint:

```
uvicorn backend.ai.rename_worker_app:app --host 0.0.0.0 --port 8000
```

Remap worker service entrypoint:

```
uvicorn backend.ai.remap_worker_app:app --host 0.0.0.0 --port 8000
```

Docker images:
- `Dockerfile` (main API)
- `Dockerfile.detector` (detector service)
- `Dockerfile.ai-rename` (rename worker service)
- `Dockerfile.ai-remap` (remap worker service)
- `backend/requirements.txt` is main API deps; `backend/requirements-detector.txt` adds CommonForms (by [jbarrow](https://github.com/jbarrow/commonforms)).

Worker deploy script (Cloud Run):

```
npm run deploy:openai-workers
```

`scripts/deploy-openai-workers.sh` deploys rename/remap light+heavy services with `--no-allow-unauthenticated`, enforces caller service-account invoker IAM, and refreshes per-service worker audience/service URL env vars from each deployed Cloud Run URL.

Detector deploy script (Cloud Run):

```
npm run deploy:detector-services
```

`scripts/deploy-detector-services.sh` deploys detector light+heavy services with `--no-allow-unauthenticated`, enforces caller service-account invoker IAM, and refreshes detector audience/service URL env vars from each deployed Cloud Run URL.

Full prod deploy (backend + detector + OpenAI workers + frontend):

```
npm run deploy:all-services
```

`scripts/deploy-all-services.sh` orchestrates all service deploy steps in prod order and requires `ENV=prod` in the backend env file before proceeding.
