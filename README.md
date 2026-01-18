# DullyPDF

FastAPI + React app for detecting PDF form fields, renaming candidates with OpenAI,
and editing fields in a PDF viewer. The main pipeline is CommonForms detection,
optional OpenAI rename, and schema-only mapping.

## Quick start (dev)

```bash
npm install
npm run dev
```

Open the UI at `http://localhost:5173`. For a step-by-step walkthrough, see
`docs/getting-started.md`.

## Test files

Use the tracked fixtures in `quickTestFiles/`:

- `quickTestFiles/new_patient_forms_1915ccb015.pdf`
- `quickTestFiles/new_patient_forms_1915ccb015_mock.csv`
- `quickTestFiles/healthdb_vw_form_fields.csv`

## Docs

- `docs/getting-started.md`
- `backend/README.md`
- `frontend/README.md`
- `backend/fieldDetecting/docs/README.md`
