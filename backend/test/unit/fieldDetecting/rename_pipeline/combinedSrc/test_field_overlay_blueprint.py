"""Blueprint for unit tests of `field_overlay.py`.

Required coverage:
- coordinate conversion to pixel corners
- checkbox label selection logic
- text-fit helper behavior
- `draw_overlay` for normal and empty inputs

Edge cases:
- off-page rectangles
- tiny draw regions

Important context:
- Overlay rendering is used to provide context tags for rename prompting.
"""
