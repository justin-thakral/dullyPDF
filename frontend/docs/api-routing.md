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
- `POST /api/fill-links/public/{token}/retry-signing`
- `GET /api/signing/options`
- `GET /api/signing/requests`
- `POST /api/signing/requests`
- `GET /api/signing/requests/{requestId}`
- `GET /api/signing/requests/{requestId}/artifacts`
- `GET /api/signing/requests/{requestId}/artifacts/{artifactKey}`
- `POST /api/signing/requests/{requestId}/send`
- `GET /api/signing/public/{token}`
- `POST /api/signing/public/{token}/bootstrap`
- `GET /api/signing/public/{token}/document`
- `GET /api/signing/public/{token}/artifacts/{artifactKey}`
- `POST /api/signing/public/{token}/review`
- `POST /api/signing/public/{token}/consent`
- `POST /api/signing/public/{token}/manual-fallback`
- `POST /api/signing/public/{token}/adopt-signature`
- `POST /api/signing/public/{token}/complete`
- `POST /api/sessions/{sessionId}/touch`

`frontend/src/main.tsx` also sends a best-effort warmup request to:

- `GET /api/health`

Signing-specific payload notes:

- `POST /api/signing/requests` now carries source provenance fields such as `sourceType`, `sourceId`, `sourceLinkId`, and `sourceRecordLabel` so `Fill and Sign` drafts can tie a frozen PDF back to a reviewed workspace fill or a stored Fill By Link response.
- `POST /api/signing/requests/{requestId}/send` uploads the immutable source PDF as `multipart/form-data` and may include `ownerReviewConfirmed=true` for `fill_and_sign` requests. The backend rejects `Fill and Sign` sends unless that explicit owner review confirmation is present.
- `POST /api/fill-links` and `PATCH /api/fill-links/{linkId}` now accept an optional `signingConfig` for template links. When `enabled=true`, the config maps the signer name/email questions, declares the signature mode/category/manual-fallback policy, and tells the backend to exclude signing-managed questions from the published public form.
- `POST /api/fill-links/public/{token}/submit` may return `signing.enabled` and `signing.publicPath`. When present, the respondent success state should hand off into `/sign/:token` instead of ending at the normal Fill By Link completion screen.
- `POST /api/fill-links/public/{token}/retry-signing` lets the respondent recover from a transient signing-handoff failure by retrying against the already stored response record instead of resubmitting the web form.

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

Production frontend builds resolve backend traffic against the current site origin instead of a direct Cloud Run hostname. `firebase.json` therefore rewrites the backend-owned same-origin families to Cloud Run for `/api/**` and `/detect-fields/**` (plus their exact-root variants), while only the known SPA-owned browser routes (`/upload`, `/ui`, `/ui/profile`, `/ui/forms/:formId`, `/ui/groups/:groupId`, `/respond/:token`, `/sign/:token`, and the account-action handlers) are rewritten to `index.html`. There is intentionally no catch-all `** -> /index.html` rewrite, because unknown public URLs must fall through to Hosting `404.html` instead of becoming soft 404 homepage responses. The new Fill By Link -> Sign handoff stays within that same route pair: respondents begin on `/respond/:token`, then continue into `/sign/:token` only after the backend has stored the response and created the immutable signing request.

Public token routes also get Hosting-level `Cache-Control: no-store,max-age=0` headers for `/respond/**` and `/sign/**` so emailed bearer-style links are not cached after a signer or respondent opens them in the browser.

For the lightweight shell endpoints (`/api/health`, `/api/profile`, `/api/saved-forms`, `/api/groups`, and related nested GET routes), the frontend also treats Cloud Run platform `429 no available instance` responses as transient cold-start failures. The homepage shell waits on `/api/health` before it mounts signed-in workflow/profile runtime flows, and the shared GET fetch wrapper retries the original request after the health probe succeeds instead of surfacing the first cold-start response to the user. The health wait now uses bounded exponential backoff up to a longer deadline (90 seconds by default, configurable with `VITE_BACKEND_READY_MAX_WAIT_MS`) because real prod cold starts can outlast the old short retry window during Cloud Run instance provisioning or revision cutovers.

## Local development behavior

- Vite proxies `/api/*` to `VITE_API_URL` (`frontend/vite.config.ts`).
- Detection requests still use detection base resolution from `detectionApi.ts`.

## Rule of thumb for new frontend calls

- Use relative `/api/...` for endpoints that should stay same-origin.
- In production, `buildApiUrl(...)` and the detection base helpers should still resolve to the current site origin so Hosting rewrites stay in the request path.
