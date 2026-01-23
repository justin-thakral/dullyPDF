# Rename flow (overlay + OpenAI)

This rename flow is part of the **main pipeline** (CommonForms detection + OpenAI rename).
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
- Per-page candidate list (CommonForms widgets + extracted labels).
- Per-page field list (from the CommonForms detector).

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
- Optional checkbox rules for Search & Fill when schema headers are provided (`checkboxRules`).

API response note:
- `POST /detect-fields` queues detection and returns a `sessionId`.
- `GET /detect-fields/{sessionId}` returns the baseline `fields` array once ready.
- `POST /api/renames/ai` returns renamed `fields`, the rename report, optional `checkboxRules`, and the same `sessionId`.
- The original name is preserved in `originalName` so the UI can reconcile edits.
- Template overlay `rect` values may be sent as `{x,y,width,height}` or `[x1,y1,x2,y2]` (originTop points). The backend normalizes to `{x,y,width,height}` before OpenAI calls.

The OpenAI response is line-based to avoid JSON parsing failures:
`|| originalFieldName | suggestedRename | renameConfidence | isItAfieldConfidence`

When schema headers are provided, the response includes a trailing JSON block:
`BEGIN_CHECKBOX_RULES_JSON ... END_CHECKBOX_RULES_JSON`

Files:
- `backend/fieldDetecting/rename_pipeline/combinedSrc/field_overlay.py`: renders the overlay image with field IDs centered inside field boxes and centered on checkbox squares.
- `backend/fieldDetecting/rename_pipeline/combinedSrc/rename_resolver.py`: calls OpenAI and applies renames to fields.
- `backend/fieldDetecting/rename_pipeline/combinedSrc/openai_utils.py`: retries the Responses API when a model rejects `temperature`.
- `backend/ai/rename_pipeline.py`: orchestration used by `/api/renames/ai` (render + labels + rename).

## Confidence gating

- `renameConfidence` measures how confident the model is in the proposed name.
- `isItAfieldConfidence` measures how confident the model is that the overlay item is a real field.
- Fields with `isItAfieldConfidence < SANDBOX_RENAME_MIN_FIELD_CONF` are kept, but their names
  remain unchanged (`renameConfidence = 0`). The response still records them in `dropped` for
  visibility.

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

- `SANDBOX_RENAME_MODEL`: model name (default is `gpt-5.2`)
- `SANDBOX_RENAME_MAX_OUTPUT_TOKENS`: cap output tokens per page
- `SANDBOX_RENAME_MIN_FIELD_CONF`: drop threshold for `isItAfieldConfidence`
- `SANDBOX_RENAME_OVERLAY_QUALITY`: overlay image quality (default 92, 96 for commonforms)
- `SANDBOX_RENAME_OVERLAY_MAX_DIM`: max dimension for overlay scaling (default 6000)
- `SANDBOX_RENAME_OVERLAY_FORMAT`: `png` or `jpeg`
- `SANDBOX_RENAME_DENSE_FIELD_COUNT`: dense page threshold
- `SANDBOX_RENAME_DENSE_MIN_CENTER_DIST`: dense page spacing threshold
- `SANDBOX_RENAME_DENSE_MAX_DIM`: max dimension for dense pages
- `SANDBOX_RENAME_DENSE_FORMAT`: format override for dense pages
- `SANDBOX_RENAME_PREV_PAGE_FRACTION`: previous-page crop height fraction
- `SANDBOX_RENAME_PREV_PAGE_TOP_FRACTION`: top-of-page trigger threshold

CommonForms-specific:

- `COMMONFORMS_CONFIDENCE_GREEN` / `COMMONFORMS_CONFIDENCE_YELLOW`
