"""Blueprint for unit tests of helper logic in `backend/detector_main.py`.

Required coverage:
- `_allow_unauthenticated` env gating
- `_parse_retry_count`
- `_max_task_attempts` / `_should_finalize_failure`
- `_retry_headers`
- `_require_internal_auth`
- `_finish_detection_failure`

Edge cases:
- prod ignores unauthenticated mode
- missing audience/service account config
- retry finalization boundary (`max_attempts - 1`)

Important context:
- Failure finalization logic controls whether Cloud Tasks retries or marks terminal failure.
"""
