"""Blueprint for unit tests of `backend/scripts/verify_session_owner.py`.

Required coverage:
- `_expect_forbidden` and `_expect_allowed` helper behavior
- `main()` success/failure exit code behavior based on composed checks

Edge cases:
- unexpected exception branches in helper wrappers

Important context:
- This script validates session ownership guard assumptions used in production paths.
"""
