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
- `npm run build`
- `npm run preview`
- `npm run test`
- `npm run lint`

## API routing in local dev

- Vite proxies `/api/*` to `VITE_API_URL` (`frontend/vite.config.ts`).
- Detection requests use `VITE_DETECTION_API_URL` when set, otherwise `VITE_SANDBOX_API_URL`, then fallback to `http://localhost:8000`.
- See `frontend/docs/api-routing.md` for the full same-origin vs direct-call split.

## reCAPTCHA env flags

- `VITE_RECAPTCHA_SITE_KEY`
- `VITE_CONTACT_REQUIRE_RECAPTCHA`
- `VITE_SIGNUP_REQUIRE_RECAPTCHA`
