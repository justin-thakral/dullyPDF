# Checkbox Rules System

This document explains exactly how checkbox rules are generated, validated, persisted, and executed during Search & Fill.

## Why this exists

Simple direct matching works when a row key already equals a checkbox field name, but many forms model checkboxes as grouped options:

- `i_smoker_yes` / `i_smoker_no`
- `i_allergies_penicillin` / `i_allergies_shellfish`
- `i_marital_status_single` / `i_marital_status_married`

`checkboxRules` and `checkboxHints` provide structured metadata that maps row values to those groups.

## Data model

### `checkboxRules`

- `databaseField`: schema field name used as input
- `groupKey`: checkbox group identifier in the template
- `operation`: `yes_no | enum | list | presence`
- optional `trueOption`
- optional `falseOption`
- optional `valueMap`
- optional `confidence`
- optional `reasoning`

### `checkboxHints`

- `databaseField`
- `groupKey`
- optional `operation`
- optional `directBooleanPossible`

Hints are fallback metadata. Rules are higher-priority.

## Rule generation paths

Rules can be produced by two OpenAI flows.

1. Rename+schema flow: `POST /api/renames/ai` with `schemaId`
2. Mapping flow: `POST /api/schema-mappings/ai`

### Rename flow rule generation

File: `backend/fieldDetecting/rename_pipeline/combinedSrc/rename_resolver.py`

1. The prompt requests line-based renames plus a trailing checkbox JSON block.
2. JSON is parsed only between:
   - `BEGIN_CHECKBOX_RULES_JSON`
   - `END_CHECKBOX_RULES_JSON`
3. Every candidate rule is normalized and allowlisted:
   - `databaseField` must exist in the selected schema allowlist.
   - `groupKey` must exist in detected checkbox groups from renamed fields.
   - `operation` must be one of `yes_no|enum|list|presence`.
4. Duplicate rules are deduped by `(databaseField, groupKey, operation)` and the highest-confidence rule is kept.

Important detail:
- Rename can also infer checkbox field naming (`groupKey`, `optionKey`) even when no schema is provided, but `checkboxRules` are only retained when they pass schema and group allowlists.

### Mapping flow rule and hint generation

Files:
- `backend/ai/schema_mapping.py`
- `backend/services/mapping_service.py`

1. Backend builds an allowlist payload (`schemaFields` + `templateTags` only).
2. Payload is byte-capped (`OPENAI_SCHEMA_MAX_PAYLOAD_BYTES`, default 80k).
3. If too large, template tags are chunked across multiple requests while schema fields are repeated per chunk.
4. Returned `checkboxRules` and `checkboxHints` are normalized and filtered:
   - schema field must resolve to an allowed schema field
   - group key must resolve to an allowed template checkbox group
   - hint `operation` is constrained to supported values

## Persistence behavior

### Session persistence (L1/L2)

Files:
- `backend/api/routes/ai.py`
- `backend/sessions/session_store.py`
- `backend/sessions/l2_persistence.py`

- Rename writes `checkboxRules` and intentionally clears `checkboxHints`.
- Mapping writes both arrays.
- Mapping persists explicit arrays (including `[]`) so reruns can clear stale metadata.
- Session artifacts are stored as:
  - `sessions/<session_id>/checkbox-rules.json`
  - `sessions/<session_id>/checkbox-hints.json`

### Saved form persistence

Files:
- `backend/api/routes/saved_forms.py`
- `frontend/src/hooks/useSaveDownload.ts`

- Saved form payloads include `checkboxRules` and `checkboxHints`.
- Empty arrays are sent as real clears (`[]`), not omitted.
- If omitted and a `sessionId` exists, backend can fallback to session metadata.

## Runtime application order in Search & Fill

File: `frontend/src/components/features/SearchFillModal.tsx`

Checkbox application runs in strict precedence with guard sets to prevent lower-priority overrides.

1. Direct checkbox field-name boolean match.
   - Row key exactly matches a checkbox field name.
2. Direct checkbox option match.
   - Row key matches `{groupKey}_{optionKey}` (with alias normalization).
3. Direct group value match.
   - Keys like `i_<group>`, `checkbox_<group>`, or `<group>`.
4. Rule-driven application (`checkboxRules`).
5. Hint-driven boolean fallback (`checkboxHints` with `directBooleanPossible=true`).
6. Hardcoded alias fallback (`CHECKBOX_ALIASES`).

Conflict controls:
- `explicitGroupKeys` blocks lower-priority writes to already explicit groups.
- `groupValueApplied` blocks repeated or fallback writes once a group was resolved.
- ambiguous option-key collisions are detected and skipped.

### Exact rule-evaluation behavior

For each `checkboxRule`, runtime resolves a row value by `databaseField` (with normalized key fallbacks), then:

1. Normalizes `groupKey` and finds all checkbox template fields in that group.
2. Applies `operation`-specific coercion (`yes_no`, `enum`, `list`, `presence`).
3. Resolves target option(s) using `valueMap` first, then option-key aliases, then safe fallback logic.
4. Marks the group as resolved (`groupValueApplied`) so lower-precedence paths cannot overwrite it.
5. Skips ambiguous mappings (for example, multiple candidate options with the same normalized alias).

This means rule ordering matters only by precedence stage, not by per-rule confidence score.

## Operation semantics

### `yes_no`

Input handling:
- Coerces row value with presence-aware boolean parsing.
- Prefers `trueOption` / `falseOption` when present.
- If no explicit options apply, falls back to group boolean resolution (`yes`/`no` alias discovery, then first-option fallback for truthy values).

### `presence`

Input handling:
- Also uses presence-aware coercion.
- If truthy, resolves the group as checked (using option discovery/valueMap).
- If falsey and no explicit `falseOption` mapping is available, it does not force an alternate option.

### `enum`

Input handling:
- Treats the value as a single-choice category.
- Tries mapped option via `valueMap` and option aliases.
- Stops at first valid option selection.

### `list`

Input handling:
- Splits values on `, ; | /` (or accepts arrays directly).
- Attempts multi-select within a group.
- Uses `valueMap` and alias normalization per token.

### `valueMap` normalization

`valueMap` keys are normalized for:
- case
- spacing/hyphens
- punctuation stripping
- compact key forms (underscores removed)

This allows values like `Not Applicable`, `not_applicable`, and `not-applicable` to map consistently.

## Row lookup rules for `databaseField`

When executing rules/hints, Search & Fill resolves row values using normalized keys with fallbacks:

- exact key
- `patient_<key>`
- `responsible_party_<key>`
- inverse fallback when incoming key already has those prefixes

This avoids brittle failures when schema headers include section prefixes.

## Confidence semantics for rules

- `checkboxRules[].confidence` is informational metadata; it is not currently used as a runtime gate in Search & Fill.
- Runtime precedence is driven by operation order and group blocking, not by rule confidence sorting at fill time.
- In rename flow, duplicate rule variants are deduped by highest confidence before returning to the UI.

## Confidence categories and thresholds

Checkbox rule confidence and rename confidence are separate signals:

- `checkboxRules[].confidence`:
  - Optional rule metadata from model output.
  - Used only for dedupe tie-breaks in rename (`highest confidence wins` for same `(databaseField, groupKey, operation)`).
  - Not used as a fill-time threshold.

- `isItAfieldConfidence` / `renameConfidence` (from rename lines):
  - Drive field drop behavior and naming confidence on returned fields.
  - Default field drop threshold is `SANDBOX_RENAME_MIN_FIELD_CONF=0.30`.

- Category tiers used across backend/frontend:
  - High / green: `>= 0.60`
  - Medium / yellow: `>= 0.30 and < 0.60`
  - Low / red: `< 0.30`
  - Backend CommonForms thresholds can be overridden with `COMMONFORMS_CONFIDENCE_GREEN` and `COMMONFORMS_CONFIDENCE_YELLOW`.

## Practical debugging checklist

If a checkbox group is not filling as expected:

1. Confirm `groupKey`/`optionKey` exist on checkbox fields in the active session.
2. Confirm `databaseField` appears in normalized row keys (including patient/responsible_party variants).
3. Confirm rule `operation` matches source data shape (`yes_no`, `enum`, `list`, `presence`).
4. Confirm `valueMap` uses normalized values that match incoming row content.
5. Check whether an earlier explicit/direct mapping already claimed that group.
