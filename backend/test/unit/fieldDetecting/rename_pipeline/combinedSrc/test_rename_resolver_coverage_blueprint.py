from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from backend.fieldDetecting.rename_pipeline.combinedSrc import rename_resolver as rr


def test_downscale_crop_and_prev_context_helpers() -> None:
    image = np.zeros((100, 50, 3), dtype=np.uint8)

    unchanged = rr._downscale_for_model(image, max_dim=200)
    assert unchanged.shape == (100, 50, 3)

    downscaled = rr._downscale_for_model(image, max_dim=40)
    assert downscaled.shape == (40, 20, 3)

    cropped = rr._crop_prev_page_context(image, fraction=0.2)
    assert cropped.shape == (20, 50, 3)

    unchanged_crop = rr._crop_prev_page_context(image, fraction=0)
    assert unchanged_crop.shape == (100, 50, 3)

    page_fields = [(0, {"rect": [10, 5, 20, 15]}), (1, {"rect": [10, 30, 20, 40]})]
    assert rr._should_include_prev_context(page_fields, page_height=100, top_fraction=0.1) is True
    assert rr._should_include_prev_context(page_fields, page_height=100, top_fraction=0.01) is False


def test_distance_and_label_context_helpers() -> None:
    min_dist = rr._min_center_distance([[0, 0, 10, 10], [10, 0, 20, 10], [100, 100, 110, 110]], early_stop=11.0)
    assert min_dist == pytest.approx(10.0)
    assert rr._min_center_distance([[0, 0, 10, 10]]) is None

    overlap_dist, overlaps = rr._label_context([0, 0, 10, 10], [[5, 5, 15, 15]])
    assert overlap_dist == pytest.approx(0.0)
    assert overlaps is True

    separate_dist, separate_overlaps = rr._label_context([0, 0, 10, 10], [[20, 20, 30, 30]])
    assert separate_dist is not None and separate_dist > 0
    assert separate_overlaps is False


def test_build_overlay_fields_is_deterministic_and_maps_indices() -> None:
    page_fields = [
        (3, {"page": 1, "rect": [0, 0, 10, 10], "type": "text"}),
        (7, {"page": 1, "rect": [10, 0, 20, 10], "type": "checkbox"}),
    ]

    first_overlay, first_map = rr._build_overlay_fields(1, page_fields)
    second_overlay, second_map = rr._build_overlay_fields(1, page_fields)

    assert first_overlay == second_overlay
    assert first_map == second_map
    assert set(first_map.values()) == {3, 7}
    assert all(len(item["name"]) == 3 for item in first_overlay)


def test_attach_checkbox_label_hints_prefers_right_label_and_truncates() -> None:
    long_label = "This is a very long checkbox label that should be trimmed for prompt stability"
    overlay_fields = [{"name": "abc", "type": "checkbox", "rect": [10, 10, 20, 20]}]
    page_candidates = {
        "labels": [
            {"bbox": [0, 10, 8, 20], "text": "Left label"},
            {"bbox": [22, 10, 60, 20], "text": long_label},
        ]
    }

    enriched = rr._attach_checkbox_label_hints(overlay_fields, page_candidates=page_candidates)

    assert enriched[0]["labelHintText"].endswith("…")
    assert len(enriched[0]["labelHintText"]) == 48
    assert enriched[0]["labelHintBbox"] == [22, 10, 60, 20]


def test_select_database_prompt_fields_shortlists_only_above_threshold() -> None:
    overlay_fields = [{"name": "a1b", "type": "text", "labelHintText": "Patient Name"}]

    under_limit_fields, under_total, under_truncated = rr._select_database_prompt_fields(
        ["patient_name", "patient_email", "patient_phone"],
        overlay_fields=overlay_fields,
        full_threshold=3,
        shortlist_limit=2,
    )
    assert under_total == 3
    assert under_truncated is False
    assert under_limit_fields == ["patient_name", "patient_email", "patient_phone"]

    over_limit_fields, over_total, over_truncated = rr._select_database_prompt_fields(
        ["patient_name"] + [f"schema_{i}" for i in range(10)],
        overlay_fields=overlay_fields,
        full_threshold=3,
        shortlist_limit=2,
    )
    assert over_total == 11
    assert over_truncated is True
    assert len(over_limit_fields) == 2
    assert "patient_name" in over_limit_fields


def test_compact_prompt_noise_dedupes_duplicate_bullets() -> None:
    raw = "\n".join(
        [
            "Rules:",
            "- Keep overlay IDs stable.",
            "- Keep overlay IDs stable.",
            "",
            "",
            "- Use snake_case.",
        ]
    )
    compacted = rr._compact_prompt_noise(raw)
    assert compacted.count("- Keep overlay IDs stable.") == 1
    assert "\n\n\n" not in compacted


def test_build_prompt_includes_option_hint_and_commonforms_guidance(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rr, "COMMONFORMS_CONFIDENCE_GREEN", 0.91)
    monkeypatch.setattr(rr, "COMMONFORMS_CONFIDENCE_YELLOW", 0.72)
    overlay_fields = [
        {
            "name": "abc",
            "type": "checkbox",
            "rect": [10, 10, 20, 20],
            "labelHintText": "Smoker",
        }
    ]
    page_candidates = {"pageWidth": 100, "pageHeight": 100, "labels": [{"bbox": [22, 10, 60, 20], "text": "Smoker"}]}

    system_message, user_message = rr._build_prompt(
        1,
        overlay_fields,
        page_candidates=page_candidates,
        confidence_profile="commonforms",
        database_fields=["patient_smoker"],
    )

    assert "CommonForms confidence guidance" in system_message
    assert "Green >= 0.91" in system_message
    assert 'option_hint="Smoker"' in user_message
    assert "DATABASE_FIELDS" in user_message
    assert "- patient_smoker" in user_message


def test_normalize_checkbox_rule_rejects_invalid_and_cleans_value_map() -> None:
    invalid_operation = rr._normalize_checkbox_rule(
        {"databaseField": "consent", "groupKey": "consent", "operation": "unsupported"},
        allowed_schema_map={"consent": "consent"},
        allowed_group_keys={"consent"},
    )
    assert invalid_operation is None

    invalid_schema = rr._normalize_checkbox_rule(
        {"databaseField": "unknown", "groupKey": "consent", "operation": "presence"},
        allowed_schema_map={"consent": "consent"},
        allowed_group_keys={"consent"},
    )
    assert invalid_schema is None

    normalized = rr._normalize_checkbox_rule(
        {
            "databaseField": "consent",
            "groupKey": "consent",
            "operation": "enum",
            "valueMap": {"yes": "Y", None: "N", "no": None},
            "confidence": "92%",
            "reasoning": "mapped from explicit yes/no options",
        },
        allowed_schema_map={"consent": "consent"},
        allowed_group_keys={"consent"},
    )

    assert normalized is not None
    assert normalized["databaseField"] == "consent"
    assert normalized["groupKey"] == "consent"
    assert normalized["operation"] == "enum"
    assert normalized["valueMap"] == {"yes": "Y"}
    assert normalized["confidence"] == pytest.approx(0.92)
    assert normalized["reasoning"] == "mapped from explicit yes/no options"


def test_run_openai_rename_pipeline_requires_api_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY not set"):
        rr.run_openai_rename_pipeline(
            rendered_pages=[{"page_index": 1, "image": np.zeros((20, 20, 3), dtype=np.uint8)}],
            candidates=[{"page": 1, "labels": []}],
            fields=[{"name": "A", "type": "text", "page": 1, "rect": [1, 1, 5, 5], "confidence": 0.8}],
            output_dir=tmp_path,
        )


def test_run_openai_rename_pipeline_skips_openai_when_page_candidates_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    openai_ctor = pytest.fail
    monkeypatch.setattr(
        rr,
        "create_openai_client",
        lambda **_kwargs: openai_ctor("OpenAI should not be called"),
    )
    monkeypatch.setattr(rr, "run_threaded_map", lambda tasks, fn, max_workers, label: [])

    report, renamed = rr.run_openai_rename_pipeline(
        rendered_pages=[{"page_index": 1, "image": np.zeros((20, 20, 3), dtype=np.uint8)}],
        candidates=[],
        fields=[{"name": "Patient Name", "type": "text", "page": 1, "rect": [1, 1, 5, 5], "confidence": 0.8}],
        output_dir=tmp_path,
        database_fields=["patient_name"],
    )

    assert report["dropped"] == []
    assert report["checkboxRules"] == []
    assert len(renamed) == 1
    assert renamed[0]["name"] == "patient_name"
    assert renamed[0]["mappingConfidence"] == pytest.approx(0.0)


def test_run_openai_rename_pipeline_no_fields_short_circuits_without_api_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    report, renamed = rr.run_openai_rename_pipeline(
        rendered_pages=[],
        candidates=[],
        fields=[],
        output_dir=tmp_path,
    )

    assert renamed == []
    assert report["renames"] == []
    assert report["dropped"] == []


def test_run_openai_rename_pipeline_raises_when_overlay_render_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(rr, "resolve_workers", lambda *args, **kwargs: 1)
    monkeypatch.setattr(
        rr,
        "_build_overlay_fields",
        lambda *_args, **_kwargs: (
            [{"page": 1, "rect": [1, 1, 5, 5], "type": "text", "name": "abc", "displayName": "abc"}],
            {"abc": 0},
        ),
    )
    monkeypatch.setattr(rr, "_attach_checkbox_label_hints", lambda overlay_fields, **_kwargs: overlay_fields)
    monkeypatch.setattr(rr, "draw_overlay", lambda *_args, **_kwargs: None)

    with pytest.raises(RuntimeError, match="Failed to render overlay image"):
        rr.run_openai_rename_pipeline(
            rendered_pages=[{"page_index": 1, "image": np.zeros((20, 20, 3), dtype=np.uint8)}],
            candidates=[{"page": 1, "pageWidth": 100.0, "pageHeight": 100.0, "labels": []}],
            fields=[{"name": "Patient Name", "type": "text", "page": 1, "rect": [1, 1, 5, 5], "confidence": 0.8}],
            output_dir=tmp_path,
        )


def test_run_openai_rename_pipeline_keeps_defaults_for_missing_openai_lines(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(rr, "resolve_workers", lambda *args, **kwargs: 1)
    monkeypatch.setattr(
        rr,
        "_build_overlay_fields",
        lambda *_args, **_kwargs: (
            [
                {"page": 1, "rect": [1, 1, 5, 5], "type": "text", "name": "abc", "displayName": "abc"},
                {"page": 1, "rect": [10, 1, 14, 5], "type": "text", "name": "def", "displayName": "def"},
            ],
            {"abc": 0, "def": 1},
        ),
    )
    monkeypatch.setattr(rr, "_attach_checkbox_label_hints", lambda overlay_fields, **_kwargs: overlay_fields)
    monkeypatch.setattr(rr, "_build_prompt", lambda *_args, **_kwargs: ("system", "user"))
    monkeypatch.setattr(rr, "draw_overlay", lambda *_args, **_kwargs: np.zeros((20, 20, 3), dtype=np.uint8))
    monkeypatch.setattr(rr, "image_bgr_to_data_url", lambda *_args, **_kwargs: "data:image/png;base64,abc")
    monkeypatch.setattr(rr, "create_openai_client", lambda **_kwargs: object())
    monkeypatch.setattr(
        rr,
        "responses_create_with_temperature_fallback",
        lambda *_args, **_kwargs: type("_Resp", (), {"output_text": "|| abc | patient_name | 0.9 | 0.9"})(),
    )
    monkeypatch.setattr(rr, "extract_response_text", lambda response: response.output_text)

    report, renamed = rr.run_openai_rename_pipeline(
        rendered_pages=[{"page_index": 1, "image": np.zeros((20, 20, 3), dtype=np.uint8)}],
        candidates=[{"page": 1, "pageWidth": 100.0, "pageHeight": 100.0, "labels": []}],
        fields=[
            {"name": "Field One", "type": "text", "page": 1, "rect": [1, 1, 5, 5], "confidence": 0.8},
            {"name": "Field Two", "type": "text", "page": 1, "rect": [10, 1, 14, 5], "confidence": 0.8},
        ],
        output_dir=tmp_path,
    )

    assert report["dropped"] == []
    assert len(report["renames"]) == 2
    assert renamed[0]["name"] == "patient_name"
    assert renamed[1]["name"] == "field_two"
