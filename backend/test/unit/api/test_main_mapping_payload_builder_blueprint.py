"""Blueprint for unit tests of mapping-result sanitization in `backend/main.py`.

Required coverage:
- `_build_schema_mapping_payload` allowlist filtering for:
  - mappings
  - templateRules
  - checkboxRules
  - checkboxHints
  - identifierKey
- confidence coercion/clamping and notes handling
- unmapped field calculations

Edge cases:
- AI response with alternate key names
- non-dict entries and malformed structures
- schema/template hallucinations from model output

Important context:
- This is the critical anti-hallucination guard before returning AI mapping results.
"""
