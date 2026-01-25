# Pipeline Improvement Guide (Rename -> Remap -> Search & Fill)

This document teaches Codex how to run a controlled pipeline experiment focused on maximizing Search & Fill accuracy.
It is a plan and guide only; do not execute the pipeline unless explicitly asked.

## Scope

- Environment: dev by default.
- Pipeline: CommonForms (by jbarrow) detection -> OpenAI rename -> OpenAI schema mapping -> Search & Fill.
- Data: local PDFs + synthetic/mock schema data only.
- Excludes: legacy OpenCV pipeline in `legacy/fieldDetecting/`.

## Prerequisites

- Backend + frontend running (`npm run dev` or `npm run dev:stack`).
- OpenAI key available for rename/mapping.
- Firebase auth working (MCP login or UI login).
- MCP configured per `mcp/README.md` (optional but recommended for repeatable API + UI runs).

## Safety rails

- Use dev resources; keep prod read-only unless explicitly told otherwise.
- Use synthetic/mock database data only.
- Do not log tokens, credentials, or real user data.

## Baseline test assets

Primary PDF candidate (non-AcroForm, CommonForms-friendly):
- `samples/fieldDetecting/pdfs/native/consent/base_form.pdf`

Fallbacks if detection results are too sparse or noisy:
- `samples/fieldDetecting/pdfs/native/intake/patient-Intake-pdf.pdf`
- `samples/fieldDetecting/pdfs/native/consent/template_test_form.pdf`

Tip: confirm the PDF is not an AcroForm by checking `Form: none` via `pdfinfo`.

## PDF selection and rotation

Goal: test many different PDFs, but only optimize on one at a time. After a PDF is optimized, retire it so it is not reused for the next cycle.

Selection rules:
- Prefer non-AcroForm PDFs with visible, well-labeled form fields.
- Avoid extremely low-resolution scans unless the goal is scan robustness.
- Keep page count reasonable (1-4 pages) for faster iteration.

Process:
1) Choose a candidate PDF and run the baseline pipeline.
2) Optimize the pipeline for that PDF until Search & Fill is maximized.
3) Move the PDF into the “retired” list below so it is not used again for optimization.
4) Pick a new candidate and repeat.

Retired PDFs (do not use for new optimization runs):
- _None yet_

## Plan of record (high-level)

1) Establish a reproducible baseline run and capture artifacts.
2) Build a mock schema file designed to stress the remapper.
3) Measure rename, mapping, and Search & Fill accuracy.
4) Iterate on detection, rename, and mapping parameters with one change per run.
5) Track deltas until Search & Fill percent is maximized.

## Plan-first workflow (no instant changes)

Before changing any settings, prompts, or code, produce a written plan that lists:
- The top issues discovered in the current run (ordered by impact).
- The likely cause of each issue.
- Proposed fixes or experiments for each issue.
- The expected metric impact (rename, mapping, fill) if the fix works.

Only apply changes after the plan is reviewed and agreed to.

## Evidence and logging

- Store artifacts per run in `mcp/debugging/pipeline-improve/YYYYMMDD/`.
- Capture:
  - Detection output (fields JSON + sessionId).
  - Rename report + renamed fields.
  - Mapping output + checkbox rules (if any).
  - UI screenshots for detection, mapping, and filled results.

Create a run log file per experiment:
- `mcp/debugging/pipeline-improve/YYYYMMDD/run-<short-label>.md`

## Standard pipeline run (baseline)

Use either API or UI. For first pass, prefer the UI to validate end-to-end behavior.

### 1) Detection (CommonForms)

UI path:
1. Upload the PDF and run detection.
2. Wait for the fields list to populate.
3. Export or record the detected fields list (count + sample names).

API path:
- `POST /detect-fields` with `pipeline=commonforms`.
- Poll `GET /detect-fields/{sessionId}` until ready.

Capture:
- `sessionId`
- Total fields detected
- Any obvious misses or false positives

### 2) OpenAI rename

UI path:
1. Trigger OpenAI rename from the UI (confirm OpenAI prompt).
2. Save the rename report and renamed fields.

API path:
- `POST /api/renames/ai` with `{ "sessionId": "..." }`.

Capture:
- `renameConfidence` and `isItAfieldConfidence` summaries
- Renamed fields JSON
- Overlay artifacts in `backend/fieldDetecting/outputArtifacts/`

### 3) Build the mock schema database

Goal: force the remapper to do real work. Every renamed field should have a corresponding schema column,
but the column name should not be an exact match.

Rules for mock headers:
- Use synonyms or alternate phrasing (e.g., `first_name` -> `given_name`).
- Use abbreviations or domain slang (`date_of_birth` -> `dob`, `policy_number` -> `policy_id`).
- Change word order or add qualifiers (`employer_name` -> `current_employer`).
- Introduce a few noise columns not present on the PDF.

Data rules:
- Include a unique record identifier for Search (e.g., `record_id`).
- Provide 2-3 rows with realistic values for every field.
- For checkbox fields, use explicit checkbox columns or enum values to trigger group rules.

Save the mock DB under:
- `mcp/debugging/pipeline-improve/YYYYMMDD/mock-db.csv`

Also create a mapping reference table to score accuracy:
- `mcp/debugging/pipeline-improve/YYYYMMDD/expected-mapping.csv`

### 4) OpenAI remap (schema mapping)

UI path:
1. Upload/select the mock DB file.
2. Run “Map DB” and wait for success.

API path:
- `POST /api/schema-mappings/ai` with schema headers + template tags (or use combined rename+map).

Capture:
- Mapping results (per field -> schema column).
- Checkbox rules output (if any).

### 5) Search & Fill validation

1. Open “Search, Fill & Clear”.
2. Search for a known record ID.
3. Fill and verify that values appear in the overlay.

Capture:
- Screenshot of filled fields.
- List of fields that failed to fill or filled incorrectly.

## Metrics and scoring

Use the same definitions for every run:

- Detection coverage:
  - `detected_fields / expected_fields` (manual count from the PDF layout)
- Rename accuracy:
  - `correct_renames / total_fields` (manual review for baseline)
- Mapping accuracy:
  - `correct_mappings / mapped_fields` (compare to expected-mapping.csv)
- Fill success:
  - `correct_filled_fields / target_fields`

Overall pipeline score (simple baseline):
- `fill_success * mapping_accuracy` (primary metric)

## Optimization loop (after baseline)

Make one change per run so deltas are attributable. Examples:

Detection:
- Adjust `COMMONFORMS_CONFIDENCE`, `COMMONFORMS_IMAGE_SIZE`, or `COMMONFORMS_MULTILINE`.
- Swap PDFs if scan quality is the limiting factor.

Rename:
- Adjust `SANDBOX_RENAME_MIN_FIELD_CONF`, overlay quality, or dense-page settings.
- Verify overlays are legible; poor overlays reduce rename accuracy.

Mapping:
- Refine mock schema headers to test edge cases (synonyms, abbreviations, word order).
- Use combined rename+map only after standalone mapping results are understood.

Search & Fill:
- Ensure checkbox columns use `i_`/`checkbox_` prefixes when required.
- Verify date/phone formatting matches UI expectations.

## Run log template

```
# Pipeline improvement run: <short label>

## Context
- Date:
- Environment: dev
- PDF:
- Mock DB:
- Notes:

## Results
- Detection coverage:
- Rename accuracy:
- Mapping accuracy:
- Fill success:

## Failures
- Detection:
- Rename:
- Mapping:
- Fill:

## Evidence
- Overlays:
- Rename report:
- Mapping output:
- Screenshots:

## Next change
- <single change to test next>
```

## Stop conditions

Stop and ask for guidance if:
- Detection returns zero fields or repeated 5xx errors.
- OpenAI credits are exhausted or OpenAI calls fail repeatedly.
- Any step requires using prod resources or real data.
