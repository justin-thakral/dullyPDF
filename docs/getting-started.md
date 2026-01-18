# Getting Started

This guide covers a quick local setup for the main pipeline and points you to
small, tracked fixtures for manual testing.

## Prereqs

- Node.js (for the frontend tooling)
- Python 3.10+ (for the backend)

## Run the full stack (dev)

From the repo root:

```bash
npm install
npm run dev
```

This starts the FastAPI backend and the Vite frontend together. You can also run
them separately with `npm run backend:dev` and `npm run frontend:dev`.

## Environment setup

The scripts copy example env files into `env/` if they do not exist:

- Backend: `env/backend.dev.env` (from `config/backend.dev.env.example`)
- Frontend: `env/frontend.dev.env` (from `config/frontend.dev.env.example`)

After the first run, open the files in `env/` and update:

- Backend: `FIREBASE_PROJECT_ID`, `FORMS_BUCKET`, `TEMPLATES_BUCKET`,
  optional `OPENAI_API_KEY`.
- Frontend: `VITE_API_URL`, Firebase web config values (`VITE_FIREBASE_*`).

`npm run backend:dev` loads `env/backend.dev.env`, then pulls Firebase Admin
credentials via Secret Manager if configured.
`npm run frontend:dev` copies `env/frontend.dev.env` into `frontend/.env.local`
for Vite.

## OpenAI (optional)

Rename and schema mapping require `OPENAI_API_KEY`. If the key is missing, those
actions will fail while CommonForms detection still works.

## Quick test files

Use the tracked fixtures in `quickTestFiles/`:

- `quickTestFiles/new_patient_forms_1915ccb015.pdf`
- `quickTestFiles/new_patient_forms_1915ccb015_mock.csv` (Search & Fill rows)
- `quickTestFiles/healthdb_vw_form_fields.csv` (schema headers)

Notes:
- CSV/Excel rows stay in the browser; only headers/types are sent to the server.
- Do not add PHI/PII to tracked files.

## More docs

- `backend/README.md`
- `frontend/README.md`
