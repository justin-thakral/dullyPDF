# Running the Frontend

## Recommended (from repo root)

```bash
npm run frontend:dev
```

This command runs `scripts/use-frontend-env.sh dev`, which writes `frontend/.env.local` from committed public config plus optional local overrides, then starts Vite.

The script always starts from `config/public/frontend.dev.env` and appends local overrides from:
- `env/frontend.dev.env` (legacy local override, optional)
- `env/frontend.dev.local.env` (preferred local override, optional)

## Direct run (from `frontend/`)

```bash
cd frontend
npm install
npm run dev
```

Vite will use the next available port (typically `http://localhost:5173`).
If you run the backend from `env/backend.dev.env` or `env/backend.dev.stack.env`, keep `SIGNING_APP_ORIGIN`
aligned to that same frontend origin so emailed signing links point at the live dev server.

## Full-stack scripts (from repo root)

```bash
npm run dev
```

This runs backend + frontend together via `concurrently`.

```bash
npm run dev:stack
```

This runs the prod-like dev stack (backend container + frontend dev server).
When `STRIPE_SECRET_KEY` is present and `stripe` is installed, the stack also auto-starts Stripe CLI forwarding to the local billing webhook on host port `8010` by default.

```bash
npm run dev:stack:stop
```

`npm run dev:stack` reads:
- `env/backend.dev.stack.env` (backend settings; copied from `config/backend.dev.stack.env.example` when missing)
- `config/public/frontend.stack.env` (frontend committed public settings)
- optional `env/frontend.stack.local.env` for local-only overrides

## Build and test scripts

From repo root:
- `npm run frontend:build:dev`
- `npm run frontend:build:prod`
- `npm run test:frontend`

From `frontend/`:
- `npm run build:dev`
- `npm run build:prod`
- `npm run preview`
- `npm run test`
- `npm run lint`

Avoid plain `npm run build` from `frontend/`. The build now requires an explicit
env target so the bundle cannot accidentally reuse a stale local `.env.local`.
For prod builds, keep `VITE_FIREBASE_AUTH_DOMAIN` on `dullypdf.firebaseapp.com`
unless you have also updated every OAuth provider callback to allow the custom
domain `__/auth/handler` endpoint and widened the hosting CSP accordingly.
When `VITE_GOOGLE_ADS_TAG_ID` is enabled for prod, the hosting CSP also needs
`https://googleads.g.doubleclick.net` in `script-src` so Google Ads conversion
follow-up requests do not get blocked after `gtag.js` loads.

## API routing in local dev

- Vite proxies `/api/*` to `VITE_API_URL` (`frontend/vite.config.ts`).
- Detection requests use `VITE_DETECTION_API_URL` when set, otherwise `VITE_SANDBOX_API_URL`, then fallback to `http://localhost:8000`.
- See `frontend/docs/api-routing.md` for the full same-origin vs direct-call split.

## Public routes worth checking during local dev

- `http://localhost:5173/usage-docs` and child `/usage-docs/*` routes for public documentation copy.
- `http://localhost:5173/free-features` and `http://localhost:5173/premium-features` for public plan messaging and signed-in premium purchase CTA behavior.
- Intent/SEO routes such as `/pdf-to-fillable-form`, `/fill-pdf-from-csv`, and `/fill-pdf-by-link`.
- Fill By Link respondent routes under `/respond/:token`. The route shell is public and mobile-friendly; live submissions still depend on the backend being available.
- Signing routes under `/sign/:token`. The route is public and mobile-friendly; milestone 3 now includes the signer ceremony for `Sign` mode with session bootstrap, immutable PDF review, consumer e-consent gating, signature adoption, manual fallback recording, and an explicit final sign action. The adopt-signature step now supports typed-name, default legal-name, drawn, and uploaded-image signature marks before completion. Consumer previews now stay locked until consent, Fill By Link sourced requests now show an email-OTP verification step before the immutable PDF or manual fallback action is revealed, signer links expire after the configured request TTL, and public ceremony actions require the same client fingerprint that bootstrapped the session. Completed signer downloads now reuse that same bound session too, so reopening a finished request still needs the current signing session instead of a naked artifact URL. When a PDF signing identity is configured, the completed signed PDF also carries an embedded cryptographic PDF signature in addition to the rendered signature mark and audit artifacts.
- Validation routes under `/verify-signing/:token`. The page is public, does not require a signing session, and reports whether the retained audit envelope plus signed-PDF hashes still line up for one completed request.
- The owner signing dialog on `/ui` now supports batch signer entry via pasted TXT/CSV data or uploaded `.txt` / `.csv` files, and its `Responses` tab tracks waiting vs signed requests with direct artifact downloads.
- In local/dev, signing invites may fall back to manual link sharing if Gmail API delivery is not configured or fails. The `Responses` tab will show `Manual link` / `Invite failed` states so the owner can copy the signer URL directly.
- Mobile landing/demo copy should still explain Fill By Link even though the full editor remains desktop-only under the 900px breakpoint.
- Public token browser routes (`/respond/:token` and `/sign/:token`) are served with `Cache-Control: no-store` in production hosting so link-bearing pages are not cached by the browser or intermediary caches.

## Signing smoke checks

Public signer ceremony smoke from `frontend/`:

```bash
cd frontend
PLAYWRIGHT_BASE_URL=http://127.0.0.1:4173 node test/playwright/run_signing_public_smoke.mjs
```

Owner-side signing smoke from repo root:

```bash
PLAYWRIGHT_BASE_URL=http://127.0.0.1:4173 node frontend/test/playwright/run_signing_owner_smoke.mjs
```

The owner smoke signs into the workspace with a Firebase custom token, opens a real fillable PDF in the editor, adds a signature anchor, saves a signing draft, and sends the immutable request with mocked signing endpoints. Both smoke scripts write screenshots and JSON summaries under `frontend/output/playwright/`.

## reCAPTCHA env flags

- `VITE_RECAPTCHA_SITE_KEY`
- `VITE_CONTACT_REQUIRE_RECAPTCHA`
- `VITE_SIGNUP_REQUIRE_RECAPTCHA`
- `VITE_FILL_LINK_REQUIRE_RECAPTCHA`
