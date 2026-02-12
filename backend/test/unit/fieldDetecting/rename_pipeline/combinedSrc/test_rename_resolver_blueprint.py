from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from backend.fieldDetecting.rename_pipeline.combinedSrc import rename_resolver as rr


def test_normalization_helpers_cover_text_and_checkbox_paths() -> None:
    assert rr._to_snake_case(" Patient Name ") == "patient_name"
    assert rr._normalize_name("Patient Name", "text") == "patient_name"
    assert rr._normalize_name("Patient Name", "checkbox") == "i_patient_name"
    assert rr._normalize_checkbox_component("Has Allergies") == "has_allergies"
    assert rr._humanize_group_label("marital_status") == "marital status"


def test_confidence_helpers_and_commonforms_categories(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rr, "COMMONFORMS_CONFIDENCE_GREEN", 0.8)
    monkeypatch.setattr(rr, "COMMONFORMS_CONFIDENCE_YELLOW", 0.65)

    assert rr._parse_confidence("92%") == pytest.approx(0.92)
    assert rr._parse_confidence("0.7") == pytest.approx(0.7)
    assert rr._parse_confidence("bad") == 0.0

    assert rr._commonforms_category(0.85) == "green"
    assert rr._commonforms_category(0.7) == "yellow"
    assert rr._commonforms_category(0.2) == "red"


def test_tag_generation_is_deterministic_and_bounds_checked() -> None:
    seed = rr._stable_seed("page:1")
    first = rr._generate_base32_tags(5, seed=seed)
    second = rr._generate_base32_tags(5, seed=seed)

    assert first == second
    assert len(set(first)) == 5

    with pytest.raises(ValueError):
        rr._generate_base32_tags(len(rr.BASE32_TAGS) + 1, seed=seed)


def test_parse_openai_lines_ignores_malformed_and_unknown_overlay_ids() -> None:
    text = "\n".join(
        [
            "|| a1b | patient_name | 0.90 | 0.95",
            "|| unknown | ignored | 0.9 | 0.9",
            "not-a-rename-line",
            "|| malformed | missing-columns",
        ]
    )

    entries = rr._parse_openai_lines(text, overlay_map={"a1b": 3})

    assert len(entries) == 1
    assert entries[0]["fieldIndex"] == 3
    assert entries[0]["suggestedRename"] == "patient_name"


def test_parse_checkbox_rules_and_normalization() -> None:
    response = """
BEGIN_CHECKBOX_RULES_JSON
[
  {
    "databaseField": "Marital Status",
    "groupKey": "marital status",
    "operation": "yes_no",
    "trueOption": "Yes",
    "falseOption": "No",
    "confidence": "0.88"
  }
]
END_CHECKBOX_RULES_JSON
"""

    rules = rr._parse_checkbox_rules(response)
    normalized = rr._normalize_checkbox_rule(
        rules[0],
        allowed_schema_map={"marital_status": "marital_status"},
        allowed_group_keys={"marital_status"},
    )

    assert normalized is not None
    assert normalized["databaseField"] == "marital_status"
    assert normalized["groupKey"] == "marital_status"
    assert normalized["operation"] == "yes_no"
    assert normalized["trueOption"] == "yes"
    assert normalized["falseOption"] == "no"


def test_dedupe_field_names_applies_suffixes_and_checkbox_prefixes() -> None:
    fields = [
        {"name": "Patient Name", "type": "text", "page": 1, "rect": [0, 0, 10, 10]},
        {"name": "patient_name", "type": "text", "page": 1, "rect": [20, 0, 30, 10]},
        {"name": "consent", "type": "checkbox", "page": 1, "rect": [40, 0, 50, 10]},
    ]

    rr._dedupe_field_names(fields)

    assert fields[0]["name"] == "patient_name"
    assert fields[1]["name"] == "patient_name_1"
    assert fields[2]["name"] == "i_consent"


def test_run_openai_rename_pipeline_orchestrates_with_mocked_boundaries(
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
                {"page": 1, "rect": [10, 10, 20, 20], "type": "checkbox", "name": "a1b", "displayName": "a1b"},
                {"page": 1, "rect": [30, 10, 40, 20], "type": "checkbox", "name": "c2d", "displayName": "c2d"},
            ],
            {"a1b": 0, "c2d": 1},
        ),
    )
    monkeypatch.setattr(rr, "_attach_checkbox_label_hints", lambda overlay_fields, **_kwargs: overlay_fields)
    monkeypatch.setattr(rr, "_build_prompt", lambda *_args, **_kwargs: ("system", "user"))
    monkeypatch.setattr(
        rr,
        "draw_overlay",
        lambda *_args, **_kwargs: np.zeros((40, 40, 3), dtype=np.uint8),
    )
    monkeypatch.setattr(rr, "image_bgr_to_data_url", lambda *_args, **_kwargs: "data:image/png;base64,abc")

    response_text = "\n".join(
        [
            "|| a1b | marital_status_yes | 0.80 | 0.90",
            "|| c2d | marital_status_no | 0.70 | 0.20",
            rr.CHECKBOX_RULES_START,
            '[{"databaseField":"marital_status","groupKey":"marital_status","operation":"yes_no","trueOption":"yes","falseOption":"no","confidence":"0.91"}]',
            rr.CHECKBOX_RULES_END,
        ]
    )
    monkeypatch.setattr(rr, "create_openai_client", lambda **_kwargs: object())
    monkeypatch.setattr(
        rr,
        "responses_create_with_temperature_fallback",
        lambda *_args, **_kwargs: SimpleNamespace(output_text=response_text),
    )
    monkeypatch.setattr(rr, "extract_response_text", lambda response: response.output_text)

    rendered_pages = [{"page_index": 1, "image": np.zeros((40, 40, 3), dtype=np.uint8)}]
    candidates = [{"page": 1, "pageWidth": 100.0, "pageHeight": 100.0, "labels": []}]
    fields = [
        {
            "name": "orig_yes",
            "type": "checkbox",
            "page": 1,
            "rect": [10.0, 10.0, 20.0, 20.0],
            "confidence": 0.6,
            "source": "commonforms",
            "category": "yellow",
        },
        {
            "name": "orig_no",
            "type": "checkbox",
            "page": 1,
            "rect": [30.0, 10.0, 40.0, 20.0],
            "confidence": 0.6,
            "source": "commonforms",
            "category": "yellow",
        },
    ]

    report, renamed = rr.run_openai_rename_pipeline(
        rendered_pages,
        candidates,
        fields,
        output_dir=tmp_path,
        confidence_profile="commonforms",
        adjust_field_confidence=True,
        database_fields=["marital_status"],
    )

    assert len(renamed) == 2
    assert renamed[0]["name"] == "i_marital_status_yes"
    assert renamed[0]["groupKey"] == "marital_status"
    assert renamed[0]["optionKey"] == "yes"

    assert renamed[1]["name"] == "i_marital_status_no"
    assert renamed[1]["renameConfidence"] == 0.0
    assert renamed[1]["category"] == "red"

    assert report["dropped"] == ["orig_no"]
    assert report["checkboxRules"]
    assert report["checkboxRules"][0]["databaseField"] == "marital_status"


def test_run_openai_rename_pipeline_includes_prev_page_context_for_top_fields(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(rr, "resolve_workers", lambda *args, **kwargs: 1)
    monkeypatch.setattr(
        rr,
        "_build_overlay_fields",
        lambda *_args, **_kwargs: (
            [{"page": 2, "rect": [10, 5, 30, 15], "type": "text", "name": "a1b", "displayName": "a1b"}],
            {"a1b": 0},
        ),
    )
    monkeypatch.setattr(rr, "_attach_checkbox_label_hints", lambda overlay_fields, **_kwargs: overlay_fields)
    monkeypatch.setattr(rr, "_build_prompt", lambda *_args, **_kwargs: ("system", "user"))
    monkeypatch.setattr(rr, "draw_overlay", lambda *_args, **_kwargs: np.zeros((40, 40, 3), dtype=np.uint8))

    encoded_urls: list[str] = []

    def _fake_data_url(*_args, **_kwargs):
        token = f"data:image/png;base64,{len(encoded_urls)}"
        encoded_urls.append(token)
        return token

    monkeypatch.setattr(rr, "image_bgr_to_data_url", _fake_data_url)

    captured_messages: list[list[dict]] = []

    def _fake_response(*_args, **kwargs):
        captured_messages.append(kwargs["input"])
        return SimpleNamespace(output_text="|| a1b | patient_name | 0.8 | 0.9")

    monkeypatch.setattr(rr, "create_openai_client", lambda **_kwargs: object())
    monkeypatch.setattr(rr, "responses_create_with_temperature_fallback", _fake_response)
    monkeypatch.setattr(rr, "extract_response_text", lambda response: response.output_text)

    rendered_pages = [
        {"page_index": 1, "image": np.zeros((50, 50, 3), dtype=np.uint8)},
        {"page_index": 2, "image": np.zeros((50, 50, 3), dtype=np.uint8)},
    ]
    candidates = [
        {"page": 2, "pageWidth": 100.0, "pageHeight": 100.0, "labels": []},
    ]
    fields = [
        {
            "name": "orig_top",
            "type": "text",
            "page": 2,
            "rect": [10.0, 5.0, 30.0, 15.0],
            "confidence": 0.7,
        }
    ]

    rr.run_openai_rename_pipeline(rendered_pages, candidates, fields, output_dir=tmp_path)

    assert captured_messages
    user_content = captured_messages[0][1]["content"]
    image_items = [item for item in user_content if item.get("type") == "input_image"]
    assert len(image_items) == 3
    assert any(item.get("detail") == "low" for item in image_items)


def test_run_openai_rename_pipeline_uses_dense_overlay_env_tuning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("SANDBOX_RENAME_DENSE_FIELD_COUNT", "2")
    monkeypatch.setenv("SANDBOX_RENAME_OVERLAY_MAX_DIM", "1000")
    monkeypatch.setenv("SANDBOX_RENAME_DENSE_MAX_DIM", "2345")
    monkeypatch.setenv("SANDBOX_RENAME_DENSE_FORMAT", "jpg")

    monkeypatch.setattr(rr, "resolve_workers", lambda *args, **kwargs: 1)
    monkeypatch.setattr(
        rr,
        "_build_overlay_fields",
        lambda *_args, **_kwargs: (
            [
                {"page": 1, "rect": [10, 10, 30, 20], "type": "text", "name": "a1b", "displayName": "a1b"},
                {"page": 1, "rect": [35, 10, 55, 20], "type": "text", "name": "c2d", "displayName": "c2d"},
            ],
            {"a1b": 0, "c2d": 1},
        ),
    )
    monkeypatch.setattr(rr, "_attach_checkbox_label_hints", lambda overlay_fields, **_kwargs: overlay_fields)
    monkeypatch.setattr(rr, "_build_prompt", lambda *_args, **_kwargs: ("system", "user"))
    monkeypatch.setattr(rr, "draw_overlay", lambda *_args, **_kwargs: np.zeros((40, 40, 3), dtype=np.uint8))

    downscale_max_dims: list[int] = []

    def _capture_downscale(image, *, max_dim: int):
        downscale_max_dims.append(max_dim)
        return image

    monkeypatch.setattr(rr, "_downscale_for_model", _capture_downscale)

    image_formats: list[str] = []

    def _capture_data_url(*_args, **kwargs):
        image_formats.append(kwargs["format"])
        return "data:image/jpeg;base64,abc"

    monkeypatch.setattr(rr, "image_bgr_to_data_url", _capture_data_url)
    monkeypatch.setattr(rr, "create_openai_client", lambda **_kwargs: object())
    monkeypatch.setattr(
        rr,
        "responses_create_with_temperature_fallback",
        lambda *_args, **_kwargs: SimpleNamespace(
            output_text="|| a1b | first_name | 0.8 | 0.9\n|| c2d | last_name | 0.7 | 0.9"
        ),
    )
    monkeypatch.setattr(rr, "extract_response_text", lambda response: response.output_text)

    rendered_pages = [{"page_index": 1, "image": np.zeros((40, 40, 3), dtype=np.uint8)}]
    candidates = [{"page": 1, "pageWidth": 100.0, "pageHeight": 100.0, "labels": []}]
    fields = [
        {"name": "orig_1", "type": "text", "page": 1, "rect": [10.0, 10.0, 30.0, 20.0], "confidence": 0.7},
        {"name": "orig_2", "type": "text", "page": 1, "rect": [35.0, 10.0, 55.0, 20.0], "confidence": 0.7},
    ]

    rr.run_openai_rename_pipeline(rendered_pages, candidates, fields, output_dir=tmp_path)

    # clean page and overlay both use the dense max dim.
    assert downscale_max_dims[:2] == [2345, 2345]
    assert image_formats[:2] == ["jpg", "jpg"]


def test_run_openai_rename_pipeline_dedupes_checkbox_rules_by_highest_confidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(rr, "resolve_workers", lambda *args, **kwargs: 1)
    monkeypatch.setattr(
        rr,
        "_build_overlay_fields",
        lambda *_args, **_kwargs: (
            [{"page": 1, "rect": [10, 10, 20, 20], "type": "checkbox", "name": "a1b", "displayName": "a1b"}],
            {"a1b": 0},
        ),
    )
    monkeypatch.setattr(rr, "_attach_checkbox_label_hints", lambda overlay_fields, **_kwargs: overlay_fields)
    monkeypatch.setattr(rr, "_build_prompt", lambda *_args, **_kwargs: ("system", "user"))
    monkeypatch.setattr(rr, "draw_overlay", lambda *_args, **_kwargs: np.zeros((30, 30, 3), dtype=np.uint8))
    monkeypatch.setattr(rr, "image_bgr_to_data_url", lambda *_args, **_kwargs: "data:image/png;base64,abc")

    response_text = "\n".join(
        [
            "|| a1b | marital_status_yes | 0.8 | 0.9",
            rr.CHECKBOX_RULES_START,
            '[{"databaseField":"marital_status","groupKey":"marital_status","operation":"yes_no","confidence":"0.30"},'
            '{"databaseField":"marital_status","groupKey":"marital_status","operation":"yes_no","confidence":"0.90"}]',
            rr.CHECKBOX_RULES_END,
        ]
    )
    monkeypatch.setattr(rr, "create_openai_client", lambda **_kwargs: object())
    monkeypatch.setattr(
        rr,
        "responses_create_with_temperature_fallback",
        lambda *_args, **_kwargs: SimpleNamespace(output_text=response_text),
    )
    monkeypatch.setattr(rr, "extract_response_text", lambda response: response.output_text)

    rendered_pages = [{"page_index": 1, "image": np.zeros((30, 30, 3), dtype=np.uint8)}]
    candidates = [{"page": 1, "pageWidth": 100.0, "pageHeight": 100.0, "labels": []}]
    fields = [
        {
            "name": "orig_checkbox",
            "type": "checkbox",
            "page": 1,
            "rect": [10.0, 10.0, 20.0, 20.0],
            "confidence": 0.7,
        }
    ]

    report, _renamed = rr.run_openai_rename_pipeline(
        rendered_pages,
        candidates,
        fields,
        output_dir=tmp_path,
        database_fields=["marital_status"],
    )

    assert len(report["checkboxRules"]) == 1
    assert report["checkboxRules"][0]["databaseField"] == "marital_status"
    assert report["checkboxRules"][0]["confidence"] == pytest.approx(0.9)


# ---------------------------------------------------------------------------
# Edge-case tests added below
# ---------------------------------------------------------------------------


def test_to_snake_case_with_empty_string_returns_field() -> None:
    """An empty string (or whitespace-only input) should produce the fallback
    name 'field' rather than an empty string, because the cleaned variable
    will be empty after stripping and the early-return fires."""
    assert rr._to_snake_case("") == "field"
    assert rr._to_snake_case("   ") == "field"
    assert rr._to_snake_case("!!!") == "field"


def test_parse_checkbox_rules_with_malformed_json_returns_empty() -> None:
    """When the JSON block between the sentinels is malformed (not valid JSON),
    _parse_checkbox_rules should gracefully fall back to an empty list via
    the json.JSONDecodeError catch, without raising."""
    malformed_response = (
        f"{rr.CHECKBOX_RULES_START}\n"
        "[{not valid json}]\n"
        f"{rr.CHECKBOX_RULES_END}\n"
    )
    result = rr._parse_checkbox_rules(malformed_response)
    assert result == []


def test_parse_checkbox_rules_with_empty_response_returns_empty() -> None:
    """An empty or None response text should return an empty list immediately,
    hitting the early-return guard at the top of _parse_checkbox_rules."""
    assert rr._parse_checkbox_rules("") == []
    assert rr._parse_checkbox_rules(None) == []


def test_dedupe_field_names_no_duplicates_no_suffix() -> None:
    """When all field names are unique after normalization, no numeric suffix
    should be appended.  This verifies the n == 0 branch in _dedupe_field_names."""
    fields = [
        {"name": "First Name", "type": "text", "page": 1, "rect": [0, 0, 10, 10]},
        {"name": "Last Name", "type": "text", "page": 1, "rect": [20, 0, 30, 10]},
        {"name": "Email", "type": "text", "page": 1, "rect": [40, 0, 50, 10]},
    ]
    rr._dedupe_field_names(fields)
    names = sorted(f["name"] for f in fields)
    assert names == ["email", "first_name", "last_name"]
    # Confirm no suffix was added (no _1, _2, etc.)
    for f in fields:
        assert not f["name"].endswith("_1")
        assert not f["name"].endswith("_2")
