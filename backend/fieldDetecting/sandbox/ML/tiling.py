from __future__ import annotations

from typing import Iterable, List, Tuple


def tile_positions(length: int, tile_size: int, stride: int) -> List[int]:
    """
    Compute deterministic tile start positions that cover the full dimension.
    """
    if length <= tile_size:
        return [0]
    positions = list(range(0, length - tile_size + 1, stride))
    last = length - tile_size
    if positions[-1] != last:
        positions.append(last)
    return positions


def iter_tiles(
    image_w: int, image_h: int, tile_size: int, stride: int
) -> Iterable[Tuple[int, int, int, int]]:
    """
    Yield (x, y, w, h) for each tile in row-major order.
    """
    xs = tile_positions(image_w, tile_size, stride)
    ys = tile_positions(image_h, tile_size, stride)
    for y in ys:
        for x in xs:
            w = min(tile_size, image_w - x)
            h = min(tile_size, image_h - y)
            yield x, y, w, h
