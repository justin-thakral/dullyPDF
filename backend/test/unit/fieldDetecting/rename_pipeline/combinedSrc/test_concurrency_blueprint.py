"""Blueprint for unit tests of `concurrency.py`.

Required coverage:
- `_int_from_env`
- `resolve_workers`
- `run_threaded_map` order preservation and fallback path

Edge cases:
- invalid env worker values
- single-item and single-worker short-circuit

Important context:
- Deterministic output order is required by downstream overlay/field mapping logic.
"""
