"""Blueprint for unit tests of `backend/firebaseDB/role_cli.py` CLI behavior.

Required coverage:
- argument validation (`--email` or `--uid` required)
- role normalization and custom claim update
- Firestore role update payload
- optional rename-count reset path

Edge cases:
- invalid input combinations
- missing Firebase user lookup

Important context:
- This script is operational tooling for account-role management.
"""
