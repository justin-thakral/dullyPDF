# Rename flow (overlay + OpenAI)

This rename flow is part of the **main pipeline** (CommonForms (by [jbarrow](https://github.com/jbarrow/commonforms)) detection + OpenAI rename).
It is not tied to the legacy sandbox router.

The rename flow exists to solve a common failure mode: geometry is detected correctly, but
names are missing or low-quality because labels are noisy or ambiguous. We render a full-page
overlay with short field IDs, then ask the model to propose better names using the overlay
and the raw page image as context.

Compliance note: OpenAI rename receives PDF page images plus overlay tags. When the combined
rename+map flow is used, schema headers are sent in the same request. No row data or field
values are ever sent. The UI warns users before sending PDF pages or schema headers to OpenAI.

## When to use it

- You have good candidate geometry (lines, checkboxes, boxes) but field naming is poor.
- You want to rename known fields without re-detecting geometry.

## Inputs and outputs

Inputs:
- One page image per page (rendered at `SANDBOX_DPI`).
- Per-page candidate list (CommonForms (by [jbarrow](https://github.com/jbarrow/commonforms)) widgets + extracted labels).
- Per-page field list (from the CommonForms (by [jbarrow](https://github.com/jbarrow/commonforms)) detector).

Outputs:
- A `renames` array keyed by the on-overlay field name:
  - `originalFieldName`
  - `suggestedRename`
  - `renameConfidence`
  - `isItAfieldConfidence`
- A renamed field list where each field gets:
  - `originalName`, `renameConfidence`, `isItAfieldConfidence`
  - Normalized `name` (snake_case, checkbox prefix `i_`)
  - Checkbox grouping hints (`groupKey`, `optionKey`, `groupLabel`, `optionLabel`) when available
  - `mappingConfidence` when a rename matches a schema header name
- Optional fill-time rules when schema headers are provided:
  - `checkboxRules`
  - `radioGroupSuggestions`
  - `textTransformRules` (deterministic text split/join/copy operations)
  - `fillRules` envelope (`version`, `checkboxRules`, `textTransformRules`)

API response note:
- `POST /detect-fields` queues detection and returns a `sessionId`.
- `GET /detect-fields/{sessionId}` returns the baseline `fields` array once ready.
- `POST /api/renames/ai` returns renamed `fields`, the rename report, optional `checkboxRules`, and the same `sessionId` when running inline mode.
- `POST /api/renames/ai` can also return `status=queued` + `jobId` in task mode.
- `GET /api/renames/ai/{jobId}` returns queued/running/failed/complete status for async rename jobs.
- `POST /api/schema-mappings/ai` can return `status=queued` + `jobId` in task mode.
- `GET /api/schema-mappings/ai/{jobId}` returns queued/running/failed/complete status for async remap jobs.
- Mapping responses include `mappings` plus deterministic rule payloads (`checkboxRules`, `radioGroupSuggestions`, `textTransformRules`, `fillRules`) used by Search & Fill.
- The original name is preserved in `originalName` so the UI can reconcile edits.
- Template overlay `rect` values may be sent as `{x,y,width,height}` or `[x1,y1,x2,y2]` (originTop points). The backend normalizes to a consistent numeric shape before use: schema mapping allowlists use `{x,y,width,height}`, while rename geometry uses `[x1,y1,x2,y2]`.

The OpenAI response is line-based to avoid JSON parsing failures:
`|| originalFieldName | suggestedRename | renameConfidence | isItAfieldConfidence`

When schema headers are provided, the response includes a trailing JSON block:
`BEGIN_CHECKBOX_RULES_JSON ... END_CHECKBOX_RULES_JSON`

Files:
- `backend/fieldDetecting/rename_pipeline/combinedSrc/field_overlay.py`: renders the overlay image with field IDs centered inside field boxes and centered on checkbox squares.
- `backend/fieldDetecting/rename_pipeline/combinedSrc/rename_resolver.py`: calls OpenAI and applies renames to fields.
- `backend/fieldDetecting/rename_pipeline/combinedSrc/prompt_builder.py`: prompt assembly, prompt-noise compaction, and schema shortlist selection.
- `backend/fieldDetecting/rename_pipeline/combinedSrc/payload_budgeter.py`: payload size estimation plus image fallback ladder (clean/prev tightening, prev-drop, overlay downscale).
- `backend/fieldDetecting/rename_pipeline/combinedSrc/openai_utils.py`: retries the Responses API when a model rejects `temperature`.
- `backend/ai/rename_pipeline.py`: orchestration used by `/api/renames/ai` (render + labels + rename).

Overlay readability note:
- Checkbox tags are fit adaptively per checkbox box size, not a fixed text scale.
- For tiny checkbox boxes, renderer truncates/downsized text to keep tag text inside bounds.
- Checkbox label scoring is shared between overlay debug behavior and rename hint generation.

## Confidence model and gating

The rename flow carries multiple confidence values with different purposes.

### 1) `isItAfieldConfidence` (fieldness confidence)

- Source: model output line `|| ... | isItAfieldConfidence`.
- Meaning: confidence that a candidate is a real fillable field (not decorative content).
- Runtime role:
  - Always written to each renamed field as `isItAfieldConfidence`.
  - Compared against `SANDBOX_RENAME_MIN_FIELD_CONF` (default `0.30`).
  - If below threshold, the field is added to `dropped` and `renameConfidence` is forced to `0`.

Important:
- Fields below threshold are not removed from the returned field list. They remain editable in UI.

### 2) `renameConfidence` (name confidence)

- Source: model output line `|| ... | renameConfidence | ...`.
- Meaning: confidence that the suggested field name is correct.
- Runtime role:
  - Stored per field as `renameConfidence`.
  - Forced to `0` when `isItAfieldConfidence < SANDBOX_RENAME_MIN_FIELD_CONF`.

### 3) `mappingConfidence` (schema-alignment confidence in combined mode)

- Produced only when schema headers are included in rename (`/api/renames/ai` with `schemaId`).
- Current behavior:
  - If normalized renamed field name matches a schema field exactly, `mappingConfidence` is set to that field's `renameConfidence`.
  - Otherwise `mappingConfidence` is `null`.

### 4) CommonForms category thresholds (green/yellow/red)

When category recalculation is enabled (`adjust_field_confidence=True` path), category is derived from `isItAfieldConfidence` using:

- green: `>= COMMONFORMS_CONFIDENCE_GREEN` (default `0.60`)
- yellow: `>= COMMONFORMS_CONFIDENCE_YELLOW` and `< green` (default `0.30..0.59`)
- red: `< COMMONFORMS_CONFIDENCE_YELLOW` (default `<0.30`)

Notes:
- API rename currently keeps returning confidence numbers regardless of category refresh.
- Frontend filtering is confidence-number driven and does not require backend `category`.

### 5) Frontend confidence tiers (high/medium/low)

Frontend UI (`frontend/src/utils/confidence.ts`) uses:

- high: `>= 0.60`
- medium: `>= 0.30 and < 0.60`
- low: `< 0.30`

Field list confidence filtering uses `fieldConfidence` first (mapped from `isItAfieldConfidence` when present), then falls back to naming confidence when needed.

## Overlay naming and mapping

Each field is assigned a short, page-local ID so the model can refer to it unambiguously:

- IDs are 3-character base32 tags (alphabet excludes visually confusing characters).
- Tags are sampled deterministically per page using a stable seed (page index + field count).
- The overlay keeps a lookup map: `overlay_id -> original field index` so we can apply renames
  without mutating the original list order.

Field labels on each overlay are made unique per page. If the base name repeats, suffixes
are appended (`name`, `name_1`, `name_2`, ...). This lets OpenAI disambiguate duplicates.

## Prompt payload

The prompt provides three inputs per page:

1) The raw page image (no overlays).
2) The overlay image with the field IDs.
3) Optional bottom slice of the previous page if fields appear near the top edge.

Each field in the prompt includes metadata derived from candidate context:

- `label_dist`: minimum distance to the nearest label bounding box.
- `overlaps_label`: whether the field intersects a label bbox.
- `w_ratio` / `h_ratio`: width and height relative to page size.
- `option_hint` (checkboxes only): a nearby label text hint.

These values steer the model away from paragraph text, long rules, or decorative boxes.

Prompt hygiene:
- `SANDBOX_RENAME_PROMPT_HYGIENE` (default on) removes only exact duplicate bullet lines and repeated blank lines.
- This reduces noise while preserving unique instructions.

Schema list policy:
- If schema size is `<= SANDBOX_RENAME_DB_PROMPT_FULL_THRESHOLD` (default `1000`), all fields are included in the rename prompt.
- If schema size is above threshold, prompt includes a ranked shortlist of likely matches (`SANDBOX_RENAME_DB_PROMPT_SHORTLIST_LIMIT`, default `450`) based on token overlap with page overlay IDs and checkbox option hints.
- If prompt text still exceeds `SANDBOX_RENAME_PAGE_PROMPT_CHAR_BUDGET`, shortlist can be reduced again using `SANDBOX_RENAME_DB_PROMPT_BUDGET_SHORTLIST_LIMIT`.

## Checkbox label hints

Checkboxes are too small to host long IDs plus label context, so a best-effort label hint is
attached in the prompt:

- We score nearby labels by distance to the checkbox, vertical alignment, and right-side bias.
- The best-scoring label is included as `option_hint="<label text>"` in the prompt metadata.

The hint is used to shape `groupKey` / `optionKey` outputs after renaming.

## Dense page handling

Pages with many fields (or very tight spacing) are rendered at higher resolution to keep IDs
legible. A page is considered dense when:

- Field count >= `SANDBOX_RENAME_DENSE_FIELD_COUNT`, or
- The minimum distance between field centers <= `SANDBOX_RENAME_DENSE_MIN_CENTER_DIST`.

Dense pages use `SANDBOX_RENAME_DENSE_MAX_DIM` and `SANDBOX_RENAME_DENSE_FORMAT`.

## Image payload profiles and budgets

Rename uses separate image profiles for model input:

- Clean page image profile (`SANDBOX_RENAME_CLEAN_*`) for lower-cost visual context.
- Overlay image profile (`SANDBOX_RENAME_OVERLAY_*`) for tag fidelity.

Default intent:
- Clean image is sent with lower detail (`low`) unless overridden.
- Overlay image is sent with high detail (`high`) so short IDs remain readable.

Per-page preflight budgets:
- Prompt budget: `SANDBOX_RENAME_PAGE_PROMPT_CHAR_BUDGET`
- Image budget: `SANDBOX_RENAME_PAGE_IMAGE_BYTE_BUDGET`

Fallback ladder when above budget:
1. Tighten clean image settings (`SANDBOX_RENAME_BUDGET_CLEAN_*`) and force clean/prev detail to low.
2. Drop previous-page crop context.
3. Reduce overlay max dimension down toward `SANDBOX_RENAME_OVERLAY_MIN_DIM`.
4. If still above budget, continue with best-effort payload and log a warning.

## Previous-page context

If fields appear near the top of a page, a cropped slice of the previous page is included to
avoid mislabeling carry-over headers. This behavior is controlled by:

- `SANDBOX_RENAME_PREV_PAGE_FRACTION` (height of the cropped slice)
- `SANDBOX_RENAME_PREV_PAGE_TOP_FRACTION` (top-of-page threshold to trigger it)

## Schema alignment (combined mode)

Schema alignment can happen in two ways:
- `/api/schema-mappings/ai` for mapping-only runs (schema headers + template tags).
- `/api/renames/ai` with schema headers for the combined rename+map run (PDF pages + overlay tags + schema headers).

Both paths send only schema header names/types and template tags. No row data or field values
are sent. The UI warns users before sending schema headers to OpenAI.

## Async worker mode

When `OPENAI_RENAME_MODE=tasks` / `OPENAI_REMAP_MODE=tasks`, the main API enqueues Cloud Tasks jobs
instead of waiting for OpenAI calls inline. Dedicated worker services execute the heavy steps:

- Rename worker: `backend/ai/rename_worker_app.py`
- Remap worker: `backend/ai/remap_worker_app.py`

This avoids long request/response windows on the main API and makes frontend polling explicit.

Optional prewarm behavior:
- Detection requests can include `prewarmRename=true` / `prewarmRemap=true`.
- The detector service triggers a best-effort `/health` call to worker services when
  remaining pages are below `OPENAI_PREWARM_REMAINING_PAGES` (default 3), if
  `OPENAI_PREWARM_ENABLED=true`.

## Prompt behavior

The prompt explicitly instructs the model to reject:
- boxes sitting on paragraph text
- page-break lines or section separators
- checkboxes that appear inside paragraphs or without aligned option text
- double-checkbox overlaps (keep the best, drop the duplicate)

Per-field metadata (label distance + size ratios) is included to reinforce these rules.

## Running it

Via API (two-step):

Tip: avoid pasting real tokens into shell history. Export a token in your environment
and reference it in the header (for example, `-H "Authorization: Bearer ${FIREBASE_ID_TOKEN}"`).

```bash
curl -X POST http://localhost:8000/detect-fields \\
  -H "Authorization: Bearer <firebase-id-token>" \\
  -F "file=@sample.pdf" \\
  -F "pipeline=commonforms"

curl -X GET http://localhost:8000/detect-fields/<sessionId> \\
  -H "Authorization: Bearer <firebase-id-token>"

curl -X POST http://localhost:8000/api/renames/ai \\
  -H "Authorization: Bearer <firebase-id-token>" \\
  -H "Content-Type: application/json" \\
  -d '{"sessionId":"<sessionId>"}'
```

Artifacts:
- Overlays: `backend/fieldDetecting/outputArtifacts/overlays/temp<first5><last5>_openai/page_<n>.png`
- Renames: `backend/fieldDetecting/outputArtifacts/json/temp<first5><last5>_renames.json`
- Fields with names applied: `backend/fieldDetecting/outputArtifacts/json/temp<first5><last5>_fields_renamed.json`

`temp<first5><last5>` is derived from the first five and last five characters of the PDF filename stem.

## Configuration reference

Common rename settings (all optional):

- `SANDBOX_RENAME_MODEL`: model name (default is `gpt-5-mini`)
- `SANDBOX_RENAME_MAX_OUTPUT_TOKENS`: cap output tokens per page
- `SANDBOX_RENAME_MIN_FIELD_CONF`: drop threshold for `isItAfieldConfidence`
- `SANDBOX_RENAME_OVERLAY_QUALITY`: overlay image quality (default 92, 96 for commonforms)
- `SANDBOX_RENAME_OVERLAY_MAX_DIM`: max dimension for overlay scaling (default 6000)
- `SANDBOX_RENAME_OVERLAY_FORMAT`: `png`, `jpg`, or `webp`
- `SANDBOX_RENAME_OVERLAY_DETAIL`: OpenAI image detail for overlay (`high`, `low`, `auto`)
- `SANDBOX_RENAME_OVERLAY_MIN_DIM`: minimum overlay max-dim during budget fallback
- `SANDBOX_RENAME_CLEAN_QUALITY`: clean image quality
- `SANDBOX_RENAME_CLEAN_MAX_DIM`: clean image max dimension
- `SANDBOX_RENAME_CLEAN_FORMAT`: `png`, `jpg`, or `webp`
- `SANDBOX_RENAME_CLEAN_DETAIL`: OpenAI image detail for clean image (`low` default)
- `SANDBOX_RENAME_PREV_PAGE_DETAIL`: OpenAI image detail for previous-page crop
- `SANDBOX_RENAME_DENSE_FIELD_COUNT`: dense page threshold
- `SANDBOX_RENAME_DENSE_MIN_CENTER_DIST`: dense page spacing threshold
- `SANDBOX_RENAME_DENSE_MAX_DIM`: max dimension for dense pages
- `SANDBOX_RENAME_DENSE_FORMAT`: format override for dense pages
- `SANDBOX_RENAME_PAGE_PROMPT_CHAR_BUDGET`: per-page prompt character budget
- `SANDBOX_RENAME_PAGE_IMAGE_BYTE_BUDGET`: per-page image payload budget
- `SANDBOX_RENAME_BUDGET_CLEAN_MAX_DIM`: tightened clean max dim during fallback
- `SANDBOX_RENAME_BUDGET_CLEAN_QUALITY`: tightened clean quality during fallback
- `SANDBOX_RENAME_BUDGET_CLEAN_FORMAT`: tightened clean format during fallback
- `SANDBOX_RENAME_DB_PROMPT_FULL_THRESHOLD`: schema count threshold for full inclusion (default `1000`)
- `SANDBOX_RENAME_DB_PROMPT_SHORTLIST_LIMIT`: schema shortlist size when threshold is exceeded
- `SANDBOX_RENAME_DB_PROMPT_BUDGET_SHORTLIST_LIMIT`: reduced shortlist size when prompt budget is still exceeded
- `SANDBOX_RENAME_PROMPT_HYGIENE`: toggle duplicate-bullet prompt cleanup
- `SANDBOX_RENAME_PREV_PAGE_FRACTION`: previous-page crop height fraction
- `SANDBOX_RENAME_PREV_PAGE_TOP_FRACTION`: top-of-page trigger threshold
- `OPENAI_REQUEST_TIMEOUT_SECONDS`: OpenAI SDK per-request timeout (default 75)
- `OPENAI_MAX_RETRIES`: OpenAI SDK retry count (default 1)
- `OPENAI_WORKER_MAX_RETRIES`: worker-side OpenAI SDK retries (default 0 to avoid multiplying Cloud Tasks retries)
- `OPENAI_PRICE_INPUT_PER_1M_USD` / `OPENAI_PRICE_OUTPUT_PER_1M_USD`: optional token rates used for per-job USD estimates
- `OPENAI_PRICE_CACHED_INPUT_PER_1M_USD` / `OPENAI_PRICE_REASONING_OUTPUT_PER_1M_USD`: optional subclass rates for cached/reasoning tokens

CommonForms (by [jbarrow](https://github.com/jbarrow/commonforms)) specific:

- `COMMONFORMS_CONFIDENCE_GREEN` / `COMMONFORMS_CONFIDENCE_YELLOW`
