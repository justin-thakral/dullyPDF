"""Blueprint for unit tests of `backend/fieldDetecting/logs/cleanOutput.py`.

Required coverage:
- CLI arg parsing and path selection
- dry-run mode behavior
- full cleanup mode behavior

Edge cases:
- missing directories/files
- partial cleanup failures and exit codes

Important context:
- Cleanup tooling keeps local artifacts manageable during detector debugging.
"""
