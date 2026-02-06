# Running the Frontend

## From repo root

```bash
npm run frontend:dev
```

This starts the frontend dev server using `scripts/use-frontend-env.sh` to load the correct env vars.

## From the frontend folder

```bash
cd frontend
npm install
npm run dev
```

Vite will use the next available port (typically `http://localhost:5173`).

## Running full stack

```bash
npm run dev
```

This runs backend + frontend together via `concurrently`.

## API routing notes

In production, the site uses Firebase Hosting rewrites so the browser can call some backend routes
as same-origin requests under `/api/...` (for example `/api/recaptcha/assess`). This avoids CORS
preflights and makes cold starts feel less blocking.

In local development, Vite proxies `/api` to `VITE_API_URL` (see `frontend/vite.config.ts`) so the same
relative `/api/...` calls work without CORS. Endpoints that are not proxied in production (OpenAI and
some large upload/stream routes) still call the backend base URL directly via `VITE_API_URL`.

For the full details and the current allowlist/blocklist, see `frontend/docs/api-routing.md`.

## Running prod-like dev stack

```bash
npm run dev:stack
```

This runs a local backend container that enqueues Cloud Tasks to the `dullypdf-dev`
detector service. The stack runs the backend in prod mode (revocation checks on,
legacy endpoints disabled) while still targeting dev resources. Use
`npm run dev:stack:stop` to clean up containers and dev processes if the terminal
exits unexpectedly.

`npm run dev:stack` reads `env/backend.dev.stack.env` for backend settings, so
export `OPENAI_API_KEY` separately if you want rename or schema mapping enabled.

The dev stack uses `env/frontend.stack.env` (copied from
`config/frontend.stack.env.example`) and sets `VITE_DISABLE_ADMIN_OVERRIDE=1`
so admin override headers remain disabled for prod-like testing.

## Contact form

Set `VITE_RECAPTCHA_SITE_KEY` to enable the homepage contact form reCAPTCHA.
Use `VITE_CONTACT_REQUIRE_RECAPTCHA` and `VITE_SIGNUP_REQUIRE_RECAPTCHA` to control
whether contact and account creation require reCAPTCHA in each environment.

## Optional builds

- Dev build: `npm run build:dev`
- Prod build: `npm run build:prod`
