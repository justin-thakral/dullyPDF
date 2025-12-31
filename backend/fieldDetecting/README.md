## Sandbox PDF Field Detection

This sandbox prototype exposes a FastAPI endpoint that renders PDFs, detects geometry with OpenCV + pdfplumber, and resolves final form fields via deterministic heuristics.
The pipeline is split into **native** (text-layer) and **scanned** (image-first) flows, with an auto-router that decides based on text-layer strength.

Docs:
- `backend/fieldDetecting/docs/README.md`
- `backend/fieldDetecting/docs/tools.md`

### Setup
- Python 3.10+ (tested with 3.10)
- Create a venv at `backend/.venv`: `python3 -m venv backend/.venv`
- Install deps: `backend/.venv/bin/pip install -r backend/requirements.txt`
- Export your API key for the optional rename pass: `export OPENAI_API_KEY=sk-...`
- Configure Firebase Admin for request authentication:
  - `export FIREBASE_CREDENTIALS='{"type":"service_account", ...}'` (JSON string), or
  - `export FIREBASE_CREDENTIALS=/path/to/service-account.json`, or
  - `export GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json`
  - `export FIREBASE_PROJECT_ID=dullypdf` to explicitly match the frontend Firebase project.
- Debug gate (required for non-production toggles):
  - Add `SANDBOX_DEBUG_PASSWORD=your-secret` to `backend/.env`.
  - Start any sandbox script with `--debug` to enable debug-only features.
  - Without `--debug`, debug-only flags are ignored even if set in the environment.
  - Example: `python -m backend.main --debug`
  - Example (CLI): `python -m backend.fieldDetecting.sandbox.debug.test_local --debug path/to/sample.pdf`
- Configure Firebase Storage buckets for saved forms:
  - `export FORMS_BUCKET=dullypdf-forms`
  - `export TEMPLATES_BUCKET=dullypdf-templates`
- Protect DB connector endpoints (optional):
  - `export ADMIN_TOKEN=some-secret` (clients send `Authorization: Bearer <token>` or `x-admin-token`)
  - `SANDBOX_DEBUG_PASSWORD` is accepted as an admin token fallback for local debug flows.
  - Without `ADMIN_TOKEN`, DB connector endpoints accept Firebase-authenticated requests.
  - Set `SANDBOX_DB_REQUIRE_ADMIN=true` to require the admin token even when Firebase auth is present.
- Optional tuning:
  - `export SANDBOX_DEBUG=false` to quiet verbose logs (defaults to true, gated by `--debug`).
  - `export SANDBOX_DPI=500` to change rendering DPI.
  - `export SANDBOX_CORS_ORIGINS=http://localhost:5173` to override allowed origins (comma-separated).
  - `export SANDBOX_CORS_ORIGINS=*` to allow all origins (debug-only; ignored without `--debug`).
  - `export SANDBOX_MAX_UPLOAD_MB=50` to cap upload size for `/detect-fields`.
  - `export SANDBOX_WORKERS=4` to cap CPU-stage worker threads (render/labels/geometry/candidates).
  - `export SANDBOX_RENDER_WORKERS=2` to override render threading.
  - `export SANDBOX_LABELS_WORKERS=2` to override label extraction threading.
  - `export SANDBOX_GEOMETRY_WORKERS=2` to override geometry detection threading.
  - `export SANDBOX_CANDIDATES_WORKERS=2` to override candidate assembly threading.
  - `export SANDBOX_OPENAI_WORKERS=6` to cap concurrent OpenAI rename calls.
  - `export SANDBOX_LOG_DIR=backend/fieldDetecting/logs` to redirect log file output.
  - `export SANDBOX_LOG_FILE=sandbox.log` to change the log filename.
  - `export SANDBOX_LOG_OPENAI_RESPONSE=true` to log full OpenAI responses (sensitive; gated by `--debug`).
  - `export SANDBOX_RENAME_MODEL=gpt-5.2` to override the rename model.
  - `export SANDBOX_RENAME_MIN_FIELD_CONF=0.3` to control the field drop threshold.
  - `export SANDBOX_NATIVE_VECTOR_LINE_OVERLAP=0.60` to control vector-line injection overlap (native).
  - `export SANDBOX_NATIVE_GLYPH_LINE_OVERLAP=0.60` to control underscore/line-glyph injection overlap (native).
  - `export SANDBOX_NATIVE_LINE_CHAR_XOVERLAP=0.85` to require text overlap across most of a line before dropping it (native).
  - `export SANDBOX_TEXT_LAYER_MIN_WORDS_TOTAL=30` to tune native/scanned routing thresholds.
  - `export SANDBOX_TEXT_LAYER_MIN_WORDS_PER_PAGE=6` to tune native/scanned routing thresholds.

### Run the service
```
uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

POST a PDF:
```
curl -X POST http://localhost:8000/detect-fields \
  -F "file=@sample.pdf" \
  | jq
```

### Local test script
```
python -m backend.fieldDetecting.sandbox.debug.test_local path/to/sample.pdf
# Output defaults to backend/fieldDetecting/outputArtifacts/json/temp<first5><last5>_fields.json
```
- The router auto-selects **native** vs **scanned** based on text-layer counts. You can override it with `--pipeline native|scanned`.
- Add `--openAI` to run the rename pass over full-page overlays.
- Use `--output some/folder` to change the output root (artifacts remain temp-prefixed).
- Use `--output-dir some/folder` to force a single output root with `json/` and `overlays/`.

Overlay/debug helper (writes to `backend/fieldDetecting/outputArtifacts/` by default, with `json/` + `overlays/` subfolders):
```
python -m backend.fieldDetecting.sandbox.debug.test_rects backend/fieldDetecting/pdfs/native/consent/base_form.pdf
```

PDF sorter (classifies PDFs into native/scanned groups, default mode is `move`):
```
python -m backend.fieldDetecting.sandbox.tools.sort_pdfs --pdfs-dir backend/fieldDetecting/pdfs
```
Options:
- `--forms-dir backend/fieldDetecting/forms/native` (or another forms root) to classify filled PDFs.
- `--forms-output-root backend/fieldDetecting/forms` to choose where classified forms land (default is `forms/`).
- `--mode copy` to copy files instead of moving.

ML corpus migration (moves ML PDFs into the new native/scanned layout):
```
python -m backend.fieldDetecting.sandbox.tools.migrate_ml_pdfs
```
Outputs:
- `backend/fieldDetecting/pdfs/native`
- `backend/fieldDetecting/pdfs/scanned`
Note: ML migration only moves input PDFs; it does not emit JSON or overlays.

### Input PDFs
- Source PDFs live in `backend/fieldDetecting/pdfs/native/` and `backend/fieldDetecting/pdfs/scanned/` (subfolders: `hippa/`, `consent/`, `intake/`).
- `backend/fieldDetecting/pdfs/manifest.json` tracks native vs scanned classifications for sandbox runs.

### Sandbox layout
- `sandbox/combinedSrc/` shared pipeline code used by both native + scanned flows.
- `sandbox/nativeSrc/` text-layer pipeline logic.
- `sandbox/scannedSrc/` scanned pipeline logic.
- `sandbox/ML/` ML-specific scripts and datasets.
- `sandbox/debug/` debug CLI helpers (Python-only; reference images live in `docs/images/`).
- `sandbox/test/` pytest files.
- `sandbox/tools/` one-off maintenance utilities (sorting, batch ops).
- `forms/` output PDFs split into `native/` and `scanned/`.
- `outputArtifacts/` contains `json/` and `overlays/` for pipeline/debug outputs.
- `sandbox/tools/artifactManager.py` deletes temp-prefixed debug artifacts.
- `sandbox/tools/migrate_analysis_artifacts.py` migrates legacy `analysis_*` runs into `json/` + `overlays/`.

### What it does
1) `sandbox/combinedSrc/render_pdf.py` renders each page at 500 DPI with PyMuPDF and records pixel-to-point scaling.
2) `sandbox/combinedSrc/detect_geometry.py` finds underlines, rectangles, and checkbox-like squares with OpenCV and converts them back to PDF points (origin top-left).
3) `sandbox/combinedSrc/extract_labels.py` groups text lines with pdfplumber into label candidates.
4) `sandbox/combinedSrc/build_candidates.py` merges geometry + labels into per-page candidate JSON.
5) `sandbox/combinedSrc/rename_resolver.py` optionally calls OpenAI on full-page overlays to rename fields and filter low-confidence fields.
6) `main.py` wraps the pipeline behind `/detect-fields`; `sandbox/debug/test_local.py` runs it from the CLI.
7) Routing is in `sandbox/combinedSrc/pipeline_router.py`, with pipeline entrypoints in `sandbox/nativeSrc/` and `sandbox/scannedSrc/`.

### Notes
- Coordinate system is `originTop` with US Letter default dimensions (612x792 points) preserved from the PDF.
- Page numbers are 1-based.
- Logging is descriptive but controlled by `SANDBOX_DEBUG`; set to false after debugging to quiet the console.
- Sandbox logs are also written to `backend/fieldDetecting/logs/sandbox.log` by default.
