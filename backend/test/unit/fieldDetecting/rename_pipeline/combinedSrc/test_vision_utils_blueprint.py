import base64

import numpy as np
import pytest

from backend.fieldDetecting.rename_pipeline.combinedSrc import vision_utils


def test_image_bgr_to_data_url_encodes_non_empty_payload() -> None:
    image = np.full((8, 8, 3), 127, dtype=np.uint8)

    data_url = vision_utils.image_bgr_to_data_url(image, format="jpg", quality=80)

    assert data_url.startswith("data:image/jpeg;base64,")
    payload = data_url.split(",", 1)[1]
    decoded = base64.b64decode(payload)
    assert len(decoded) > 0


@pytest.mark.parametrize(
    "image",
    [
        np.array([], dtype=np.uint8),
        np.zeros((0, 0, 3), dtype=np.uint8),
    ],
)
def test_image_bgr_to_data_url_rejects_invalid_or_empty_images(image: np.ndarray) -> None:
    with pytest.raises(Exception):
        vision_utils.image_bgr_to_data_url(image)


# ---------------------------------------------------------------------------
# Edge-case tests added below
# ---------------------------------------------------------------------------


def test_image_bgr_to_data_url_raises_when_imencode_returns_false(mocker) -> None:
    """When cv2.imencode returns ok=False (e.g. unsupported format or corrupt
    data), image_bgr_to_data_url should raise a RuntimeError with a
    descriptive message rather than proceeding with invalid data."""
    # Patch cv2.imencode to simulate an encoding failure.
    mocker.patch.object(
        vision_utils.cv2,
        "imencode",
        return_value=(False, None),
    )
    image = np.full((8, 8, 3), 127, dtype=np.uint8)
    with pytest.raises(RuntimeError, match="Failed to encode image"):
        vision_utils.image_bgr_to_data_url(image, format="bmp")


def test_image_bgr_to_data_url_with_dot_prefix_format() -> None:
    """The format parameter should be normalized via lstrip('.') so that
    passing '.jpg' works the same as 'jpg'.  This exercises the lstrip
    behavior on line 22 of vision_utils.py."""
    image = np.full((8, 8, 3), 200, dtype=np.uint8)

    data_url = vision_utils.image_bgr_to_data_url(image, format=".jpg", quality=75)

    # The result should use the jpeg MIME type, confirming the dot was stripped.
    assert data_url.startswith("data:image/jpeg;base64,")
    payload = data_url.split(",", 1)[1]
    decoded = base64.b64decode(payload)
    assert len(decoded) > 0
