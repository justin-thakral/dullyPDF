# Rename flow (overlay + OpenAI)

The rename flow exists to solve a common failure mode: fields are detected correctly, but names are missing or low-quality because labels are noisy or ambiguous.

Instead of trying to infer names purely from the candidate JSON, we render a full-page overlay with field names and ask the model to propose better names.

## When to use it

- You have good candidate geometry (lines, checkboxes, boxes) but field naming is poor.
- You want to rename known fields without re-detecting geometry.

## Inputs and outputs

Inputs:
- One page image per page (rendered at `SANDBOX_DPI`).
- Per-page candidate list (for overlay context).
- Per-page field list (from the heuristic resolver).

Outputs:
- A `renames` array keyed by the on-overlay field name:
  - `originalFieldName`
  - `suggestedRename`
  - `renameConfidence`
  - `isItAfieldConfidence`

The OpenAI response is line-based to avoid JSON parsing failures:
`|| originalFieldName | suggestedRename | renameConfidence | isItAfieldConfidence`

Files:
- `backend/fieldDetecting/sandbox/combinedSrc/field_overlay.py`: renders the overlay image and prints the field name above each field.
- `backend/fieldDetecting/sandbox/combinedSrc/rename_resolver.py`: calls OpenAI and applies renames to fields.

## Confidence gating

- `renameConfidence` measures how confident the model is in the proposed name.
- `isItAfieldConfidence` measures how confident the model is that the overlay item is a real field.
- Fields with `isItAfieldConfidence < SANDBOX_RENAME_MIN_FIELD_CONF` are dropped.

## Overlay naming

Field labels on each overlay are made unique per page. If the base name repeats, suffixes
are appended (`name`, `name_1`, `name_2`, ...). This lets OpenAI disambiguate duplicates.

## Prompt behavior

The prompt explicitly instructs the model to reject:
- boxes sitting on paragraph text
- page-break lines or section separators
- checkboxes that appear inside paragraphs or without aligned option text
- double-checkbox overlaps (keep the best, drop the duplicate)

Per-field metadata (label distance + size ratios) is included to reinforce these rules.

## Running it

Via CLI:

```bash
python3 -m backend.fieldDetecting.sandbox.debug.test_local path/to/sample.pdf --openAI
```

Artifacts:
- Overlays: `backend/fieldDetecting/outputArtifacts/overlays/temp<first5><last5>_openai/page_<n>.png`
- Renames: `backend/fieldDetecting/outputArtifacts/json/temp<first5><last5>_renames.json`
- Fields with names applied: `backend/fieldDetecting/outputArtifacts/json/temp<first5><last5>_fields_renamed.json`

`temp<first5><last5>` is derived from the first five and last five characters of the PDF filename stem.
