"""Unit tests for backend.ai.rename_pipeline."""

import json
from pathlib import Path

import pytest

from backend.ai import rename_pipeline


def test_build_candidates_maps_page_metadata_and_label_collation() -> None:
    rendered_pages = [
        {
            "page_index": "2",
            "width_points": "612",
            "height_points": 792.5,
            "rotation": "90",
            "image_width_px": "1600",
            "image_height_px": 2000,
        }
    ]
    labels_by_page = {2: [{"text": "Patient Name"}]}

    candidates = rename_pipeline._build_candidates(rendered_pages, labels_by_page)

    assert candidates == [
        {
            "page": 2,
            "pageWidth": 612.0,
            "pageHeight": 792.5,
            "rotation": 90,
            "imageWidthPx": 1600,
            "imageHeightPx": 2000,
            "labels": [{"text": "Patient Name"}],
        }
    ]


def test_build_candidates_defaults_missing_metadata_and_empty_labels() -> None:
    rendered_pages = [{}]

    candidates = rename_pipeline._build_candidates(rendered_pages, labels_by_page={})

    assert candidates == [
        {
            "page": 1,
            "pageWidth": 0.0,
            "pageHeight": 0.0,
            "rotation": 0,
            "imageWidthPx": 0,
            "imageHeightPx": 0,
            "labels": [],
        }
    ]


def test_write_json_creates_parent_and_writes_payload(tmp_path: Path) -> None:
    output_path = tmp_path / "debug" / "renames.json"
    payload = {"ok": True, "fields": [{"name": "first_name"}]}

    rename_pipeline._write_json(output_path, payload)

    assert output_path.is_file()
    assert json.loads(output_path.read_text(encoding="utf-8")) == payload


def test_run_openai_rename_on_pdf_orchestrates_pipeline_calls_in_order(mocker) -> None:
    rendered_pages = [{"page_index": 1, "width_points": 100, "height_points": 200}]
    labels_by_page = {1: [{"text": "First Name"}]}
    candidates = [{"page": 1, "labels": [{"text": "First Name"}]}]
    fields = [{"name": "A1", "type": "text"}]
    rename_report = {"summary": "ok"}
    renamed_fields = [{"name": "first_name"}]
    call_order: list[str] = []

    def _render(pdf_bytes: bytes):
        call_order.append("render")
        assert pdf_bytes == b"%PDF-1.4"
        return rendered_pages

    def _extract(pdf_bytes: bytes, pages):
        call_order.append("extract")
        assert pdf_bytes == b"%PDF-1.4"
        assert pages == rendered_pages
        return labels_by_page

    def _build(pages, labels):
        call_order.append("build")
        assert pages == rendered_pages
        assert labels == labels_by_page
        return candidates

    def _resolve(
        pages,
        candidate_payload,
        fields_payload,
        *,
        output_dir: Path,
        confidence_profile: str,
        database_fields,
    ):
        call_order.append("resolve")
        assert pages == rendered_pages
        assert candidate_payload == candidates
        assert fields_payload == fields
        assert output_dir.name == "overlays"
        assert confidence_profile == "commonforms"
        assert database_fields == ["first_name", "last_name"]
        return rename_report, renamed_fields

    mocker.patch("backend.ai.rename_pipeline.render_pdf_to_images", side_effect=_render)
    mocker.patch("backend.ai.rename_pipeline.extract_labels", side_effect=_extract)
    mocker.patch("backend.ai.rename_pipeline._build_candidates", side_effect=_build)
    resolver = mocker.patch(
        "backend.ai.rename_pipeline.run_openai_rename_pipeline",
        side_effect=_resolve,
    )
    mocker.patch("backend.ai.rename_pipeline.debug_enabled", return_value=False)
    write_json = mocker.patch("backend.ai.rename_pipeline._write_json")

    report, renamed = rename_pipeline.run_openai_rename_on_pdf(
        pdf_bytes=b"%PDF-1.4",
        pdf_name="sample.pdf",
        fields=fields,
        database_fields=["first_name", "last_name"],
    )

    assert report == rename_report
    assert renamed == renamed_fields
    assert call_order == ["render", "extract", "build", "resolve"]
    resolver.assert_called_once()
    write_json.assert_not_called()


def test_run_openai_rename_on_pdf_writes_debug_artifacts_when_enabled(mocker) -> None:
    rendered_pages = [{"page_index": 1}]
    labels_by_page = {1: [{"text": "Name"}]}
    candidates = [{"page": 1, "labels": [{"text": "Name"}]}]
    rename_report = {"changes": 1}
    renamed_fields = [{"name": "first_name"}]

    mocker.patch("backend.ai.rename_pipeline.render_pdf_to_images", return_value=rendered_pages)
    mocker.patch("backend.ai.rename_pipeline.extract_labels", return_value=labels_by_page)
    mocker.patch("backend.ai.rename_pipeline._build_candidates", return_value=candidates)
    mocker.patch(
        "backend.ai.rename_pipeline.run_openai_rename_pipeline",
        return_value=(rename_report, renamed_fields),
    )
    mocker.patch("backend.ai.rename_pipeline.debug_enabled", return_value=True)
    write_json = mocker.patch("backend.ai.rename_pipeline._write_json")

    rename_pipeline.run_openai_rename_on_pdf(
        pdf_bytes=b"%PDF-1.4",
        pdf_name="sample.pdf",
        fields=[{"name": "A1"}],
    )

    assert write_json.call_count == 2
    first_path, first_payload = write_json.call_args_list[0].args
    second_path, second_payload = write_json.call_args_list[1].args
    assert first_path.name == "renames.json"
    assert first_payload == rename_report
    assert second_path.name == "fields_renamed.json"
    assert second_payload == {"fields": renamed_fields}


# ---------------------------------------------------------------------------
# Edge-case tests added for additional branch coverage
# ---------------------------------------------------------------------------


def test_build_candidates_multiple_pages_routes_labels_correctly() -> None:
    """With 2+ rendered pages, each page's labels should be routed to the
    correct candidate entry based on page_index, and pages without labels
    should receive an empty list."""
    rendered_pages = [
        {
            "page_index": 1,
            "width_points": 612,
            "height_points": 792,
            "rotation": 0,
            "image_width_px": 1600,
            "image_height_px": 2000,
        },
        {
            "page_index": 2,
            "width_points": 612,
            "height_points": 792,
            "rotation": 0,
            "image_width_px": 1600,
            "image_height_px": 2000,
        },
        {
            "page_index": 3,
            "width_points": 612,
            "height_points": 792,
            "rotation": 0,
            "image_width_px": 1600,
            "image_height_px": 2000,
        },
    ]
    labels_by_page = {
        1: [{"text": "First Name"}, {"text": "Last Name"}],
        3: [{"text": "Signature"}],
        # Page 2 intentionally has no labels
    }

    candidates = rename_pipeline._build_candidates(rendered_pages, labels_by_page)

    assert len(candidates) == 3
    # Page 1 gets its two labels
    assert candidates[0]["page"] == 1
    assert candidates[0]["labels"] == [{"text": "First Name"}, {"text": "Last Name"}]
    # Page 2 has no labels in the map so it should get an empty list
    assert candidates[1]["page"] == 2
    assert candidates[1]["labels"] == []
    # Page 3 gets its single label
    assert candidates[2]["page"] == 3
    assert candidates[2]["labels"] == [{"text": "Signature"}]


def test_run_openai_rename_on_pdf_propagates_sub_call_exception(mocker) -> None:
    """When a sub-call (e.g. render_pdf_to_images) raises an exception inside
    run_openai_rename_on_pdf, the exception should propagate to the caller
    without being silently swallowed."""
    mocker.patch(
        "backend.ai.rename_pipeline.render_pdf_to_images",
        side_effect=RuntimeError("renderer exploded"),
    )

    with pytest.raises(RuntimeError, match="renderer exploded"):
        rename_pipeline.run_openai_rename_on_pdf(
            pdf_bytes=b"%PDF-1.4",
            pdf_name="broken.pdf",
            fields=[{"name": "A1", "type": "text"}],
        )


def test_run_openai_rename_on_pdf_propagates_rename_pipeline_exception(mocker) -> None:
    """When run_openai_rename_pipeline itself raises, the error should bubble up."""
    rendered_pages = [{"page_index": 1, "width_points": 100, "height_points": 200}]
    mocker.patch("backend.ai.rename_pipeline.render_pdf_to_images", return_value=rendered_pages)
    mocker.patch("backend.ai.rename_pipeline.extract_labels", return_value={1: []})
    mocker.patch(
        "backend.ai.rename_pipeline.run_openai_rename_pipeline",
        side_effect=ValueError("pipeline failed"),
    )
    mocker.patch("backend.ai.rename_pipeline.debug_enabled", return_value=False)

    with pytest.raises(ValueError, match="pipeline failed"):
        rename_pipeline.run_openai_rename_on_pdf(
            pdf_bytes=b"%PDF-1.4",
            pdf_name="broken.pdf",
            fields=[{"name": "A1", "type": "text"}],
        )
