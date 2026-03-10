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
- `PATCH /api/profile/downgrade-retention`
- `POST /api/profile/downgrade-retention/delete-now`
- `POST /api/contact`
- `POST /api/recaptcha/assess`
- `POST /api/billing/checkout-session`
- `POST /api/billing/subscription/cancel`
- `POST /api/billing/reconcile`
- `POST /api/schemas`
- `GET /api/saved-forms`
- `GET /api/saved-forms/{formId}`
- `DELETE /api/saved-forms/{formId}`
- `POST /api/saved-forms/{formId}/session`
- `PATCH /api/saved-forms/{formId}/editor-snapshot`
- `GET /api/groups`
- `POST /api/groups`
- `GET /api/groups/{groupId}`
- `PATCH /api/groups/{groupId}`
- `DELETE /api/groups/{groupId}`
- `GET /api/fill-links`
- `POST /api/fill-links`
- `PATCH /api/fill-links/{linkId}`
- `POST /api/fill-links/{linkId}/close`
- `GET /api/fill-links/{linkId}/responses`
- `GET /api/fill-links/{linkId}/responses/{responseId}`
- `GET /api/fill-links/public/{token}`
- `POST /api/fill-links/public/{token}/submit`
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

`firebase.json` must rewrite the backend-owned same-origin path families to Cloud Run before the final SPA rewrite. In practice that means `/api/profile` plus `/api/profile/**`, `/api/saved-forms` plus `/api/saved-forms/**`, `/api/groups` plus `/api/groups/**`, `/api/fill-links` plus `/api/fill-links/**`, along with the exact health/contact/recaptcha/billing/schema routes. If a same-origin API path is missing from Hosting rewrites, Firebase serves `index.html` and the frontend will fail when it tries to parse HTML as JSON.

## Local development behavior

- Vite proxies `/api/*` to `VITE_API_URL` (`frontend/vite.config.ts`).
- Detection requests still use detection base resolution from `detectionApi.ts`.

## Rule of thumb for new frontend calls

- Use relative `/api/...` for endpoints that should stay same-origin.
- Use `buildApiUrl(...)` (or detection base helpers) when a direct backend call is intended.
