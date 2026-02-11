"""Blueprint for unit tests of `backend/env_utils.py`.

Required coverage:
- `env_value(name)`:
  - unset -> empty string
  - trims leading/trailing spaces
- `env_truthy(name)`:
  - accepts 1/true/yes (case-insensitive)
  - rejects empty/0/false/no
- `int_env(name, default)`:
  - unset -> default
  - valid int -> parsed int
  - invalid int -> default

Important context:
- These helpers drive environment behavior across nearly all backend modules.
"""
