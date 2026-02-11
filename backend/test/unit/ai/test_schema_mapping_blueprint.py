"""Blueprint for unit tests of `backend/ai/schema_mapping.py`.

Required coverage:
- `build_allowlist_payload` normalization/truncation/type coercion
- `validate_payload_size` size enforcement
- `_split_template_tags` chunking behavior and errors
- `_merge_schema_mapping_response`
- `_parse_json` fallback extraction
- `call_openai_schema_mapping` and chunked orchestration

Edge cases:
- OpenAI response_format rejection fallback
- missing API key -> explicit configuration error
- malformed model output (non-JSON wrapping)

Important context:
- This module is the schema-only AI mapping gateway (no row data allowed).
"""
