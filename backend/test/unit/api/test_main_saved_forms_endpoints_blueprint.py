"""Blueprint for route-level unit tests of saved-form endpoints in `backend/main.py`.

Endpoints to cover (with patched dependencies):
- `GET /api/saved-forms`
- `GET /api/saved-forms/{form_id}`
- `GET /api/saved-forms/{form_id}/download`
- `POST /api/saved-forms/{form_id}/session`
- `POST /api/saved-forms`
- `DELETE /api/saved-forms/{form_id}`

Required scenarios:
- ownership and not-found checks
- saved-form limit enforcement for base/god tiers
- overwrite path (`overwriteFormId`) updates existing form
- upload -> storage -> DB consistency behavior
- metadata merging for checkboxRules/checkboxHints and originalSessionId
- cleanup of uploaded blobs when DB persistence fails

Edge cases:
- form/template bucket path mismatch or missing gs:// path
- delete failures on one of multiple storage objects

Important context:
- This route family manages user-persisted PDFs and is security-sensitive.
"""
