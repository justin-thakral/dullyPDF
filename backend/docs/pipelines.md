# Pipelines: native vs scanned

The sandbox has two top-level pipelines:

- **Native pipeline** (`nativeSrc/`): For PDFs with a usable text layer.
- **Scanned pipeline** (`scannedSrc/`): For scanned/image-first PDFs where the text layer is missing or unreliable.

Both pipelines share the same expensive preprocessing steps (rendering, geometry detection, label extraction). The final field resolution is deterministic; OpenAI is only used for an optional rename pass.

## Routing (auto)

The router lives in `backend/combinedSrc/pipeline_router.py`.

It computes a `TextLayerStats` summary (word counts per page) and chooses:
- `native` when the text layer has enough words (configurable thresholds).
- `scanned` otherwise.

Environment tuning:
- `SANDBOX_TEXT_LAYER_MIN_WORDS_TOTAL` (default 30)
- `SANDBOX_TEXT_LAYER_MIN_WORDS_PER_PAGE` (default 6)

## Shared preprocessing (both pipelines)

The shared artifact builder (`build_artifacts`) produces:

1) **Rendered pages**: `backend/combinedSrc/render_pdf.py`
   - Converts each PDF page into an OpenCV BGR image at `SANDBOX_DPI` (default 500).
   - Records page point dimensions and pixel scaling.

2) **Geometry candidates**: `backend/combinedSrc/detect_geometry.py`
   - Uses OpenCV morphology/contours to detect underline segments (text inputs).
   - Detects checkbox-like squares.
   - Detects boxes/signature-like rectangles.
   - Converts pixel bboxes back into PDF points (originTop), because downstream consumers use point space.

3) **Label candidates**: `backend/combinedSrc/extract_labels.py`
   - Attempts pdfplumber text extraction first.
   - Falls back to OCR when a page has 0 extractable words (`backend/combinedSrc/ocr_labels.py`).

4) **Candidate assembly**: `backend/combinedSrc/build_candidates.py`
   - Merges geometry + label detection into one per-page JSON structure.
   - Assigns stable `candidateId` values like `line-3-12`, `checkbox-7-44`, `box-2-8`.
   - Applies filtering to reduce common false positives (e.g., checkbox glyphs inside words).

5) **Calibration**: `backend/combinedSrc/calibration.py`
   - Computes median label height per page for more stable rect sizing heuristics.

## Native resolver (text-layer)

Location: `backend/combinedSrc/heuristic_resolver.py` (invoked by `nativeSrc/pipeline.py`)

Input: the merged candidates JSON (page dims, labels, candidates).

Output: a list of form fields referencing candidateIds:
- `name`: snake_case
- `type`: `text | checkbox | signature | date`
- `page`: 1-based page index
- `candidateId`: which geometry candidate backs the field
- `confidence`: heuristic confidence

Native-only adjustments (before resolving):
- Text-layer geometry is extracted and used to inject checkbox glyph/vector candidates.
- Line/checkbox candidates are filtered if they overlap text glyphs too heavily.

## Scanned resolver

Location: `backend/combinedSrc/heuristic_resolver.py` (invoked by `scannedSrc/pipeline.py`)

Input: the rendered page images + per-page candidate lists.

The scanned pipeline relies on the same deterministic resolver; the only difference is the
router decision based on text-layer strength.

## OpenAI rename pass

Location: `backend/combinedSrc/rename_resolver.py`

The rename pass runs after fields are resolved:
- Builds a full-page overlay with candidate geometry + field labels.
- Sends one overlay per page to OpenAI.
- Each field label is unique on a page (`name`, `name_1`, etc.) so duplicates can be disambiguated.
- Parses line-based output (`|| orig | suggested | renameConfidence | isItAfieldConfidence`) to rename fields and drop low-confidence entries.
- Drops fields when `isItAfieldConfidence < SANDBOX_RENAME_MIN_FIELD_CONF` (default 0.30).
