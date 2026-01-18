"""
Coordinate conversion helpers between PDF points and rendered image pixels.

All conversions assume originTop coordinates and account for per-page rotation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Tuple

from .config import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class PageBox:
    """
    Geometry reference for mapping between rendered image pixels and PDF points.

    Coordinate conventions:
    - All point coordinates are in PDF points (1/72 inch) with originTop.
    - page_width/page_height refer to the unrotated CropBox size in points.
    - rotation is the page rotation in degrees clockwise (0/90/180/270).
    """

    page_width: float
    page_height: float
    rotation: int

    @property
    def rotated_width(self) -> float:
        return self.page_width if self.rotation in (0, 180) else self.page_height

    @property
    def rotated_height(self) -> float:
        return self.page_height if self.rotation in (0, 180) else self.page_width


def normalize_rotation(rotation: int) -> int:
    """
    Normalize a rotation value to 0/90/180/270, defaulting to 0 for unknown values.
    """
    rot = int(rotation) % 360
    if rot not in (0, 90, 180, 270):
        logger.warning("Unsupported rotation %s; treating as 0", rotation)
        return 0
    return rot


def get_scale_factors(
    image_width_px: int, image_height_px: int, page: PageBox
) -> Tuple[float, float]:
    """
    Return (sx, sy) where sx/sy are points-per-pixel in the rendered image axes.
    """
    sx = page.rotated_width / float(image_width_px)
    sy = page.rotated_height / float(image_height_px)
    return sx, sy


def rotate_point_forward(x: float, y: float, page: PageBox) -> Tuple[float, float]:
    """
    Map a point from unrotated (CropBox) coordinates to rotated display coordinates.

    Rotation is clockwise and the origin is top-left in both systems.
    """
    rot = normalize_rotation(page.rotation)
    W, H = page.page_width, page.page_height
    if rot == 0:
        return x, y
    if rot == 90:
        # r.x = H - u.y, r.y = u.x
        return H - y, x
    if rot == 180:
        return W - x, H - y
    # rot == 270
    return y, W - x


def rotate_point_inverse(x: float, y: float, page: PageBox) -> Tuple[float, float]:
    """
    Map a point from rotated display coordinates back to unrotated (CropBox) coordinates.
    """
    rot = normalize_rotation(page.rotation)
    W, H = page.page_width, page.page_height
    if rot == 0:
        return x, y
    if rot == 90:
        # u.x = r.y, u.y = H - r.x
        return y, H - x
    if rot == 180:
        return W - x, H - y
    # rot == 270
    return W - y, x


def px_to_pts(
    x_px: float,
    y_px: float,
    image_width_px: int,
    image_height_px: int,
    page: PageBox,
) -> Tuple[float, float]:
    """
    Convert image pixel coordinates to PDF points (originTop, unrotated CropBox space).

    Steps:
    1) Scale px->pts in rotated display space.
    2) Undo rotation to return to CropBox point space.
    """
    sx, sy = get_scale_factors(image_width_px, image_height_px, page)
    x_rot = x_px * sx
    y_rot = y_px * sy
    return rotate_point_inverse(x_rot, y_rot, page)


def pts_to_px(
    x_pt: float,
    y_pt: float,
    image_width_px: int,
    image_height_px: int,
    page: PageBox,
) -> Tuple[float, float]:
    """
    Convert PDF points (originTop, unrotated CropBox) to image pixels.
    """
    x_rot, y_rot = rotate_point_forward(x_pt, y_pt, page)
    sx, sy = get_scale_factors(image_width_px, image_height_px, page)
    if sx == 0 or sy == 0:
        return 0.0, 0.0
    return x_rot / sx, y_rot / sy


def px_bbox_to_pts_bbox(
    bbox_px: Tuple[int, int, int, int],
    image_width_px: int,
    image_height_px: int,
    page: PageBox,
) -> List[float]:
    """
    Convert a pixel bbox (x, y, w, h) to a point bbox [x1, y1, x2, y2] in originTop points.
    """
    x, y, w, h = bbox_px
    x1, y1 = px_to_pts(x, y, image_width_px, image_height_px, page)
    x2, y2 = px_to_pts(x + w, y + h, image_width_px, image_height_px, page)
    return [min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)]


def pts_bbox_to_px_bbox(
    bbox_pts: Iterable[float],
    image_width_px: int,
    image_height_px: int,
    page: PageBox,
) -> List[float]:
    """
    Convert a points bbox [x1, y1, x2, y2] to a pixel bbox [x1, y1, x2, y2] (corners).
    """
    x1, y1, x2, y2 = list(bbox_pts)
    px1, py1 = pts_to_px(x1, y1, image_width_px, image_height_px, page)
    px2, py2 = pts_to_px(x2, y2, image_width_px, image_height_px, page)
    return [min(px1, px2), min(py1, py2), max(px1, px2), max(py1, py2)]
