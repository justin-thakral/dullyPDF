"""
Label extraction from text layers with OCR fallback.

We clean noisy tokens (checkbox glyph artifacts, punctuation-only tokens) and group
words into phrase-level labels to avoid spanning unrelated columns on the same row.
"""

import io
import os
import re
from typing import Dict, List, Optional, Tuple

import pdfplumber

from .checkbox_glyphs import CHECKBOX_CID_RE, CHECKBOX_GLYPHS, CHECKBOX_GLYPH_STR, CHECKBOX_SYMBOL_GLYPHS
from .concurrency import resolve_workers, run_threaded_map
from .config import get_logger

logger = get_logger(__name__)

_PUNCT_ONLY_RE = re.compile(r"^[_\\-|\\u2013\\u2014=]+$")
_QUOTE_ONLY_RE = re.compile(r"^[\\\"'`]+$")
_DOT_ONLY_RE = re.compile(r"^[.]{1,3}$")
_CHECKBOX_ARTIFACT_CORE_RE = re.compile(r"^[0Oo6Dd]{1,4}$")
_BULLET_PREFIX_RE = re.compile(r"^[©0Oo6Dd]{1,2}[)=]+")


def _median(values: List[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def _clean_word_token(text: str) -> str | None:
    """
    Clean a word token extracted from PDF text or OCR.

    Motivation:
    - Some scanned PDFs include a low-quality OCR text layer. pdfplumber will extract those
      tokens (e.g., `oO`, `6`, `0)`), which are *checkbox glyph artifacts*, not real label text.
    - If we keep those tokens, label grouping can produce junk phrases that then steal nearby
      underlines and create false text fields.

    Strategy:
    - Strip known bullet prefixes (`O)=Past` -> `Past`).
    - Drop pure-punctuation noise tokens and obvious checkbox-glyph artifacts.
    - Keep the rest unchanged so real labels remain available to the resolver.
    """
    raw = (text or "").strip()
    if not raw:
        return None

    # Strip checkbox glyph prefixes that are used as visual bullets.
    if CHECKBOX_GLYPH_STR:
        raw = raw.lstrip(CHECKBOX_GLYPH_STR).strip()
        if not raw:
            return None

    compact = re.sub(r"\\s+", "", raw)
    if not compact:
        return None

    # Drop obvious standalone bullet glyphs.
    if compact in {"©", "®", "™"}:
        return None

    # Strip common OCR bullet prefixes that get glued to the next word.
    cleaned = _BULLET_PREFIX_RE.sub("", raw).strip()
    # Some PDFs (or OCR layers) prefix legend text with stray punctuation (e.g. "=Past Condition").
    # This punctuation is not semantically meaningful, but it breaks downstream normalization.
    cleaned = cleaned.lstrip("=").strip()
    if not cleaned:
        return None

    # Drop pure punctuation noise (table rules, divider strokes, stray quotes/dots).
    compact_cleaned = re.sub(r"\\s+", "", cleaned)
    if _PUNCT_ONLY_RE.fullmatch(compact_cleaned) or _QUOTE_ONLY_RE.fullmatch(compact_cleaned) or _DOT_ONLY_RE.fullmatch(compact_cleaned):
        return None

    return cleaned


def _word_looks_like_checkbox_artifact(text: str, w_pt: float, h_pt: float) -> bool:
    """
    Return True when a word token is likely a checkbox/square glyph artifact (not label text).

    We run this on *word tokens*, not grouped phrases, so the bbox is small and the size/aspect
    tests are meaningful.
    """
    token = (text or "").strip()
    if not token:
        return True
    if token in CHECKBOX_GLYPHS or token in CHECKBOX_SYMBOL_GLYPHS:
        return True
    if CHECKBOX_CID_RE.fullmatch(token):
        return True
    size = max(float(w_pt), float(h_pt))
    if size <= 0:
        return True

    compact = re.sub(r"\\s+", "", token)

    # Strip punctuation wrappers and then check for small "O/0/o/6" clusters.
    core = compact.strip("()[]{}<>.,;:+-=*'\\\"|/\\\\")
    if not core:
        core = compact
    if not _CHECKBOX_ARTIFACT_CORE_RE.fullmatch(core):
        return False

    # A common OCR/text-layer artifact is to interpret checkbox/legend squares as:
    # - `oO`, `OO`, `0`, `6` (sometimes with a weird tall/narrow bbox)
    #
    # These tokens are never meaningful label text, but they can poison label->underline
    # matching (e.g., "OO Asthma" stealing a nearby underline).
    #
    # We intentionally drop them regardless of size because in practice they only originate
    # from checkbox squares, legend markers, or low-quality OCR layers.
    return True


def _filter_words(words: List[Dict]) -> List[Dict]:
    """Filter + clean word tokens before grouping them into phrase labels."""
    cleaned_words: List[Dict] = []
    dropped = 0
    for w in words or []:
        text = w.get("text")
        x0 = w.get("x0")
        x1 = w.get("x1")
        top = w.get("top")
        bottom = w.get("bottom")
        if text is None or x0 is None or x1 is None or top is None or bottom is None:
            continue

        new_text = _clean_word_token(str(text))
        if not new_text:
            dropped += 1
            continue
        w_pt = float(x1) - float(x0)
        h_pt = float(bottom) - float(top)
        if _word_looks_like_checkbox_artifact(new_text, w_pt, h_pt):
            dropped += 1
            continue

        # Preserve existing keys used downstream, but replace text with the cleaned version.
        cleaned = dict(w)
        cleaned["text"] = new_text
        cleaned_words.append(cleaned)

    if dropped:
        logger.debug("Filtered %s noise/checkbox-artifact word tokens", dropped)
    return cleaned_words


def _group_words_into_lines(words: List[Dict]) -> List[Dict]:
    """
    Group nearby words into label candidates.

    This intentionally produces *phrase-level* labels rather than one label spanning an entire row.
    Reason:
    - Some forms place multiple labels on the same baseline (e.g., "City  State  ZIP").
    - A naive "one bbox per line" would span across large whitespace between phrases.
    - That causes false overlaps with underline-based field rects and can incorrectly push fields
      below underlines.
    """
    grouped: List[Dict] = []
    heights = []
    for word in words:
        if not {"top", "bottom"} <= set(word.keys()):
            continue
        h = float(word["bottom"]) - float(word["top"])
        if h > 0:
            heights.append(h)
    median_h = _median(heights) or 10.0
    # Scale grouping thresholds by the typical word height so large fonts do not over-merge
    # and small fonts do not over-split label phrases.
    y_tolerance = max(3.0, min(10.0, median_h * 0.6))

    for word in words:
        if not {"text", "top", "bottom", "x0", "x1"} <= set(word.keys()):
            continue
        y_mid = (float(word["top"]) + float(word["bottom"])) / 2
        target_group = None
        for group in grouped:
            if abs(group["y_mid"] - y_mid) <= y_tolerance:
                target_group = group
                break
        if target_group is None:
            target_group = {"y_mid": y_mid, "words": []}
            grouped.append(target_group)
        target_group["words"].append(word)

    labels: List[Dict] = []
    gap_threshold = max(12.0, min(36.0, median_h * 2.4))

    for group in sorted(grouped, key=lambda g: g["y_mid"]):
        tokens = sorted(group["words"], key=lambda w: float(w["x0"]))
        if not tokens:
            continue

        current: List[Dict] = []
        prev_x1 = None
        for tok in tokens:
            x0 = float(tok["x0"])
            if prev_x1 is not None and (x0 - prev_x1) > gap_threshold:
                labels.extend(_tokens_to_labels(current))
                current = []
            current.append(tok)
            prev_x1 = float(tok["x1"])
        labels.extend(_tokens_to_labels(current))

    return labels


def _tokens_to_labels(tokens: List[Dict]) -> List[Dict]:
    if not tokens:
        return []
    text = " ".join(tok["text"] for tok in tokens)
    x0 = min(float(tok["x0"]) for tok in tokens)
    x1 = max(float(tok["x1"]) for tok in tokens)
    top = min(float(tok["top"]) for tok in tokens)
    bottom = max(float(tok["bottom"]) for tok in tokens)
    return [{"text": text, "bbox": [x0, top, x1, bottom]}]


def _extract_labels_from_page(
    page: pdfplumber.page.Page,
    *,
    page_idx: int,
    render: Optional[Dict],
) -> List[Dict]:
    """
    Extract and clean word tokens for a single page, then group them into label phrases.

    Data structures:
    - Input: pdfplumber Page (vector text extraction).
    - Output: list of {text, bbox} label dicts in PDF point coordinates (originTop).
    """
    words = page.extract_words(
        use_text_flow=True,
        keep_blank_chars=False,
        x_tolerance=1.5,
        y_tolerance=2,
    )
    filtered_words = _filter_words(words or [])

    labels = _group_words_into_lines(filtered_words)
    logger.debug(
        "Page %s labels: %s word groups (rotation %s, size %.1fx%.1f pts)",
        page_idx,
        len(labels),
        page.rotation,
        page.width,
        page.height,
    )
    return labels


def _extract_labels_for_page(
    pdf_bytes: bytes,
    *,
    page_idx: int,
    render: Optional[Dict],
) -> Tuple[int, List[Dict]]:
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        page = pdf.pages[page_idx - 1]
        labels = _extract_labels_from_page(page, page_idx=page_idx, render=render)
    return page_idx, labels


def extract_labels(
    pdf_bytes: bytes,
    rendered_pages: Optional[List[Dict]] = None,
    *,
    max_workers: Optional[int] = None,
) -> Dict[int, List[Dict]]:
    """
    Extract page-level label candidates from text blocks using pdfplumber.

    Returns a dict keyed by 1-based page index containing label text and
    bounding boxes (originTop, points).
    """
    labels_by_page: Dict[int, List[Dict]] = {}
    rendered_by_page = {int(p.get("page_index") or 0): p for p in (rendered_pages or [])}
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        page_count = len(pdf.pages)
    logger.info("Extracting label candidates from %s pages", page_count)
    max_workers = max_workers or resolve_workers("labels", default=min(4, os.cpu_count() or 4))

    # Sequential path keeps a single pdfplumber handle (cheaper than reopening per page).
    if max_workers <= 1 or page_count <= 1:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page_idx, page in enumerate(pdf.pages, start=1):
                labels = _extract_labels_from_page(
                    page,
                    page_idx=page_idx,
                    render=rendered_by_page.get(page_idx),
                )
                labels_by_page[page_idx] = labels
        return labels_by_page

    # Parallel path opens the PDF per worker to avoid sharing pdfplumber objects across threads.
    page_indices = list(range(1, page_count + 1))
    results = run_threaded_map(
        page_indices,
        lambda idx: _extract_labels_for_page(
            pdf_bytes, page_idx=idx, render=rendered_by_page.get(idx)
        ),
        max_workers=max_workers,
        label="labels",
    )
    for idx, labels in results:
        labels_by_page[idx] = labels
    return labels_by_page
