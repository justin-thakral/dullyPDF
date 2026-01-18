# CommonForms Pipeline (Main)

This is the **primary** field-detection pipeline used by `backend/main.py`. It runs the
CommonForms ML detector and returns field geometry plus confidence metadata.

Legacy note:
- The old OpenCV-based sandbox pipeline (native/scanned routing) now lives in
  `legacy/fieldDetecting/` and is not part of the main pipeline.

## Flow overview

1) Render PDF pages with CommonForms `render_pdf`.
2) Run the chosen detector (FFDNet or FFDetr) to produce widget bounding boxes.
3) Convert normalized boxes into PDF point-space rectangles (originTop).
4) Emit fields with CommonForms metadata.
5) Optional: run OpenAI rename (overlay images) and schema-only mapping via the API endpoints.

## Input expectations

- PDFs must be readable by CommonForms (encrypted PDFs raise a hard error).
- Geometry is derived from rendered page images; scan quality and DPI affect results.
- Existing AcroForm fields are not required; CommonForms detects new widgets from pixels.

## Field naming + coordinate system

- Default names: `commonforms_<type>_p<page>_<idx>`.
- `candidateId` mirrors the same pattern and is stable per run.
- `rect` is `[x1, y1, x2, y2]` in PDF points with `originTop` (top-left).

## Signature handling

If CommonForms detects a `Signature` widget:
- default behavior emits it as a `text` field
- set `use_signature_fields=True` in `detect_commonforms_fields` to emit `signature`

## Entry points

- API: `backend/main.py` -> `detect_commonforms_fields` in
  `backend/fieldDetecting/commonforms/commonForm.py`.
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

CommonForms detection:
- `COMMONFORMS_MODEL` (default `FFDNet-L`)
- `COMMONFORMS_CONFIDENCE` (default `0.3`)
- `COMMONFORMS_IMAGE_SIZE` (default `1600`)
- `COMMONFORMS_DEVICE` (default `cpu`)
- `COMMONFORMS_FAST` (default `false`)
- `COMMONFORMS_MULTILINE` (default `false`)
- `COMMONFORMS_BATCH_SIZE` (default `4`)
- `COMMONFORMS_CONFIDENCE_GREEN` / `COMMONFORMS_CONFIDENCE_YELLOW`

Runtime guards:
- `SANDBOX_DISABLE_TENSORBOARD` (default `true`) disables TensorBoard hooks when importing torch.

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
