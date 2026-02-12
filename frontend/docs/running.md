# Running the Frontend

## Recommended (from repo root)

```bash
npm run frontend:dev
```

This command runs `scripts/use-frontend-env.sh dev`, which copies `env/frontend.dev.env` to `frontend/.env.local`, then starts Vite.

If `env/frontend.dev.env` does not exist, the script creates it from `config/frontend.dev.env.example`.

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
- `env/frontend.stack.env` (frontend settings; copied from `config/frontend.stack.env.example` when missing)

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
