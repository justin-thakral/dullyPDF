"""Blueprint for unit tests of `output_layout.py`.

Required coverage:
- `ensure_output_layout` directory creation
- `temp_prefix_from_pdf` naming format and collision resistance

Edge cases:
- pdf path outside cwd
- fallback stem behavior

Important context:
- Stable artifact naming/layout simplifies debugging and reproducibility.
"""
