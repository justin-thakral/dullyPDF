import math

import pytest

from backend.fieldDetecting.rename_pipeline.combinedSrc import coords


def test_normalize_rotation_handles_supported_and_unsupported_values() -> None:
    assert coords.normalize_rotation(450) == 90
    assert coords.normalize_rotation(-90) == 270
    assert coords.normalize_rotation(45) == 0


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_forward_inverse_rotation_are_consistent(rotation: int) -> None:
    page = coords.PageBox(page_width=200.0, page_height=100.0, rotation=rotation)
    x, y = 33.0, 12.5

    rx, ry = coords.rotate_point_forward(x, y, page)
    ux, uy = coords.rotate_point_inverse(rx, ry, page)

    assert ux == pytest.approx(x)
    assert uy == pytest.approx(y)


def test_px_pts_round_trip_conversion() -> None:
    page = coords.PageBox(page_width=200.0, page_height=100.0, rotation=90)

    x_pt, y_pt = 40.0, 20.0
    x_px, y_px = coords.pts_to_px(x_pt, y_pt, image_width_px=400, image_height_px=200, page=page)
    round_x, round_y = coords.px_to_pts(x_px, y_px, image_width_px=400, image_height_px=200, page=page)

    assert round_x == pytest.approx(x_pt)
    assert round_y == pytest.approx(y_pt)


def test_bbox_helpers_order_min_max_after_conversion() -> None:
    page = coords.PageBox(page_width=100.0, page_height=80.0, rotation=180)

    pts_bbox = coords.px_bbox_to_pts_bbox((90, 70, -30, -20), 200, 160, page)
    px_bbox = coords.pts_bbox_to_px_bbox([80.0, 60.0, 20.0, 10.0], 200, 160, page)

    assert pts_bbox[0] <= pts_bbox[2]
    assert pts_bbox[1] <= pts_bbox[3]
    assert px_bbox[0] <= px_bbox[2]
    assert px_bbox[1] <= px_bbox[3]


def test_pts_to_px_degenerate_page_scale_returns_zero() -> None:
    page = coords.PageBox(page_width=0.0, page_height=0.0, rotation=0)

    x_px, y_px = coords.pts_to_px(10.0, 10.0, image_width_px=100, image_height_px=100, page=page)

    assert math.isclose(x_px, 0.0)
    assert math.isclose(y_px, 0.0)
