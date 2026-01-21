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

## Optional builds

- Dev build: `npm run build:dev`
- Prod build: `npm run build:prod`
