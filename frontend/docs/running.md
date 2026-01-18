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

## Optional builds

- Dev build: `npm run build:dev`
- Prod build: `npm run build:prod`
