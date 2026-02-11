"""Blueprint for unit tests of `coords.py` conversion math.

Required coverage:
- rotation normalization
- forward/inverse rotation pair behavior
- px<->pts point conversion
- bbox conversion helpers with min/max ordering

Edge cases:
- unsupported rotations
- degenerate scale factors

Important context:
- Geometric correctness is fundamental for accurate overlay and field placement.
"""
