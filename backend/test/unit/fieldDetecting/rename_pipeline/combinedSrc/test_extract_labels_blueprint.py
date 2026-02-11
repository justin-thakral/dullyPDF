from __future__ import annotations

import io
from dataclasses import dataclass
from typing import List

import pytest

from backend.fieldDetecting.rename_pipeline.combinedSrc import extract_labels


@dataclass
class _FakePage:
    words: List[dict]
    rotation: int = 0
    width: float = 100.0
    height: float = 100.0

    def extract_words(self, **_kwargs):
        return list(self.words)


class _FakePdf:
    def __init__(self, pages: List[_FakePage]) -> None:
        self.pages = pages

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _tb):
        return False


def _patch_pdfplumber_open(
    monkeypatch: pytest.MonkeyPatch,
    pages_word_sets: List[List[dict]],
) -> None:
    def _open(*_args, **_kwargs):
        pages = [_FakePage(words=words) for words in pages_word_sets]
        return _FakePdf(pages)

    monkeypatch.setattr(extract_labels.pdfplumber, "open", _open)


def _word(text: str, x0: float, top: float, x1: float, bottom: float) -> dict:
    return {
        "text": text,
        "x0": x0,
        "x1": x1,
        "top": top,
        "bottom": bottom,
    }


def test_clean_word_token_and_checkbox_artifact_filtering() -> None:
    assert extract_labels._clean_word_token("O)=Past Condition") == "Past Condition"
    assert extract_labels._clean_word_token("=Value") == "Value"
    assert extract_labels._clean_word_token("___") is None

    assert extract_labels._word_looks_like_checkbox_artifact("OO", 100.0, 100.0) is True
    assert extract_labels._word_looks_like_checkbox_artifact("Patient", 20.0, 8.0) is False


def test_filter_words_drops_noise_and_preserves_valid_tokens() -> None:
    words = [
        _word("OO", 0, 0, 4, 4),
        _word("...", 5, 0, 9, 4),
        _word("Patient", 10, 0, 40, 8),
        _word("Name", 42, 0, 60, 8),
    ]

    filtered = extract_labels._filter_words(words)

    assert [w["text"] for w in filtered] == ["Patient", "Name"]


def test_group_words_into_lines_splits_phrases_on_large_gap() -> None:
    words = [
        _word("City", 10, 10, 28, 18),
        _word("State", 31, 10, 54, 18),
        _word("ZIP", 120, 10, 136, 18),
    ]

    labels = extract_labels._group_words_into_lines(words)

    assert labels[0]["text"] == "City State"
    assert labels[1]["text"] == "ZIP"


def test_extract_labels_single_page_and_empty_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_pdfplumber_open(monkeypatch, pages_word_sets=[[]])

    labels_by_page = extract_labels.extract_labels(b"%PDF-1.4", max_workers=1)

    assert labels_by_page == {1: []}


def test_extract_labels_multi_page_parallel_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_pdfplumber_open(
        monkeypatch,
        pages_word_sets=[
            [_word("Patient", 10, 10, 40, 18), _word("Name", 42, 10, 60, 18)],
            [_word("DOB", 10, 12, 24, 20)],
        ],
    )

    labels_by_page = extract_labels.extract_labels(
        b"%PDF-1.4",
        rendered_pages=[{"page_index": 1}, {"page_index": 2}],
        max_workers=2,
    )

    assert sorted(labels_by_page.keys()) == [1, 2]
    assert labels_by_page[1][0]["text"] == "Patient Name"
    assert labels_by_page[2][0]["text"] == "DOB"


# ---------------------------------------------------------------------------
# Edge-case tests added below
# ---------------------------------------------------------------------------


def test_filter_words_with_missing_required_keys_returns_empty() -> None:
    """Words that are missing any of the required keys (text, x0, x1, top,
    bottom) should be silently skipped by the guard at the top of
    _filter_words.  This ensures robustness against malformed PDF
    extraction output."""
    # Each dict is missing at least one required key.
    words_missing_keys = [
        {"text": "Hello"},                             # missing x0, x1, top, bottom
        {"x0": 0, "x1": 10, "top": 0, "bottom": 8},  # missing text
        {"text": "World", "x0": 0, "top": 0, "bottom": 8},  # missing x1
        {"text": "Foo", "x0": 0, "x1": 10, "top": 0},       # missing bottom
        {"text": "Bar", "x0": 0, "x1": 10, "bottom": 8},    # missing top
        {},                                                    # entirely empty dict
    ]

    result = extract_labels._filter_words(words_missing_keys)
    assert result == []


def test_filter_words_with_none_input_returns_empty() -> None:
    """Passing None as the words list should be handled gracefully by the
    'words or []' guard and return an empty list."""
    result = extract_labels._filter_words(None)
    assert result == []
