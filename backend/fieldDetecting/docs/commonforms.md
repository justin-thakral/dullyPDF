# CommonForms (by [jbarrow](https://github.com/jbarrow/commonforms)) Pipeline (Main)

This is the **primary** field-detection pipeline used by the detector service
(`backend/detector_main.py`). The main API queues detection jobs and the detector
executes CommonForms (by [jbarrow](https://github.com/jbarrow/commonforms)) ML inference to return field geometry plus confidence metadata.

Legacy note:
- The old OpenCV-based sandbox pipeline (native/scanned routing) now lives in
  `legacy/fieldDetecting/` and is not part of the main pipeline.

## Flow overview

1) Render PDF pages with CommonForms (by [jbarrow](https://github.com/jbarrow/commonforms)) `render_pdf`.
2) Run the chosen detector (FFDNet or FFDetr) to produce widget bounding boxes.
3) Convert normalized boxes into PDF point-space rectangles (originTop).
4) Emit fields with CommonForms (by [jbarrow](https://github.com/jbarrow/commonforms)) metadata.
5) Optional: run OpenAI rename (overlay images) and schema-only mapping via the API endpoints.

## Input expectations

- PDFs must be readable by CommonForms (by [jbarrow](https://github.com/jbarrow/commonforms)). Password-protected PDFs are rejected;
  PDFs encrypted with an empty password are decrypted during preflight.
- Geometry is derived from rendered page images; scan quality and DPI affect results.
- Existing AcroForm fields are not required; CommonForms (by [jbarrow](https://github.com/jbarrow/commonforms)) detects new widgets from pixels.

## Field naming + coordinate system

- Default names: `commonforms_<type>_p<page>_<idx>`.
- `candidateId` mirrors the same pattern and is stable per run.
- `rect` is `[x1, y1, x2, y2]` in PDF points with `originTop` (top-left).

## Signature handling

If CommonForms (by [jbarrow](https://github.com/jbarrow/commonforms)) detects a `Signature` widget:
- default behavior emits it as a `text` field
- set `use_signature_fields=True` in `detect_commonforms_fields` to emit `signature`

## Entry points

- Detector service: `backend/detector_main.py` -> `detect_commonforms_fields` in
  `backend/fieldDetecting/commonforms/commonForm.py`.
- Main API: `POST /detect-fields` queues a job, `GET /detect-fields/{sessionId}` returns results.
- Container build: `Dockerfile.detector` (CPU-only PyTorch + CommonForms (by [jbarrow](https://github.com/jbarrow/commonforms))).
- CLI:
```bash
python -m backend.fieldDetecting.commonforms.commonForm path/to/sample.pdf
```

## Outputs

`detect_commonforms_fields` returns:
- `fields`: list of field dicts with:
  - `name`, `type`, `page`, `rect` (originTop points)
  - `confidence`, `category`, `source=commonforms`, `model`, `candidateId`
- `coordinateSystem`: `originTop`
- `meta`: detection configuration (model, confidence threshold, image size, device, etc.)

Optional artifacts when `output_pdf` is provided:
- a fillable PDF with injected widgets (same coordinate system)

## Configuration (env)

CommonForms (by [jbarrow](https://github.com/jbarrow/commonforms)) detection:
- `COMMONFORMS_MODEL` (default `FFDNet-L`)
- `COMMONFORMS_MODEL_GCS_URI` (optional; GCS URI to a model weight file)
- `COMMONFORMS_CONFIDENCE` (default `0.3`)
- `COMMONFORMS_IMAGE_SIZE` (default `1600`)
- `COMMONFORMS_DEVICE` (default `cpu`)
- `COMMONFORMS_FAST` (default `false`)
- `COMMONFORMS_MULTILINE` (default `false`)
- `COMMONFORMS_BATCH_SIZE` (default `4`)
- `COMMONFORMS_CONFIDENCE_GREEN` / `COMMONFORMS_CONFIDENCE_YELLOW`
- `COMMONFORMS_WEIGHTS_CACHE_DIR` (default `/tmp/commonforms-models`)
- `COMMONFORMS_WEIGHTS_LOCK_TIMEOUT_SECONDS` (default `600`)

Runtime guards:
- `SANDBOX_DISABLE_TENSORBOARD` (default `true`) disables TensorBoard hooks when importing torch.

## Runtime requirements

- If `COMMONFORMS_MODEL_GCS_URI` is set, the detector downloads weights from GCS
  into `COMMONFORMS_WEIGHTS_CACHE_DIR` and reuses the cached file across requests.
- If no GCS URI is provided, CommonForms (by [jbarrow](https://github.com/jbarrow/commonforms)) downloads weights from HuggingFace on
  first run. Provide `HF_TOKEN` (or `HUGGINGFACE_HUB_TOKEN`) to avoid rate limits.
- Download locks older than `COMMONFORMS_WEIGHTS_LOCK_TIMEOUT_SECONDS` are treated
  as stale and removed before retrying.
- Cloud Run detector instances require more than 512Mi memory. Use 2Gi+ to
  avoid OOM restarts during model load/inference.

## Model weights in GCS (recommended for prod)

The detector uses the `COMMONFORMS_MODEL` label to pick FFDNet vs FFDetr, but it
loads weights from `COMMONFORMS_MODEL_GCS_URI` when provided. Ensure the weights
match `COMMONFORMS_MODEL` and `COMMONFORMS_FAST`.

Known weight filenames from HuggingFace:
- `FFDNet-L.pt` (repo `jbarrow/FFDNet-L`)
- `FFDNet-L.onnx` (repo `jbarrow/FFDNet-L-cpu`, used when `COMMONFORMS_FAST=true`)
- `FFDNet-S.pt` (repo `jbarrow/FFDNet-S`)
- `FFDNet-S.onnx` (repo `jbarrow/FFDNet-S-cpu`)
- `FFDetr.pth` (repo `jbarrow/FFDetr`)

Example flow:
```bash
huggingface-cli download jbarrow/FFDNet-L FFDNet-L.pt --local-dir /tmp/commonforms
gcloud storage cp /tmp/commonforms/FFDNet-L.pt gs://<models-bucket>/commonforms/FFDNet-L.pt
```

## Debug output

When OpenAI rename is enabled, overlay images and JSON reports are written to:
`backend/fieldDetecting/outputArtifacts/` under temp-prefixed folders.

## Optional OpenAI rename + schema mapping

After detection, the backend can optionally:
- Rename PDF fields via OpenAI overlays:
  - `POST /api/renames/ai`
  - Requires `OPENAI_API_KEY`
  - Requires available OpenAI credits.
- Map PDF fields to schema metadata via OpenAI:
  - `backend/ai/schema_mapping.py`
  - Requires `OPENAI_API_KEY`
  - Requires available OpenAI credits and user-owned schema/template checks.

## Time complexity (high level)

- Rendering and detection scale with page count and image size.
- Detector inference dominates runtime (model-dependent).
