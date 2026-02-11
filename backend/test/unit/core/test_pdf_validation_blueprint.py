"""Blueprint for unit tests of `backend/pdf_validation.py`.

Required coverage:
- empty bytes -> `PdfValidationError`
- corrupted bytes -> `PdfValidationError`
- valid PDF returns `PdfValidationResult` with page_count >= 1
- encrypted PDF handling:
  - reject when cannot decrypt and `allow_encrypted=False`
  - decrypt with empty password when allowed
  - pass through when `allow_encrypted=True`

Edge cases:
- metadata read errors during rewrite should not break flow
- page-count extraction exceptions should map to readable validation errors

Important context:
- Detection and template session endpoints rely on this guard before pipeline execution.
"""
