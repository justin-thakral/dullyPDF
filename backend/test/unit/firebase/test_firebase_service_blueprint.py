"""Blueprint for unit tests of `backend/firebaseDB/firebase_service.py`.

Required coverage:
- credential loading from JSON string and file path
- revocation-check mode selection
- init caching (`_firebase_app`, `_firebase_init_error`)
- Firestore/storage client getters
- `verify_id_token` parsing + exception handling

Edge cases:
- invalid credential JSON
- missing Authorization token formats
- clock skew env parsing

Important context:
- All authenticated API routes depend on this auth/bootstrap layer.
"""
