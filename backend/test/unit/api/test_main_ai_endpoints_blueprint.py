"""Blueprint for route-level unit tests of AI endpoints in `backend/main.py`.

Endpoints to cover (with patched dependencies):
- `POST /api/renames/ai`
- `POST /api/schema-mappings/ai`

Required scenarios:
- missing/invalid session/schema/template validation
- rate-limit denial paths
- credit charge amounts (rename=1, rename+schema=2, mapping=1)
- credit refund on downstream OpenAI failure
- session persistence of renames, checkboxRules, checkboxHints
- mapping payload sanitization pass-through to response envelope

Edge cases:
- empty templateFields and no session fallback fields
- schema ownership mismatch
- OpenAI error with custom status_code attribute

Important context:
- These routes enforce billing-like credits and must be safe against model hallucinations.
"""
