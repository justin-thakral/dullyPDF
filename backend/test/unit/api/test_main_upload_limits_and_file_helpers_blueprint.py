"""Blueprint for unit tests of upload/file helper functions in `backend/main.py`.

Required coverage:
- `_resolve_upload_limit`
- `_read_upload_bytes`
- `_write_upload_to_temp`
- `_parse_json_list_form_field`
- filename helpers:
  - `_sanitize_basename_segment`
  - `_safe_pdf_download_filename`
  - `_log_pdf_label`

Edge cases:
- over-limit uploads return 413 and cleanup temp artifacts
- invalid JSON payloads map to 400
- path traversal and CRLF in filenames

Important context:
- Upload handling is shared by detect, materialize, template session, and saved forms routes.
"""
