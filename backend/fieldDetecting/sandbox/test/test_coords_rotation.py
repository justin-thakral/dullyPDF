import pytest

from backend.fieldDetecting.sandbox.combinedSrc.coords import (
    PageBox,
    px_to_pts,
    pts_to_px,
    rotate_point_forward,
    rotate_point_inverse,
)


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_rotate_point_round_trip(rotation: int):
    page = PageBox(page_width=612.0, page_height=792.0, rotation=rotation)
    points = [
        (0.0, 0.0),
        (10.0, 20.0),
        (200.0, 400.0),
        (611.0, 791.0),
    ]
    for x, y in points:
        rx, ry = rotate_point_forward(x, y, page)
        x2, y2 = rotate_point_inverse(rx, ry, page)
        assert pytest.approx(x2, abs=1e-6) == x
        assert pytest.approx(y2, abs=1e-6) == y


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_px_pts_round_trip(rotation: int):
    # Use a synthetic image that exactly matches rotated page dims at 10 px/pt.
    page = PageBox(page_width=612.0, page_height=792.0, rotation=rotation)
    image_w = int(round(page.rotated_width * 10))
    image_h = int(round(page.rotated_height * 10))
    pixels = [
        (0, 0),
        (100, 200),
        (image_w - 1, image_h - 1),
    ]
    for px, py in pixels:
        x_pt, y_pt = px_to_pts(px, py, image_w, image_h, page)
        px2, py2 = pts_to_px(x_pt, y_pt, image_w, image_h, page)
        assert pytest.approx(px2, abs=1e-3) == px
        assert pytest.approx(py2, abs=1e-3) == py
