"""Blueprint for unit tests of `backend/firebaseDB/detection_database.py`.

Required coverage:
- `record_detection_request`
- `update_detection_request`

Edge cases:
- required ID validation
- merge semantics on update
- optional `page_count` and `error` handling

Important context:
- Detection operational telemetry and retries depend on these records.
"""
