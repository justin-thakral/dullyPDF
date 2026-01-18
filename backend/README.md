## Backend

FastAPI service for PDF field detection, schema-only OpenAI mapping, and saved-form storage. The entrypoint is `backend/main.py` and the main pipeline uses CommonForms under `backend/fieldDetecting/commonforms/`. The legacy OpenCV pipeline lives in `legacy/fieldDetecting/` and is not part of the main pipeline.

### Core flows

- Detection: `POST /detect-fields` (CommonForms field detection only).
- CommonForms-only: `POST /api/process-pdf` (legacy upload helper; dev-only; auth required; no rename/mapping).
- Register fillable: `POST /api/register-fillable` (dev-only; auth required; store PDF bytes without running detection).
- OpenAI rename (overlay tags + PDF pages; schema headers included for combined rename+map): `POST /api/renames/ai`.
- Schema metadata: `POST /api/schemas`, `GET /api/schemas`.
- Schema mapping (OpenAI): `POST /api/schema-mappings/ai`.
- Schema mapping storage: `POST /api/schema-mappings`.
- Saved forms: `GET /api/saved-forms`, `POST /api/saved-forms`, `GET /api/saved-forms/{id}`, `GET /api/saved-forms/{id}/download`, `DELETE /api/saved-forms/{id}`.

### Runtime requirements

- CommonForms + PyTorch for detection.
- OpenAI API key for rename + schema mapping (schema metadata only).
- Firebase Admin for auth and role claims.
- GCS buckets for saved forms and templates.

### Minimum env (dev)

- `FIREBASE_PROJECT_ID`
- `FIREBASE_CREDENTIALS` (JSON string), `GOOGLE_APPLICATION_CREDENTIALS` (path), or
  `FIREBASE_CREDENTIALS_SECRET` (Secret Manager name loaded by `scripts/*backend*.sh`)
- `FIREBASE_CREDENTIALS_PROJECT` (Secret Manager project, if different from `FIREBASE_PROJECT_ID`)
- `FORMS_BUCKET`, `TEMPLATES_BUCKET`
- `OPENAI_API_KEY` (only if schema mapping enabled)
- `SANDBOX_CORS_ORIGINS` (comma-separated list)
- `SANDBOX_ENABLE_LEGACY_ENDPOINTS` (dev-only; defaults to true; ignored in prod)
- `ADMIN_TOKEN` (dev-only override; do not ship to prod)

### Notes

- The backend keeps a short-lived in-memory session cache in `_API_SESSION_CACHE` for detection results (LRU capped by `SANDBOX_SESSION_MAX_ENTRIES`).
- Session cache entries expire after `SANDBOX_SESSION_TTL_SECONDS` (default 3600) and are swept every `SANDBOX_SESSION_SWEEP_INTERVAL_SECONDS`.
- Base users start with 10 lifetime OpenAI credits; each page consumed per rename/mapping run (combined counts once per page). God role bypasses credits.
- Schema metadata (headers/types) is stored in Firestore; CSV/Excel rows and field values never reach the server.
- Postgres/SQL integrations are not part of the runtime path (moved to `legacy/`).
- OpenAI rate limiting uses Firestore (`SANDBOX_RATE_LIMIT_BACKEND=firestore`) with the `rate_limits` collection by default.
- Detection rate limiting uses `SANDBOX_DETECT_RATE_LIMIT_WINDOW_SECONDS` and `SANDBOX_DETECT_RATE_LIMIT_PER_USER`.

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

Prefer the repo scripts so the backend uses `backend/.venv` (CommonForms requires
NumPy 1.x and will fail under NumPy 2.x if you run with a system Python):

```
./scripts/run-backend-dev.sh env/backend.dev.env
```
