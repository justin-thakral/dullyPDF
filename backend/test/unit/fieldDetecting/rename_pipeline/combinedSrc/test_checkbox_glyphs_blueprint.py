"""Blueprint for unit tests of `checkbox_glyphs.py`.

Required coverage:
- `_font_looks_symbol`
- `_is_private_use`
- `is_checkbox_glyph`

Edge cases:
- empty text/font values
- private-use unicode ranges

Important context:
- Glyph classification reduces false checkbox-label artifacts during rename prep.
"""
