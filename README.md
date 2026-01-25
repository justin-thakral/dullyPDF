# DullyPDF

FastAPI + React app for detecting PDF form fields, renaming candidates with OpenAI,
and editing fields in a PDF viewer. The main pipeline is CommonForms (by [jbarrow](https://github.com/jbarrow/commonforms)) detection,
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

## Cleanup

Use the repo cleanup entrypoint to clear generated artifacts:

```bash
python3 clean.py --mcp --mcp-logs --mcp-screenshots
python3 clean.py --runs --tmp --test-results
python3 clean.py --field-detect-logs --mcp-bug-logs --frontend-tmp
python3 clean.py --all --dry-run
```

Each directory also ships its own `cleanOutput.py` script (see `mcp/`, `runs/`, `test-results/`, `tmp/`, `backend/fieldDetecting/logs/`, `mcp/codexBugs/logs/`, and `frontend/`).

## Docs

- `docs/getting-started.md`
- `backend/README.md`
- `frontend/README.md`
- `backend/fieldDetecting/docs/README.md`
