# Detecting pipeline (CommonForms) - how it actually works

This doc explains the machine learning (ML) detector in plain terms: what it is,
why we store model weights in a cloud bucket, what "the detector service starts"
means, and how to run the pipeline end-to-end.

This is the **main pipeline** (CommonForms by jbarrow). The legacy OpenCV pipeline
lives in `legacy/fieldDetecting/` and is not part of production.

## Quick glossary (basic terms)

- **Detector**: The ML model that finds form fields (text boxes, checkboxes) in a PDF.
- **Model weights**: The learned parameters of the ML model. Think of them as the
  "trained brain" of the detector.
- **Inference**: Running the model to produce predictions (field boxes + confidence).
- **Detector service**: A separate FastAPI service (`backend/detection/detector_app.py`) that
  runs the model. It is separate from the main API so it can scale and isolate heavy
  ML compute.
- **Session**: A tracking ID for a detection request. It stores metadata + results
  in Firestore and GCS.
- **GCS**: Google Cloud Storage. We use buckets for PDFs and detector outputs.
- **Cloud Tasks**: The queue used in production to call the detector service.

## Why model weights are stored in a cloud bucket

The detector needs model weights to run inference. In production we store those
weights in GCS and point to them with `COMMONFORMS_MODEL_GCS_URI`.

Reasons:

- **Consistency**: Every detector instance uses the exact same weights.
- **Speed + stability**: We avoid downloading from HuggingFace on every cold start
  (and avoid rate limits). GCS is fast and under our control.
- **Smaller images**: We keep the Docker image smaller by not baking large weights
  into it.
- **Safer updates**: You can roll forward/back by updating the GCS object path.

How it works in code:

- On the first detection request, the detector checks `COMMONFORMS_MODEL_GCS_URI`.
- If set, it downloads the weight file into `COMMONFORMS_WEIGHTS_CACHE_DIR`
  (default `/tmp/commonforms-models`).
- The file is cached per instance so subsequent requests reuse it.

If no GCS URI is provided, CommonForms falls back to downloading from HuggingFace
(on first use). That works locally, but is slower and easier to rate-limit.

## What "the detector service starts" means

There are two different "start" events:

1) **Service start (container boot)**
   - The FastAPI app boots (`uvicorn backend.detection.detector_app:app ...`).
   - `/health` returns `{"status":"ok"}` once it is ready.
   - It does **not** run detection yet.

2) **Detection start (per job)**
   - The main API (or Cloud Tasks) sends a job to `/internal/detect`.
   - The detector validates auth + session metadata.
   - It downloads the PDF from GCS, runs the model, and writes results.
   - Session status flips from `queued` -> `running` -> `complete` or `failed`.

So: "detector service started" means the container is running. It does not mean a
particular PDF is being processed yet.

## End-to-end pipeline in production (full flow)

1) **Client uploads a PDF** to the main API: `POST /detect-fields`.
2) **Main API validates + stores** the PDF in GCS and creates a session record in Firestore.
3) **Main API enqueues a Cloud Task** with the session ID + GCS path.
4) **Cloud Tasks calls the detector** (`/internal/detect`) with an OIDC token.
5) **Detector service**:
   - Verifies the token and session.
   - Downloads PDF bytes from GCS.
   - Runs CommonForms inference.
   - Writes `fields` + `result` JSON back to GCS and updates Firestore.
6) **Client polls** `GET /detect-fields/{sessionId}` until status is `complete`.
7) **Optional**: client calls `/api/renames/ai` for OpenAI renaming and
   `/api/schema-mappings/ai` for schema mapping.

Key point: the main API **does not** run the model in prod. It queues work and the
separate detector service does the heavy lifting.

## How to use it (local and prod-style)

### Option A: local, in-process (fastest for dev)

This runs the model inside the main API process.

1) Install detector deps:
   - `backend/requirements-detector.txt`
2) Set `DETECTOR_MODE=local`.
3) Start the backend (`./scripts/run-backend-dev.sh env/backend.dev.env`).
4) Call detection:

```bash
curl -X POST http://localhost:8000/detect-fields \
  -H "Authorization: Bearer <firebase-id-token>" \
  -F "file=@sample.pdf" \
  -F "pipeline=commonforms"
```

The response will include `sessionId` and, when run locally, it may already
contain results (no queue).

### Option B: prod-style (Cloud Tasks + detector service)

This matches production behavior.

1) Run the detector service (locally or Cloud Run):

```bash
uvicorn backend.detection.detector_app:app --host 0.0.0.0 --port 8000
```

2) Configure Cloud Tasks + detector env vars:
   - `DETECTOR_MODE=tasks`
   - `DETECTOR_TASKS_PROJECT`, `DETECTOR_TASKS_LOCATION`
   - `DETECTOR_TASKS_QUEUE` (or light/heavy split)
   - `DETECTOR_SERVICE_URL` (or light/heavy)
   - `DETECTOR_TASKS_SERVICE_ACCOUNT`

3) Call `POST /detect-fields` on the main API.
4) Poll `GET /detect-fields/{sessionId}` until status is `complete`.

The dev stack (`npm run dev:stack`) is the easiest way to simulate this flow
locally while still using Cloud Tasks + Cloud Run in `dullypdf-dev`.

## What you get back (field data)

Each detected field includes:

- `name`, `type`, `page`, `rect` (originTop points)
- `confidence`, `category`, `source=commonforms`, `model`, `candidateId`

The `rect` uses **originTop** coordinates: `[x1, y1, x2, y2]` where the origin is
the **top-left** of the page (PDF points).

## Common pitfalls and how to recognize them

- **Detector not running**: jobs stay `queued` or fail fast. Check detector logs
  and ensure the `/internal/detect` endpoint is reachable from Cloud Tasks.
- **Missing detector deps** (local mode): backend throws
  `CommonForms dependencies are missing; set DETECTOR_MODE=tasks or install detector deps.`
- **Weights missing**: if `COMMONFORMS_MODEL_GCS_URI` points to a non-existent
  object, the detector fails on first run.
- **Encrypted PDFs**: password-protected PDFs are rejected; empty-password PDFs are
  decrypted during preflight.

## Related docs

- `backend/fieldDetecting/docs/commonforms.md`
- `backend/fieldDetecting/docs/rename-flow.md`
- `backend/fieldDetecting/docs/security.md`
- `backend/README.md`
