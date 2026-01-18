# Frontend

React + TypeScript UI for viewing PDFs, editing detected fields, running Search & Fill, and saving forms. The frontend talks to the FastAPI backend for detection, OpenAI rename, and schema mapping (schema headers only).

## Quick start

From the repo root (recommended):

```bash
npm run frontend:dev
```

Or run it directly:

```bash
cd frontend
npm install
npm run dev
```

Vite will pick the next available port (typically `http://localhost:5173`).

## Environment

The dev scripts source env vars via `scripts/use-frontend-env.sh`. Common entries:
- `VITE_API_URL` / `VITE_DETECTION_API_URL` for backend base URLs.
- Firebase Identity Platform keys (`VITE_FIREBASE_*`).
- `VITE_ADMIN_TOKEN` (dev-only; never use in production builds).

## Docs

See `frontend/docs/README.md` for architecture and workflow notes.
