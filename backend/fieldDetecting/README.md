## CommonForms (by [jbarrow](https://github.com/jbarrow/commonforms)) PDF Field Detection

This backend runs the CommonForms (by [jbarrow](https://github.com/jbarrow/commonforms)) detector (via a dedicated detector service) and supports
schema-only OpenAI mapping via separate endpoints. The legacy OpenCV sandbox pipeline has been moved into
`legacy/fieldDetecting/` and is not part of the main pipeline.

Docs:
- `backend/fieldDetecting/docs/README.md`
- `backend/fieldDetecting/docs/commonforms.md`
- `backend/fieldDetecting/docs/rename-flow.md`
- `backend/fieldDetecting/docs/security.md`

### Pipeline summary

1) CommonForms (by [jbarrow](https://github.com/jbarrow/commonforms)) renders PDF pages and detects widgets.
2) Detected widgets are converted into field objects (originTop rectangles).
3) Optional OpenAI rename uses overlay images to propose better names.
4) Optional schema mapping (OpenAI) produces mapping rules and checkbox group rules.

### Field schema (core shape)

Each field returned by detection includes:
- `name`, `type`, `page`, `rect` (originTop points)
- `confidence`, `category`, `source`, `model`, `candidateId`
- Optional rename metadata: `originalName`, `renameConfidence`, `isItAfieldConfidence`
- Optional checkbox metadata: `groupKey`, `optionKey`, `groupLabel`, `optionLabel`

### Output artifacts (debug only)

When rename is enabled, artifacts land under `backend/fieldDetecting/outputArtifacts/`:
- overlays: rendered pages + field IDs
- json: candidate lists, renamed field payloads, and rename reports

### Runtime logs

Runtime logs are written under `backend/fieldDetecting/logs/`.

Cleanup:

```
python3 backend/fieldDetecting/logs/cleanOutput.py --all
```

You can also run `python3 clean.py --field-detect-logs` from the repo root. Add `--dry-run` to preview.

### Setup

- Python 3.10+
- Create a venv at `backend/.venv`: `python3 -m venv backend/.venv`
- Install deps: `backend/.venv/bin/pip install -r backend/requirements.txt` (main API) or
  `backend/.venv/bin/pip install -r backend/requirements-detector.txt` (detector service).
- Export your API key for the optional rename + schema mapping passes: `export OPENAI_API_KEY=sk-...`
- Configure Firebase Admin for request authentication:
  - `export FIREBASE_CREDENTIALS='{"type":"service_account", ...}'` (JSON string), or
  - `export FIREBASE_CREDENTIALS=/path/to/service-account.json`, or
  - `export GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json`
  - `export FIREBASE_CREDENTIALS_SECRET=dullypdf-prod-firebase-admin` (Secret Manager name)
  - `export FIREBASE_CREDENTIALS_PROJECT=dullypdf` (Secret Manager project)
  - `export FIREBASE_PROJECT_ID=dullypdf` to explicitly match the frontend Firebase project.
  - `scripts/run-backend-*.sh` and `scripts/set-role-*.sh` fetch Secret Manager credentials via gcloud.
- Configure Firebase Storage buckets for saved forms:
  - `export FORMS_BUCKET=dullypdf-forms`
  - `export TEMPLATES_BUCKET=dullypdf-templates`
- Optional admin override (dev only):
  - `export ADMIN_TOKEN=some-secret` (clients send `Authorization: Bearer <token>` or `x-admin-token`; ignored in prod or when `SANDBOX_ALLOW_ADMIN_OVERRIDE=false`)

### Roles

Roles are reserved for admin workflows; schema/template access is enforced per user.

### OpenAI rename guardrails

- Rename runs via `POST /api/renames/ai` and requires an authenticated user.
- OpenAI rename sends PDF pages + overlay tags; schema headers are included when a schema is selected for combined rename+map.
- The UI warns users about which PDF pages, field tags, and schema headers are sent to OpenAI before each run.

### CommonForms (by [jbarrow](https://github.com/jbarrow/commonforms)) tuning

- `COMMONFORMS_MODEL` (default `FFDNet-L`)
- `COMMONFORMS_MODEL_GCS_URI` (optional; GCS URI to model weights)
- `COMMONFORMS_CONFIDENCE` (default `0.3`)
- `COMMONFORMS_IMAGE_SIZE` (default `1600`)
- `COMMONFORMS_DEVICE` (default `cpu`)
- `COMMONFORMS_FAST` (default `false`)
- `COMMONFORMS_MULTILINE` (default `false`)
- `COMMONFORMS_BATCH_SIZE` (default `4`)
- `COMMONFORMS_WEIGHTS_CACHE_DIR` (default `/tmp/commonforms-models`)
- `COMMONFORMS_WEIGHTS_LOCK_TIMEOUT_SECONDS` (default `600`)

### Run the service

```
./scripts/run-backend-dev.sh env/backend.dev.env
```

### Detect fields

Tip: avoid pasting real tokens into shell history. Export a token in your environment
and reference it in the header (for example, `-H "Authorization: Bearer ${FIREBASE_ID_TOKEN}"`).

```
curl -X POST http://localhost:8000/detect-fields \
  -H "Authorization: Bearer <firebase-id-token>" \
  -F "file=@sample.pdf" \
  -F "pipeline=commonforms"
```

Poll for results:

```
curl -X GET http://localhost:8000/detect-fields/<sessionId> \
  -H "Authorization: Bearer <firebase-id-token>"
```
