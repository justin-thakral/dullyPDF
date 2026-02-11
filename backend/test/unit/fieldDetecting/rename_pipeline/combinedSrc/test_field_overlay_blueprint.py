from pathlib import Path

import numpy as np
import pytest

from backend.fieldDetecting.rename_pipeline.combinedSrc import field_overlay
from backend.fieldDetecting.rename_pipeline.combinedSrc.coords import PageBox


def _page_candidates() -> dict:
    return {
        "page": 1,
        "pageWidth": 100.0,
        "pageHeight": 100.0,
        "rotation": 0,
        "imageWidthPx": 100,
        "imageHeightPx": 100,
        "labels": [
            {"text": "Option A", "bbox": [24.0, 11.0, 40.0, 20.0]},
            {"text": "Far Left", "bbox": [0.0, 11.0, 8.0, 20.0]},
        ],
        "lineCandidates": [{"id": "ln1", "bbox": [10.0, 40.0, 80.0, 42.0]}],
        "boxCandidates": [{"id": "bx1", "bbox": [10.0, 50.0, 30.0, 70.0]}],
        "checkboxCandidates": [{"id": "cb1", "bbox": [10.0, 10.0, 20.0, 20.0], "detector": "ocr"}],
    }


def test_to_px_corners_clamps_off_page_rectangles() -> None:
    page = PageBox(page_width=100.0, page_height=100.0, rotation=0)

    x1, y1, x2, y2 = field_overlay._to_px_corners(
        [-10.0, -5.0, 120.0, 130.0],
        image_width_px=100,
        image_height_px=100,
        page_box=page,
    )

    assert (x1, y1, x2, y2) == (0, 0, 99, 99)


def test_to_px_corners_swaps_reversed_coordinates() -> None:
    page = PageBox(page_width=100.0, page_height=100.0, rotation=0)

    x1, y1, x2, y2 = field_overlay._to_px_corners(
        [80.0, 60.0, 20.0, 30.0],
        image_width_px=100,
        image_height_px=100,
        page_box=page,
    )

    assert x1 <= x2
    assert y1 <= y2


def test_pick_checkbox_label_prefers_right_aligned_nearby_label() -> None:
    checkbox = [10.0, 10.0, 20.0, 20.0]
    labels = [
        {"text": "left", "bbox": [0.0, 10.0, 8.0, 20.0]},
        {"text": "right", "bbox": [24.0, 10.0, 40.0, 20.0]},
    ]

    picked = field_overlay._pick_checkbox_label(checkbox, labels)

    assert picked and picked["text"] == "right"


def test_fit_text_in_box_handles_tiny_regions() -> None:
    label, scale = field_overlay._fit_text_in_box("VeryLongLabelText", max_width=8, max_height=6)

    assert label
    assert scale > 0


def test_draw_overlay_writes_image_for_normal_and_off_page_inputs(tmp_path: Path) -> None:
    image = np.zeros((100, 100, 3), dtype=np.uint8)
    out_path = tmp_path / "overlay.png"
    fields = [
        {"page": 1, "type": "text", "name": "patient_name", "rect": [10.0, 10.0, 60.0, 25.0]},
        {"page": 1, "type": "checkbox", "name": "i_option_a", "rect": [10.0, 10.0, 20.0, 20.0]},
        {"page": 1, "type": "text", "name": "offpage", "rect": [120.0, 120.0, 140.0, 140.0]},
    ]

    rendered = field_overlay.draw_overlay(
        image,
        _page_candidates(),
        fields,
        out_path,
        field_labels_inside=True,
        highlight_checkbox_labels=True,
        return_image=True,
    )

    assert out_path.exists()
    assert rendered is not None
    assert rendered.shape == image.shape


def test_draw_overlay_rejects_empty_image(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="empty image"):
        field_overlay.draw_overlay(
            np.array([], dtype=np.uint8),
            _page_candidates(),
            [],
            tmp_path / "bad.png",
        )


def test_draw_overlay_raises_when_image_write_fails(tmp_path: Path, mocker) -> None:
    image = np.zeros((100, 100, 3), dtype=np.uint8)
    mocker.patch.object(field_overlay.cv2, "imwrite", return_value=False)

    with pytest.raises(RuntimeError, match="Failed to write overlay image"):
        field_overlay.draw_overlay(
            image,
            _page_candidates(),
            [],
            tmp_path / "overlay.png",
        )
