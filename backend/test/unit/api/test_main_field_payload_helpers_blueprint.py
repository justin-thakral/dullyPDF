"""Blueprint for unit tests of field payload geometry/sanitization helpers in `backend/main.py`.

Required coverage:
- rect coercion helpers (`_rect_from_xywh`, `_rect_from_corners`, etc.)
- `TemplateOverlayField` rect validator modes (dict/list)
- `_coerce_field_payloads`
- `_template_fields_to_rename_fields`
- `_estimate_template_page_count`

Edge cases:
- invalid numeric strings
- negative/zero width/height
- mixed payload shapes and missing values

Important context:
- These helpers normalize frontend/editor payloads before rename/materialize flows.
"""
