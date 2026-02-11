"""Blueprint for unit tests of `render_pdf.py`.

Required coverage:
- single-page and multi-page render paths
- worker-based render path order guarantees
- metadata fields (`page_index`, `scale`, page/image dimensions)

Edge cases:
- grayscale and RGBA conversion paths
- low/high DPI behavior

Important context:
- Rendered page metadata is consumed by label extraction and rename resolver.
"""
