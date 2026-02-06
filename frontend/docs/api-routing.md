# API Routing (Firebase Hosting Rewrites)

DullyPDF serves the React SPA from Firebase Hosting and runs the FastAPI backend on Cloud Run.
In production, some backend routes are proxied through Firebase Hosting so the browser can call them
as same-origin requests on `https://dullypdf.com`.

## Why Proxy Through Hosting

- Remove CORS preflights (OPTIONS). When Cloud Run is scaled to zero, the preflight can "pay" the cold start
  and delay the real request (especially noticeable during signup reCAPTCHA verification).
- Keep Cloud Run scale-to-zero while making the user experience feel less stuck by shifting the first backend
  call earlier (see warmup below).

## How It Works (Prod)

- `firebase.json` defines `hosting.rewrites` that forward selected paths to the Cloud Run service
  `dullypdf-backend` in `us-central1`.
- The frontend calls these endpoints using relative URLs like `/api/profile`.
- The SPA catch-all rewrite (`"source": "**" -> /index.html`) must remain last so `/api/...` paths do not
  fall through to the SPA.

Warmup:

- On initial load, the frontend does a fire-and-forget `GET /api/health` (see `frontend/src/main.tsx`).
  This does not remove cold starts, but it moves the cold start earlier so signup doesn't feel blocked.

## Endpoints Proxied (Same-Origin)

These are forwarded by Firebase Hosting to Cloud Run (see `firebase.json`):

- `GET /api/health`
- `POST /api/recaptcha/assess`
- `POST /api/contact`
- `GET /api/profile`
- `GET /api/schemas`
- `POST /api/schemas`
- `POST /api/sessions/*/touch`
- `GET /api/saved-forms`
- `GET /api/saved-forms/*`
- `DELETE /api/saved-forms/*`
- `POST /api/saved-forms/*/session`

## Endpoints Not Proxied (Direct To Cloud Run)

Firebase Hosting's Cloud Run rewrites have an approximate 60 second request timeout. Endpoints that can
exceed that (or that involve large uploads/streams) are intentionally not proxied.

OpenAI (can exceed 60s):

- `POST /api/renames/ai`
- `POST /api/schema-mappings/ai`

Detection (can be slow; kept direct):

- `POST /detect-fields`
- `GET /detect-fields/{session_id}`

Large upload/stream endpoints (kept direct):

- `POST /api/templates/session`
- `POST /api/forms/materialize`
- `GET /api/saved-forms/{form_id}/download`

## Frontend Call Rules

- Prefer same-origin `/api/...` for proxied endpoints (see `frontend/src/api.ts` and `frontend/src/services/detectionApi.ts`).
- Use `buildApiUrl(...)` (base = `VITE_API_URL`) for endpoints that are not proxied.

This split is intentional: it removes preflights for the fast routes while keeping the long-running routes
out of the Hosting proxy timeout.

## Local Development

- Vite proxies `/api` to `VITE_API_URL` (see `frontend/vite.config.ts`) so same-origin `/api/...` calls work
  locally without CORS issues.
- Detection calls use `VITE_DETECTION_API_URL` (see `frontend/src/services/detectionApi.ts`).
- When running the full stack (`npm run dev`), the defaults point to `http://localhost:8000`.

## Adding A New Endpoint

- If the endpoint is typically < 60 seconds and has small request/response bodies, add a Hosting rewrite
  and call it as `/api/...` from the frontend.
- If it can exceed 60 seconds, streams responses, or uploads large files, keep it as a direct-to-Cloud-Run
  call (use `buildApiUrl(...)` in the frontend).

## Operational Notes

- Client IP: when requests are proxied through Hosting, `request.client.host` in FastAPI will be a Google
  infrastructure IP. Because the Cloud Run service is also publicly reachable, we treat `X-Forwarded-For`
  as attacker-controlled in the general case (direct callers can spoof it). In production we keep
  `SANDBOX_TRUST_PROXY_HEADERS=false` and use global caps like `CONTACT_RATE_LIMIT_GLOBAL` /
  `SIGNUP_RATE_LIMIT_GLOBAL` for public endpoints instead of per-IP limits.

- reCAPTCHA hostname allowlist: in production we set `RECAPTCHA_ALLOWED_HOSTNAMES` (for example
  `dullypdf.com,dullypdf.web.app,dullypdf.firebaseapp.com`) so tokens minted on other origins are rejected.
