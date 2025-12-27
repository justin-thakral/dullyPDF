from backend.combinedSrc.detect_geometry import _merge_horizontal_segments


def test_merge_horizontal_segments_keeps_left_extent_when_out_of_order():
    """
    Regression test for a subtle ordering bug in `_merge_horizontal_segments`.

    Real scans can jitter line segments by a couple of pixels in Y. Because segments are
    sorted primarily by Y before merging, two segments on the *same* underline can be
    processed out-of-order in X. The merge logic must:
    - Merge the segments when they overlap (or are close)
    - Expand BOTH left and right X extents, not drop the left-most portion
    """
    # Segment A starts further right, but has a slightly smaller y1 (so it is processed first).
    # Segment B overlaps A but starts left; it arrives second in the loop.
    segments = [
        (100, 0, 200, 10),  # x1,y1,x2,y2
        (50, 3, 120, 13),
    ]
    merged = _merge_horizontal_segments(segments, y_tol=3, x_gap_tol=0)
    assert merged == [(50, 0, 150, 13)]  # x,y,w,h


def test_merge_horizontal_segments_does_not_merge_disjoint_out_of_order():
    """
    Ensure we do not incorrectly merge a far-left segment into a far-right segment.

    This is the failure mode that caused the "First Name ____" underline to disappear:
    the left segment satisfied a one-sided x-gap check when processed after a right segment.
    """
    segments = [
        (100, 0, 200, 10),
        (0, 3, 50, 13),
    ]
    merged = _merge_horizontal_segments(segments, y_tol=3, x_gap_tol=0)
    assert len(merged) == 2
    assert (100, 0, 100, 10) in merged
    assert (0, 3, 50, 10) in merged
