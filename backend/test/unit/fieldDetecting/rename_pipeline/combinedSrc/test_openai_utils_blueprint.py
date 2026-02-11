from types import SimpleNamespace

import pytest
from openai import OpenAIError

from backend.fieldDetecting.rename_pipeline.combinedSrc import openai_utils


class _FakeResponses:
    def __init__(self, side_effects):
        self._side_effects = list(side_effects)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        effect = self._side_effects.pop(0)
        if isinstance(effect, Exception):
            raise effect
        return effect


class _FakeClient:
    def __init__(self, side_effects):
        self.responses = _FakeResponses(side_effects)


def test_error_text_extracts_common_error_shapes() -> None:
    exc = Exception("fallback")
    setattr(exc, "message", "from-message")
    assert openai_utils._error_text(exc) == "from-message"

    exc2 = Exception("fallback")
    setattr(exc2, "body", {"error": "from-body"})
    assert "from-body" in openai_utils._error_text(exc2)


def test_is_temperature_unsupported_detects_model_message() -> None:
    exc = OpenAIError('"temperature" is not supported with this model')
    assert openai_utils._is_temperature_unsupported(exc) is True

    exc2 = OpenAIError("network timeout")
    assert openai_utils._is_temperature_unsupported(exc2) is False


def test_responses_create_retries_without_temperature_on_unsupported_error() -> None:
    client = _FakeClient(
        [
            OpenAIError('"temperature" is not supported with this model'),
            {"ok": True},
        ]
    )

    result = openai_utils.responses_create_with_temperature_fallback(
        client,
        model="gpt-test",
        input=[{"role": "user", "content": "hello"}],
        text={"format": {"type": "text"}},
        max_output_tokens=32,
        temperature=0,
    )

    assert result == {"ok": True}
    assert len(client.responses.calls) == 2
    assert "temperature" in client.responses.calls[0]
    assert "temperature" not in client.responses.calls[1]


def test_responses_create_reraises_non_temperature_errors() -> None:
    client = _FakeClient([OpenAIError("quota exceeded")])

    with pytest.raises(OpenAIError, match="quota"):
        openai_utils.responses_create_with_temperature_fallback(
            client,
            model="gpt-test",
            input=[],
            text={"format": {"type": "text"}},
            max_output_tokens=16,
            temperature=0,
        )


def test_extract_response_text_prefers_output_text_then_joins_parts() -> None:
    response = SimpleNamespace(output_text="direct")
    assert openai_utils.extract_response_text(response) == "direct"

    nested = SimpleNamespace(
        output_text=None,
        output=[
            SimpleNamespace(content=[SimpleNamespace(text="hello"), SimpleNamespace(text=" ")]),
            SimpleNamespace(content=[SimpleNamespace(text="world")]),
        ],
    )
    assert openai_utils.extract_response_text(nested) == "hello world"


# ---------------------------------------------------------------------------
# Edge-case tests added below
# ---------------------------------------------------------------------------


def test_error_text_falls_back_to_str_when_no_special_attrs() -> None:
    """When the exception has none of the special attributes (message, error,
    body, response), _error_text should fall back to str(exc).  This tests
    the final return path at the bottom of the function."""
    exc = Exception("plain fallback message")
    # Ensure none of the probed attributes exist.
    assert not hasattr(exc, "message")
    assert not hasattr(exc, "error")
    assert not hasattr(exc, "body")
    assert not hasattr(exc, "response")
    result = openai_utils._error_text(exc)
    assert result == "plain fallback message"


def test_extract_response_text_with_empty_response_returns_empty_string() -> None:
    """When the response has neither output_text nor output (or both are
    empty/None), extract_response_text should return an empty string rather
    than raising.  This exercises the fallback path through the empty
    parts list."""
    # Case 1: both output_text and output are None
    empty_response = SimpleNamespace(output_text=None, output=None)
    assert openai_utils.extract_response_text(empty_response) == ""

    # Case 2: output_text is empty string (falsy), output is empty list
    empty_response_2 = SimpleNamespace(output_text="", output=[])
    assert openai_utils.extract_response_text(empty_response_2) == ""

    # Case 3: output items exist but have no text content
    empty_parts = SimpleNamespace(
        output_text=None,
        output=[SimpleNamespace(content=[SimpleNamespace(text=None)])],
    )
    assert openai_utils.extract_response_text(empty_parts) == ""

    # Case 4: no output_text attr, no output attr (bare object)
    bare = SimpleNamespace()
    assert openai_utils.extract_response_text(bare) == ""
