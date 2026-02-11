"""Blueprint for unit tests of `backend/firebaseDB/storage_service.py`.

Required coverage:
- bucket config guards
- object-path safety validators
- gs:// URI parsing and allowlist checks
- upload/download/stream/delete helper behavior

Edge cases:
- unsafe object paths (absolute, traversal, CRLF, backslash, too long)
- non-allowlisted bucket URIs
- stream fallback from blob.open to in-memory bytes

Important context:
- This is the only storage boundary for PDFs and session artifacts.
"""
