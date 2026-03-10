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
- Schema mapping (OpenAI): `POST /api/schema-mappings/ai` (returns mappings plus fill-time rule payloads; updates session mapping state).
- Schema mapping job status (task mode): `GET /api/schema-mappings/ai/{jobId}`.
- Saved forms: `GET /api/saved-forms`, `POST /api/saved-forms` (supports `overwriteFormId` to replace an existing saved form), `GET /api/saved-forms/{id}`, `GET /api/saved-forms/{id}/download`, `POST /api/saved-forms/{id}/session`, `PATCH /api/saved-forms/{id}/editor-snapshot`, `DELETE /api/saved-forms/{id}`.
- Template groups: `GET /api/groups`, `POST /api/groups`, `GET /api/groups/{id}`, `DELETE /api/groups/{id}` (named containers for existing saved forms; deleting a saved form automatically removes it from every group).
- Fill By Link: `GET /api/fill-links`, `POST /api/fill-links`, `PATCH /api/fill-links/{id}`, `POST /api/fill-links/{id}/close`, and public `/api/fill-links/public/*` routes (supports one link per saved template or one merged link per open group). Template links can optionally freeze a publish snapshot so accepted respondents can download a PDF copy of their own submission later via a public response download route.
- Template session (fillable upload): `POST /api/templates/session` (stores PDF bytes + fields so rename/mapping can run).
- Materialize fillable: `POST /api/forms/materialize` (auth required; injects fields into a PDF upload and enforces fillable page limits).
- Profile summary: `GET /api/profile` (tier info, credits, limits, billing metadata, and downgrade-retention state when applicable).
- Downgrade retention controls: `PATCH /api/profile/downgrade-retention` (swap the kept saved forms during grace) and `POST /api/profile/downgrade-retention/delete-now` (purge queued saved forms + dependent Fill By Link records immediately).
- Billing webhook health: `GET /api/billing/webhook-health` (auth required; reports whether Stripe webhook delivery prerequisites are healthy. Full endpoint diagnostics are restricted to `ROLE_GOD`; other users receive a redacted status summary).
- Billing reconciliation: `POST /api/billing/reconcile` (auth required; regular users reconcile a specific checkout session they started, while `ROLE_GOD` can audit recent `checkout.session.completed` events across users).
- Contact form: `POST /api/contact` (public; reCAPTCHA required; sends email via Gmail API).
- reCAPTCHA verify: `POST /api/recaptcha/assess` (public; used for account creation checks).

### Production API routing (Firebase Hosting rewrites)

In production, the SPA is served from Firebase Hosting and a subset of backend endpoints are proxied
through Hosting rewrites so the browser can call them as same-origin `/api/...` requests. This is
primarily to remove CORS preflights (OPTIONS) from fast JSON endpoints (notably reCAPTCHA verification
and profile fetches) so Cloud Run scale-to-zero cold starts feel less blocking.

Given the current signed-in startup flow, production should keep `BACKEND_MIN_INSTANCES=1` in
`env/backend.prod.env` so the backend stays warm for same-origin `/api/profile`, `/api/groups`, and
`/api/saved-forms` bootstrap requests. A future warm-shell split could relax that requirement.

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
- `BACKEND_RUNTIME_SERVICE_ACCOUNT` for production deploys so Cloud Run attaches the
  intended runtime identity before ADC-backed Firebase Admin starts.
- `FIREBASE_CREDENTIALS` (JSON string) or `GOOGLE_APPLICATION_CREDENTIALS` (path) for local/dev,
  or `FIREBASE_USE_ADC=true` on GCP. Production Cloud Run deploys now require ADC-only and reject
  Firebase JSON credential env/path overrides.
- `FIREBASE_CREDENTIALS_SECRET` (local/dev helper Secret Manager name loaded by `scripts/*backend*.sh`)
- `FIREBASE_CREDENTIALS_PROJECT` (local/dev helper Secret Manager project, if different from `FIREBASE_PROJECT_ID`)
- `FORMS_BUCKET`, `TEMPLATES_BUCKET`
- `OPENAI_API_KEY` (only if schema mapping enabled)
- `CONTACT_TO_EMAIL`, `CONTACT_FROM_EMAIL`
- `GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET`, `GMAIL_REFRESH_TOKEN`
- `GMAIL_USER_ID` (optional; defaults to `me`)
- `RECAPTCHA_SITE_KEY`
- `RECAPTCHA_PROJECT_ID` (or `FIREBASE_PROJECT_ID` / `GCP_PROJECT_ID`)
- `RECAPTCHA_CONTACT_ACTION` (default `contact`; overrides legacy `RECAPTCHA_EXPECTED_ACTION`)
- `RECAPTCHA_SIGNUP_ACTION` (default `signup`; overrides legacy `RECAPTCHA_EXPECTED_ACTION`)
- `RECAPTCHA_ALLOWED_HOSTNAMES` (comma-separated allowlist; supports `*.example.com`; required in prod when reCAPTCHA is enabled)
- `RECAPTCHA_MIN_SCORE` (default 0.5)
- `CONTACT_REQUIRE_RECAPTCHA` (default true)
- `CONTACT_RATE_LIMIT_WINDOW_SECONDS`, `CONTACT_RATE_LIMIT_PER_IP`
- `CONTACT_RATE_LIMIT_GLOBAL` (optional; global cap for `/api/contact` regardless of caller IP)
- `SIGNUP_REQUIRE_RECAPTCHA` (default true)
- `SIGNUP_RATE_LIMIT_WINDOW_SECONDS`, `SIGNUP_RATE_LIMIT_PER_IP`
- `SIGNUP_RATE_LIMIT_GLOBAL` (optional; global cap for `/api/recaptcha/assess` regardless of caller IP)
- `FILL_LINK_REQUIRE_RECAPTCHA` (default true; must remain true in production)
- `FILL_LINK_TOKEN_SECRET` (required in production; public Fill By Link URLs are signed from the link id instead of storing new plaintext bearer tokens, and the prod example placeholder is rejected at startup/deploy)
- `FILL_LINK_VIEW_RATE_WINDOW_SECONDS`, `FILL_LINK_VIEW_RATE_PER_IP`
- `FILL_LINK_VIEW_RATE_GLOBAL` (optional; global cap for anonymous Fill By Link page loads)
- `FILL_LINK_SUBMIT_RATE_WINDOW_SECONDS`, `FILL_LINK_SUBMIT_RATE_PER_IP`
- `FILL_LINK_SUBMIT_RATE_GLOBAL` (optional; global cap for anonymous Fill By Link submissions)
- `FILL_LINK_DOWNLOAD_RATE_WINDOW_SECONDS`, `FILL_LINK_DOWNLOAD_RATE_PER_IP`
- `FILL_LINK_DOWNLOAD_RATE_GLOBAL` (optional; global cap for anonymous respondent PDF downloads)
- `FILL_LINK_MAX_ANSWER_VALUE_CHARS`, `FILL_LINK_MAX_TOTAL_ANSWER_CHARS`, `FILL_LINK_MAX_MULTI_SELECT_VALUES`
- `FILL_LINK_ALLOW_LEGACY_PUBLIC_TOKENS` (default false; temporary fallback for previously issued plaintext Fill By Link URLs only)
- `SANDBOX_TRUST_PROXY_HEADERS` (default false; only enable when Cloud Run is reachable *only* via a trusted proxy that strips spoofed headers)
- `SANDBOX_CORS_ORIGINS` (comma-separated list)
- `SANDBOX_ENABLE_LEGACY_ENDPOINTS` (dev-only; defaults to true; ignored in prod)
- `ADMIN_TOKEN` (dev-only override; ignored when `ENV=prod` or `SANDBOX_ALLOW_ADMIN_OVERRIDE=false`)
- `SANDBOX_DETECT_MAX_PAGES_BASE`, `SANDBOX_DETECT_MAX_PAGES_GOD`
- `SANDBOX_FILLABLE_MAX_PAGES_BASE`, `SANDBOX_FILLABLE_MAX_PAGES_GOD`
- `SANDBOX_SAVED_FORMS_MAX_BASE`, `SANDBOX_SAVED_FORMS_MAX_GOD`
- `SANDBOX_SCHEMA_TTL_SECONDS`
- `SANDBOX_OPENAI_LOG_TTL_SECONDS`
- `SANDBOX_ENABLE_DOCS` (optional; defaults to enabled outside prod; set to `false` to disable OpenAPI/docs in dev/test; ignored in prod)
- `DETECTOR_MODE` (`tasks` for production)
- `DETECTOR_TASKS_PROJECT`, `DETECTOR_TASKS_LOCATION`
- `DETECTOR_TASKS_QUEUE` or `DETECTOR_TASKS_QUEUE_LIGHT`
- `DETECTOR_SERVICE_URL` or `DETECTOR_SERVICE_URL_LIGHT`
- `DETECTOR_TASKS_QUEUE_HEAVY`, `DETECTOR_SERVICE_URL_HEAVY` (optional; for 10+ page PDFs)
- `DETECTOR_ROUTING_MODE` (optional; `cpu`, `split`, or `gpu` when backend env files keep both CPU and GPU detector URLs)
- `DETECTOR_SERVICE_URL_LIGHT_GPU`, `DETECTOR_SERVICE_URL_HEAVY_GPU` (optional; used by `split`/`gpu` routing)
- `DETECTOR_TASKS_HEAVY_PAGE_THRESHOLD` (default 10)
- `DETECTOR_TASKS_SERVICE_ACCOUNT`
- `DETECTOR_TASKS_AUDIENCE`, `DETECTOR_TASKS_AUDIENCE_LIGHT`, `DETECTOR_TASKS_AUDIENCE_HEAVY` (optional)
- `DETECTOR_TASKS_AUDIENCE_LIGHT_GPU`, `DETECTOR_TASKS_AUDIENCE_HEAVY_GPU` (optional)
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
- `OPENAI_CREDITS_PAGE_BUCKET_SIZE` (default 5; credits scale per `ceil(page_count / bucket_size)`)
- `OPENAI_CREDITS_RENAME_BASE_COST` (default 1)
- `OPENAI_CREDITS_REMAP_BASE_COST` (default 1)
- `OPENAI_CREDITS_RENAME_REMAP_BASE_COST` (default 2)
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
- Credit refunds now retry automatically (`OPENAI_CREDIT_REFUND_MAX_ATTEMPTS`, `OPENAI_CREDIT_REFUND_RETRY_BACKOFF_MS`) and unresolved failures are recorded in Firestore (`credit_refund_failures`) for reconciliation.
- Detection can emit best-effort OpenAI worker prewarm requests when `OPENAI_PREWARM_ENABLED=true` and remaining pages are below `OPENAI_PREWARM_REMAINING_PAGES`.
- Encrypted PDFs are rejected before detection to avoid repeated task retries.
- `DETECTOR_TASKS_MAX_ATTEMPTS` on the detector service should match the Cloud Tasks queue max attempts to finalize failures on the last retry.
- Session ownership guards can be sanity-checked with `python -m backend.scripts.verify_session_owner`.
- One-off Gmail sends can be run with `python -m backend.scripts.send_gmail_once <recipient> "<subject>" "<body>"`.
  The script uses the existing Gmail prod env vars, appends successful recipients to `tmp/sent-email-recipients.txt`,
  and exits with failure when the recipient already exists in that sent log (override path via `--sent-log-path`).
  Follow-ups are blocked by default and require explicit flags:
  `--mode followup --followup-flag FOLLOWUP_OK` (follow-up log path defaults to `tmp/sent-email-followups.txt`).
- Outbound research + personalization + sending guidance for Codex terminals is documented in
  `backend/scripts/outbound_email_playbook.md`.
- Generated outbound lead artifacts under `backend/scripts/leads/` are local-only and can be
  removed with `python3 clean.py --outbound-leads` (also included in the default `npm run clean`).
- Base users start with 10 lifetime OpenAI credits. Credits are billed per page bucket using server-side page counts:
  `total_credits = operation_base_cost * ceil(page_count / OPENAI_CREDITS_PAGE_BUCKET_SIZE)`.
  Defaults: Rename base cost `1`, Remap base cost `1`, Rename+Remap base cost `2`; with default bucket size `5`, a 10-page Rename+Remap costs `4`. God role bypasses credits.
- `GET /api/profile` now includes `creditPricing` (server bucket/base-cost settings), `billing` metadata (`enabled`, plan catalog, subscription linkage/status, and cancellation schedule fields), and `retention` metadata when a downgraded free account is inside the saved-form grace window.
- Downgrade retention keeps the default oldest saved forms up to the free limit, stores the rest in a 30-day delete queue, and closes dependent Fill By Link records immediately. The queue can be purged manually with `POST /api/profile/downgrade-retention/delete-now` or automatically through `backend/scripts/purge_downgrade_retention.py`.
- Email/password logins must be email-verified; OAuth providers are treated as verified.
- Schema metadata (headers/types) is stored in Firestore; CSV/Excel/JSON rows and field values never reach the server.
- Schema mapping may emit deterministic fill rules (`fillRules`), including `checkboxRules`, `checkboxHints`, and `textTransformRules` (for split/join text fill cases).
- Session and saved-form metadata persist `textTransformRules` alongside checkbox rule metadata so Search & Fill can replay deterministic transforms.
- Template Fill By Link can persist an owner-controlled respondent-download snapshot that freezes the published PDF storage path, normalized field payload, and saved-form fill rules at publish time. Public respondent downloads materialize from that snapshot plus the stored respondent answer record; group links never expose PDF downloads.
- Saved-form metadata can reference a versioned editor snapshot JSON artifact in storage so reopen/group-switch flows can hydrate page sizes and extracted fields without repeating PDF extraction on every open. Snapshot upload is best-effort during save and can be backfilled later through `PATCH /api/saved-forms/{id}/editor-snapshot`.
- Postgres/SQL integrations are not part of the runtime path (moved to `legacy/`).
- OpenAI rate limiting uses Firestore (`SANDBOX_RATE_LIMIT_BACKEND=firestore`) with the `rate_limits` collection by default.
- Detection rate limiting uses `SANDBOX_DETECT_RATE_LIMIT_WINDOW_SECONDS` and `SANDBOX_DETECT_RATE_LIMIT_PER_USER`.
- Detection and OpenAI rename/remap rate limits now fail closed when the Firestore limiter is unavailable.
- Public `/api/contact` and `/api/recaptcha/assess` rate limits fail closed when the Firestore limiter is unavailable.
- Enable Firestore TTL on `rate_limits.expires_at` to auto-expire rate limit counters.
- OpenAI and detection request logs use `SANDBOX_OPENAI_LOG_TTL_SECONDS` with Firestore TTL on `openai_requests.expires_at`,
  `openai_rename_requests.expires_at`, `credit_refund_failures.expires_at`, and `detection_requests.expires_at`.
- One-time cleanup tasks (schema TTL backfill, template mapping purge) live in `scripts/cleanup_firestore_artifacts.py`.
- OpenAPI/Docs routes are always disabled in prod. Outside prod they default to enabled and can be disabled with `SANDBOX_ENABLE_DOCS=false`.

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
Set `DETECTOR_ROUTING_MODE=cpu|split|gpu` in the stack env to switch detector
traffic between CPU-only, CPU-light/GPU-heavy, and GPU-only routing. The CPU
services keep the existing names (`dullypdf-detector-light`, `...-heavy`); GPU
services default to `dullypdf-detector-light-gpu` / `...-heavy-gpu`. The legacy
`DEV_STACK_DETECTOR_GPU=true` flag still maps to `DETECTOR_ROUTING_MODE=gpu`
when the new routing mode is unset. If GPU quota is only available in a
different Cloud Run region than the Cloud Tasks queues, set `DETECTOR_GPU_REGION`
in the stack env. In `dullypdf-dev`, the current working example is
`DETECTOR_GPU_REGION=us-east4`.
When `DEV_STACK_BUILD=1` is set, `npm run dev:stack` now rebuilds the local
backend image and redeploys detector + OpenAI worker Cloud Run services using
`scripts/deploy-detector-services.sh` and `scripts/deploy-openai-workers.sh`
before starting the local stack.
To clean up lingering processes,
run:

```
npm run dev:stack:stop
```

To run a CPU vs GPU detector benchmark (same PDF set, detection duration, Cloud
Run request latency, billable-second cost estimate), use:

```
scripts/benchmark-detector-cpu-gpu.sh env/backend.dev.stack.env
```

The benchmark script deploys CPU and GPU detector services in separate regions
when `BENCH_GPU_REGION` or `DETECTOR_GPU_REGION` is set. That lets the local
backend keep using the existing Cloud Tasks queues while GPU detector services
live in the region that actually has L4 quota.
Benchmark deploys now stay private by default and refuse to target the
`dullypdf` prod project unless `BENCH_ALLOW_PROD_PROJECT=true` is set.
Public detector benchmarks require an explicit `BENCH_ALLOW_UNAUTHENTICATED=true`.

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

### Billing testing (dev)

`npm run dev` now auto-starts Stripe CLI forwarding for local billing when `STRIPE_SECRET_KEY` is present in `env/backend.dev.env`, forwarding to `http://localhost:${PORT}/api/billing/webhook` and injecting the listener session webhook secret into the backend process.

Local Stripe forwarding notes:
- Local forwarding is tunnel-based and does not create a Stripe dashboard webhook endpoint.
- Because of that, local `npm run dev` forces `STRIPE_ENFORCE_WEBHOOK_HEALTH=false` for the backend process so checkout is not blocked by endpoint-health enforcement.
- Set `STRIPE_DEV_LISTEN_ENABLED=false` to run local dev without Stripe forwarding.

Use these commands when validating Stripe billing checkout/webhook behavior:

```bash
pytest backend/test/unit/api/test_main_billing_endpoints_blueprint.py
pytest backend/test/unit/core/test_billing_service_blueprint.py
pytest backend/test/integration/test_billing_webhook_integration.py
```

For a live smoke test against a running backend, including signed webhook security checks,
card outcome event coverage (`4242`, `3155`, `0002`, `9995`), duplicate-event handling, and
subscription lifecycle events:

```bash
./scripts/test-billing-webhooks.sh env/backend.dev.env http://localhost:8000
```

For prod deploys, `scripts/deploy-backend.sh` requires Stripe keys to come from
Secret Manager bindings (`STRIPE_SECRET_KEY_SECRET`, `STRIPE_WEBHOOK_SECRET_SECRET`)
and rejects literal `STRIPE_SECRET_KEY` / `STRIPE_WEBHOOK_SECRET` values. The deploy
script also hard-fails unless `backend/test/integration/test_billing_webhook_integration.py`
passes. The same deploy step also resolves the active detector URLs/audiences from
`DETECTOR_ROUTING_MODE`, so switching detector traffic between CPU, split, and GPU
is an env-file change plus backend redeploy.

Webhook fulfillment and checkout guardrails:
- Refill checkout fulfillment (`checkout.session.completed` for `refill_500`) is applied only when the user is currently Pro at fulfillment time.
- Refill checkout credits are validated against the configured Stripe refill price mapping before credits are granted; mismatched or unresolvable refill metadata now returns a retriable non-2xx webhook response so fulfillment is not silently acknowledged.
- Pro checkout session creation (`pro_monthly` / `pro_yearly`) is blocked when the user already has an active subscription.
- Pro checkout now binds to a stable Stripe customer, reuses an existing open Pro checkout session for that customer when present, blocks checkout when that customer already has an active Pro subscription in Stripe, and uses deterministic per-plan idempotency keys so concurrent duplicate session creates collapse without monthly/yearly key collisions.
- Refill checkout session creation is blocked unless the user is currently eligible for refill fulfillment (active Pro state).
- Refill checkout now also binds to a stable Stripe customer and reuses an existing open refill session for that customer when present, which prevents accidental duplicate session creation during quick retries.
- Checkout session creation can be hard-blocked by Stripe webhook health (`STRIPE_ENFORCE_WEBHOOK_HEALTH=true`) so new purchases are disabled when delivery prerequisites are unhealthy.
- Set `STRIPE_WEBHOOK_ENDPOINT_URL` to the exact webhook URL your backend receives. Webhook health checks match this specific URL and fail closed when enforcement is enabled but the URL is missing/misconfigured.
- `POST /api/billing/reconcile` lets authenticated users recover missed paid checkout fulfillment for a specific checkout session they started; `ROLE_GOD` can still reconcile across users from recent Stripe events.
- Subscription lifecycle role changes (`customer.subscription.updated` / `customer.subscription.deleted`) are applied only for configured Pro price ids; unrelated subscription products are ignored.
- Subscription cancel requests are allowed when the user has a stored Stripe subscription id, even if role state drifted from `pro`, so users can always stop billing.
- Fresh in-progress webhook locks now return a retriable non-2xx response instead of a duplicate `200` so Stripe retries rather than dropping fulfillment.
- `BILLING_EVENT_LOCK_TIMEOUT_SECONDS` defaults to `120` seconds to reduce stale-lock retry delays after worker crashes.
- When lock clearing fails after a webhook error, the handler now attempts a lock-document delete fallback to shorten retry stalls caused by transient Firestore write failures.
- Pro checkout and invoice fulfillment now promote membership and persist Stripe subscription linkage in one Firestore transaction.
- `STRIPE_MAX_PROCESSED_EVENTS` defaults to `256` and should stay bounded in production so Stripe dedupe history cannot bloat long-lived user documents. The separate `billing_events` collection remains the primary idempotency record.
- `STRIPE_CHECKOUT_IDEMPOTENCY_WINDOW_SECONDS` defaults to `300`; this windowed idempotency applies to Pro plan checkout creation. Refill checkouts use attempt-scoped idempotency keys so consecutive refill purchases do not redirect to a previously completed session.
- Checkout redirect URLs always include a `billing` query parameter (`success`/`cancel`) even when custom URLs are configured.
- In `ENV=prod`, startup fails fast if Stripe billing vars are missing or if checkout redirect URLs are not `https://`.

### Billing webhook troubleshooting (prod)

When Stripe webhooks misbehave in production, use this sequence:

1. Find the event in Cloud Logging by Stripe id and route:
   - Filter example:
     ```text
     resource.type="cloud_run_revision"
     resource.labels.service_name="dullypdf-backend"
     jsonPayload.stripeEventId="evt_..."
     ```
   - The billing route logs `stripeEventId`, `eventType`, duplicate detection, completion, and retryable failures.

2. Inspect Firestore lock/event state:
   - Collection: `billing_events`
   - Document id: Stripe `event.id`
   - Key fields: `status` (`processing|processed|failed`), `attempts`, `updated_at`.
   - A stuck `processing` status older than `BILLING_EVENT_LOCK_TIMEOUT_SECONDS` can be reclaimed automatically; use `status=failed` (or clear the doc) only as an incident action.

3. Resend from Stripe after fixing root cause:
   - Stripe CLI:
     ```bash
     stripe events resend evt_... --webhook-endpoint=we_...
     ```
   - Or replay from Stripe Dashboard event timeline.

4. Re-run local smoke checks against the target backend:
   - `./scripts/test-billing-webhooks.sh env/backend.dev.env http://localhost:8000`

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

`scripts/deploy-detector-services.sh` now supports `DETECTOR_ROUTING_MODE=cpu|split|gpu`
plus `DETECTOR_DEPLOY_VARIANTS=active|cpu|gpu|both`. `active` deploys the services
used by the selected routing mode, while `both` predeploys CPU and GPU detector
stacks so later backend flips only require changing `DETECTOR_ROUTING_MODE` and
redeploying the backend.

Full prod deploy (backend + detector + OpenAI workers + frontend):

```
npm run deploy:all-services
```

`scripts/deploy-all-services.sh` orchestrates all service deploy steps in prod order and requires `ENV=prod` in the backend env file before proceeding.
