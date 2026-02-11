"""Blueprint for route-level unit tests of detector endpoint in `backend/detector_main.py`.

Endpoint to cover (with patched dependencies):
- `POST /internal/detect`

Required scenarios:
- auth success/failure paths
- pipeline and pdfPath validation
- missing metadata and pdf_path mismatch handling
- successful detection updates session metadata and logs
- PdfValidationError finalization to failed status payload
- unexpected exception:
  - retries (500 with retry headers)
  - terminal failure when max attempts reached

Edge cases:
- decrypted PDF info path
- task retry header missing/invalid values

Important context:
- This endpoint executes async detector jobs and drives task retry semantics.
"""
