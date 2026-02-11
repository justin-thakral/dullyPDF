"""Blueprint for unit tests of `backend/fieldDetecting/rename_pipeline/debug_flags.py`.

Required coverage:
- debug flag detection and argv mutation
- debug password resolution precedence
- `debug_enabled` gating by ENV and force flag

Edge cases:
- prod always disables debug mode
- force flag requires password presence

Important context:
- Import-time argv mutation can affect tests; isolate imports and reset sys.argv.
"""
