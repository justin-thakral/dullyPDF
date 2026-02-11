"""Blueprint for unit tests of `vision_utils.py`.

Required coverage:
- `image_bgr_to_data_url` output format and non-empty encoding

Edge cases:
- invalid or empty image arrays

Important context:
- Data URL conversion is used when embedding image context in prompt payloads.
"""
