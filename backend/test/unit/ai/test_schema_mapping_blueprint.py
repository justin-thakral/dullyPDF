"""Unit tests for backend.ai.schema_mapping."""

import json
from types import SimpleNamespace

import pytest

from backend.ai import schema_mapping


def _response_with_content(content: str):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


class _FakeCompletions:
    def __init__(self, effects):
        self._effects = list(effects)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        effect = self._effects.pop(0)
        if isinstance(effect, Exception):
            raise effect
        return effect


class _FakeOpenAIClient:
    def __init__(self, effects):
        self.chat = SimpleNamespace(completions=_FakeCompletions(effects))


class _ResponseFormatError(Exception):
    def __init__(self, message: str = "response_format is not supported") -> None:
        super().__init__(message)
        self.param = "response_format"
        self.message = message


def test_build_allowlist_payload_normalizes_truncates_and_coerces(mocker) -> None:
    mocker.patch.object(schema_mapping, "MAX_FIELD_NAME_LEN", 6)
    mocker.patch.object(schema_mapping, "MAX_SCHEMA_FIELDS", 3)
    mocker.patch.object(schema_mapping, "MAX_TEMPLATE_FIELDS", 3)

    payload = schema_mapping.build_allowlist_payload(
        schema_fields=[
            {"name": "  First Name  ", "type": "STRING"},
            {"name": "VeryLongFieldName", "type": "not-allowed"},
            {"name": "   ", "type": "date"},
        ],
        template_fields=[
            {
                "name": "  CandidateTag  ",
                "type": "CHECKBOX",
                "page": "2",
                "rect": {"x": 1, "y": "bad", "width": 2.5, "height": 3},
                "groupKey": " grp ",
                "optionKey": " opt ",
                "option_label": " Option Label Long ",
                "group_label": " Group Label Long ",
            },
            {"name": " ", "type": "text"},
            {
                "name": "FallbackTag",
                "type": "unknown",
                "page": "not-a-number",
                "rect": "not-a-rect",
            },
        ],
    )

    assert payload["schemaFields"] == [
        {"name": "First ", "type": "string"},
        {"name": "VeryLo", "type": "string"},
    ]
    assert payload["templateTags"] == [
        {
            "tag": "Candid",
            "type": "checkbox",
            "page": 2,
            "rect": {"x": 1.0, "width": 2.5, "height": 3.0},
            "groupKey": "grp",
            "optionKey": "opt",
            "optionLabel": "Option",
            "groupLabel": "Group ",
        },
        {
            "tag": "Fallba",
            "type": "text",
            "page": 1,
            "rect": None,
            "groupKey": None,
            "optionKey": None,
            "optionLabel": None,
            "groupLabel": None,
        },
    ]
    assert payload["totalSchemaFields"] == 2
    assert payload["totalTemplateTags"] == 2


def test_validate_payload_size_enforces_maximum(mocker) -> None:
    mocker.patch.object(schema_mapping, "MAX_PAYLOAD_BYTES", 20)

    schema_mapping.validate_payload_size({"ok": "small"})
    with pytest.raises(ValueError, match="OpenAI payload too large"):
        schema_mapping.validate_payload_size({"x": "a" * 100})


def test_split_template_tags_chunks_and_preserves_order(mocker) -> None:
    mocker.patch.object(schema_mapping, "MAX_PAYLOAD_BYTES", 320)
    schema_fields = [{"name": "field_a", "type": "string"}]
    template_tags = [
        {
            "tag": f"T{idx}",
            "type": "text",
            "page": 1,
            "rect": None,
            "groupKey": None,
            "optionKey": None,
            "optionLabel": None,
            "groupLabel": None,
        }
        for idx in range(20)
    ]

    chunks = schema_mapping._split_template_tags(schema_fields, template_tags)
    flattened = [tag for chunk in chunks for tag in chunk["templateTags"]]

    assert len(chunks) > 1
    assert flattened == template_tags
    assert all(schema_mapping._payload_size(chunk) <= schema_mapping.MAX_PAYLOAD_BYTES for chunk in chunks)


def test_split_template_tags_raises_when_schema_alone_exceeds_budget(mocker) -> None:
    mocker.patch.object(schema_mapping, "MAX_PAYLOAD_BYTES", 10)

    with pytest.raises(ValueError, match="OpenAI payload too large"):
        schema_mapping._split_template_tags([{"name": "field", "type": "string"}], [])


def test_split_template_tags_raises_when_single_tag_exceeds_budget(mocker) -> None:
    mocker.patch.object(schema_mapping, "MAX_PAYLOAD_BYTES", 220)
    schema_fields = [{"name": "field", "type": "string"}]
    oversized_tag = {
        "tag": "A" * 500,
        "type": "text",
        "page": 1,
        "rect": None,
        "groupKey": None,
        "optionKey": None,
        "optionLabel": None,
        "groupLabel": None,
    }

    with pytest.raises(ValueError, match="OpenAI payload too large"):
        schema_mapping._split_template_tags(schema_fields, [oversized_tag])


def test_merge_schema_mapping_response_merges_lists_filters_invalid_and_preserves_identifier() -> None:
    aggregate = {
        "mappings": [],
        "templateRules": [],
        "checkboxRules": [],
        "checkboxHints": [],
        "notes": [],
        "identifierKey": "existing_id",
    }

    schema_mapping._merge_schema_mapping_response(
        aggregate,
        {
            "mappings": [{"schemaField": "a"}, "bad"],
            "template_rules": [{"rule": 1}, None],
            "checkbox_rules": [{"groupKey": "g"}, 123],
            "checkbox_hints": [{"databaseField": "d"}, "skip"],
            "patientIdentifierField": "new_id",
            "notes": "note-1",
        },
    )
    schema_mapping._merge_schema_mapping_response(
        aggregate,
        {"mappings": [{"schemaField": "b"}], "identifierKey": "another_id", "notes": "note-2"},
    )

    assert aggregate["mappings"] == [{"schemaField": "a"}, {"schemaField": "b"}]
    assert aggregate["templateRules"] == [{"rule": 1}]
    assert aggregate["checkboxRules"] == [{"groupKey": "g"}]
    assert aggregate["checkboxHints"] == [{"databaseField": "d"}]
    assert aggregate["identifierKey"] == "existing_id"
    assert aggregate["notes"] == ["note-1", "note-2"]


def test_merge_schema_mapping_response_ignores_non_dict_input() -> None:
    aggregate = {"mappings": [], "templateRules": [], "checkboxRules": [], "checkboxHints": [], "notes": []}
    schema_mapping._merge_schema_mapping_response(aggregate, "not-a-dict")  # type: ignore[arg-type]
    assert aggregate == {"mappings": [], "templateRules": [], "checkboxRules": [], "checkboxHints": [], "notes": []}


def test_parse_json_extracts_embedded_object() -> None:
    content = "Model says:\n```json\n{\"mappings\": [{\"schemaField\": \"a\"}], \"notes\": \"ok\"}\n```"
    result = schema_mapping._parse_json(content)
    assert result == {"mappings": [{"schemaField": "a"}], "notes": "ok"}


def test_parse_json_returns_default_when_no_json_object_present() -> None:
    result = schema_mapping._parse_json("No JSON payload here")
    assert result == {"mappings": [], "notes": "Non-JSON response received"}


def test_call_openai_schema_mapping_raises_when_api_key_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="OpenAI API key not configured") as excinfo:
        schema_mapping.call_openai_schema_mapping({"schemaFields": [], "templateTags": []})

    assert getattr(excinfo.value, "status_code", None) == 503


def test_call_openai_schema_mapping_uses_json_response_format_and_parses_wrapped_json(
    monkeypatch: pytest.MonkeyPatch,
    mocker,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    client = _FakeOpenAIClient(
        [_response_with_content("prefix {\"mappings\": [], \"notes\": \"wrapped\"} suffix")]
    )
    mocker.patch("backend.ai.schema_mapping.create_openai_client", return_value=client)

    result = schema_mapping.call_openai_schema_mapping({"schemaFields": [], "templateTags": []})

    assert result == {"mappings": [], "notes": "wrapped"}
    assert len(client.chat.completions.calls) == 1
    first_call = client.chat.completions.calls[0]
    assert first_call["response_format"] == {"type": "json_object"}


def test_call_openai_schema_mapping_retries_without_response_format_when_rejected(
    monkeypatch: pytest.MonkeyPatch,
    mocker,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    client = _FakeOpenAIClient(
        [_ResponseFormatError(), _response_with_content("{\"mappings\": [{\"schemaField\": \"ok\"}]}")]
    )
    mocker.patch("backend.ai.schema_mapping.create_openai_client", return_value=client)

    result = schema_mapping.call_openai_schema_mapping({"schemaFields": [], "templateTags": []})

    assert result == {"mappings": [{"schemaField": "ok"}]}
    assert len(client.chat.completions.calls) == 2
    assert "response_format" in client.chat.completions.calls[0]
    assert "response_format" not in client.chat.completions.calls[1]


def test_call_openai_schema_mapping_collects_usage_and_honors_retry_override(
    monkeypatch: pytest.MonkeyPatch,
    mocker,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    response = _response_with_content("{\"mappings\": []}")
    response.usage = {
        "prompt_tokens": 11,
        "completion_tokens": 7,
        "total_tokens": 18,
        "prompt_tokens_details": {"cached_tokens": 3},
        "completion_tokens_details": {"reasoning_tokens": 2},
    }
    client = _FakeOpenAIClient([response])
    create_client = mocker.patch("backend.ai.schema_mapping.create_openai_client", return_value=client)
    usage_events = []

    result = schema_mapping.call_openai_schema_mapping(
        {"schemaFields": [], "templateTags": []},
        usage_collector=usage_events,
        openai_max_retries=0,
    )

    assert result == {"mappings": []}
    create_client.assert_called_once_with(api_key="test-key", max_retries_override=0)
    assert usage_events == [
        {
            "api": "chat_completions",
            "model": schema_mapping.OPENAI_SCHEMA_MODEL,
            "input_tokens": 11,
            "output_tokens": 7,
            "total_tokens": 18,
            "cached_input_tokens": 3,
            "reasoning_output_tokens": 2,
        }
    ]


def test_call_openai_schema_mapping_chunked_merges_chunk_responses(mocker) -> None:
    payload = {"schemaFields": [{"name": "f"}], "templateTags": [{"tag": "A"}, {"tag": "B"}]}
    chunks = [
        {"schemaFields": [{"name": "f"}], "templateTags": [{"tag": "A"}], "totalSchemaFields": 1, "totalTemplateTags": 1},
        {"schemaFields": [{"name": "f"}], "templateTags": [{"tag": "B"}], "totalSchemaFields": 1, "totalTemplateTags": 1},
    ]

    mocker.patch("backend.ai.schema_mapping._payload_size", return_value=schema_mapping.MAX_PAYLOAD_BYTES + 1)
    split = mocker.patch("backend.ai.schema_mapping._split_template_tags", return_value=chunks)
    call_mapping = mocker.patch(
        "backend.ai.schema_mapping.call_openai_schema_mapping",
        side_effect=[
            {"mappings": [{"schemaField": "first"}], "notes": "chunk-1"},
            {
                "mappings": [{"schemaField": "second"}],
                "templateRules": [{"templateTag": "B"}],
                "checkboxRules": [{"groupKey": "group"}],
                "checkboxHints": [{"databaseField": "first"}],
                "notes": "chunk-2",
            },
        ],
    )

    result = schema_mapping.call_openai_schema_mapping_chunked(payload)

    split.assert_called_once_with(payload["schemaFields"], payload["templateTags"])
    assert call_mapping.call_count == 2
    assert result["mappings"] == [{"schemaField": "first"}, {"schemaField": "second"}]
    assert result["templateRules"] == [{"templateTag": "B"}]
    assert result["checkboxRules"] == [{"groupKey": "group"}]
    assert result["checkboxHints"] == [{"databaseField": "first"}]
    assert result["notes"] == "chunk-1; chunk-2"


def test_call_openai_schema_mapping_chunked_passthrough_when_payload_within_budget(mocker) -> None:
    payload = {"schemaFields": [], "templateTags": []}
    mocker.patch("backend.ai.schema_mapping._payload_size", return_value=100)
    call_mapping = mocker.patch("backend.ai.schema_mapping.call_openai_schema_mapping", return_value={"ok": True})
    split = mocker.patch("backend.ai.schema_mapping._split_template_tags")

    result = schema_mapping.call_openai_schema_mapping_chunked(payload)

    assert result == {"ok": True}
    call_mapping.assert_called_once_with(payload)
    split.assert_not_called()


def test_call_openai_schema_mapping_chunked_raises_when_split_returns_no_chunks(mocker) -> None:
    payload = {"schemaFields": [{"name": "f"}], "templateTags": [{"tag": "A"}]}
    mocker.patch("backend.ai.schema_mapping._payload_size", return_value=schema_mapping.MAX_PAYLOAD_BYTES + 1)
    mocker.patch("backend.ai.schema_mapping._split_template_tags", return_value=[])

    with pytest.raises(ValueError, match="OpenAI payload too large"):
        schema_mapping.call_openai_schema_mapping_chunked(payload)


# ---------------------------------------------------------------------------
# Edge-case tests added for additional branch coverage
# ---------------------------------------------------------------------------


def test_parse_json_regex_fallback_returns_default_on_invalid_embedded_json() -> None:
    """When the regex r'\\{[\\s\\S]*\\}' extracts a substring that is still
    invalid JSON, _parse_json should fall back to the default dict rather than
    propagating JSONDecodeError."""
    content = "Here is {broken json} end"
    import re
    match = re.search(r"\{[\s\S]*\}", content)
    assert match is not None, "regex should match the braces"
    result = schema_mapping._parse_json(content)
    assert isinstance(result, dict)
    assert result.get("notes") == "Non-JSON response received"


def test_call_openai_schema_mapping_none_content_falls_back_to_empty_dict(
    monkeypatch: pytest.MonkeyPatch,
    mocker,
) -> None:
    """When the OpenAI response has choices[0].message.content == None, the
    function should fall back to '{}' so that _parse_json returns an empty dict
    rather than raising."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    # Simulate a response where content is None
    response = _response_with_content(None)  # type: ignore[arg-type]
    # The `or "{}"` fallback in call_openai_schema_mapping turns None into "{}"
    response.choices[0].message.content = None
    client = _FakeOpenAIClient([response])
    mocker.patch("backend.ai.schema_mapping.create_openai_client", return_value=client)

    result = schema_mapping.call_openai_schema_mapping(
        {"schemaFields": [], "templateTags": []}
    )

    # json.loads("{}") produces an empty dict
    assert result == {}


def test_merge_schema_mapping_response_identifier_from_patientIdentifierField() -> None:
    """When the aggregate has no prior identifierKey but the response contains
    'patientIdentifierField', the merge should adopt it as identifierKey."""
    aggregate: dict = {
        "mappings": [],
        "templateRules": [],
        "checkboxRules": [],
        "checkboxHints": [],
        "notes": [],
    }

    schema_mapping._merge_schema_mapping_response(
        aggregate,
        {"patientIdentifierField": "MRN", "notes": "set-from-patient-field"},
    )

    assert aggregate["identifierKey"] == "MRN"
    assert aggregate["notes"] == ["set-from-patient-field"]


def test_split_template_tags_single_chunk_when_all_tags_fit(mocker) -> None:
    """When all template tags fit within the MAX_PAYLOAD_BYTES budget, only a
    single chunk should be returned containing every tag."""
    # Use a generous budget so everything fits in one chunk
    mocker.patch.object(schema_mapping, "MAX_PAYLOAD_BYTES", 100_000)

    schema_fields = [{"name": "field_a", "type": "string"}]
    template_tags = [
        {
            "tag": f"T{idx}",
            "type": "text",
            "page": 1,
            "rect": None,
            "groupKey": None,
            "optionKey": None,
            "optionLabel": None,
            "groupLabel": None,
        }
        for idx in range(5)
    ]

    chunks = schema_mapping._split_template_tags(schema_fields, template_tags)

    assert len(chunks) == 1, "All tags should fit in a single chunk"
    assert chunks[0]["templateTags"] == template_tags
    assert chunks[0]["totalTemplateTags"] == 5
    assert chunks[0]["schemaFields"] == schema_fields
