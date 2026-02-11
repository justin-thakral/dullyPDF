"""Blueprint for unit tests of `form_filler.py`.

Required coverage:
- rect and field-kind normalization helpers
- existing widget dedupe/reset helpers
- checkbox value application
- text appearance generation/update
- `inject_fields_from_template` and `inject_fields` high-level flow

Edge cases:
- duplicate widgets by near-equal geometry
- unsupported/partial field payloads
- missing AcroForm

Important context:
- This module powers `/api/forms/materialize` and fillable output correctness.
"""
