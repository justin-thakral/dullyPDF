# Security hardening guide (dev -> production)

This project is still in development, so the default setup favors speed over strict security. Before moving to production, make the changes below.

## 0) Full auth + credential guide (dev vs prod)

This section documents how Firebase Admin credentials, client auth tokens, and schema
metadata flow through the system. I reviewed every file that references credentials,
admin tokens, or auth headers (search terms: `FIREBASE_`, `GOOGLE_APPLICATION_CREDENTIALS`,
`ADMIN_TOKEN`, `VITE_ADMIN_TOKEN`, `firebase`, `x-admin-token`, `Authorization`, `secret`).

### Credential types and where they live

1) **Firebase Web config (frontend, public)**
   - Stored in Vite env files (`env/frontend.dev.env`, `config/frontend.*.env.example`).
   - Used by `frontend/src/config/firebaseConfig.ts` and `frontend/src/services/firebaseClient.ts`.
   - These values are not secrets, but should still be restricted via Firebase console
     (authorized domains, API key restrictions).

2) **Firebase Admin credentials (backend, secret)**
   - Stored in Secret Manager:
     - dev: `dullypdf-dev-firebase-admin`
     - prod: `dullypdf-prod-firebase-admin`
   - Loaded by scripts via `scripts/_load_firebase_secret.sh` into `FIREBASE_CREDENTIALS`
     (JSON string) before the backend starts.
   - Consumed by `backend/firebaseDB/firebase_service.py`.

3) **Admin override token (backend only)**
   - `ADMIN_TOKEN` in `env/backend.dev.env` / `env/backend.prod.env`.
   - Optional dev override for admin-only endpoints.
   - Ignored when `ENV=prod`.
   - Set `SANDBOX_ALLOW_ADMIN_OVERRIDE=false` to disable in dev (prod-like runs).
   - Frontend can attach it only in dev via `VITE_ADMIN_TOKEN` (never in prod).

4) **Firebase ID tokens (client auth)**
   - Created by Firebase Auth in the browser (`frontend/src/services/auth.ts`).
   - Cached in memory only (`frontend/src/services/authTokenStore.ts`).
   - Attached to API requests in `frontend/src/services/apiConfig.ts`.
   - Verified on backend in `backend/firebaseDB/firebase_service.py` via `verify_id_token`.

5) **Schema metadata (server stored, TTL)**
   - Derived from client-side CSV/Excel/JSON parsing (headers/types only).
   - Stored in Firestore via `backend/firebaseDB/schema_database.py` with TTL expiry
     (`SANDBOX_SCHEMA_TTL_SECONDS`, `schema_metadata.expires_at`).
   - CSV/Excel/JSON rows and field values are never uploaded to the server.

### Dev flow (local)

1) `scripts/run-backend-dev.sh` loads `env/backend.dev.env`.
2) If `FIREBASE_CREDENTIALS_SECRET` is set, the script fetches the secret from
   Secret Manager and exports `FIREBASE_CREDENTIALS` (JSON).
3) `backend/firebaseDB/firebase_service.py` initializes Firebase Admin using
   `FIREBASE_CREDENTIALS` or `GOOGLE_APPLICATION_CREDENTIALS`.
4) Frontend uses the dev Firebase web config from `env/frontend.dev.env`.
5) Client ID tokens are attached as `Authorization: Bearer <token>` to backend calls.
6) Dev-only `VITE_ADMIN_TOKEN` can be injected into `x-admin-token` headers
   by `frontend/src/services/apiConfig.ts`.
7) Detector service can set `DETECTOR_ALLOW_UNAUTHENTICATED=true` for local testing
   (ignored in prod).

### Prod flow (runtime)

1) Backend should start with a runtime service account and `FIREBASE_USE_ADC=true`
   on Cloud Run (recommended). Use `FIREBASE_CREDENTIALS` only for non-GCP runs.
2) `scripts/run-backend-prod.sh` can be used for local prod testing; in real prod,
   prefer ADC (no JSON keys on disk).
3) Frontend uses `config/frontend.prod.env.example` values (Firebase web config).
4) `VITE_ADMIN_TOKEN` must not be set in prod builds.

### Detector service auth (prod)

1) Main API enqueues detection jobs via Cloud Tasks with an OIDC token.
2) Cloud Tasks uses `DETECTOR_TASKS_SERVICE_ACCOUNT` to mint the token.
3) Detector service validates the token audience (`DETECTOR_TASKS_AUDIENCE` or detector URL).
4) Restrict callers with `DETECTOR_CALLER_SERVICE_ACCOUNT` (required in prod).
5) Run the detector service with private ingress and allow only the main API
   service account to invoke it (no public access).

### File-by-file map (credential + auth related)

Backend scripts + env:
- `scripts/_load_firebase_secret.sh` loads Secret Manager into `FIREBASE_CREDENTIALS`.
- `scripts/run-backend-dev.sh`, `scripts/run-backend-prod.sh` load env + secrets.
- `scripts/set-role-dev.sh`, `scripts/set-role-prod.sh` load env + secrets for CLI role updates.
- `env/backend.dev.env`, `env/backend.prod.env` define runtime env vars (ignored by git).
- `config/backend.dev.env.example`, `config/backend.prod.env.example` document env vars.
- `mcp/.env.local` can be sourced by `scripts/run-backend-dev.sh` for local-only secrets (for example `OPENAI_API_KEY`).

Firebase Admin + auth:
- `backend/firebaseDB/firebase_service.py` loads credentials and verifies ID tokens.
- `backend/firebaseDB/role_cli.py` sets custom claims and writes roles to Firestore.
- `backend/firebaseDB/app_database.py` stores user role + OpenAI credit balances in Firestore.
- `backend/main.py` enforces auth checks for schema mapping endpoints.

Schema mapping data:
- `backend/firebaseDB/schema_database.py` stores schema metadata (headers/types only).
- `backend/ai/schema_mapping.py` builds allowlist payloads for schema mapping requests.
- `backend/firebaseDB/schema_database.py` stores OpenAI rename/mapping request metadata only.
- `backend/firebaseDB/detection_database.py` stores detection request metadata only.

Frontend auth:
- `frontend/src/config/firebaseConfig.ts` loads public Firebase config.
- `frontend/src/services/firebaseClient.ts` initializes Firebase.
- `frontend/src/services/auth.ts` signs in and refreshes ID tokens.
- `frontend/src/services/authTokenStore.ts` stores tokens in-memory only.
- `frontend/src/services/apiConfig.ts` attaches ID token + optional admin token.

Repo hygiene:
- `.gitignore` ignores `serviceAccounts/` and service account JSON patterns.
- `serviceAccounts/` is empty and ignored (keys removed).

### What looks secure already

- Firebase Admin credentials are stored in Secret Manager and not in git.
- `serviceAccounts/` and common key patterns are gitignored.
- Admin override tokens are only injected in dev (`env.DEV` gates admin headers) and ignored when `ENV=prod`.
- Revocation checks are enabled in prod by default (`FIREBASE_CHECK_REVOKED` or `ENV=prod`).
- Password-based logins are blocked until the email is verified; OAuth providers are treated as verified.
- Schema metadata is stored without CSV/Excel/JSON rows or field values.
- Storage paths are allowlisted and validated in `backend/firebaseDB/storage_service.py`.

### Things to review or tighten further

- **Logging**: ensure schema metadata and request metadata are the only stored OpenAI metadata.
- **Retention**: OpenAI + detection logs expire via `SANDBOX_OPENAI_LOG_TTL_SECONDS` and Firestore TTL on
  `openai_requests.expires_at`, `openai_rename_requests.expires_at`, `detection_requests.expires_at`.
- **Credits**: base users start with 10 lifetime OpenAI credits; credits are consumed per page. Credits are refunded when an OpenAI request fails before producing a response.
- **Secret access**: restrict `roles/secretmanager.secretAccessor` to only the backend runtime SA.
- **Keyless prod**: prefer ADC/Workload Identity in production to avoid JSON keys entirely
  (`FIREBASE_USE_ADC=true` on Cloud Run).

## 1) God-mode endpoints: do not expose admin tokens to the client

Current behavior:
- The backend can accept an `ADMIN_TOKEN` (or `SANDBOX_DEBUG_PASSWORD` with `--debug`) as a god-mode override in dev.
- The frontend can optionally send an `x-admin-token` header in development.

Production hardening:
1) **Do not set `VITE_ADMIN_TOKEN` in production builds.** Vite inlines `VITE_*` values into the client bundle, which makes them public.
2) **Set `ADMIN_TOKEN` only on the backend server** (via environment or secret manager).
3) **Use Firebase custom claims for server-side role checks.**
   - Keep any admin override on the server only.
4) **Disable the override in prod-like environments** by setting `SANDBOX_ALLOW_ADMIN_OVERRIDE=false`.

## 1a) Role CLI (god-mode scripting)

Use `backend/firebaseDB/role_cli.py` whenever you need to flip a user into `role=god` (or back to `base`), reset rename quotas, or sync Firestore metadata with Firebase custom claims. The script is typically invoked through the helper wrappers so that it inherits a production-like environment and credential loading:

- `scripts/set-role-dev.sh [env-file]`
- `scripts/set-role-prod.sh [env-file]`

Each wrapper loads the matching `env/backend.*.env`, exports the values (`set -a`), and then sources `scripts/_load_firebase_secret.sh` to hydrate `FIREBASE_CREDENTIALS` from Secret Manager via `FIREBASE_CREDENTIALS_SECRET`/`FIREBASE_CREDENTIALS_PROJECT` if present. Afterward it runs the CLI inside `backend/.venv/bin/python` for consistent dependencies.

If you prefer to call the module directly, ensure your shell exports the same key environment variables:

- `FIREBASE_CREDENTIALS` (either a JSON blob or a path to a service account file) *or* `GOOGLE_APPLICATION_CREDENTIALS` when relying on ADC.
- `FIREBASE_PROJECT_ID` (or set `GCP_PROJECT_ID`/embed it in the credentials payload).
- `ENV` (typically `dev` or `prod`) so Firebase revocation checks default appropriately.
- Any overrides you need for the target environment (e.g., `SANDBOX_ALLOW_ADMIN_OVERRIDE` or `FIREBASE_CREDENTIALS_SECRET`).

The script resolves credentials via `backend/firebaseDB/firebase_service.py`, requiring valid service account data with a `private_key`. Typical invocation looks like:

```
FIREBASE_PROJECT_ID=dullypdf python -m backend.firebaseDB.role_cli --email admin@example.com --role god
```

If you rely on Secret Manager, configure `FIREBASE_CREDENTIALS_SECRET` (and `FIREBASE_CREDENTIALS_PROJECT` if the secret is housed in a different GCP project) before running the helper scripts so that `_load_firebase_secret.sh` can run `gcloud secrets versions access latest ...` and export the JSON into `FIREBASE_CREDENTIALS` at runtime.

Keep the CLI invocations gated inside secure admin environments because they write custom claims and Firestore documents that give users unlimited renames, DB access, search, and schema mapping capabilities.

### Copy-paste instructions

Use this snippet wherever you need a simple checklist or bash command to grant someone god mode:

````markdown
1. Load the matching env + secrets:
   - `scripts/set-role-dev.sh --email aparcelluzzi30@gmail.com --role god`
   - `scripts/set-role-prod.sh --email aparcelluzzi30@gmail.com --role god`
   - Add `--reset-rename-count` to zero the rename quota.

2. Explicit credentials command (if not using the helper scripts):

   ```bash
   FIREBASE_PROJECT_ID=dullypdf python -m backend.firebaseDB.role_cli \
     --email aparcelluzzi30@gmail.com --role god
   ```

3. Ensure the environment exports:
   - `FIREBASE_CREDENTIALS` (JSON blob or service-account path) *or* `GOOGLE_APPLICATION_CREDENTIALS`
   - `FIREBASE_PROJECT_ID` (or `GCP_PROJECT_ID` / embedded project ID)
   - `ENV` (`dev` or `prod`) for revocation defaults
   - Any required overrides such as `FIREBASE_CREDENTIALS_SECRET` + `_load_firebase_secret.sh`

4. This CLI writes `role=god` custom claims plus Firestore metadata (unlimited renames, DB/search/mapping access). Keep execution limited to secure admin hosts.
````

## 2) Firebase token revocation enforcement

Current behavior:
- Tokens are verified with optional revocation checks.
- Revocation checks are enabled when `FIREBASE_CHECK_REVOKED=true` or `ENV=prod`.

Production hardening:
1) Keep `FIREBASE_CHECK_REVOKED=true` in production.
2) Handle revocation errors explicitly:
   - Expect `RevokedIdTokenError` and return `401` with a user-friendly message.
3) Plan for a small latency increase:
   - Revocation checks require additional calls to Firebase.

## 3) Debug flags

Debug-only behavior should never be enabled in production.

Checklist:
- Use `--debug` only for local development.
- Debug flags are ignored when `ENV=prod`.
- Keep `SANDBOX_CORS_ORIGINS=*` disabled in production.
- Keep `SANDBOX_LOG_OPENAI_RESPONSE` disabled in production.
- `SANDBOX_ENABLE_LEGACY_ENDPOINTS` controls legacy `/api/process-pdf` and `/api/register-fillable` in dev; it is ignored in prod (always disabled).
- `SANDBOX_ENABLE_DOCS` is ignored in prod (OpenAPI/Docs remain disabled).

## 4) Upload limits + storage paths

Current behavior:
- PDF uploads are capped by `SANDBOX_MAX_UPLOAD_MB` (default 50MB).
- GCS paths are validated to be relative and within allowlisted buckets.
- Uploaded PDFs are stored with `Cache-Control: private, no-store`.

Production hardening:
1) Tune upload caps to match infrastructure limits.
2) Keep bucket allowlists strict (`FORMS_BUCKET`, `TEMPLATES_BUCKET`).
3) Reject any user input that attempts path traversal (`../`) or absolute paths.

## 4b) Session cache retention

Current behavior:
- Detection sessions are cached in memory (L1) with PDF bytes for follow-on rename/mapping.
- Session metadata and artifacts are persisted in Firestore + GCS (L2) for multi-instance access.
- L1 entries expire after `SANDBOX_SESSION_TTL_SECONDS` (default 7200) with sweeps every
  `SANDBOX_SESSION_SWEEP_INTERVAL_SECONDS`, and LRU eviction at `SANDBOX_SESSION_MAX_ENTRIES`.
- L2 entries should expire via Firestore TTL and a scheduled cleanup job that deletes
  session artifacts in GCS aligned to the same TTL.
- Sessions without an owning `user_id` are denied access by user-authenticated endpoints.

Production hardening:
1) Keep the TTL short enough to minimize retention of sensitive PDFs.
2) Keep `SANDBOX_SESSION_MAX_ENTRIES` low enough to bound memory use.
3) Ensure `SANDBOX_SESSION_L2_TOUCH_SECONDS` throttles L2 updates to limit Firestore writes.

## 4c) Detection rate limiting

Current behavior:
- `/detect-fields` enforces per-user limits via the shared rate limiter.

Production hardening:
1) Tune `SANDBOX_DETECT_RATE_LIMIT_WINDOW_SECONDS` and `SANDBOX_DETECT_RATE_LIMIT_PER_USER`.

## 5) Environment + secrets hygiene

Checklist:
- Store credentials in a secret manager (not `.env` files) for production.
- Use `FIREBASE_CREDENTIALS_SECRET` + `FIREBASE_CREDENTIALS_PROJECT` with the backend scripts
  to load Firebase Admin credentials without keeping JSON files in env folders.
- Never commit `.env` files to git.
- Rotate admin tokens when moving to production.

## 6) OpenAI response logging

Current behavior:
- Schema mapping and rename calls store only metadata (request id, user id, schema id/template id/session id, timestamp).
- OpenAI rename overlays are written to a temporary directory and deleted after the request completes.

Production hardening:
1) Ensure `SANDBOX_LOG_OPENAI_RESPONSE` is `false`.
2) Avoid logging raw prompts/responses that may contain PII.

## 7) HIPAA guardrails for OpenAI

OpenAI rename receives PDF pages + overlay tags. Schema mapping receives schema header names/types
and template tags. Combined rename+map sends PDF pages plus schema headers in a single request.
No row data or field values are sent. The UI warns users before sending PDF pages or schema headers
to OpenAI.

Enforced safeguards:
1) Client CSV/Excel/JSON parsing happens locally; only headers/types are sent to the server.
2) Server-side allowlist builders strip any non-schema/template data before OpenAI calls.
3) The UI warns users about PDF pages, field tags, and schema headers before OpenAI calls.

Schema mapping limits and quotas:
- `OPENAI_SCHEMA_MAPPING_MODEL`
- `OPENAI_SCHEMA_MAX_FIELDS`, `OPENAI_TEMPLATE_MAX_FIELDS`
- `OPENAI_SCHEMA_MAX_PAYLOAD_BYTES`, `OPENAI_SCHEMA_MAX_FIELD_NAME_LEN`
- `OPENAI_SCHEMA_RATE_LIMIT_WINDOW_SECONDS`, `OPENAI_SCHEMA_RATE_LIMIT_PER_USER`
- `SANDBOX_RATE_LIMIT_BACKEND` (default `firestore`)
- `SANDBOX_RATE_LIMIT_COLLECTION` (default `rate_limits`)
- `BASE_OPENAI_CREDITS` (default 10)

Schema mapping behavior:
- When the payload exceeds `OPENAI_SCHEMA_MAX_PAYLOAD_BYTES`, the backend splits template tags into smaller chunks and merges the results.
- If a single chunk still exceeds the limit, the request is rejected and the schema/template must be reduced.

OpenAI rename limits and quotas:
- `OPENAI_RENAME_RATE_LIMIT_WINDOW_SECONDS`, `OPENAI_RENAME_RATE_LIMIT_PER_USER`
- `SANDBOX_RATE_LIMIT_BACKEND` (default `firestore`)
- `BASE_OPENAI_CREDITS` (default 10)

Operational note:
- Enable Firestore TTL on `${SANDBOX_RATE_LIMIT_COLLECTION}.expires_at` to auto-expire counters.

## 8) Minimum production config

Set these on the backend server:
- `ADMIN_TOKEN=<secure random value>`
- `SANDBOX_CORS_ORIGINS=https://your-domain.com`

And keep these unset/false:
- `SANDBOX_LOG_OPENAI_RESPONSE`
- `SANDBOX_CORS_ORIGINS=*`
