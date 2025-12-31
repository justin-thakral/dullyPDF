# Running the sandbox

This sandbox is designed for local iteration: generate candidates, resolve fields (native/scanned), and write overlay images + JSON outputs for QA.

## Setup

From repo root:

1) Create venv:
```bash
python3 -m venv backend/.venv
```

2) Install deps:
```bash
backend/.venv/bin/pip install -r backend/requirements.txt
```

3) Ensure OpenAI API key is available for the optional rename pass:
```bash
export OPENAI_API_KEY=...
```

The sandbox also tries to load keys from `backend/.env` if present (see `backend/fieldDetecting/sandbox/combinedSrc/config.py`).

## Run the FastAPI service

```bash
uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

Upload a PDF:
```bash
curl -X POST http://localhost:8000/detect-fields -F "file=@sample.pdf" | jq
```

## Run the CLI (recommended)

The main CLI lives at `backend/fieldDetecting/sandbox/debug/test_local.py`:

```bash
python3 -m backend.fieldDetecting.sandbox.debug.test_local path/to/sample.pdf
```

### Choose the pipeline

- Auto routing (default):
```bash
python3 -m backend.fieldDetecting.sandbox.debug.test_local path/to/sample.pdf --pipeline auto
```

- Force native:
```bash
python3 -m backend.fieldDetecting.sandbox.debug.test_local path/to/sample.pdf --pipeline native
```

- Force scanned:
```bash
python3 -m backend.fieldDetecting.sandbox.debug.test_local path/to/sample.pdf --pipeline scanned
```

### Debug overlays

- Candidate + field overlays for QA (generated automatically by some debug flows).
- Overlay-only utility:
```bash
python3 -m backend.fieldDetecting.sandbox.debug.test_rects backend/fieldDetecting/pdfs/native/consent/base_form.pdf
```

Outputs are written under `backend/fieldDetecting/outputArtifacts/` by default:
- `backend/fieldDetecting/outputArtifacts/json/*.json` (temp-prefixed, e.g. `temp<first5><last5>_fields.json`)
- `backend/fieldDetecting/outputArtifacts/overlays/*.png`

### OpenAI rename pass (full-page overlays)

The rename pass is separate from field resolution and renames fields using per-page overlays:

```bash
python3 -m backend.fieldDetecting.sandbox.debug.test_local path/to/sample.pdf --openAI
```

Outputs:
- `backend/fieldDetecting/outputArtifacts/json/temp<first5><last5>_renames.json`
- `backend/fieldDetecting/outputArtifacts/json/temp<first5><last5>_fields_renamed.json`
- `backend/fieldDetecting/outputArtifacts/overlays/temp<first5><last5>_openai/page_<n>.png`

## Common tuning

- `SANDBOX_DPI` (rendering DPI, default 500)
- `SANDBOX_OPENAI_WORKERS` (max parallel rename calls)
- `SANDBOX_RENAME_MODEL` (default `gpt-5.2`)
- `SANDBOX_RENAME_MAX_OUTPUT_TOKENS`
- `SANDBOX_RENAME_MIN_FIELD_CONF` (drop threshold, default 0.30)

## Cleanup temp artifacts

Use the artifact manager to delete temp-prefixed outputs:

```bash
python3 -m backend.fieldDetecting.sandbox.tools.artifactManager --dry-run
python3 -m backend.fieldDetecting.sandbox.tools.artifactManager
```

## Migrate legacy analysis artifacts

Older runs stored outputs under `outputArtifacts/analysis_*`. Migrate those into the
standard `json/` + `overlays/` layout with:

```bash
python3 -m backend.fieldDetecting.sandbox.tools.migrate_analysis_artifacts --dry-run
python3 -m backend.fieldDetecting.sandbox.tools.migrate_analysis_artifacts
```

## Inject fields into a PDF (sandbox-only)

If you want a fillable PDF created from a JSON template, use:

```bash
python3 -m backend.fieldDetecting.sandbox.combinedSrc.form_filler input.pdf template.json --output output_form.pdf
```

Notes:
- This is explicitly for sandbox debugging; it performs server-side PDF modifications and should not be used in the production pipeline.

## Logging and debug flags

Debug gate (required for local-only toggles):
- Add `SANDBOX_DEBUG_PASSWORD=your-secret` to `backend/.env`.
- Start scripts with `--debug` to enable debug-only behavior.
- Without `--debug`, debug-only flags are ignored even if set.
- DB connector endpoints accept Firebase-authenticated requests by default.
- Set `SANDBOX_DB_REQUIRE_ADMIN=true` to require `ADMIN_TOKEN` (or the debug password with `--debug`).
- `SANDBOX_DEBUG_PASSWORD` is accepted as an admin token fallback for local debug flows.

Global debug toggle (gated by `--debug`):
- `SANDBOX_DEBUG=true|false`

Common tuning:
- `SANDBOX_DPI` (default 500)
- `SANDBOX_RENAME_MODEL`
- `SANDBOX_RENAME_MAX_OUTPUT_TOKENS`
- `SANDBOX_RENAME_MIN_FIELD_CONF`
 - `SANDBOX_CORS_ORIGINS=*` (debug-only; ignored without `--debug`)
