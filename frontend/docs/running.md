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

## Full-stack scripts (from repo root)

```bash
npm run dev
```

This runs backend + frontend together via `concurrently`.

```bash
npm run dev:stack
```

This runs the prod-like dev stack (backend container + frontend dev server).

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

## API routing in local dev

- Vite proxies `/api/*` to `VITE_API_URL` (`frontend/vite.config.ts`).
- Detection requests use `VITE_DETECTION_API_URL` when set, otherwise `VITE_SANDBOX_API_URL`, then fallback to `http://localhost:8000`.
- See `frontend/docs/api-routing.md` for the full same-origin vs direct-call split.

## Public routes worth checking during local dev

- `http://localhost:5173/usage-docs` and child `/usage-docs/*` routes for public documentation copy.
- `http://localhost:5173/free-features` and `http://localhost:5173/premium-features` for public plan messaging and signed-in premium purchase CTA behavior.
- Intent/SEO routes such as `/pdf-to-fillable-form`, `/fill-pdf-from-csv`, and `/fill-pdf-by-link`.
- Fill By Link respondent routes under `/respond/:token`. The route shell is public and mobile-friendly; live submissions still depend on the backend being available.
- Mobile landing/demo copy should still explain Fill By Link even though the full editor remains desktop-only under the 900px breakpoint.

## reCAPTCHA env flags

- `VITE_RECAPTCHA_SITE_KEY`
- `VITE_CONTACT_REQUIRE_RECAPTCHA`
- `VITE_SIGNUP_REQUIRE_RECAPTCHA`
- `VITE_FILL_LINK_REQUIRE_RECAPTCHA`
