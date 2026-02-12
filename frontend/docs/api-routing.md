# API Routing

This frontend uses two API call styles:

- Same-origin paths like `/api/profile` (relative URL).
- Direct backend URLs built with `buildApiUrl(...)` (base URL from env).

The split is implemented in `frontend/src/services/api.ts`, `frontend/src/services/detectionApi.ts`, and `frontend/src/services/apiConfig.ts`.

## API base resolution

`frontend/src/services/apiConfig.ts` resolves the base URL in this order:

1. `VITE_API_URL`
2. `VITE_SANDBOX_API_URL`
3. `VITE_DETECTION_API_URL`
4. fallback `http://localhost:8000`

`frontend/src/services/detectionApi.ts` resolves detection base in this order:

1. `VITE_DETECTION_API_URL`
2. `VITE_SANDBOX_API_URL`
3. fallback `http://localhost:8000`

## Same-origin endpoints used by the frontend

These calls are made with relative `/api/...` paths:

- `GET /api/profile`
- `POST /api/contact`
- `POST /api/recaptcha/assess`
- `POST /api/schemas`
- `GET /api/saved-forms`
- `GET /api/saved-forms/{formId}`
- `DELETE /api/saved-forms/{formId}`
- `POST /api/saved-forms/{formId}/session`
- `POST /api/sessions/{sessionId}/touch`

`frontend/src/main.tsx` also sends a best-effort warmup request to:

- `GET /api/health`

## Direct backend endpoints used by the frontend

These calls are made with absolute URLs (via `buildApiUrl(...)` or detection base):

- `POST /api/renames/ai`
- `POST /api/schema-mappings/ai`
- `POST /api/templates/session`
- `POST /api/forms/materialize`
- `POST /api/saved-forms`
- `GET /api/saved-forms/{formId}/download`
- `POST /detect-fields`
- `GET /detect-fields/{sessionId}`
- `POST /api/sessions/{sessionId}/touch` (detection polling keep-alive path on detection base)

## Production behavior

`firebase.json` includes Hosting rewrites for selected `/api/...` routes (for example `/api/profile`, `/api/contact`, `/api/recaptcha/assess`, `/api/saved-forms` patterns, and `/api/health`). Routes not covered by rewrites are called directly by the frontend via backend base URL.

## Local development behavior

- Vite proxies `/api/*` to `VITE_API_URL` (`frontend/vite.config.ts`).
- Detection requests still use detection base resolution from `detectionApi.ts`.

## Rule of thumb for new frontend calls

- Use relative `/api/...` for endpoints that should stay same-origin.
- Use `buildApiUrl(...)` (or detection base helpers) when a direct backend call is intended.
