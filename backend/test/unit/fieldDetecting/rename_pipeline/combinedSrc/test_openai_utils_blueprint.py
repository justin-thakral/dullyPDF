"""Blueprint for unit tests of `openai_utils.py`.

Required coverage:
- `_error_text`
- `_is_temperature_unsupported`
- `responses_create_with_temperature_fallback`
- `extract_response_text`

Edge cases:
- heterogeneous SDK error shapes
- partial response content arrays

Important context:
- This utility prevents model compatibility issues from breaking rename flows.
"""
