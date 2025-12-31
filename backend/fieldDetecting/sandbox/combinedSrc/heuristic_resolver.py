from __future__ import annotations

import math
import os
import re
import statistics
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from .config import DEFAULT_THRESHOLDS, get_logger
from .label_index import LabelIndex
from .rect_builder import (
    make_box_field_rect,
    make_checkbox_rect,
    make_signature_field_rect_from_underline,
    make_text_field_rect_from_underline,
)

logger = get_logger(__name__)

# Toggle granular diagnostics for initials fallback behavior.
DEBUG_INITIALS_FALLBACK = False


def _is_all_caps(text: str) -> bool:
    """
    Return True when `text` is all-caps (ignoring digits/punctuation).

    This is used to identify section headers on scanned forms, which often appear in
    uppercase and should not consume nearby mini-underlines ("____") meant for row items.
    """
    letters = [ch for ch in (text or "") if ch.isalpha()]
    return bool(letters) and all(ch.isupper() for ch in letters)


def _is_all_caps_header_like(text: str) -> bool:
    """
    Heuristic: identify labels that are likely SECTION HEADERS, not input prompts.

    We DO NOT want these labels to match short underscore blanks (morph_short),
    because that creates false text fields (see MSQ pages like "DIGESTIVE TRACT").

    We intentionally keep this conservative:
    - Allow common abbreviations used as real input prompts (ZIP, SSN, DOB, ID, etc.)
    - Avoid treating labels ending with ":" as headers (those are usually prompts)
    """
    raw = (text or "").strip()
    if not raw:
        return False
    if raw.endswith(":"):
        return False
    if not _is_all_caps(raw):
        return False

    # Common, short input abbreviations that should still be allowed as real labels.
    allow = {"SSN", "DOB", "ID", "ZIP", "MRN", "NPI", "TIN", "EIN"}
    compact = re.sub(r"[^A-Z0-9]+", "", raw.upper())
    if compact in allow:
        return False

    letters = [ch for ch in raw if ch.isalpha()]
    # A single 1–3 letter token (e.g., "Y", "N") is not a header; treat as neutral.
    if len(letters) <= 3:
        return False
    return True


def _to_snake_case(text: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", " ", (text or "").strip()).strip()
    if not cleaned:
        return "field"
    return re.sub(r"\s+", "_", cleaned.lower())


def _normalize_prompt_tokens(text: str) -> List[str]:
    tokens = re.findall(r"[a-z0-9]+", (text or "").lower())
    if not tokens:
        return []
    fixups = {
        "ther": "other",
        "lease": "please",
        "hat": "what",
        "hich": "which",
        "ould": "would",
    }
    return [fixups.get(tok, tok) for tok in tokens]


def _paragraph_base_from_label(text: str) -> str:
    raw = (text or "").strip()
    if not raw:
        return "paragraph"
    tokens = _normalize_prompt_tokens(raw)
    if not tokens:
        return "paragraph"
    stopwords = {
        "please",
        "briefly",
        "describe",
        "list",
        "explain",
        "provide",
        "detail",
        "details",
        "state",
        "tell",
        "how",
        "what",
        "which",
        "would",
        "could",
        "should",
        "may",
        "might",
        "any",
        "all",
        "the",
        "a",
        "an",
        "of",
        "for",
        "to",
        "your",
        "you",
        "with",
        "and",
        "or",
        "if",
        "yes",
        "no",
        "does",
        "do",
        "did",
        "are",
        "is",
        "be",
        "as",
        "on",
        "in",
        "at",
        "this",
        "that",
        "these",
        "those",
        "etc",
    }
    filtered = [tok for tok in tokens if tok not in stopwords and len(tok) > 3]
    garbage = {
        "please",
        "what",
        "which",
        "how",
        "where",
        "when",
        "would",
        "could",
        "should",
        "lease",
    }
    while filtered:
        head = filtered[0]
        if head in garbage or any(head == word[1:] for word in garbage if len(word) > 4):
            filtered = filtered[1:]
            continue
        break
    if not filtered:
        return "paragraph"
    base = "_".join(filtered[:4])
    if base in {"please", "how", "what"}:
        return "paragraph"
    return base or "paragraph"


def _next_name(counts: Dict[str, int], base: str) -> str:
    n = counts.get(base, 0) + 1
    counts[base] = n
    return f"{base}_{n}"


def _infer_type_from_label(text: str) -> str:
    lower = (text or "").lower()
    if "signature" in lower:
        return "signature"
    # Keep "date" as an explicit type; downstream injectors may treat it as text.
    if "date" in lower:
        return "date"
    return "text"


def _category_for_confidence(confidence: float, thresholds: Dict[str, float]) -> str:
    if confidence >= thresholds["high"]:
        return "green"
    if confidence >= thresholds["medium"]:
        return "yellow"
    if confidence >= thresholds["min"]:
        return "red"
    return "red"


def _bbox_mid(bbox: List[float]) -> Tuple[float, float]:
    return (bbox[0] + bbox[2]) / 2.0, (bbox[1] + bbox[3]) / 2.0


def _rects_intersect(a: List[float], b: List[float]) -> bool:
    """Axis-aligned bbox intersection in originTop points."""
    if len(a) != 4 or len(b) != 4:
        return False
    return not (a[2] <= b[0] or a[0] >= b[2] or a[3] <= b[1] or a[1] >= b[3])


def _label_is_probably_input(label: Dict, median_label_height: float) -> bool:
    """
    Heuristic filter for pdfplumber-derived label phrases.

    We want to focus on short "prompt-like" labels (e.g., "First name", "Telephone") and
    avoid long paragraphs or section headers.
    """
    text = (label.get("text") or "").strip()
    bbox = label.get("bbox") or []
    if not text or len(bbox) != 4:
        return False

    # Drop tiny OCR/text-layer artifacts that come from checkbox glyphs being misread as text
    # (e.g., "oO", "OO", "0", "6"). These frequently appear near legends and can steal real
    # underlines, creating bogus text fields.
    compact = re.sub(r"\\s+", "", text)
    if re.fullmatch(r"[0Oo6Dd]{1,4}", compact or ""):
        return False

    # Exclude obvious section headers (all-caps). These are not input prompts.
    # This also prevents headers from consuming nearby mini-underlines and creating
    # "random" fields on questionnaire pages.
    if _is_all_caps_header_like(text):
        return False

    # Filter out very long phrases (instruction paragraphs), but allow longer prompt-style
    # questions/colon labels since these often introduce short blanks in clinical forms.
    word_count = len(text.split())
    is_prompt_punct = text.rstrip().endswith(("?", ":"))
    if len(text) > 42 or word_count > 7:
        if not is_prompt_punct and not _label_is_paragraph_prompt(text):
            return False
        if _label_is_paragraph_prompt(text):
            if len(text) > 180 or word_count > 28:
                return False
        else:
            if len(text) > 90 or word_count > 14 or "." in text:
                return False
    normalized = re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()
    if normalized in {"for office use only", "office use only"}:
        return False
    if ":" not in text and "?" not in text:
        if normalized in {"i", "yes", "no", "yes i", "no i"}:
            return False
    if normalized in {"chart", "chart #", "chart number", "chart no"}:
        if not (text.endswith(":") or text.endswith("?")):
            return False
    # Paragraph fragments often start with lowercase and lack prompt punctuation.
    first_alpha = next((ch for ch in text if ch.isalpha()), "")
    if first_alpha and first_alpha.islower():
        lower = text.lower()
        if ":" not in text and "?" not in text and "*" not in text:
            if "email" not in lower and "e-mail" not in lower:
                return False
    # Sentence fragments that end with a period are rarely prompts.
    if text.endswith(".") and ":" not in text:
        if len(text.split()) <= 3:
            return False
    # Short stopword-like fragments are usually OCR splits from longer sentences.
    tokens = re.findall(r"[a-z0-9]+", text.lower())
    if len(tokens) == 1 and len(tokens[0]) <= 4:
        stopwords = {
            "a",
            "an",
            "and",
            "are",
            "as",
            "at",
            "be",
            "been",
            "by",
            "can",
            "do",
            "does",
            "did",
            "for",
            "from",
            "had",
            "has",
            "have",
            "if",
            "in",
            "is",
            "it",
            "may",
            "of",
            "on",
            "or",
            "the",
            "to",
            "was",
            "were",
            "will",
            "with",
            "you",
            "your",
        }
        if tokens[0] in stopwords and not text.endswith((":","?")):
            return False

    height = float(bbox[3]) - float(bbox[1])
    if median_label_height <= 0:
        return True

    # Keep typical label sizes; drop unusually large headers.
    if height > median_label_height * 2.6:
        return False
    # Extremely tiny text is often footnotes / page numbers.
    if height < median_label_height * 0.55:
        return False

    # Skip obvious section markers when they are short but not input prompts.
    lower = text.lower()
    if lower.startswith("section ") and any(ch.isdigit() for ch in lower[:12]):
        return False
    # Some documents use short uppercase headers (e.g., "DATA") that should not become fields.
    # Do not blanket-exclude all-caps labels because legitimate inputs like "ZIP" are common.
    if lower in {"data", "fatca", "crs"}:
        return False
    return True


def _label_looks_like_non_input_header(
    label_text: str,
    label_bbox: List[float],
    *,
    page_width: float,
    page_height: float,
    median_label_height: float,
) -> bool:
    """
    Identify labels that are likely section/title headers, not input prompts.

    Motivation:
    - Scanned forms often contain a centered title block at the top of the page.
      OCR returns these as normal labels, and a greedy label->underline assignment can
      steal real underlines (e.g., "Center for Integrative Medicine" stealing "Today's Date").
    - Section headers inside shaded pills are often larger than normal labels and should not
      become form fields.

    This is intentionally conservative and relies on geometry (position/size) instead of
    hard-coded text lists.
    """
    raw = (label_text or "").strip()
    if not raw or len(label_bbox) != 4:
        return False
    if raw.endswith(":"):
        # Prompts commonly use trailing ":".
        return False

    x1, y1, x2, y2 = [float(v) for v in label_bbox]
    width = max(0.0, x2 - x1)
    height = max(0.0, y2 - y1)
    mid_x = (x1 + x2) / 2.0
    mid_y = (y1 + y2) / 2.0

    lower = raw.lower()
    # Allow common prompts even when they are visually prominent.
    allow_keywords = ("date", "name", "address", "phone", "email", "dob", "ssn", "id")
    if any(k in lower for k in allow_keywords):
        return False

    # Title block near the top: wide, centered, slightly larger than the median label height.
    if page_height > 0 and mid_y <= page_height * 0.25:
        centered = abs(mid_x - (page_width / 2.0)) <= (page_width * 0.18)
        wide = width >= (page_width * 0.22)
        larger = median_label_height <= 0 or height >= (median_label_height * 1.15)
        if centered and wide and larger:
            return True

    # Large section headers (often inside shaded pills) tend to be taller than normal labels.
    if median_label_height > 0 and height >= (median_label_height * 1.80):
        return True

    return False


def _label_looks_like_option_group(text: str) -> bool:
    """
    Legacy no-op placeholder (text-only heuristics removed).
    """
    return False


def _label_looks_like_option_group_geom(
    label_text: str,
    label_bbox: List[float],
    page_labels: List[Dict],
    underline_candidates: List[Dict],
    checkbox_candidates: List[Dict],
    *,
    page_width: float,
    median_label_height: float,
) -> bool:
    """
    Geometry-driven option-group detector.

    Heuristic:
    - Multiple checkbox candidates on the same row.
    - Multiple short labels on that row (often the option words).
    - No nearby underline (if there is, this is likely a prompt with a text blank).
    """
    if len(label_bbox) != 4:
        return False
    if not checkbox_candidates or not page_labels:
        return False
    if _label_has_nearby_underline(
        label_bbox,
        underline_candidates,
        median_label_height=median_label_height,
    ):
        return False

    _, label_mid_y = _bbox_mid(label_bbox)
    row_tol = max(6.0, median_label_height * 0.9)
    short_limit = max(24.0, median_label_height * 4.5)
    short_height = max(10.0, median_label_height * 1.6)
    right_band = label_bbox[2] - max(2.0, median_label_height * 0.4)

    row_labels: List[List[float]] = []
    short_labels = 0
    short_right = 0
    for lb in page_labels:
        lbbox = lb.get("bbox") or []
        if len(lbbox) != 4:
            continue
        _, lb_mid_y = _bbox_mid(lbbox)
        if abs(lb_mid_y - label_mid_y) > row_tol:
            continue
        row_labels.append(lbbox)
        width = float(lbbox[2]) - float(lbbox[0])
        height = float(lbbox[3]) - float(lbbox[1])
        if width <= short_limit and height <= short_height:
            short_labels += 1
            if float(lbbox[0]) >= right_band:
                short_right += 1

    if len(row_labels) < 2:
        return False

    row_checkboxes: List[float] = []
    for cb in checkbox_candidates:
        cbbox = cb.get("bbox") or []
        if len(cbbox) != 4:
            continue
        cb_mid_x, cb_mid_y = _bbox_mid(cbbox)
        if abs(cb_mid_y - label_mid_y) > row_tol:
            continue
        row_checkboxes.append(cb_mid_x)

    if len(row_checkboxes) < 2:
        return False

    checkbox_span = max(row_checkboxes) - min(row_checkboxes) if row_checkboxes else 0.0
    if short_labels >= 2 and short_right >= 1:
        return True
    if short_labels >= 3 and len(row_checkboxes) >= 2:
        return True
    if len(row_checkboxes) >= 3 and checkbox_span >= (page_width * 0.18):
        return True
    return False


GLOBAL_MATCH_MIN_LABELS = int(os.getenv("SANDBOX_GLOBAL_MATCH_MIN_LABELS", "8"))
GLOBAL_MATCH_MIN_LINES = int(os.getenv("SANDBOX_GLOBAL_MATCH_MIN_LINES", "8"))
GLOBAL_MATCH_MAX_PAIRS = int(os.getenv("SANDBOX_GLOBAL_MATCH_MAX_PAIRS", "6000"))
GLOBAL_MATCH_MAX_SCORE = float(os.getenv("SANDBOX_GLOBAL_MATCH_MAX_SCORE", "160"))


def _assign_underlines_globally(
    labels: List[Dict],
    underline_candidates: List[Dict],
    *,
    page_idx: int,
    expected_offset: float,
    blocked_line_ids: set[str],
    footer_bands: Optional[List[Tuple[float, float]]],
    paragraph_bands: Optional[List[Tuple[float, float]]],
    full_width_line_ids: Optional[set[str]],
    split_line_ids: Optional[set[str]],
    page_width: float,
    page_labels: List[Dict],
    median_label_height: float,
) -> Dict[int, Tuple[Dict, float, str]]:
    """
    Greedy global assignment of labels to underlines for dense pages.

    This reduces label->line shifting when many candidates are packed together.
    """
    if len(labels) < GLOBAL_MATCH_MIN_LABELS or len(underline_candidates) < GLOBAL_MATCH_MIN_LINES:
        return {}
    if len(labels) * len(underline_candidates) > GLOBAL_MATCH_MAX_PAIRS:
        return {}

    pairs: List[Tuple[float, int, int]] = []
    label_candidates = 0
    for label_idx, label in enumerate(labels):
        label_text = (label.get("text") or "").strip()
        label_bbox = label.get("bbox") or []
        if len(label_bbox) != 4:
            continue
        if _label_is_paragraph_prompt(label_text):
            continue
        if _label_is_short_question_fragment(
            label_text,
            label_bbox,
            page_labels=page_labels,
            median_label_height=median_label_height,
        ):
            continue

        header_like = _is_all_caps_header_like(label_text)
        label_in_paragraph = _label_in_paragraph_band(label_bbox, paragraph_bands or [])
        colon_label = label_text.endswith(":")
        colon_prompt_like = colon_label and _label_is_prompt_like(label_text)
        colon_requires_long = colon_label and not colon_prompt_like and not _label_supports_other_blank(label_text)
        label_width = max(1.0, float(label_bbox[2]) - float(label_bbox[0]))
        colon_min_len = max(24.0, median_label_height * 2.6, min(120.0, label_width * 1.15))

        found = False
        for line_idx, cand in enumerate(underline_candidates):
            cid = cand.get("id")
            if not cid:
                continue
            if cid in blocked_line_ids:
                continue
            if split_line_ids and cid in split_line_ids:
                continue
            if full_width_line_ids and cid in full_width_line_ids:
                if not _label_supports_full_width_line(label_text):
                    continue
            bbox = cand.get("bbox") or []
            if len(bbox) != 4:
                continue
            length = float(cand.get("length") or (float(bbox[2]) - float(bbox[0])))
            if colon_requires_long and length < colon_min_len:
                continue
            if median_label_height > 0:
                micro_len = max(12.0, median_label_height * 1.5)
                if length <= micro_len and not (
                    _label_supports_micro_underline(label_text)
                    or _label_is_paragraph_prompt(label_text)
                ):
                    continue
            if header_like and cand.get("detector") == "morph_short":
                continue
            if paragraph_bands and _in_footer_band(bbox, paragraph_bands) and not label_in_paragraph:
                if not _label_supports_paragraph_band_line(label_text):
                    _, line_mid_y = _bbox_mid(bbox)
                    _, label_mid_y = _bbox_mid(label_bbox)
                    if abs(line_mid_y - label_mid_y) > max(6.0, median_label_height * 0.6):
                        continue
            if cand.get("detector") == "morph_short" and footer_bands:
                if _in_footer_band(bbox, footer_bands) and not _label_supports_footer_short_line(
                    label_text
                ):
                    continue
            if page_width and page_labels and median_label_height > 0:
                if length >= page_width * 0.75:
                    if _line_has_yes_no_tokens(
                        bbox,
                        page_labels,
                        max_dy=max(8.0, median_label_height * 1.2),
                    ):
                        if not _label_supports_grid_text_line(label_text):
                            continue
            start_tolerance = 15.0 if cand.get("detector") == "morph_short" else 10.0
            score = _score_label_to_line(
                label_bbox,
                bbox,
                expected_offset=expected_offset,
                start_tolerance=start_tolerance,
            )
            if score is None or score > GLOBAL_MATCH_MAX_SCORE:
                continue
            pairs.append((score, label_idx, line_idx))
            found = True
        if found:
            label_candidates += 1

    if label_candidates < max(4, int(len(labels) * 0.4)):
        return {}

    pairs.sort(key=lambda item: item[0])
    used_labels: set[int] = set()
    used_lines: set[int] = set()
    assignments: Dict[int, Tuple[Dict, float, str]] = {}
    for score, label_idx, line_idx in pairs:
        if label_idx in used_labels or line_idx in used_lines:
            continue
        assignments[label_idx] = (underline_candidates[line_idx], score, "right")
        used_labels.add(label_idx)
        used_lines.add(line_idx)

    if assignments:
        logger.debug(
            "Global underline match assigned %s/%s labels on page %s",
            len(assignments),
            len(labels),
            page_idx,
        )
    return assignments


def _label_supports_footer_short_line(text: str) -> bool:
    """
    Allow short underlines in footer regions only when the label is a true prompt.
    """
    raw = (text or "").strip()
    lower = raw.lower()
    if "?" in raw:
        words = re.findall(r"[a-z0-9]+", lower)
        if len(words) <= 6:
            return True
    if ":" in raw:
        if any(key in lower for key in ("signature", "sign", "initial", "date", "dob", "ssn")):
            return True
        if any(key in lower for key in ("name", "phone", "zip", "id")):
            return True
        if len(raw) <= 6:
            return True
        return False
    return any(key in lower for key in ("signature", "sign", "initial", "date"))


def _label_supports_other_blank(text: str) -> bool:
    """
    Return True when a label likely introduces an "Other/specify" free-text blank.
    """
    raw = (text or "").strip()
    if not raw:
        return False
    lower = raw.lower()
    if "other" not in lower and "specify" not in lower and "describe" not in lower:
        return False
    if ":" in raw:
        return True
    if any(key in lower for key in ("specify", "describe")):
        return True
    return False


def _label_supports_left_blank(text: str) -> bool:
    """
    Return True when a label likely matches a short blank to its LEFT.

    This is used for score-style prompts (e.g., "____ Pain") and avoids
    stealing nearby grid separators in dense forms.
    """
    raw = (text or "").strip()
    if not raw:
        return False
    lower = raw.lower()
    if any(key in lower for key in ("score", "rating", "scale", "0-10", "1-10", "1 to 10")):
        return True
    if any(key in lower for key in ("pain", "severity", "level")):
        return True
    return False


def _label_supports_grid_text_line(text: str) -> bool:
    """
    Return True when a label inside checkbox grids likely expects free text input.

    Keep this narrow to avoid turning every yes/no row separator into a text field.
    """
    raw = (text or "").strip()
    if not raw:
        return False
    lower = raw.lower()
    if "if yes" in lower or "if so" in lower:
        return True
    if any(
        key in lower
        for key in (
            "describe",
            "discuss",
            "explain",
            "reason",
            "why",
            "where",
            "when",
            "how many",
            "how much",
            "frequency",
            "duration",
            "list",
            "specify",
            "other",
            "name",
            "address",
            "phone",
            "date",
            "relationship",
            "type",
            "quantity",
            "per day",
            "per week",
            "days per",
        )
    ):
        return True
    if ":" in raw:
        words = re.findall(r"[A-Za-z0-9]+", raw)
        if len(words) <= 5:
            return True
    return False


def _label_is_yes_no_question(text: str) -> bool:
    """
    Return True when the label is a Yes/No question (checkbox-only prompt).

    We use this to avoid matching lines *below* the prompt when the row is meant
    to be answered by checkboxes rather than free-text.
    """
    raw = (text or "").strip()
    if not raw:
        return False
    lower = raw.lower()
    tokens = re.findall(r"[a-z]+", lower)
    if "yes" not in tokens or "no" not in tokens:
        return False
    if ":" in raw:
        return False
    if "?" in raw:
        return True
    prefixes = (
        "do ",
        "does ",
        "did ",
        "are ",
        "is ",
        "was ",
        "were ",
        "have ",
        "has ",
        "had ",
        "can ",
        "could ",
        "would ",
        "should ",
        "will ",
    )
    return any(lower.startswith(prefix) for prefix in prefixes)


def _page_has_checkbox_noise(
    checkbox_candidates: List[Dict],
    page_labels: List[Dict],
    *,
    median_label_height: float,
) -> bool:
    """
    Return True when checkbox candidates look like dense text-layer noise.

    We use this to suppress checkbox creation on non-form pages (e.g., academic papers)
    where circle detection latches onto small letter glyphs.
    """
    if not checkbox_candidates:
        return False
    circle = [
        cb
        for cb in checkbox_candidates
        if str(cb.get("detector") or "").startswith("text_mask_circle")
    ]
    if len(circle) < 40:
        return False
    sizes = [
        min(float(cb["bbox"][2]) - float(cb["bbox"][0]), float(cb["bbox"][3]) - float(cb["bbox"][1]))
        for cb in circle
        if cb.get("bbox") and len(cb.get("bbox") or []) == 4
    ]
    if not sizes:
        return False
    median_size = statistics.median(sizes)
    size_limit = max(4.8, median_label_height * 0.45)
    if median_size > size_limit:
        return False
    total = len(checkbox_candidates)
    circle_share = len(circle) / max(1, total)
    grid_complete = sum(1 for cb in checkbox_candidates if cb.get("detector") == "grid_complete")
    label_count = len(page_labels or [])
    circle_per_label = len(circle) / max(1, label_count)
    if circle_share >= 0.85 and (len(circle) >= 80 or label_count >= 40):
        return True
    if grid_complete >= 80:
        return True
    if len(circle) >= 120 and circle_per_label >= 1.5:
        return True
    return False


def _page_has_text_only_checkbox_noise(
    checkbox_candidates: List[Dict],
    underline_candidates: List[Dict],
    box_candidates: List[Dict],
    *,
    prompt_like_count: int,
    label_count: int,
    median_label_height: float,
) -> bool:
    """
    Return True when a page looks like narrative text (no real blanks) but
    spurious checkbox candidates appear from text glyphs.

    This is intentionally conservative to avoid dropping real checkbox-only pages:
    - Require *some* underline candidates, but only very short ones.
    - Require no box candidates.
    - Require checkbox detectors to come only from text-mask sources.
    - Keep prompt-like label count low.
    """
    if not checkbox_candidates:
        return False
    if box_candidates:
        return False
    if prompt_like_count > 4:
        return False

    allowed_detectors = {
        "text_mask_raw",
        "text_mask_close2",
        "text_mask_close2x2",
        "text_mask_close3",
        "text_mask_circle_raw",
        "text_mask_circle_close2",
        "text_mask_circle_close2x2",
        "text_mask_circle_close3",
        "grid_complete",
    }
    for cb in checkbox_candidates:
        detector = str(cb.get("detector") or "").lower()
        if detector and detector not in allowed_detectors:
            return False

    dense_text = prompt_like_count <= 1 and label_count >= 80
    if dense_text and len(checkbox_candidates) <= 30:
        return True

    line_lengths: List[float] = []
    for ln in underline_candidates or []:
        bbox = ln.get("bbox")
        if not bbox or len(bbox) != 4:
            continue
        length = float(ln.get("length") or (float(bbox[2]) - float(bbox[0])))
        if length > 0:
            line_lengths.append(length)
    if not line_lengths:
        return False
    max_len = max(line_lengths)
    min_line_len = max(40.0, median_label_height * 5.0)
    if max_len >= min_line_len:
        return False
    if len(checkbox_candidates) > 24:
        return False
    return True


def _line_has_grid_text_prompt(
    line_bbox: List[float],
    labels: List[Dict],
    *,
    max_dx: float,
    max_dy: float,
) -> bool:
    """
    Return True when a grid-adjacent line aligns with an open-text prompt label.
    """
    if len(line_bbox) != 4:
        return False
    line_mid_x, line_mid_y = _bbox_mid(line_bbox)
    for label in labels or []:
        label_text = (label.get("text") or "").strip()
        if not _label_supports_grid_text_line(label_text):
            continue
        label_bbox = label.get("bbox") or []
        if len(label_bbox) != 4:
            continue
        lb_mid_x, lb_mid_y = _bbox_mid(label_bbox)
        if abs(lb_mid_y - line_mid_y) > max_dy:
            continue
        if abs(lb_mid_x - line_mid_x) > max_dx:
            continue
        return True
    return False


def _label_is_short_question_fragment(
    label_text: str,
    label_bbox: List[float],
    *,
    page_labels: Optional[List[Dict]] = None,
    median_label_height: float = 0.0,
) -> bool:
    """
    Return True when a short question fragment should be suppressed as a prompt.

    Example: "problem?" on a row that also contains "Describe:" on the right.
    """
    raw = (label_text or "").strip()
    if not raw or len(label_bbox) != 4 or not raw.endswith("?"):
        return False
    tokens = re.findall(r"[a-z]+", raw.lower())
    if not tokens or len(tokens) > 2:
        return False
    allow = {"why", "who", "when", "where", "what", "how", "which"}
    is_wh = tokens[0] in allow
    if is_wh:
        return False
    if not page_labels:
        return False
    _, label_mid_y = _bbox_mid(label_bbox)
    row_tol = max(6.0, median_label_height * 0.9)
    for lb in page_labels:
        if lb is None or lb.get("text") == label_text:
            continue
        text = (lb.get("text") or "").strip()
        if not text:
            continue
        lbbox = lb.get("bbox") or []
        if len(lbbox) != 4:
            continue
        _, lb_mid_y = _bbox_mid(lbbox)
        if abs(lb_mid_y - label_mid_y) > row_tol:
            continue
        if float(lbbox[0]) <= float(label_bbox[0]) + 4.0:
            continue
        lower = text.lower()
        if ":" in text or any(
            key in lower
            for key in ("describe", "discuss", "specify", "explain", "details", "detail")
        ):
            return True
    return False


def _label_supports_initials_blank(text: str) -> bool:
    """
    Return True when a label is plausible context for an initials blank.
    """
    raw = (text or "").strip()
    if not raw:
        return False
    lower = raw.lower()
    if any(key in lower for key in ("initial", "sign", "signature")):
        return True
    words = re.findall(r"[a-z0-9]+", lower)
    alpha_words = [word for word in words if re.search(r"[a-z]", word)]
    letter_count = sum(ch.isalpha() for ch in raw)
    digit_count = sum(ch.isdigit() for ch in raw)
    if len(alpha_words) < 3:
        return False
    if letter_count > 0 and digit_count / max(1, letter_count) > 0.35:
        return False
    return len(words) >= 4 and len(raw) >= 20


def _label_blocks_initials_fallback(text: str) -> bool:
    """
    Return True when a label indicates the line is embedded in sentence text.
    """
    raw = (text or "").strip()
    if not raw:
        return False
    if not re.search(r"[A-Za-z0-9]", raw):
        return False
    if raw.endswith(":") or raw.endswith("?"):
        return False
    if any(key in raw.lower() for key in ("yes", "no", "y", "n")):
        return False
    lower = raw.lower()
    if any(key in lower for key in ("initial", "sign", "signature", "date", "name", "print")):
        return False
    return True


def _label_supports_line_above(text: str) -> bool:
    """
    Return True when a label plausibly sits BELOW its underline.

    Many forms render signature/date labels *under* the line rather than above it.
    We keep this narrow so we do not invert line/label matching for general prompts.
    """
    raw = (text or "").strip().lower()
    if not raw:
        return False
    return any(key in raw for key in ("signature", "sign", "initial", "date", "print"))


def _text_has_word(text: str, word: str) -> bool:
    return re.search(rf"\b{re.escape(word)}\b", text) is not None


def _label_supports_micro_underline(text: str) -> bool:
    raw = (text or "").strip()
    if not raw:
        return False
    if raw.endswith(":") or raw.endswith("?"):
        return True
    lower = raw.lower()
    if any(key in lower for key in ("initial", "sign", "signature")):
        return True
    tokens = re.findall(r"[a-z0-9]+", lower)
    if len(tokens) == 1 and len(tokens[0]) <= 4:
        allow = {"mi", "id", "dob", "ssn", "zip", "age", "mrn", "npi", "tin", "ein", "date"}
        return tokens[0] in allow
    return False


def _label_is_noise_prompt(text: str) -> bool:
    raw = (text or "").strip()
    if not raw:
        return False
    lower = raw.lower()
    if any(key in lower for key in ("inform", "understand")):
        return True
    if "please" in lower and raw.endswith(".") and not raw.endswith((":","?")):
        return True
    if re.search(r"\babove\b", lower) and (":" in raw or "?" in raw):
        return True
    if lower.endswith("to:"):
        return True
    return False


def _label_is_loose_prompt(text: str) -> bool:
    raw = (text or "").strip()
    if not raw:
        return False
    tokens = _normalize_prompt_tokens(raw)
    lower = " ".join(tokens)
    if raw.endswith(":") or raw.endswith("?"):
        return True
    if _label_is_prompt_like(raw) or _label_is_paragraph_prompt(raw):
        return True
    if "please" in lower:
        return True
    if any(key in lower for key in _LONG_PARAGRAPH_PROMPT_KEYWORDS):
        return True
    if any(_text_has_word(lower, key) for key in _PROMPT_LABEL_KEYWORDS):
        return True
    return False


def _collect_option_list_label_indices(
    labels: List[Dict],
    *,
    median_label_height: float,
) -> set[int]:
    """
    Identify labels likely belonging to checkbox option lists (dense, left-aligned stacks).
    """
    if not labels:
        return set()
    candidates = []
    for idx, label in enumerate(labels):
        text = (label.get("text") or "").strip()
        bbox = label.get("bbox") or []
        if not text or len(bbox) != 4:
            continue
        lower = text.lower()
        if "*" in text:
            continue
        if any(
            key in lower
            for key in (
                "name",
                "phone",
                "email",
                "address",
                "date",
                "dob",
                "birth",
                "city",
                "state",
                "zip",
                "relationship",
                "insurance",
                "member",
                "group",
                "contact",
                "id",
            )
        ):
            continue
        if text.endswith(":") or text.endswith("?"):
            continue
        if ":" in text or "?" in text:
            continue
        if len(text) > 28 or len(text.split()) > 5:
            continue
        height = float(bbox[3]) - float(bbox[1])
        if median_label_height > 0 and height > (median_label_height * 1.6):
            continue
        candidates.append((idx, bbox))
    if len(candidates) < 10:
        return set()

    tol = max(10.0, median_label_height * 1.2)
    candidates.sort(key=lambda item: item[1][0])
    clusters: List[List[Tuple[int, List[float]]]] = []
    current = [candidates[0]]
    current_x = candidates[0][1][0]
    for entry in candidates[1:]:
        if abs(entry[1][0] - current_x) <= tol:
            current.append(entry)
            current_x = sum(item[1][0] for item in current) / len(current)
        else:
            clusters.append(current)
            current = [entry]
            current_x = entry[1][0]
    clusters.append(current)

    result: set[int] = set()
    for cluster in clusters:
        if len(cluster) < 10:
            continue
        ys = [item[1][1] for item in cluster] + [item[1][3] for item in cluster]
        if (max(ys) - min(ys)) < (median_label_height * 6.0):
            continue
        for idx, _ in cluster:
            result.add(idx)
    return result


def _label_supports_full_width_line(text: str) -> bool:
    """
    Return True when a full-width line likely represents a real input prompt.
    """
    raw = (text or "").strip()
    if not raw:
        return False
    lower = raw.lower()
    if any(_text_has_word(lower, key) for key in ("signature", "sign")):
        return True
    if "date" in lower:
        words = re.findall(r"[a-z0-9]+", lower)
        return len(words) >= 2
    if any(
        _text_has_word(lower, key)
        for key in (
            "describe",
            "explain",
            "list",
            "detail",
            "details",
            "comment",
            "comments",
            "notes",
            "note",
            "other",
            "reason",
            "why",
            "how",
            "what",
            "symptom",
            "complaint",
            "relationship",
            "contact",
        )
    ):
        return True
    if ":" in raw and any(_text_has_word(lower, key) for key in ("other", "specify", "preference")):
        return True
    if any(_text_has_word(lower, key) for key in ("name", "address", "phone", "email")):
        return len(raw.split()) <= 4
    return False


def _label_supports_paragraph_band_line(text: str) -> bool:
    """
    Return True when a label is a prompt even inside dense text bands.
    """
    raw = (text or "").strip()
    if not raw:
        return False
    lower = raw.lower()
    if "*" in raw or raw.endswith((":","?")):
        return True
    if any(
        key in lower
        for key in (
            "name",
            "date",
            "dob",
            "birth",
            "phone",
            "email",
            "address",
            "city",
            "state",
            "zip",
            "relationship",
            "member",
            "group",
            "insurance",
            "contact",
        )
    ):
        return True
    return False


def _label_supports_split_line(text: str) -> bool:
    """
    Return True when a label looks like a prompt for a multi-column line.
    """
    raw = (text or "").strip()
    if not raw:
        return False
    lower = raw.lower()
    if "*" in raw or raw.endswith(":") or raw.endswith("?"):
        return True
    if any(
        key in lower
        for key in (
            "name",
            "phone",
            "email",
            "address",
            "date",
            "dob",
            "birth",
            "city",
            "state",
            "zip",
            "relationship",
            "insurance",
            "member",
            "group",
            "contact",
            "id",
        )
    ):
        return True
    return False


def _label_min_line_dy(
    label_bbox: List[float],
    underline_candidates: List[Dict],
    *,
    min_overlap: float,
) -> Optional[float]:
    """
    Return the minimum dy to any underline below the label with sufficient overlap.
    """
    if len(label_bbox) != 4 or not underline_candidates:
        return None
    lx1, ly1, lx2, ly2 = [float(v) for v in label_bbox]
    label_width = max(1.0, lx2 - lx1)
    best = None
    for ln in underline_candidates:
        bbox = ln.get("bbox") or []
        if len(bbox) != 4:
            continue
        ux1, uy1, ux2, _ = [float(v) for v in bbox]
        if uy1 < (ly2 - 1.0):
            continue
        overlap = min(lx2, ux2) - max(lx1, ux1)
        if overlap <= 0:
            continue
        if (overlap / label_width) < min_overlap:
            continue
        dy = uy1 - ly2
        if best is None or dy < best:
            best = dy
    return best


def _line_has_yes_no_tokens(
    line_bbox: List[float],
    labels: List[Dict],
    *,
    max_dy: float,
    min_hits: int = 2,
) -> bool:
    """
    Return True when a line sits on the same row as Yes/No option labels.
    """
    if len(line_bbox) != 4:
        return False
    line_mid_y = (float(line_bbox[1]) + float(line_bbox[3])) / 2.0
    line_x1, line_x2 = float(line_bbox[0]), float(line_bbox[2])
    hits = 0
    for label in labels or []:
        text = (label.get("text") or "").strip().lower()
        if not text:
            continue
        tokens = re.findall(r"[a-z]+", text)
        if not tokens or not any(tok in {"yes", "no", "y", "n"} for tok in tokens):
            continue
        bbox = label.get("bbox") or []
        if len(bbox) != 4:
            continue
        _, lb_mid_y = _bbox_mid(bbox)
        if abs(lb_mid_y - line_mid_y) > max_dy:
            continue
        lb_mid_x = (float(bbox[0]) + float(bbox[2])) / 2.0
        if lb_mid_x < (line_x1 - 6.0) or lb_mid_x > (line_x2 + 6.0):
            continue
        hits += 1
        if hits >= min_hits:
            return True
    return False


def _label_row_has_yes_no_tokens(
    label_bbox: List[float],
    labels: List[Dict],
    *,
    median_label_height: float,
) -> bool:
    """
    Return True when Yes/No tokens appear on the same row as the label.
    """
    if len(label_bbox) != 4:
        return False
    if not labels:
        return False
    _, label_mid_y = _bbox_mid(label_bbox)
    row_tol = max(6.0, median_label_height * 1.1)
    seen_yes = False
    seen_no = False
    for lb in labels or []:
        text = (lb.get("text") or "").strip().lower()
        if not text:
            continue
        lbbox = lb.get("bbox") or []
        if len(lbbox) != 4:
            continue
        _, lb_mid_y = _bbox_mid(lbbox)
        if abs(lb_mid_y - label_mid_y) > row_tol:
            continue
        tokens = re.findall(r"[a-z]+", text)
        if any(tok in {"yes", "y"} for tok in tokens):
            seen_yes = True
        if any(tok in {"no", "n"} for tok in tokens):
            seen_no = True
        if seen_yes and seen_no:
            return True
    return False


def _label_row_has_checkboxes(
    label_bbox: List[float],
    checkbox_candidates: List[Dict],
    *,
    median_label_height: float,
    max_dx: float,
) -> bool:
    """
    Return True when checkbox candidates appear on the same row as the label.
    """
    if len(label_bbox) != 4 or not checkbox_candidates:
        return False
    label_mid_x, label_mid_y = _bbox_mid(label_bbox)
    row_tol = max(12.0, median_label_height * 2.5)
    for cb in checkbox_candidates or []:
        cb_bbox = cb.get("bbox") or []
        if len(cb_bbox) != 4:
            continue
        cb_mid_x, cb_mid_y = _bbox_mid(cb_bbox)
        if abs(cb_mid_y - label_mid_y) > row_tol:
            continue
        if abs(cb_mid_x - label_mid_x) > max_dx:
            continue
        return True
    return False


def _label_has_nearby_underline(
    label_bbox: List[float],
    underline_candidates: List[Dict],
    *,
    median_label_height: float,
) -> bool:
    """
    Return True when a label has a nearby underline (right-of-row or just below).
    """
    if len(label_bbox) != 4 or not underline_candidates:
        return False
    lx1, ly1, lx2, ly2 = [float(v) for v in label_bbox]
    label_mid_y = (ly1 + ly2) / 2.0
    label_width = max(1.0, lx2 - lx1)
    row_tol = max(10.0, median_label_height * 1.4)
    below_tol = max(16.0, median_label_height * 2.6)
    min_len = max(12.0, median_label_height * 1.5)
    for ln in underline_candidates:
        bbox = ln.get("bbox") or []
        if len(bbox) != 4:
            continue
        length = float(ln.get("length") or (float(bbox[2]) - float(bbox[0])))
        if length < min_len:
            continue
        line_mid_y = (float(bbox[1]) + float(bbox[3])) / 2.0
        if abs(line_mid_y - label_mid_y) <= row_tol and float(bbox[0]) >= (lx2 - 6.0):
            return True
        if float(bbox[1]) >= (ly2 - 2.0):
            dy = float(bbox[1]) - ly2
            if dy > below_tol:
                continue
            overlap = min(float(bbox[2]), lx2) - max(float(bbox[0]), lx1)
            if overlap <= 0.0:
                continue
            if (overlap / label_width) >= 0.25:
                return True
    return False


def _compute_full_width_line_ids(
    underline_candidates: List[Dict],
    *,
    page_width: float,
    median_label_height: float,
) -> set[str]:
    """
    Identify dense clusters of full-width lines that are likely row separators.
    """
    if page_width <= 0:
        return set()
    margin = max(6.0, page_width * 0.02)
    min_len = page_width * 0.75
    entries = []
    for ln in underline_candidates or []:
        cid = ln.get("id")
        bbox = ln.get("bbox")
        if not cid or not bbox or len(bbox) != 4:
            continue
        length = float(ln.get("length") or (float(bbox[2]) - float(bbox[0])))
        if length < min_len:
            continue
        if float(bbox[0]) > margin:
            continue
        if float(bbox[2]) < (page_width - margin):
            continue
        _, mid_y = _bbox_mid(bbox)
        entries.append((mid_y, cid))
    if len(entries) < 6:
        return set()
    entries.sort(key=lambda item: item[0])
    gap_tol = max(14.0, min(36.0, median_label_height * 3.0))
    dense_gaps = sum(
        1
        for idx in range(len(entries) - 1)
        if (entries[idx + 1][0] - entries[idx][0]) <= gap_tol
    )
    if dense_gaps < 4:
        return set()
    return {cid for _, cid in entries}


def _compute_paragraph_line_bands(
    labels: List[Dict],
    *,
    page_width: float,
    median_label_height: float,
) -> List[Tuple[float, float]]:
    """
    Identify dense text lines that represent paragraphs, not prompts.
    """
    if not labels:
        return []

    line_tol = max(2.0, median_label_height * 0.6)
    entries = []
    for lb in labels:
        bbox = lb.get("bbox") or []
        if len(bbox) != 4:
            continue
        _, mid_y = _bbox_mid(bbox)
        text = (lb.get("text") or "").strip()
        char_count = sum(ch.isalnum() for ch in text)
        height = float(bbox[3]) - float(bbox[1])
        entries.append((mid_y, bbox, char_count, height))
    if not entries:
        return []

    entries.sort(key=lambda item: item[0])
    clusters: List[List[Tuple[float, List[float], int, float]]] = []
    current = [entries[0]]
    current_mid = entries[0][0]
    for entry in entries[1:]:
        if abs(entry[0] - current_mid) <= line_tol:
            current.append(entry)
            current_mid = sum(item[0] for item in current) / len(current)
        else:
            clusters.append(current)
            current = [entry]
            current_mid = entry[0]
    clusters.append(current)

    bands: List[Tuple[float, float]] = []
    for cluster in clusters:
        count = len(cluster)
        min_x = min(item[1][0] for item in cluster)
        max_x = max(item[1][2] for item in cluster)
        total_chars = sum(item[2] for item in cluster)
        avg_height = sum(item[3] for item in cluster) / count
        width = max_x - min_x

        dense = False
        if count >= 4 and width >= page_width * 0.50:
            dense = True
        elif count >= 3 and width >= page_width * 0.50:
            dense = True
        elif total_chars >= 35 and width >= page_width * 0.40:
            dense = True
        elif count >= 3 and total_chars >= 24 and width >= page_width * 0.55:
            dense = True

        if not dense:
            continue
        if median_label_height > 0 and avg_height > median_label_height * 1.35:
            continue

        min_y = min(item[1][1] for item in cluster) - line_tol
        max_y = max(item[1][3] for item in cluster) + line_tol
        bands.append((min_y, max_y))
    return bands


def _label_in_paragraph_band(label_bbox: List[float], bands: List[Tuple[float, float]]) -> bool:
    if len(label_bbox) != 4 or not bands:
        return False
    _, mid_y = _bbox_mid(label_bbox)
    return any(lower <= mid_y <= upper for lower, upper in bands)


def _line_in_paragraph_band(line_bbox: List[float], bands: List[Tuple[float, float]]) -> bool:
    if len(line_bbox) != 4 or not bands:
        return False
    _, mid_y = _bbox_mid(line_bbox)
    return any(lower <= mid_y <= upper for lower, upper in bands)


def _label_is_paragraph_prompt(text: str) -> bool:
    raw = (text or "").strip()
    if not raw:
        return False
    if _is_all_caps(raw):
        return False
    tokens = _normalize_prompt_tokens(raw)
    lower = " ".join(tokens)
    words = tokens
    has_prompt_punct = raw.endswith(":") or raw.endswith("?")
    if has_prompt_punct:
        if _label_supports_other_blank(raw):
            return True
        if raw.endswith("?") and len(words) <= 6:
            return True
        if len(words) <= 6 and any(key in lower for key in _PARAGRAPH_PROMPT_KEYWORDS):
            return True
        if len(words) <= 26 and any(key in lower for key in _LONG_PARAGRAPH_PROMPT_KEYWORDS):
            return True
        return False
    if raw.endswith("."):
        if len(words) <= 32 and any(key in lower for key in _LONG_PARAGRAPH_PROMPT_KEYWORDS):
            return True
        if len(words) <= 18 and any(key in lower for key in _PARAGRAPH_PROMPT_KEYWORDS):
            return True
        return False
    if len(words) <= 4 and any(key in lower for key in _PARAGRAPH_PROMPT_KEYWORDS):
        return True
    if len(words) <= 12 and any(key in lower for key in _LONG_PARAGRAPH_PROMPT_KEYWORDS):
        return True
    if "(" in raw and ")" in raw:
        if any(key in lower for key in _LONG_PARAGRAPH_PROMPT_KEYWORDS):
            return True
    return False


_PROMPT_LABEL_KEYWORDS = (
    "name",
    "date",
    "dob",
    "birth",
    "age",
    "sex",
    "gender",
    "phone",
    "email",
    "address",
    "city",
    "state",
    "zip",
    "county",
    "member",
    "policy",
    "group",
    "plan",
    "insurance",
    "provider",
    "facility",
    "fax",
    "signature",
    "sign",
    "initial",
    "print",
    "relationship",
    "contact",
    "employer",
    "diagnosis",
    "assessment",
    "history",
    "objective",
    "subjective",
    "impression",
    "recommendation",
    "notes",
    "comment",
    "comments",
    "reason",
    "symptom",
    "complaint",
    "mrn",
    "ssn",
    "id",
    "npi",
    "tin",
    "ein",
    "type",
    "quantity",
    "dosage",
    "dose",
    "frequency",
    "amount",
)

_PARAGRAPH_PROMPT_KEYWORDS = (
    "name",
    "date",
    "dob",
    "birth",
    "age",
    "sex",
    "gender",
    "phone",
    "email",
    "address",
    "city",
    "state",
    "zip",
    "signature",
    "sign",
    "initial",
    "print",
    "relationship",
    "contact",
    "member",
    "policy",
    "group",
    "plan",
    "insurance",
    "provider",
    "facility",
    "fax",
    "ssn",
    "id",
    "mrn",
    "npi",
    "tin",
    "ein",
)

_LONG_PARAGRAPH_PROMPT_KEYWORDS = (
    "please",
    "describe",
    "list",
    "explain",
    "provide",
    "detail",
    "details",
    "reason",
    "why",
    "what",
    "how",
    "briefly",
    "current",
    "previous",
    "history",
    "medication",
    "medications",
    "dosage",
    "response",
    "side effect",
    "side effects",
    "additional",
    "benefits",
    "drawbacks",
    "visit",
)


def _label_is_prompt_like(text: str) -> bool:
    raw = (text or "").strip()
    if not raw:
        return False
    if _label_is_paragraph_prompt(raw):
        return True
    tokens = _normalize_prompt_tokens(raw)
    if not tokens:
        return False
    if len(tokens) > 6:
        return False
    lower = " ".join(tokens)
    if raw.endswith("?"):
        return True
    if raw.endswith(":"):
        if _label_supports_other_blank(raw):
            return True
        if len(tokens) <= 5:
            return True
        return any(_text_has_word(lower, key) for key in _PROMPT_LABEL_KEYWORDS)
    return any(_text_has_word(lower, key) for key in _PROMPT_LABEL_KEYWORDS)


def _count_prompt_like_labels(
    labels: List[Dict],
    *,
    paragraph_bands: List[Tuple[float, float]],
) -> int:
    count = 0
    for label in labels or []:
        label_text = (label.get("text") or "").strip()
        label_bbox = label.get("bbox") or []
        if len(label_bbox) != 4:
            continue
        if paragraph_bands and _label_in_paragraph_band(label_bbox, paragraph_bands):
            continue
        if _label_is_prompt_like(label_text):
            count += 1
    return count


def _line_has_prompt_label_nearby(
    line_bbox: List[float],
    labels: List[Dict],
    *,
    max_dx: float,
    max_dy: float,
) -> bool:
    """
    Return True when a line candidate is near a label that looks like a prompt.
    """
    if len(line_bbox) != 4:
        return False
    line_mid_x, line_mid_y = _bbox_mid(line_bbox)
    for label in labels or []:
        label_text = (label.get("text") or "").strip()
        if not _label_is_loose_prompt(label_text):
            continue
        label_bbox = label.get("bbox") or []
        if len(label_bbox) != 4:
            continue
        lb_mid_x, lb_mid_y = _bbox_mid(label_bbox)
        if abs(lb_mid_y - line_mid_y) > max_dy:
            continue
        if abs(lb_mid_x - line_mid_x) > max_dx:
            continue
        return True
    return False


def _line_has_prompt_label_nearby_strict(
    line_bbox: List[float],
    labels: List[Dict],
    *,
    max_dx: float,
    max_dy: float,
    paragraph_bands: List[Tuple[float, float]],
) -> bool:
    if len(line_bbox) != 4:
        return False
    line_mid_x, line_mid_y = _bbox_mid(line_bbox)
    for label in labels or []:
        label_text = (label.get("text") or "").strip()
        if not _label_is_loose_prompt(label_text):
            continue
        label_bbox = label.get("bbox") or []
        if len(label_bbox) != 4:
            continue
        if paragraph_bands and _label_in_paragraph_band(label_bbox, paragraph_bands):
            continue
        lb_mid_x, lb_mid_y = _bbox_mid(label_bbox)
        if abs(lb_mid_y - line_mid_y) > max_dy:
            continue
        if abs(lb_mid_x - line_mid_x) > max_dx:
            continue
        return True
    return False


def _line_has_prompt_label_nearby_below(
    line_bbox: List[float],
    labels: List[Dict],
    *,
    max_dx: float,
    max_dy: float,
    min_label_y: float,
) -> bool:
    if len(line_bbox) != 4:
        return False
    line_mid_x, line_mid_y = _bbox_mid(line_bbox)
    for label in labels or []:
        label_text = (label.get("text") or "").strip()
        if not _label_is_loose_prompt(label_text):
            continue
        label_bbox = label.get("bbox") or []
        if len(label_bbox) != 4:
            continue
        _, lb_mid_y = _bbox_mid(label_bbox)
        if lb_mid_y < min_label_y:
            continue
        if abs(lb_mid_y - line_mid_y) > max_dy:
            continue
        lb_mid_x = (float(label_bbox[0]) + float(label_bbox[2])) / 2.0
        if abs(lb_mid_x - line_mid_x) > max_dx:
            continue
        return True
    return False


def _compose_row_label_text(
    label: Dict,
    labels: List[Dict],
    *,
    median_label_height: float,
    page_width: float,
) -> str:
    if not label:
        return ""
    label_text = (label.get("text") or "").strip()
    label_bbox = label.get("bbox") or []
    if len(label_bbox) != 4:
        return label_text
    _, label_mid_y = _bbox_mid(label_bbox)
    row_tol = max(6.0, median_label_height * 0.9)
    left_edge = float(label_bbox[0]) - 8.0
    right_edge = float(label_bbox[2]) + max(260.0, page_width * 0.6)

    row_labels = []
    for lb in labels or []:
        text = (lb.get("text") or "").strip()
        bbox = lb.get("bbox") or []
        if not text or len(bbox) != 4:
            continue
        _, mid_y = _bbox_mid(bbox)
        if abs(mid_y - label_mid_y) > row_tol:
            continue
        if float(bbox[0]) < left_edge or float(bbox[0]) > right_edge:
            continue
        row_labels.append((float(bbox[0]), text))

    if not row_labels:
        return label_text
    row_labels.sort(key=lambda item: item[0])
    joined = " ".join(text for _, text in row_labels)
    joined = re.sub(r"[\\x00-\\x1f\\x7f]+", " ", joined)
    joined = re.sub(r"\\s+", " ", joined).strip()
    return joined or label_text


def _compose_prompt_text_above_line(
    line_bbox: List[float],
    labels: List[Dict],
    *,
    median_label_height: float,
    page_width: float,
    max_dy: float,
) -> str:
    if len(line_bbox) != 4:
        return ""
    line_x1, line_y1, line_x2, _ = [float(v) for v in line_bbox]
    min_y = line_y1 - max_dy
    max_y = line_y1 + max(4.0, median_label_height * 0.6)
    labels_in_band = []
    for lb in labels or []:
        text = (lb.get("text") or "").strip()
        bbox = lb.get("bbox") or []
        if not text or len(bbox) != 4:
            continue
        _, mid_y = _bbox_mid(bbox)
        if mid_y < min_y or mid_y > max_y:
            continue
        if float(bbox[2]) < (line_x1 - 6.0) or float(bbox[0]) > (line_x2 + 6.0):
            continue
        labels_in_band.append((float(bbox[1]), float(bbox[0]), text))
    if not labels_in_band:
        return ""
    labels_in_band.sort()
    joined = " ".join(text for _, _, text in labels_in_band)
    joined = re.sub(r"[\\x00-\\x1f\\x7f]+", " ", joined)
    joined = re.sub(r"\\s+", " ", joined).strip()
    return joined


def _collect_paragraph_line_group(
    anchor_line: Dict,
    underline_candidates: List[Dict],
    *,
    used_ids: set[str],
    blocked_line_ids: set[str],
    paragraph_line_ids: set[str],
    page_labels: List[Dict],
    median_label_height: float,
    page_width: float,
    table_region: Optional[List[float]],
) -> List[Dict]:
    if not anchor_line or not underline_candidates:
        return []
    anchor_bbox = anchor_line.get("bbox") or []
    if len(anchor_bbox) != 4:
        return []
    base_x1, base_y1, base_x2, base_y2 = [float(v) for v in anchor_bbox]
    base_len = max(1.0, base_x2 - base_x1)
    max_gap = max(14.0, median_label_height * 2.4)
    x_tol = max(12.0, base_len * 0.08)
    overlap_ratio_min = 0.6
    len_ratio_min = 0.55
    len_ratio_max = 1.45
    row_prompt_dy = max(6.0, median_label_height * 1.0)
    row_prompt_dx = max(120.0, page_width * 0.45) if page_width else 180.0

    candidates = []
    for ln in underline_candidates:
        if ln is anchor_line:
            continue
        bbox = ln.get("bbox") or []
        if len(bbox) != 4:
            continue
        if float(bbox[1]) <= base_y1 + 1.0:
            continue
        candidates.append(ln)
    candidates.sort(key=lambda ln: float((ln.get("bbox") or [0, 0, 0, 0])[1]))

    lines = [anchor_line]
    prev_y1 = base_y1
    for ln in candidates:
        cid = ln.get("id")
        if cid and cid in used_ids:
            continue
        if cid and cid in blocked_line_ids and cid not in paragraph_line_ids:
            # Allow paragraph line recovery to override generic blocking when it is
            # tightly aligned with the anchor underline.
            pass
        bbox = ln.get("bbox") or []
        if len(bbox) != 4:
            continue
        if table_region and _rects_intersect(bbox, table_region):
            continue
        y1 = float(bbox[1])
        if (y1 - prev_y1) > max_gap:
            break
        if _line_has_prompt_label_nearby_below(
            bbox,
            page_labels,
            max_dx=row_prompt_dx,
            max_dy=row_prompt_dy,
            min_label_y=base_y1 - 2.0,
        ):
            break
        x1, _, x2, _ = [float(v) for v in bbox]
        length = max(1.0, x2 - x1)
        len_ratio = length / base_len
        if len_ratio < len_ratio_min or len_ratio > len_ratio_max:
            break
        overlap = min(base_x2, x2) - max(base_x1, x1)
        overlap_ratio = overlap / max(1.0, min(base_len, length))
        if overlap_ratio < overlap_ratio_min:
            break
        if abs(x1 - base_x1) > x_tol and abs(x2 - base_x2) > x_tol:
            break
        lines.append(ln)
        prev_y1 = y1
    return lines


def _multiline_rect_from_underlines(
    lines: List[Dict],
    calibration: Dict,
    page_width: float,
    page_height: float,
    label_bboxes: List[List[float]],
) -> Optional[List[float]]:
    rects: List[List[float]] = []
    for ln in lines:
        bbox = ln.get("bbox") or []
        if len(bbox) != 4:
            continue
        rects.append(
            make_text_field_rect_from_underline(
                bbox, calibration, page_width, page_height, label_bboxes
            )
        )
    if not rects:
        return None
    x1 = min(rect[0] for rect in rects)
    y1 = min(rect[1] for rect in rects)
    x2 = max(rect[2] for rect in rects)
    y2 = max(rect[3] for rect in rects)
    return [x1, y1, x2, y2]

def _line_has_left_blocking_label(
    line_bbox: List[float],
    labels: List[Dict],
    *,
    max_dx: float,
    max_dy: float,
) -> bool:
    """
    Return True when a line sits immediately after regular sentence text.
    """
    if len(line_bbox) != 4:
        return False
    line_mid_y = (float(line_bbox[1]) + float(line_bbox[3])) / 2.0
    for label in labels or []:
        label_text = (label.get("text") or "").strip()
        if not _label_blocks_initials_fallback(label_text):
            continue
        label_bbox = label.get("bbox") or []
        if len(label_bbox) != 4:
            continue
        _, lb_mid_y = _bbox_mid(label_bbox)
        if abs(lb_mid_y - line_mid_y) > max_dy:
            continue
        if float(label_bbox[2]) > float(line_bbox[0]) - 1.0:
            continue
        gap = float(line_bbox[0]) - float(label_bbox[2])
        if gap <= max_dx:
            return True
    return False


def _compute_footer_noise_bands(
    labels: List[Dict],
    *,
    page_width: float,
    page_height: float,
    median_label_height: float,
) -> List[Tuple[float, float]]:
    """
    Identify footer text lines so we can avoid matching short underlines to sentences.

    We cluster label bboxes by baseline (mid_y) and treat wide, dense lines near the
    bottom of the page as footers (addresses, hyperlinks, instructions).
    """
    if not labels or page_height <= 0:
        return []

    line_tol = max(2.0, median_label_height * 0.6)
    entries = []
    for lb in labels:
        bbox = lb.get("bbox") or []
        if len(bbox) != 4:
            continue
        _, mid_y = _bbox_mid(bbox)
        height = float(bbox[3]) - float(bbox[1])
        entries.append((mid_y, bbox, height))
    if not entries:
        return []

    entries.sort(key=lambda item: item[0])
    clusters: List[List[Tuple[float, List[float], float]]] = []
    current = [entries[0]]
    current_mid = entries[0][0]
    for entry in entries[1:]:
        if abs(entry[0] - current_mid) <= line_tol:
            current.append(entry)
            current_mid = sum(item[0] for item in current) / len(current)
        else:
            clusters.append(current)
            current = [entry]
            current_mid = entry[0]
    clusters.append(current)

    bands: List[Tuple[float, float]] = []
    for cluster in clusters:
        count = len(cluster)
        mid_y = sum(item[0] for item in cluster) / count
        if mid_y < page_height * 0.60:
            continue
        min_x = min(item[1][0] for item in cluster)
        max_x = max(item[1][2] for item in cluster)
        avg_height = sum(item[2] for item in cluster) / count
        if count < 3:
            continue
        if (max_x - min_x) < page_width * 0.45:
            continue
        if median_label_height > 0 and avg_height > median_label_height * 1.2:
            continue
        min_y = min(item[1][1] for item in cluster) - line_tol
        max_y = max(item[1][3] for item in cluster) + line_tol
        bands.append((min_y, max_y))
    return bands


def _in_footer_band(bbox: List[float], bands: List[Tuple[float, float]]) -> bool:
    if len(bbox) != 4 or not bands:
        return False
    _, mid_y = _bbox_mid(bbox)
    return any(lower <= mid_y <= upper for lower, upper in bands)


def _intersection_area(a: List[float], b: List[float]) -> float:
    if len(a) != 4 or len(b) != 4:
        return 0.0
    ix1 = max(float(a[0]), float(b[0]))
    iy1 = max(float(a[1]), float(b[1]))
    ix2 = min(float(a[2]), float(b[2]))
    iy2 = min(float(a[3]), float(b[3]))
    if ix2 <= ix1 or iy2 <= iy1:
        return 0.0
    return (ix2 - ix1) * (iy2 - iy1)


def _short_line_overlaps_label_text(
    line_bbox: List[float],
    labels: List[Dict],
    *,
    min_overlap: float = 0.7,
    min_label_chars: int = 2,
) -> bool:
    """
    Return True when a short underline sits inside label text, indicating OCR baseline noise.
    """
    if len(line_bbox) != 4:
        return False
    line_area = max(0.0, float(line_bbox[2]) - float(line_bbox[0])) * max(
        0.0, float(line_bbox[3]) - float(line_bbox[1])
    )
    if line_area <= 0.0:
        return False
    for label in labels or []:
        label_text = (label.get("text") or "").strip()
        if sum(ch.isalnum() for ch in label_text) < min_label_chars:
            continue
        label_bbox = label.get("bbox") or []
        if len(label_bbox) != 4:
            continue
        if not _rects_intersect(line_bbox, label_bbox):
            continue
        overlap = _intersection_area(line_bbox, label_bbox)
        if overlap <= 0.0:
            continue
        if (overlap / line_area) >= min_overlap:
            return True
    return False


def _line_overlaps_label_text(
    line_bbox: List[float],
    labels: List[Dict],
    *,
    min_overlap: float = 0.6,
    min_label_chars: int = 3,
    expand_down: float = 0.0,
) -> bool:
    """
    Return True when an underline candidate overlaps label text heavily.

    This is used to detect text-baseline artifacts on narrative pages where
    line detection follows sentence glyphs instead of real input blanks.
    """
    if len(line_bbox) != 4:
        return False
    line_area = max(0.0, float(line_bbox[2]) - float(line_bbox[0])) * max(
        0.0, float(line_bbox[3]) - float(line_bbox[1])
    )
    if line_area <= 0.0:
        return False
    for label in labels or []:
        label_text = (label.get("text") or "").strip()
        if sum(ch.isalnum() for ch in label_text) < min_label_chars:
            continue
        label_bbox = label.get("bbox") or []
        if len(label_bbox) != 4:
            continue
        if expand_down > 0.0:
            label_bbox = [
                float(label_bbox[0]),
                float(label_bbox[1]),
                float(label_bbox[2]),
                float(label_bbox[3]) + float(expand_down),
            ]
        if not _rects_intersect(line_bbox, label_bbox):
            continue
        overlap = _intersection_area(line_bbox, label_bbox)
        if overlap <= 0.0:
            continue
        if (overlap / line_area) >= min_overlap:
            return True
    return False


def _collect_text_line_noise_ids(
    underline_candidates: List[Dict],
    labels: List[Dict],
    *,
    prompt_like_count: int,
    median_label_height: float,
) -> set[str]:
    """
    Identify underline candidates that are likely text baselines on narrative pages.

    We only activate this when:
    - prompt-like labels are scarce,
    - the page contains many label fragments (dense text),
    - and a majority of underline candidates overlap text rows.
    """
    if prompt_like_count > 2:
        return set()
    label_count = len(labels or [])
    if label_count < 40:
        return set()

    valid_lines = [
        ln
        for ln in (underline_candidates or [])
        if ln.get("bbox") and len(ln.get("bbox")) == 4
    ]
    if len(valid_lines) < 12:
        return set()
    if prompt_like_count == 0 and label_count >= 70:
        return {ln.get("id") for ln in valid_lines if ln.get("id")}

    expand_down = max(0.0, median_label_height * 0.8)
    noisy_ids: set[str] = set()
    for ln in valid_lines:
        cid = ln.get("id")
        bbox = ln.get("bbox")
        if not cid:
            continue
        if _line_overlaps_label_text(
            bbox,
            labels,
            min_overlap=0.6,
            min_label_chars=3,
            expand_down=expand_down,
        ):
            noisy_ids.add(cid)

    total = len(valid_lines)
    if total <= 0:
        return set()
    overlap_ratio_threshold = 0.55
    if label_count >= 120 and prompt_like_count <= 1:
        overlap_ratio_threshold = 0.3
    if (len(noisy_ids) / total) < overlap_ratio_threshold:
        return set()
    return noisy_ids


def _short_line_is_text_artifact(
    line_bbox: List[float],
    labels: List[Dict],
    *,
    median_label_height: float,
) -> bool:
    """
    Detect short line candidates that are actually fragments of label text baselines.
    """
    if _short_line_overlaps_label_text(line_bbox, labels, min_overlap=0.7):
        return True
    if len(line_bbox) != 4:
        return False
    line_width = max(0.0, float(line_bbox[2]) - float(line_bbox[0]))
    if line_width <= 0.0:
        return False
    line_mid_y = (float(line_bbox[1]) + float(line_bbox[3])) / 2.0
    line_tol = max(3.0, median_label_height * 1.8)

    overlap_hits = 0
    for label in labels or []:
        label_text = (label.get("text") or "").strip()
        if sum(ch.isalnum() for ch in label_text) < 2:
            continue
        label_bbox = label.get("bbox") or []
        if len(label_bbox) != 4:
            continue
        _, label_mid_y = _bbox_mid(label_bbox)
        if abs(label_mid_y - line_mid_y) > line_tol:
            continue
        overlap_x = min(line_bbox[2], label_bbox[2]) - max(line_bbox[0], label_bbox[0])
        if overlap_x <= 0:
            continue
        if (overlap_x / line_width) < 0.4:
            continue
        overlap_hits += 1
        if overlap_hits >= 3:
            return True
    return False


def _point_in_bbox(x: float, y: float, bbox: List[float], *, pad: float = 0.0) -> bool:
    """Return True when point (x,y) lies inside bbox with optional padding."""
    if len(bbox) != 4:
        return False
    x1, y1, x2, y2 = [float(v) for v in bbox]
    return (x1 + pad) <= x <= (x2 - pad) and (y1 + pad) <= y <= (y2 - pad)


def _table_cell_contains_text(cell_bbox: List[float], labels: List[Dict]) -> bool:
    """
    Return True when a table cell bbox likely contains printed text (header/example cells).

    Strategy:
    - Use the *center* of each label bbox to reduce false positives from labels that merely
      graze the cell border.
    - Only treat labels with alphabetic characters as "text"; this avoids skipping cells due
      to stray OCR punctuation noise.
    """
    if len(cell_bbox) != 4:
        return False
    for lb in labels or []:
        bbox = lb.get("bbox") or []
        if len(bbox) != 4:
            continue
        mid_x, mid_y = _bbox_mid(bbox)
        if not _point_in_bbox(mid_x, mid_y, cell_bbox, pad=1.0):
            continue
        text = (lb.get("text") or "").strip()
        if any(ch.isalpha() for ch in text):
            return True
    return False


_CHECKBOX_HEADER_TOKENS = {
    "yes",
    "no",
    "n/a",
    "na",
    "not sure",
    "unknown",
    "never",
    "now",
    "current",
    "present",
    "past",
    "in the past",
    "true",
    "false",
    "daily",
    "some",
    "none",
    "often",
    "sometimes",
    "always",
    "rarely",
    "seldom",
    "usually",
    "frequently",
    "occasionally",
    "v",
    "x",
    "check",
    "self",
    "mother",
    "father",
    "grandparent",
    "sibling",
    "other",
}

_CHECKBOX_RANGE_UNITS = {
    "day",
    "days",
    "week",
    "weeks",
    "month",
    "months",
    "year",
    "years",
}


def _normalize_checkbox_header(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", (text or "").strip().lower())
    if not cleaned:
        return ""
    cleaned = cleaned.strip("()[]{}.,;:")
    return cleaned


def _label_is_checkbox_header(text: str) -> bool:
    norm = _normalize_checkbox_header(text)
    if not norm:
        return False
    if norm in _CHECKBOX_HEADER_TOKENS:
        return True
    words = re.findall(r"[a-z0-9]+", norm)
    if words and len(words) <= 3 and all(w in _CHECKBOX_HEADER_TOKENS for w in words):
        return True
    if re.search(r"\d", norm):
        normalized = re.sub(r"\s+", " ", norm)
        normalized = re.sub(r"\bto\b", "-", normalized)
        normalized = re.sub(r"\bor\s+more\b", "or more", normalized)
        normalized = re.sub(r"\bor\s+less\b", "or less", normalized)
        normalized = re.sub(r"[\u2010\u2011\u2012\u2013\u2014\u2015\u2212]", "-", normalized)
        range_match = re.match(
            r"^\d+(\s*-\s*\d+)?(\s+or\s+(more|less))?(\s+\w+)?$",
            normalized,
        )
        if range_match:
            unit = (range_match.group(4) or "").strip()
            if not unit or unit in _CHECKBOX_RANGE_UNITS:
                return True
    if "/" in norm:
        parts = [p.strip() for p in norm.split("/") if p.strip()]
        if 1 < len(parts) <= 3 and all(p in _CHECKBOX_HEADER_TOKENS for p in parts):
            return True
    return False


def _collect_checkbox_headers(labels: List[Dict]) -> List[Dict]:
    """
    Collect checkbox-style header labels (e.g., Yes/No/Not sure).
    """
    headers: List[Dict] = []
    for lb in labels or []:
        text = (lb.get("text") or "").strip()
        if not _label_is_checkbox_header(text):
            continue
        bbox = lb.get("bbox") or []
        if len(bbox) != 4:
            continue
        headers.append(lb)
    return headers


def _collect_table_checkbox_headers(
    labels: List[Dict],
    table_region: Optional[List[float]],
    *,
    median_label_height: float,
) -> List[Dict]:
    """
    Return checkbox header labels that appear to sit above a detected table region.

    We use these header labels to classify narrow table columns as checkbox columns,
    even when the table extends far below the header row.
    """
    if not table_region:
        return []
    headers = _collect_checkbox_headers(labels)
    if not headers:
        return []

    table_left = float(table_region[0])
    table_right = float(table_region[2])
    table_top = float(table_region[1])
    header_band = max(12.0, min(120.0, median_label_height * 7.0))

    filtered: List[Dict] = []
    for lb in headers:
        bbox = lb.get("bbox") or []
        if len(bbox) != 4:
            continue
        if bbox[2] <= table_left or bbox[0] >= table_right:
            continue
        if float(bbox[3]) > (table_top + header_band):
            continue
        filtered.append(lb)
    return filtered


def _collect_table_prompt_labels(
    labels: List[Dict],
    table_region: Optional[List[float]],
    *,
    median_label_height: float,
) -> List[Dict]:
    """
    Collect prompt-like labels that sit inside or just above a detected table region.

    These labels indicate the table likely represents user input rather than chart art.
    """
    if not table_region:
        return []
    table_left = float(table_region[0])
    table_right = float(table_region[2])
    table_top = float(table_region[1])
    table_bottom = float(table_region[3])

    header_band = max(12.0, min(140.0, median_label_height * 8.0))
    side_pad = max(12.0, median_label_height * 2.0)

    prompts: List[Dict] = []
    for lb in labels or []:
        text = (lb.get("text") or "").strip()
        if not text:
            continue
        if not (
            _label_is_prompt_like(text)
            or _label_supports_grid_text_line(text)
            or _label_supports_other_blank(text)
        ):
            continue
        bbox = lb.get("bbox") or []
        if len(bbox) != 4:
            continue
        mid_x, mid_y = _bbox_mid(bbox)
        if mid_x < (table_left - side_pad) or mid_x > (table_right + side_pad):
            continue
        if mid_y < (table_top - header_band) or mid_y > (table_bottom + header_band):
            continue
        prompts.append(lb)
    return prompts


def _cluster_positions(values: List[float], tolerance: float) -> List[List[float]]:
    """
    Cluster sorted values into groups where adjacent entries are within `tolerance`.

    This is a lightweight 1D clustering helper used to estimate checkbox rows/columns.
    """
    if not values:
        return []
    sorted_vals = sorted(values)
    clusters: List[List[float]] = [[sorted_vals[0]]]
    for value in sorted_vals[1:]:
        if abs(value - clusters[-1][-1]) <= tolerance:
            clusters[-1].append(value)
        else:
            clusters.append([value])
    return clusters


def _group_cluster_centers(centers: List[float], gap_tolerance: float) -> List[List[float]]:
    """
    Group 1D cluster centers into contiguous bands separated by large gaps.

    This prevents widely separated checkbox sections from being merged into a single
    mega-region that would incorrectly block unrelated underline fields.
    """
    if not centers:
        return []
    sorted_centers = sorted(centers)
    groups: List[List[float]] = [[sorted_centers[0]]]
    for value in sorted_centers[1:]:
        if value - groups[-1][-1] <= gap_tolerance:
            groups[-1].append(value)
        else:
            groups.append([value])
    return groups


def _checkbox_row_centers(
    checkbox_candidates: List[Dict],
    *,
    median_label_height: float,
    size_hint: Optional[float] = None,
) -> List[float]:
    """
    Estimate checkbox row centers so we can snap candidates onto a shared baseline.

    We cluster checkbox midpoints in 1D (Y axis). Clusters with more than one checkbox
    represent a row; singletons are too noisy to snap.
    """
    if not checkbox_candidates:
        return []
    positions: List[float] = []
    max_size = max(14.0, median_label_height * 2.2)
    if size_hint:
        max_size = max(max_size, float(size_hint) * 1.9)
    for cb in checkbox_candidates:
        bbox = cb.get("bbox") or []
        if len(bbox) != 4:
            continue
        size = min(float(bbox[2]) - float(bbox[0]), float(bbox[3]) - float(bbox[1]))
        if size <= 0.0:
            continue
        if size > max_size:
            continue
        positions.append(_bbox_mid(bbox)[1])
    if len(positions) < 2:
        return []
    tolerance = max(4.0, min(18.0, median_label_height * 0.9))
    clusters = _cluster_positions(positions, tolerance)
    centers = [sum(cluster) / len(cluster) for cluster in clusters if len(cluster) >= 2]
    return centers


def _snap_checkbox_row(
    mid_y: float,
    row_centers: List[float],
    *,
    tolerance: float,
) -> Optional[float]:
    """
    Return the nearest row center when the checkbox is close enough to a row cluster.
    """
    if not row_centers:
        return None
    nearest = min(row_centers, key=lambda value: abs(value - mid_y))
    if abs(nearest - mid_y) <= tolerance:
        return nearest
    return None


def _estimate_checkbox_size(
    checkbox_candidates: List[Dict],
    *,
    median_label_height: float,
) -> float:
    """
    Estimate a reasonable checkbox size for a page.

    We prioritize high-confidence detectors (glyph/vector/contour/text-mask). If those are
    absent, we fall back to a lower-percentile size to avoid oversized table-cell boxes.
    """
    preferred: List[float] = []
    sizes: List[float] = []
    for cb in checkbox_candidates or []:
        bbox = cb.get("bbox") or []
        if len(bbox) != 4:
            continue
        width = float(bbox[2]) - float(bbox[0])
        height = float(bbox[3]) - float(bbox[1])
        if width <= 0.0 or height <= 0.0:
            continue
        size = min(width, height)
        sizes.append(size)
        det = str(cb.get("detector") or "").lower()
        if det in {"glyph", "vector_rect", "contour"} or det.startswith("text_mask"):
            preferred.append(size)

    target = None
    if len(preferred) >= 4:
        target = float(statistics.median(preferred))
    elif len(sizes) >= 4:
        sizes.sort()
        idx = int(len(sizes) * 0.30)
        target = float(sizes[min(idx, len(sizes) - 1)])

    if target is None:
        target = float(median_label_height) * 0.8

    target = max(5.0, min(22.0, target))
    return target


def _detect_checkbox_grid_regions(
    checkbox_candidates: List[Dict],
    *,
    median_label_height: float,
) -> List[Dict[str, float]]:
    """
    Identify checkbox grid regions (rows/columns) to suppress table grid lines.

    We look for multiple checkbox rows/columns with consistent spacing. The returned
    regions are bounding boxes (originTop points) around each grid section.
    """
    entries = []
    for cb in checkbox_candidates or []:
        bbox = cb.get("bbox") or []
        if len(bbox) != 4:
            continue
        x1, y1, x2, y2 = [float(v) for v in bbox]
        if x2 <= x1 or y2 <= y1:
            continue
        entries.append(
            {
                "bbox": [x1, y1, x2, y2],
                "mid_x": (x1 + x2) / 2.0,
                "mid_y": (y1 + y2) / 2.0,
                "size": max(x2 - x1, y2 - y1),
            }
        )
    if len(entries) < 8:
        return []

    sizes = sorted(e["size"] for e in entries)
    median_size = sizes[len(sizes) // 2]
    row_tol = max(6.0, median_label_height * 0.6, median_size * 0.75)
    col_tol = max(6.0, median_label_height * 0.6, median_size * 0.75)

    row_clusters = _cluster_positions([e["mid_y"] for e in entries], row_tol)
    if len(row_clusters) < 4:
        return []

    row_centers = [sum(cluster) / len(cluster) for cluster in row_clusters]
    sorted_centers = sorted(row_centers)
    if len(sorted_centers) > 1:
        gaps = [b - a for a, b in zip(sorted_centers, sorted_centers[1:]) if (b - a) > 0]
        gaps_sorted = sorted(gaps)
        median_gap = gaps_sorted[len(gaps_sorted) // 2] if gaps_sorted else 0.0
    else:
        median_gap = 0.0
    gap_tol = max(
        median_label_height * 4.0,
        median_gap * 4.0,
        row_tol * 3.0,
        48.0,
    )
    row_bands = _group_cluster_centers(row_centers, gap_tol)

    regions: List[Dict[str, float]] = []
    for band in row_bands:
        band_min = min(band) - row_tol
        band_max = max(band) + row_tol
        band_entries = [e for e in entries if band_min <= e["mid_y"] <= band_max]
        if len(band_entries) < 8:
            continue

        col_clusters = _cluster_positions([e["mid_x"] for e in band_entries], col_tol)
        row_count = len([c for c in row_clusters if band_min <= (sum(c) / len(c)) <= band_max])
        col_count = len(col_clusters)
        expected = row_count * col_count
        if row_count < 4 or col_count < 2:
            continue
        if expected > 0 and len(band_entries) < max(8, expected * 0.35):
            continue

        xs1 = [e["bbox"][0] for e in band_entries]
        ys1 = [e["bbox"][1] for e in band_entries]
        xs2 = [e["bbox"][2] for e in band_entries]
        ys2 = [e["bbox"][3] for e in band_entries]
        regions.append(
            {
                "x1": min(xs1),
                "y1": min(ys1),
                "x2": max(xs2),
                "y2": max(ys2),
                "rows": float(row_count),
                "cols": float(col_count),
                "count": float(len(band_entries)),
            }
        )

    return regions


def _line_overlaps_checkbox_grid(
    line_bbox: List[float],
    grid_bbox: List[float],
    *,
    page_width: float,
    median_label_height: float,
) -> bool:
    """
    Return True when a line candidate appears to be a table/grid rule.

    We only block long lines that start near the left edge of a checkbox grid and
    overlap most of the grid width. This avoids suppressing short underlines that
    live to the right of checkbox rows (e.g., "If yes, describe ____").
    """
    if len(line_bbox) != 4 or len(grid_bbox) != 4:
        return False
    line_len = float(line_bbox[2]) - float(line_bbox[0])
    if line_len <= 0.0:
        return False
    min_len = max(180.0, page_width * 0.45)
    if line_len < min_len:
        return False

    grid_pad = max(8.0, median_label_height * 0.8)
    if line_bbox[2] <= grid_bbox[0] or line_bbox[0] >= grid_bbox[2]:
        return False
    if line_bbox[3] < (grid_bbox[1] - grid_pad) or line_bbox[1] > (grid_bbox[3] + grid_pad):
        return False

    if line_bbox[0] > (grid_bbox[0] + grid_pad):
        return False

    overlap = min(line_bbox[2], grid_bbox[2]) - max(line_bbox[0], grid_bbox[0])
    if overlap <= 0.0:
        return False
    return (overlap / line_len) >= 0.55


def _table_cell_is_checkbox(
    cell_bbox: List[float],
    header_labels: List[Dict],
    *,
    median_label_height: float,
) -> bool:
    """
    Return True when a table cell is likely a checkbox slot.
    """
    if len(cell_bbox) != 4:
        return False
    width = float(cell_bbox[2]) - float(cell_bbox[0])
    height = float(cell_bbox[3]) - float(cell_bbox[1])
    if width <= 0.0 or height <= 0.0:
        return False
    max_width = max(36.0, min(90.0, median_label_height * 8.0))
    max_height = max(18.0, min(36.0, median_label_height * 3.8))
    if width > max_width or height > max_height:
        return False
    if not header_labels:
        return False

    # Header labels should sit above the cell; allow a small overlap band.
    overlap_pad = max(2.0, median_label_height * 0.4)
    for lb in header_labels:
        lb_bbox = lb.get("bbox") or []
        if len(lb_bbox) != 4:
            continue
        if lb_bbox[3] > (cell_bbox[1] + overlap_pad):
            continue
        overlap = min(cell_bbox[2], lb_bbox[2]) - max(cell_bbox[0], lb_bbox[0])
        if overlap <= 0:
            continue
        denom = min(width, max(1.0, float(lb_bbox[2]) - float(lb_bbox[0])))
        if (overlap / denom) >= 0.35:
            return True
    return False


def _score_label_to_line(
    label_bbox: List[float],
    line_bbox: List[float],
    *,
    expected_offset: float,
    start_tolerance: float = 10.0,
) -> Optional[float]:
    """
    Score a label->underline match. Lower is better.

    Coordinate system: points, originTop.
    """
    if len(label_bbox) != 4 or len(line_bbox) != 4:
        return None

    lx1, ly1, lx2, ly2 = [float(v) for v in label_bbox]
    ux1, uy1, ux2, uy2 = [float(v) for v in line_bbox]
    if ux2 <= ux1:
        return None

    label_mid_x, _ = _bbox_mid(label_bbox)

    # Underlines should generally sit below the label's baseline.
    baseline = uy2
    if baseline < ly1 - 2:
        return None

    # When a line sits on the same baseline as the label text, ensure it is not just
    # a fragment of the label's own glyph baseline. Allow only minimal overlap.
    if uy1 <= ly2 + 1:
        overlap_x = min(ux2, lx2) - max(ux1, lx1)
        if overlap_x > 0:
            line_width = max(1.0, ux2 - ux1)
            if (overlap_x / line_width) > 0.35:
                return None

    # Require underline to start after the label (typical "label on the left, line on the right"
    # form layout). This intentionally avoids matching section headers to full-width divider rules.
    starts_after_label = ux1 >= (lx2 - float(start_tolerance))
    if not starts_after_label:
        return None

    dy = abs(baseline - (ly2 + expected_offset))

    # Prefer underlines that begin near the end of the label.
    dx = max(0.0, ux1 - lx2)

    # Hard gating to avoid matching across unrelated regions.
    if dy > 90:
        return None
    if dx > 280:
        return None

    # Weighted score: row alignment matters more than x-gap.
    return dy * 1.8 + dx * 0.35


def _score_label_to_line_left(
    label_bbox: List[float],
    line_bbox: List[float],
    *,
    expected_offset: float,
) -> Optional[float]:
    """
    Score a label->underline match when the underline sits to the LEFT of the label.

    This pattern is common in questionnaire score charts where a small blank is printed as:
        ____ Symptom Name
    """
    if len(label_bbox) != 4 or len(line_bbox) != 4:
        return None

    lx1, ly1, lx2, ly2 = [float(v) for v in label_bbox]
    ux1, uy1, ux2, uy2 = [float(v) for v in line_bbox]
    if ux2 <= ux1:
        return None

    baseline = uy2
    if baseline < ly1 - 2:
        return None

    # Underline should end before the label starts (allow a small overlap for OCR jitter).
    if ux2 > (lx1 + 12):
        return None

    dy = abs(baseline - (ly2 + expected_offset))
    dx = max(0.0, lx1 - ux2)
    if dy > 90:
        return None
    if dx > 220:
        return None

    return dy * 1.8 + dx * 0.55


def _score_label_to_line_below(
    label_bbox: List[float],
    line_bbox: List[float],
    *,
    max_dy: float,
    min_overlap: float,
) -> Optional[float]:
    """
    Score a label->underline match when the label sits ABOVE the underline.

    This layout is common in modern forms where labels sit on top of a long input line:
        Last Name
        ___________________________
    """
    if len(label_bbox) != 4 or len(line_bbox) != 4:
        return None

    lx1, ly1, lx2, ly2 = [float(v) for v in label_bbox]
    ux1, uy1, ux2, uy2 = [float(v) for v in line_bbox]
    if ux2 <= ux1:
        return None

    # Require underline to be below the label.
    if uy1 <= ly2 - 1:
        return None

    dy = max(0.0, uy1 - ly2)
    if dy > max_dy:
        return None

    overlap = min(lx2, ux2) - max(lx1, ux1)
    if overlap <= 0:
        return None
    label_width = max(1.0, lx2 - lx1)
    overlap_ratio = overlap / label_width
    if overlap_ratio < min_overlap:
        return None

    if ux1 <= lx1 and ux2 >= lx2:
        dx = 0.0
    else:
        dx = min(abs(ux1 - lx1), abs(ux2 - lx2))
    return dy * 1.2 + dx * 0.5


def _score_label_to_full_width_line(
    label_bbox: List[float],
    line_bbox: List[float],
    *,
    max_dy: float,
) -> Optional[float]:
    """
    Score a label->full-width line match when the line spans the row separator.
    """
    if len(label_bbox) != 4 or len(line_bbox) != 4:
        return None
    lx1, ly1, lx2, ly2 = [float(v) for v in label_bbox]
    ux1, uy1, ux2, uy2 = [float(v) for v in line_bbox]
    if ux2 <= ux1:
        return None
    overlap = min(lx2, ux2) - max(lx1, ux1)
    if overlap <= 0:
        return None
    overlap_ratio = overlap / max(1.0, lx2 - lx1)
    if overlap_ratio < 0.35:
        return None
    dy = float(uy2) - float(ly2)
    if dy < -2.0 or dy > max_dy:
        return None
    return abs(dy) * 1.2


def _pick_best_underline(
    label_bbox: List[float],
    underline_candidates: List[Dict],
    used_ids: set[str],
    *,
    expected_offset: float,
    label_text: str = "",
    footer_bands: Optional[List[Tuple[float, float]]] = None,
    blocked_line_ids: Optional[set[str]] = None,
    paragraph_bands: Optional[List[Tuple[float, float]]] = None,
    full_width_line_ids: Optional[set[str]] = None,
    page_width: Optional[float] = None,
    page_labels: Optional[List[Dict]] = None,
    page_checkboxes: Optional[List[Dict]] = None,
    median_label_height: float = 0.0,
    split_line_ids: Optional[set[str]] = None,
) -> Tuple[Optional[Dict], Optional[float], Optional[float], Optional[str]]:
    best = None
    best_score = None
    second_best_score = None
    best_orientation: Optional[str] = None
    header_like = _is_all_caps_header_like(label_text)
    label_in_paragraph = _label_in_paragraph_band(label_bbox, paragraph_bands or [])
    _, label_mid_y = _bbox_mid(label_bbox)
    label_width = max(1.0, float(label_bbox[2]) - float(label_bbox[0])) if len(label_bbox) == 4 else 1.0
    colon_label = (label_text or "").strip().endswith(":")
    colon_prompt_like = colon_label and _label_is_prompt_like(label_text)
    colon_requires_long = colon_label and not colon_prompt_like and not _label_supports_other_blank(label_text)
    colon_min_len = max(24.0, median_label_height * 2.6, min(120.0, label_width * 1.15))
    row_has_yes_no = False
    if page_labels and median_label_height > 0:
        row_has_yes_no = _label_row_has_yes_no_tokens(
            label_bbox,
            page_labels,
            median_label_height=median_label_height,
        )
    row_has_checkbox = False
    if page_checkboxes and median_label_height > 0:
        max_dx = max(160.0, (page_width or 0.0) * 0.45) if page_width else 200.0
        row_has_checkbox = _label_row_has_checkboxes(
            label_bbox,
            page_checkboxes,
            median_label_height=median_label_height,
            max_dx=max_dx,
        )
    if _label_is_short_question_fragment(
        label_text,
        label_bbox,
        page_labels=page_labels,
        median_label_height=median_label_height,
    ):
        return None, None, None, None
    lower_label = (label_text or "").strip().lower()
    allow_header_keywords = (
        "name",
        "date",
        "dob",
        "ssn",
        "id",
        "phone",
        "email",
        "address",
        "signature",
        "sign",
        "initial",
    )
    header_colon_block = (
        _is_all_caps(label_text)
        and label_text.strip().endswith(":")
        and not any(key in lower_label for key in allow_header_keywords)
    )
    strong_right_score = None
    strong_right_limit = max(18.0, median_label_height * 2.5)
    if underline_candidates:
        for cand in underline_candidates:
            cid = cand.get("id")
            if not cid or cid in used_ids:
                continue
            if blocked_line_ids and cid in blocked_line_ids:
                continue
            if split_line_ids and cid in split_line_ids:
                continue
            bbox = cand.get("bbox")
            if not bbox:
                continue
            length = float(cand.get("length") or (float(bbox[2]) - float(bbox[0])))
            if colon_requires_long and length < colon_min_len:
                continue
            if median_label_height > 0:
                micro_len = max(12.0, median_label_height * 1.5)
                if length <= micro_len and not (
                    _label_supports_micro_underline(label_text)
                    or _label_is_paragraph_prompt(label_text)
                ):
                    continue
            if full_width_line_ids and cid in full_width_line_ids:
                if not _label_supports_full_width_line(label_text):
                    continue
            if page_width and page_labels and median_label_height > 0:
                if length >= page_width * 0.75:
                    if _line_has_yes_no_tokens(
                        bbox,
                        page_labels,
                        max_dy=max(8.0, median_label_height * 1.2),
                    ):
                        if not _label_supports_grid_text_line(label_text):
                            continue
            if header_like and cand.get("detector") == "morph_short":
                continue
            if paragraph_bands and _in_footer_band(bbox, paragraph_bands) and not label_in_paragraph:
                if not _label_supports_paragraph_band_line(label_text):
                    _, line_mid_y = _bbox_mid(bbox)
                    if abs(line_mid_y - label_mid_y) > max(6.0, median_label_height * 0.6):
                        continue
            if cand.get("detector") == "morph_short" and footer_bands:
                if _in_footer_band(bbox, footer_bands) and not _label_supports_footer_short_line(
                    label_text
                ):
                    continue
            start_tolerance = 15.0 if cand.get("detector") == "morph_short" else 10.0
            score_right = _score_label_to_line(
                label_bbox,
                bbox,
                expected_offset=expected_offset,
                start_tolerance=start_tolerance,
            )
            if score_right is None:
                continue
            if strong_right_score is None or score_right < strong_right_score:
                strong_right_score = score_right

    if header_colon_block and full_width_line_ids:
        label_y2 = float(label_bbox[3]) if len(label_bbox) == 4 else None
        if label_y2 is not None:
            y_tol = max(4.0, median_label_height * 0.6)
            for cand in underline_candidates:
                cid = cand.get("id")
                if not cid or cid not in full_width_line_ids:
                    continue
                bbox = cand.get("bbox") or []
                if len(bbox) != 4:
                    continue
                dy = float(bbox[1]) - label_y2
                if -1.0 <= dy <= y_tol:
                    return None, None, None, None
    for cand in underline_candidates:
        cid = cand.get("id")
        if not cid or cid in used_ids:
            continue
        if blocked_line_ids and cid in blocked_line_ids:
            continue
        if split_line_ids and cid in split_line_ids:
            continue
        bbox = cand.get("bbox")
        if not bbox:
            continue
        length = float(cand.get("length") or (float(bbox[2]) - float(bbox[0])))
        if colon_requires_long and length < colon_min_len:
            continue
        if median_label_height > 0:
            micro_len = max(12.0, median_label_height * 1.5)
            if length <= micro_len and not (
                _label_supports_micro_underline(label_text)
                or _label_is_paragraph_prompt(label_text)
            ):
                continue
        if full_width_line_ids and cid in full_width_line_ids:
            if not _label_supports_full_width_line(label_text):
                continue
        if page_width and page_labels and median_label_height > 0:
            if length >= page_width * 0.75:
                if _line_has_yes_no_tokens(
                    bbox,
                    page_labels,
                    max_dy=max(8.0, median_label_height * 1.2),
                ):
                    if not _label_supports_grid_text_line(label_text):
                        continue
        # Prevent all-caps section headers from consuming mini-underlines. This fixes cases
        # like "DIGESTIVE TRACT" matching the first score blank on MSQ questionnaire pages.
        if header_like and cand.get("detector") == "morph_short":
            continue
        if paragraph_bands and _in_footer_band(bbox, paragraph_bands) and not label_in_paragraph:
            if not _label_supports_paragraph_band_line(label_text):
                _, line_mid_y = _bbox_mid(bbox)
                if abs(line_mid_y - label_mid_y) > max(6.0, median_label_height * 0.6):
                    continue
        if cand.get("detector") == "morph_short" and footer_bands:
            bbox = cand.get("bbox") or []
            if _in_footer_band(bbox, footer_bands) and not _label_supports_footer_short_line(
                label_text
            ):
                continue
        # `morph_short` blanks can overlap the end of the label slightly due to OCR jitter and
        # underscore glyph spacing, so allow a bit more "start before label end" tolerance.
        start_tolerance = 15.0 if cand.get("detector") == "morph_short" else 10.0
        score_right = _score_label_to_line(
            label_bbox,
            bbox,
            expected_offset=expected_offset,
            start_tolerance=start_tolerance,
        )
        if score_right is not None and len(label_bbox) == 4:
            ly2 = float(label_bbox[3])
            uy2 = float(bbox[3])
            dy_right = abs(uy2 - (ly2 + expected_offset))
            max_right_dy = max(18.0, median_label_height * 2.5)
            if dy_right > max_right_dy:
                score_right = None
        # Only allow "blank to the LEFT of label" matching for short underscore blanks.
        # This prevents labels like "Gender Male Female" from stealing a long underline
        # that happens to sit just to the left on the same row.
        score_left = None
        if cand.get("detector") == "morph_short" and _label_supports_left_blank(label_text):
            score_left = _score_label_to_line_left(label_bbox, bbox, expected_offset=expected_offset)
        score_below = None
        if length >= 40.0:
            score_below = _score_label_to_line_below(
                label_bbox,
                bbox,
                max_dy=70.0,
                min_overlap=0.25,
            )
            if (
                score_below is not None
                and row_has_yes_no
                and not _label_supports_grid_text_line(label_text)
            ):
                score_below = None
            if (
                score_below is not None
                and row_has_checkbox
                and not _label_supports_grid_text_line(label_text)
            ):
                score_below = None
            if (
                score_below is not None
                and full_width_line_ids
                and cid in full_width_line_ids
                and strong_right_score is not None
                and strong_right_score <= strong_right_limit
            ):
                score_below = None
            if (
                score_below is not None
                and _label_is_yes_no_question(label_text)
                and not _label_supports_grid_text_line(label_text)
            ):
                score_below = None
        score_full = None
        if (
            full_width_line_ids
            and cid in full_width_line_ids
            and _label_supports_full_width_line(label_text)
            and (not row_has_yes_no or _label_supports_grid_text_line(label_text))
        ):
            score_full = _score_label_to_full_width_line(
                label_bbox,
                bbox,
                max_dy=max(8.0, median_label_height * 1.4),
            )
            if strong_right_score is not None and strong_right_score <= strong_right_limit:
                score_full = None
            if row_has_checkbox and not _label_supports_grid_text_line(label_text):
                score_full = None
        score = None
        orientation = None
        candidates = []
        if score_right is not None:
            candidates.append(("right", score_right))
        if score_left is not None:
            candidates.append(("left", score_left))
        if score_below is not None:
            candidates.append(("below", score_below))
        if score_full is not None:
            candidates.append(("full", score_full))
        if candidates:
            orientation, score = min(candidates, key=lambda item: item[1])
        if score is None:
            continue
        if best_score is None or score < best_score:
            second_best_score = best_score
            best_score = score
            best = cand
            best_orientation = orientation
        elif second_best_score is None or score < second_best_score:
            second_best_score = score
    return best, best_score, second_best_score, best_orientation


def _pick_best_box(
    label_bbox: List[float],
    box_candidates: List[Dict],
    used_ids: set[str],
) -> Optional[Dict]:
    if len(label_bbox) != 4:
        return None
    lx1, ly1, lx2, ly2 = [float(v) for v in label_bbox]
    label_mid_x, label_mid_y = _bbox_mid(label_bbox)

    best = None
    best_score = None
    for cand in box_candidates:
        cid = cand.get("id")
        if not cid or cid in used_ids:
            continue
        # Table text cells are emitted separately at high recall. Do not allow label->box
        # matching to consume these candidates, otherwise a missing underline can cause a
        # label to "jump" to a random table cell far away and create a bogus field.
        if cand.get("detector") == "table_text_cell":
            continue
        bx = cand.get("bbox")
        if not bx or len(bx) != 4:
            continue
        bx_mid_x, bx_mid_y = _bbox_mid(bx)
        dy = abs(bx_mid_y - label_mid_y)
        dx = abs(bx_mid_x - max(label_mid_x, lx2 + 10))
        # Favor boxes that sit to the right or below the label.
        if bx[0] < lx1 - 10 and bx_mid_x < label_mid_x:
            continue
        # Hard gating: boxes are usually near their label. Avoid matching across the page.
        if dy > 120:
            continue
        if dx > 420:
            continue
        score = dy * 1.5 + dx * 0.5
        if best_score is None or score < best_score:
            best_score = score
            best = cand
    return best


def _score_checkbox_to_label(checkbox_bbox: List[float], label_bbox: List[float]) -> Optional[float]:
    if len(checkbox_bbox) != 4 or len(label_bbox) != 4:
        return None
    cx1, cy1, cx2, cy2 = [float(v) for v in checkbox_bbox]
    lx1, ly1, lx2, ly2 = [float(v) for v in label_bbox]
    cb_mid_x, cb_mid_y = _bbox_mid(checkbox_bbox)
    lb_mid_x, lb_mid_y = _bbox_mid(label_bbox)

    # Checkbox labels typically sit to the right. Allow slight overlap because OCR bboxes
    # can be jittery and many forms print the label very close to the box.
    if lx1 < cx2 - 12:
        return None
    dy = abs(lb_mid_y - cb_mid_y)
    dx = lx1 - cx2
    if dy > 30:
        return None
    if dx > 400:
        return None
    return dy * 2.2 + dx * 0.8


def _label_is_checkbox_option(
    label_bbox: List[float],
    checkbox_candidates: List[Dict],
    *,
    label_text: str = "",
    score_threshold: float = 180.0,
) -> bool:
    """
    Return True when a label sits to the RIGHT of a nearby checkbox candidate.

    This is used to avoid treating checkbox option labels (e.g., "Sneezing", "Yes")
    as text-field prompts. The checkbox fields are already emitted separately.
    """
    if len(label_bbox) != 4:
        return False
    raw = (label_text or "").strip()
    if raw:
        if "*" in raw:
            return False
        lower = raw.lower()
        if "?" in raw or ":" in raw:
            return False
        if any(
            key in lower
            for key in (
                "date",
                "name",
                "address",
                "phone",
                "email",
                "describe",
                "discuss",
                "specify",
                "reason",
                "why",
                "who",
                "what",
                "how",
                "relationship",
                "insurance",
                "member",
                "group",
                "contact",
                "type",
                "quantity",
                "frequency",
                "duration",
            )
        ):
            return False
        if raw.startswith(("•", "-")):
            words = re.findall(r"[a-z0-9]+", lower)
            if len(words) >= 2:
                return False
        words = re.findall(r"[a-z0-9]+", lower)
        if len(words) >= 4:
            return False
    for cb in checkbox_candidates or []:
        cb_bbox = cb.get("bbox")
        if not cb_bbox or len(cb_bbox) != 4:
            continue
        score = _score_checkbox_to_label(cb_bbox, label_bbox)
        if score is not None and score <= float(score_threshold):
            return True
    return False


def resolve_fields_heuristically(
    candidates_json: List[Dict],
    meta: Dict,
    labels_by_page: Dict[int, List[Dict]],
    calibrations: Dict[int, Dict],
    *,
    min_confidence: float = 0.55,
) -> Dict:
    """
    Deterministic resolver.

    This is deliberately conservative:
    - We only create fields when a label has a strong nearby geometry candidate.
    - All final rects are built deterministically (underline -> typing area above underline).

    The output matches the standard response schema so downstream injectors can consume it.
    """
    thresholds = meta.get("thresholds", DEFAULT_THRESHOLDS)
    name_counts: Dict[str, int] = {}
    fields: List[Dict] = []

    for page in candidates_json:
        page_idx = int(page["page"])
        page_width = float(page.get("pageWidth") or 612.0)
        page_height = float(page.get("pageHeight") or 792.0)

        underline_candidates = list(page.get("lineCandidates") or [])
        box_candidates = list(page.get("boxCandidates") or [])
        checkbox_candidates = list(page.get("checkboxCandidates") or [])

        used_ids: set[str] = set()
        used_label_bboxes: set[Tuple[float, float, float, float]] = set()

        page_labels = labels_by_page.get(page_idx, []) or []
        label_index = LabelIndex(page_labels) if page_labels else None
        usable_labels: List[Dict] = []
        calibration = calibrations.get(page_idx, {}) or {}
        median_label_height = float(calibration.get("medianLabelHeight") or 12.0)
        expected_offset = max(4.0, min(10.0, median_label_height * 0.65))
        noisy_checkbox_page = _page_has_checkbox_noise(
            checkbox_candidates,
            page_labels,
            median_label_height=median_label_height,
        )
        if noisy_checkbox_page:
            logger.debug(
                "Suppressing checkbox fields on page %s due to checkbox noise",
                page_idx,
            )
        option_list_label_indices = _collect_option_list_label_indices(
            page_labels,
            median_label_height=median_label_height,
        )
        if option_list_label_indices:
            logger.debug(
                "Suppressed %s option-list labels on page %s",
                len(option_list_label_indices),
                page_idx,
            )
        paragraph_bands = _compute_paragraph_line_bands(
            page_labels,
            page_width=page_width,
            median_label_height=median_label_height,
        )
        footer_bands = _compute_footer_noise_bands(
            page_labels,
            page_width=page_width,
            page_height=page_height,
            median_label_height=median_label_height,
        )
        prompt_like_count = _count_prompt_like_labels(
            page_labels,
            paragraph_bands=paragraph_bands,
        )
        suppress_paragraph_bands = prompt_like_count <= 6
        text_only_checkbox_page = _page_has_text_only_checkbox_noise(
            checkbox_candidates,
            underline_candidates,
            box_candidates,
            prompt_like_count=prompt_like_count,
            label_count=len(page_labels or []),
            median_label_height=median_label_height,
        )
        suppress_checkbox_fields = noisy_checkbox_page or text_only_checkbox_page
        if text_only_checkbox_page:
            logger.debug(
                "Suppressing checkbox fields on page %s due to text-only checkbox noise",
                page_idx,
            )
        non_form_page = (
            prompt_like_count == 0
            and not checkbox_candidates
            and not box_candidates
        )
        short_line_text_ids = {
            ln.get("id")
            for ln in underline_candidates
            if ln.get("detector") == "morph_short"
            and _short_line_is_text_artifact(
                ln.get("bbox") or [],
                page_labels,
                median_label_height=median_label_height,
            )
        }
        short_line_text_ids.discard(None)
        if short_line_text_ids:
            max_dx = max(160.0, page_width * 0.45) if page_width else 200.0
            max_dy = max(8.0, median_label_height * 1.2)
            rescued = set()
            for ln in underline_candidates:
                cid = ln.get("id")
                if not cid or cid not in short_line_text_ids:
                    continue
                bbox = ln.get("bbox")
                if not bbox or len(bbox) != 4:
                    continue
                if _line_has_prompt_label_nearby(
                    bbox,
                    page_labels,
                    max_dx=max_dx,
                    max_dy=max_dy,
                ):
                    rescued.add(cid)
            if rescued:
                short_line_text_ids.difference_update(rescued)
                logger.debug(
                    "Rescued %s short lines near prompt labels on page %s",
                    len(rescued),
                    page_idx,
                )
        if short_line_text_ids:
            logger.debug(
                "Filtered %s morph_short lines overlapping label text on page %s",
                len(short_line_text_ids),
                page_idx,
            )
        paragraph_line_ids: set[str] = set()
        if paragraph_bands and suppress_paragraph_bands:
            max_dx = max(160.0, page_width * 0.45) if page_width else 200.0
            max_dy = max(10.0, median_label_height * 1.8)
            for ln in underline_candidates:
                cid = ln.get("id")
                bbox = ln.get("bbox")
                if not cid or not bbox or len(bbox) != 4:
                    continue
                if not _line_in_paragraph_band(bbox, paragraph_bands):
                    continue
                if _line_has_prompt_label_nearby_strict(
                    bbox,
                    page_labels,
                    max_dx=max_dx,
                    max_dy=max_dy,
                    paragraph_bands=paragraph_bands,
                ):
                    continue
                if _line_has_prompt_label_nearby(
                    bbox,
                    page_labels,
                    max_dx=max_dx,
                    max_dy=max_dy,
                ):
                    continue
                paragraph_line_ids.add(cid)
            if paragraph_line_ids:
                logger.debug(
                    "Filtered %s paragraph-band lines on page %s",
                    len(paragraph_line_ids),
                    page_idx,
                )
        full_width_line_ids = _compute_full_width_line_ids(
            underline_candidates,
            page_width=page_width,
            median_label_height=median_label_height,
        )
        if full_width_line_ids:
            logger.debug(
                "Marked %s full-width lines as separators on page %s",
                len(full_width_line_ids),
                page_idx,
            )

        # Pre-filter labels once so we can:
        # - Avoid repeating logic for every label->underline match attempt
        # - Trigger a "label-poor" fallback on scanned-only pages where PDF text is missing
        for label_idx, label in enumerate(page_labels):
            if label_idx in option_list_label_indices:
                label_bbox = label.get("bbox") or []
                if not _label_has_nearby_underline(
                    label_bbox,
                    underline_candidates,
                    median_label_height=median_label_height,
                ):
                    continue
            if not _label_is_probably_input(label, median_label_height):
                continue
            label_text = (label.get("text") or "").strip()
            label_bbox = label.get("bbox") or []
            if len(label_bbox) != 4:
                continue
            if suppress_paragraph_bands:
                if _label_in_paragraph_band(label_bbox, paragraph_bands) and not _label_is_loose_prompt(
                    label_text
                ):
                    continue
            if _label_looks_like_option_group_geom(
                label_text,
                label_bbox,
                page_labels,
                underline_candidates,
                checkbox_candidates,
                page_width=page_width,
                median_label_height=median_label_height,
            ):
                continue
            if _label_looks_like_non_input_header(
                label_text,
                label_bbox,
                page_width=page_width,
                page_height=page_height,
                median_label_height=median_label_height,
            ):
                continue
            if _label_is_noise_prompt(label_text):
                continue
            label_mid_y = (float(label_bbox[1]) + float(label_bbox[3])) / 2.0
            if label_mid_y >= (page_height * 0.88):
                if not _label_supports_footer_short_line(label_text):
                    continue
            if _label_is_checkbox_option(
                label_bbox,
                checkbox_candidates,
                label_text=label_text,
            ):
                continue
            usable_labels.append(label)

        # Derive a coarse table region from table-derived candidates.
        #
        # We use this to avoid creating text fields from grid border lines. Cell candidates
        # (checkbox/table_text_cell) represent the true interactive areas inside the table.
        table_related = [
            c
            for c in checkbox_candidates
            if c.get("detector") == "table_cells" and c.get("bbox") and len(c.get("bbox")) == 4
        ] + [
            b
            for b in box_candidates
            if b.get("detector") == "table_text_cell" and b.get("bbox") and len(b.get("bbox")) == 4
        ]
        table_region: Optional[List[float]] = None
        checkbox_header_labels: List[Dict] = []
        if table_related:
            xs1 = [float(t["bbox"][0]) for t in table_related]
            ys1 = [float(t["bbox"][1]) for t in table_related]
            xs2 = [float(t["bbox"][2]) for t in table_related]
            ys2 = [float(t["bbox"][3]) for t in table_related]
            pad = 6.0
            table_region = [
                max(0.0, min(xs1) - pad),
                max(0.0, min(ys1) - pad),
                min(page_width, max(xs2) + pad),
                min(page_height, max(ys2) + pad),
            ]
            checkbox_header_labels = _collect_table_checkbox_headers(
                page_labels,
                table_region,
                median_label_height=median_label_height,
            )
        checkbox_grid_regions = _detect_checkbox_grid_regions(
            checkbox_candidates,
            median_label_height=median_label_height,
        )
        table_prompt_labels = _collect_table_prompt_labels(
            page_labels,
            table_region,
            median_label_height=median_label_height,
        )
        allow_table_text_cells = bool(prompt_like_count) or bool(table_prompt_labels)
        allow_table_text_cells = allow_table_text_cells or bool(checkbox_header_labels) or bool(checkbox_grid_regions)
        allow_table_cells_checkboxes = allow_table_text_cells
        if not allow_table_cells_checkboxes and table_region:
            min_len = max(36.0, median_label_height * 3.0)
            max_len = max(180.0, (page_width or 0.0) * 0.45)
            for ln in underline_candidates:
                bbox = ln.get("bbox")
                if not bbox or len(bbox) != 4:
                    continue
                if _rects_intersect(bbox, table_region):
                    continue
                length = float(ln.get("length") or (float(bbox[2]) - float(bbox[0])))
                if length >= min_len and length <= max_len:
                    allow_table_cells_checkboxes = True
                    break
            if not allow_table_cells_checkboxes:
                for bx in box_candidates:
                    if bx.get("detector") == "table_text_cell":
                        continue
                    bbox = bx.get("bbox")
                    if not bbox or len(bbox) != 4:
                        continue
                    if _rects_intersect(bbox, table_region):
                        continue
                    allow_table_cells_checkboxes = True
                    break
        if not allow_table_cells_checkboxes:
            has_table_cells = any(
                str(cb.get("detector") or "").lower() == "table_cells"
                for cb in checkbox_candidates
            )
            if has_table_cells:
                logger.debug(
                    "Skipping table_cells checkboxes on page %s due to missing form cues",
                    page_idx,
                )
        if not allow_table_text_cells:
            has_table_cells = any(
                b.get("detector") == "table_text_cell" for b in box_candidates
            )
            if has_table_cells:
                logger.debug(
                    "Skipping table_text_cell fields on page %s due to missing prompt labels",
                    page_idx,
                )
        if checkbox_candidates and prompt_like_count == 0 and not noisy_checkbox_page:
            high_conf_checkbox = any(
                str(cb.get("detector") or "").lower()
                in {"glyph", "vector_rect", "table_cells", "grid_complete"}
                for cb in checkbox_candidates
            )
            if not high_conf_checkbox and not checkbox_grid_regions:
                noisy_checkbox_page = True
                suppress_checkbox_fields = True
                logger.debug(
                    "Suppressing checkbox fields on page %s due to missing prompt labels",
                    page_idx,
                )
        checkbox_size_hint = _estimate_checkbox_size(
            checkbox_candidates,
            median_label_height=median_label_height,
        )
        checkbox_row_centers = _checkbox_row_centers(
            checkbox_candidates,
            median_label_height=median_label_height,
            size_hint=checkbox_size_hint,
        )
        checkbox_snap_tol = max(6.0, min(28.0, median_label_height * 1.4))
        if checkbox_row_centers:
            logger.debug(
                "Snapping checkboxes to %s row centers on page %s",
                len(checkbox_row_centers),
                page_idx,
            )
        grid_line_ids: set[str] = set()
        if checkbox_grid_regions:
            for ln in underline_candidates:
                cid = ln.get("id")
                bbox = ln.get("bbox")
                if not cid or not bbox or len(bbox) != 4:
                    continue
                for region in checkbox_grid_regions:
                    grid_bbox = [region["x1"], region["y1"], region["x2"], region["y2"]]
                    if _line_overlaps_checkbox_grid(
                        bbox,
                        grid_bbox,
                        page_width=page_width,
                        median_label_height=median_label_height,
                    ):
                        if _line_has_grid_text_prompt(
                            bbox,
                            page_labels,
                            max_dx=page_width * 0.45,
                            max_dy=max(12.0, median_label_height * 2.2),
                        ):
                            break
                        grid_line_ids.add(cid)
                        break
            if grid_line_ids:
                logger.debug(
                    "Suppressing %s grid-line underlines inside checkbox tables on page %s",
                    len(grid_line_ids),
                    page_idx,
                )
                used_ids.update(grid_line_ids)
        text_line_noise_ids = _collect_text_line_noise_ids(
            underline_candidates,
            page_labels,
            prompt_like_count=prompt_like_count,
            median_label_height=median_label_height,
        )
        if text_line_noise_ids:
            logger.debug(
                "Flagged %s text-baseline line candidates on page %s",
                len(text_line_noise_ids),
                page_idx,
            )
        blocked_line_ids = set(short_line_text_ids)
        if paragraph_line_ids:
            blocked_line_ids.update(paragraph_line_ids)
        if grid_line_ids:
            blocked_line_ids.update(grid_line_ids)
        if text_line_noise_ids:
            blocked_line_ids.update(text_line_noise_ids)
            max_dx = max(140.0, page_width * 0.35) if page_width else 180.0
            max_dy = max(10.0, median_label_height * 1.6)
            suppressed = 0
            for ln in underline_candidates:
                cid = ln.get("id")
                bbox = ln.get("bbox")
                if not cid or not bbox or len(bbox) != 4:
                    continue
                if cid in blocked_line_ids:
                    continue
                if not _line_has_prompt_label_nearby(
                    bbox,
                    page_labels,
                    max_dx=max_dx,
                    max_dy=max_dy,
                ):
                    blocked_line_ids.add(cid)
                    suppressed += 1
            if suppressed:
                logger.debug(
                    "Blocked %s lines on page %s due to text-line noise",
                    suppressed,
                    page_idx,
                )
        if noisy_checkbox_page:
            noisy_line_min_len = max(120.0, median_label_height * 12.0)
            noisy_line_ids = set()
            for ln in underline_candidates:
                cid = ln.get("id")
                bbox = ln.get("bbox")
                if not cid or not bbox or len(bbox) != 4:
                    continue
                length = float(ln.get("length") or (float(bbox[2]) - float(bbox[0])))
                if length < noisy_line_min_len:
                    noisy_line_ids.add(cid)
            if noisy_line_ids:
                blocked_line_ids.update(noisy_line_ids)
                logger.debug(
                    "Blocked %s short lines on page %s due to checkbox noise",
                    len(noisy_line_ids),
                    page_idx,
                )
        if non_form_page and underline_candidates:
            blocked_line_ids.update(
                cid for cid in (ln.get("id") for ln in underline_candidates) if cid
            )
            logger.debug(
                "Blocked %s lines on page %s due to missing form cues",
                len(underline_candidates),
                page_idx,
            )
        line_candidates_by_id = {
            ln.get("id"): ln for ln in underline_candidates if ln.get("id")
        }
        split_line_ids: set[str] = set()
        split_line_labels: Dict[str, List[Dict]] = {}
        if underline_candidates and usable_labels:
            usable_lines = [
                ln for ln in underline_candidates if ln.get("id") not in blocked_line_ids
            ]
            label_min_dy: Dict[Tuple[float, float, float, float], Optional[float]] = {}
            for lb in usable_labels:
                lbbox = lb.get("bbox") or []
                if len(lbbox) != 4:
                    continue
                label_min_dy[tuple(float(v) for v in lbbox)] = _label_min_line_dy(
                    lbbox, usable_lines, min_overlap=0.25
                )
            split_max_dy = max(24.0, min(90.0, median_label_height * 10.0))
            split_min_len = max(160.0, page_width * 0.45)
            split_dy_margin = max(8.0, median_label_height * 1.2)
            for ln in underline_candidates:
                cid = ln.get("id")
                bbox = ln.get("bbox")
                if not cid or not bbox or len(bbox) != 4:
                    continue
                if cid in blocked_line_ids:
                    continue
                if table_region and _rects_intersect(bbox, table_region):
                    continue
                length = float(ln.get("length") or (float(bbox[2]) - float(bbox[0])))
                if length < split_min_len:
                    continue
                matches: List[Dict] = []
                for lb in usable_labels:
                    lb_text = (lb.get("text") or "").strip()
                    if not _label_supports_split_line(lb_text):
                        continue
                    lbbox = lb.get("bbox") or []
                    if len(lbbox) != 4:
                        continue
                    dy = float(bbox[1]) - float(lbbox[3])
                    if dy < -1.0 or dy > split_max_dy:
                        continue
                    min_dy = label_min_dy.get(tuple(float(v) for v in lbbox))
                    if min_dy is not None and dy > (min_dy + split_dy_margin):
                        continue
                    overlap = min(float(bbox[2]), float(lbbox[2])) - max(
                        float(bbox[0]), float(lbbox[0])
                    )
                    if overlap <= 0:
                        continue
                    matches.append(lb)
                if len(matches) < 2:
                    continue
                split_line_ids.add(cid)
                split_line_labels[cid] = matches
        split_label_bboxes = {
            tuple(float(v) for v in (lb.get("bbox") or []))
            for labels in split_line_labels.values()
            for lb in labels
            if isinstance(lb.get("bbox"), list) and len(lb.get("bbox")) == 4
        }

        # Checkbox fields: create fields for ALL checkbox candidates.
        #
        # Motivation:
        # - Many pages contain checkbox grids without clean nearby labels (charts, matrices,
        #   Yes/No columns). If we require a label match with confidence gating we end up
        #   dropping real checkboxes (see errorYesNoCheckBox.png).
        # - Checkbox detection itself is the hard part. Once we have robust checkbox bboxes,
        #   field creation should be exhaustive, and naming can be refined later (OpenAI rename pass).
        if not suppress_checkbox_fields:
            for cb in checkbox_candidates:
                cid = cb.get("id")
                bbox = cb.get("bbox")
                if not cid or not bbox or len(bbox) != 4:
                    continue
                detector = str(cb.get("detector") or "").lower()
                if detector == "table_cells" and not allow_table_cells_checkboxes:
                    continue
                if cid in used_ids:
                    continue

                best_label = None
                best_score = None
                cb_mid_x, cb_mid_y = _bbox_mid(bbox)
                if label_index and len(label_index):
                    label_candidates = label_index.iter_candidates(
                        cb_mid_x, cb_mid_y, k=18, y_range=40
                    )
                else:
                    label_candidates = page_labels
                for lb in label_candidates:
                    lb_bbox = lb.get("bbox") or []
                    score = _score_checkbox_to_label(bbox, lb_bbox)
                    if score is None:
                        continue
                    if best_score is None or score < best_score:
                        best_score = score
                        best_label = lb

                label_confidence = None
                if best_label is not None and best_score is not None:
                    label_text = (best_label.get("text") or "").strip()
                    # Skip legend squares (not real inputs). These appear as checkbox-like boxes
                    # next to labels like "Past Condition" / "Ongoing Condition" on some medical forms.
                    label_norm = re.sub(r"\\s+", " ", label_text).strip().lower()
                    label_norm = re.sub(r"^[^a-z0-9]+", "", label_norm)
                    label_norm = re.sub(r"[^a-z0-9]+$", "", label_norm)
                    if label_norm in {"past condition", "ongoing condition"}:
                        used_ids.add(cid)
                        continue
                    base = "i_" + _to_snake_case(label_text)
                    label_confidence = max(0.55, min(0.92, 1.0 - (best_score / 260.0)))
                    # Only use label-derived names when the match is reasonably strong; otherwise
                    # we prefer a generic checkbox name to avoid mislabeling.
                    if label_confidence >= 0.65:
                        name = _next_name(name_counts, base)
                        confidence = float(label_confidence)
                    else:
                        name = _next_name(name_counts, f"i_checkbox_p{page_idx}")
                        confidence = 0.72
                else:
                    name = _next_name(name_counts, f"i_checkbox_p{page_idx}")
                    confidence = 0.72

                snap_y = _snap_checkbox_row(
                    cb_mid_y,
                    checkbox_row_centers,
                    tolerance=checkbox_snap_tol,
                )
                if snap_y is not None and abs(float(snap_y) - float(cb_mid_y)) < 1.0:
                    snap_y = None
                force_size = detector in {"table_cells", "grid_complete"}
                label_bbox = best_label.get("bbox") if best_label else None
                if detector in {"table_cells", "grid_complete", "table_text_cell"}:
                    label_bbox = None
                if detector in {"vector_rect", "glyph"}:
                    label_bbox = None
                    snap_y = None
                if detector in {"table_cells", "grid_complete", "table_text_cell"}:
                    snap_y = None
                rect = make_checkbox_rect(
                    bbox,
                    page_width,
                    page_height,
                    label_bbox=label_bbox,
                    snap_y=snap_y,
                    median_label_height=median_label_height,
                    target_size=checkbox_size_hint,
                    force_size=force_size,
                )
                used_ids.add(cid)
                fields.append(
                    {
                        "name": name,
                        "type": "checkbox",
                        "page": page_idx,
                        "candidateId": cid,
                        "rect": rect,
                        "confidence": float(confidence),
                        "category": _category_for_confidence(float(confidence), thresholds),
                    }
                )

        global_line_assignments = _assign_underlines_globally(
            usable_labels,
            underline_candidates,
            page_idx=page_idx,
            expected_offset=expected_offset,
            blocked_line_ids=blocked_line_ids,
            footer_bands=footer_bands,
            paragraph_bands=paragraph_bands,
            full_width_line_ids=full_width_line_ids,
            split_line_ids=split_line_ids,
            page_width=page_width,
            page_labels=page_labels,
            median_label_height=median_label_height,
        )

        # Text-like fields: label -> underline/box.
        label_bboxes = [lb.get("bbox") for lb in page_labels if lb.get("bbox")]
        for label_idx, label in enumerate(usable_labels):
            label_text = (label.get("text") or "").strip()
            label_bbox = label.get("bbox") or []
            if tuple(float(v) for v in label_bbox) in split_label_bboxes:
                continue

            inferred_type = _infer_type_from_label(label_text)

            assigned = global_line_assignments.get(label_idx)
            if assigned:
                best_line, best_score, best_orientation = assigned
                second_best_score = None
            else:
                best_line, best_score, second_best_score, best_orientation = _pick_best_underline(
                    label_bbox,
                    underline_candidates,
                    used_ids,
                    expected_offset=expected_offset,
                    label_text=label_text,
                    footer_bands=footer_bands,
                    blocked_line_ids=blocked_line_ids,
                    paragraph_bands=paragraph_bands,
                    full_width_line_ids=full_width_line_ids,
                    page_width=page_width,
                    page_labels=page_labels,
                    page_checkboxes=checkbox_candidates,
                    median_label_height=median_label_height,
                    split_line_ids=split_line_ids,
                )
            chosen = None
            chosen_kind = None

            if best_line is not None:
                chosen = best_line
                chosen_kind = "line"
            else:
                best_box = _pick_best_box(label_bbox, box_candidates, used_ids)
                if best_box is not None:
                    chosen = best_box
                    chosen_kind = "box"

            if chosen is None:
                continue

            # Confidence derived from score + ambiguity between top two choices.
            # Scores are in "points space", so keep mapping intentionally coarse.
            if best_score is None:
                confidence = 0.75
            else:
                confidence = max(0.5, min(0.93, 1.0 - (best_score / 240.0)))
                if second_best_score is not None and abs(second_best_score - best_score) < 10:
                    confidence = min(confidence, 0.72)

            is_paragraph_prompt = _label_is_paragraph_prompt(label_text)
            if confidence < min_confidence:
                if not is_paragraph_prompt or confidence < (min_confidence - 0.12):
                    continue

            base = _to_snake_case(label_text)
            if best_orientation == "left" and inferred_type == "text":
                base = f"{base}_score"
            name = _next_name(name_counts, base)

            candidate_id = chosen.get("id")
            chosen_bbox = chosen.get("bbox")
            if not candidate_id or not chosen_bbox:
                continue

            if chosen_kind == "line" and inferred_type == "text" and is_paragraph_prompt:
                paragraph_lines = _collect_paragraph_line_group(
                    chosen,
                    underline_candidates,
                    used_ids=used_ids,
                    blocked_line_ids=blocked_line_ids,
                    paragraph_line_ids=paragraph_line_ids,
                    page_labels=page_labels,
                    median_label_height=median_label_height,
                    page_width=page_width,
                    table_region=table_region,
                )
            if chosen_kind == "line" and inferred_type == "text":
                paragraph_lines = _collect_paragraph_line_group(
                    chosen,
                    underline_candidates,
                    used_ids=used_ids,
                    blocked_line_ids=blocked_line_ids,
                    paragraph_line_ids=paragraph_line_ids,
                    page_labels=page_labels,
                    median_label_height=median_label_height,
                    page_width=page_width,
                    table_region=table_region,
                )
                label_name_text = _compose_row_label_text(
                    label,
                    page_labels,
                    median_label_height=median_label_height,
                    page_width=page_width,
                )
                prompt_band_text = _compose_prompt_text_above_line(
                    chosen_bbox,
                    page_labels,
                    median_label_height=median_label_height,
                    page_width=page_width,
                    max_dy=max(60.0, median_label_height * 6.0),
                )
                prompt_text = prompt_band_text or label_name_text
                use_paragraph_group = False
                if paragraph_lines and len(paragraph_lines) > 1:
                    if is_paragraph_prompt:
                        use_paragraph_group = True
                    elif len(paragraph_lines) >= 3 and _label_is_loose_prompt(prompt_text):
                        use_paragraph_group = True
                if use_paragraph_group:
                    base = f"{_paragraph_base_from_label(prompt_text)}_paragraph"
                    for ln in paragraph_lines:
                        line_id = ln.get("id")
                        line_bbox = ln.get("bbox") or []
                        if not line_id or len(line_bbox) != 4:
                            continue
                        rect = make_text_field_rect_from_underline(
                            line_bbox, calibration, page_width, page_height, label_bboxes
                        )
                        fields.append(
                            {
                                "name": _next_name(name_counts, base),
                                "type": inferred_type,
                                "page": page_idx,
                                "candidateId": line_id,
                                "rect": rect,
                                "confidence": float(confidence),
                                "category": _category_for_confidence(float(confidence), thresholds),
                            }
                        )
                        used_ids.add(line_id)
                    used_label_bboxes.add(tuple(float(v) for v in label_bbox))
                    continue

            # Deterministic rect construction.
            if inferred_type == "signature" and chosen_kind == "line":
                rect = make_signature_field_rect_from_underline(
                    chosen_bbox, calibration, page_width, page_height, label_bboxes
                )
            elif inferred_type in ("text", "date") and chosen_kind == "line":
                rect = make_text_field_rect_from_underline(
                    chosen_bbox, calibration, page_width, page_height, label_bboxes
                )
            elif chosen_kind == "box":
                rect = make_box_field_rect(chosen_bbox, page_width, page_height)
            else:
                rect = chosen_bbox

            used_ids.add(candidate_id)
            fields.append(
                {
                    "name": name,
                    "type": inferred_type,
                    "page": page_idx,
                    "candidateId": candidate_id,
                    "rect": rect,
                    "confidence": float(confidence),
                    "category": _category_for_confidence(float(confidence), thresholds),
                }
            )
            used_label_bboxes.add(tuple(float(v) for v in label_bbox))

        # Split long underlines that serve multiple column labels on the same row.
        if split_line_labels:
            split_min_segment_width = max(60.0, median_label_height * 5.5)
            for cid, matches in split_line_labels.items():
                if cid in used_ids:
                    continue
                ln = line_candidates_by_id.get(cid)
                if not ln:
                    continue
                bbox = ln.get("bbox") or []
                if len(bbox) != 4:
                    continue
                filtered = []
                for lb in matches:
                    lbbox = lb.get("bbox") or []
                    if len(lbbox) != 4:
                        continue
                    if tuple(float(v) for v in lbbox) in used_label_bboxes:
                        continue
                    filtered.append(lb)
                if len(filtered) == 1:
                    lb = filtered[0]
                    lbbox = lb.get("bbox") or []
                    if len(lbbox) != 4:
                        continue
                    label_text = (lb.get("text") or "").strip()
                    inferred_type = _infer_type_from_label(label_text)
                    if inferred_type == "signature":
                        rect = make_signature_field_rect_from_underline(
                            bbox, calibration, page_width, page_height, label_bboxes
                        )
                        field_type = "signature"
                    else:
                        rect = make_text_field_rect_from_underline(
                            bbox, calibration, page_width, page_height, label_bboxes
                        )
                        field_type = "date" if inferred_type == "date" else "text"
                    base = _to_snake_case(label_text) if label_text else "line"
                    name = _next_name(name_counts, base)
                    fields.append(
                        {
                            "name": name,
                            "type": field_type,
                            "page": page_idx,
                            "candidateId": cid,
                            "rect": rect,
                            "confidence": 0.72,
                            "category": _category_for_confidence(0.72, thresholds),
                        }
                    )
                    used_label_bboxes.add(tuple(float(v) for v in lbbox))
                    used_ids.add(cid)
                    continue
                if len(filtered) < 2:
                    continue
                filtered.sort(key=lambda lb: _bbox_mid(lb.get("bbox") or [0, 0, 0, 0])[0])
                centers = [
                    _bbox_mid(lb.get("bbox") or [0, 0, 0, 0])[0] for lb in filtered
                ]
                boundaries = [float(bbox[0])]
                for left, right in zip(centers, centers[1:]):
                    boundaries.append((left + right) / 2.0)
                boundaries.append(float(bbox[2]))
                line_used = False
                for idx, lb in enumerate(filtered):
                    lbbox = lb.get("bbox") or []
                    if len(lbbox) != 4:
                        continue
                    seg_x1 = max(float(bbox[0]), boundaries[idx])
                    seg_x2 = min(float(bbox[2]), boundaries[idx + 1])
                    if (seg_x2 - seg_x1) < split_min_segment_width:
                        continue
                    seg_bbox = [seg_x1, float(bbox[1]), seg_x2, float(bbox[3])]
                    label_text = (lb.get("text") or "").strip()
                    inferred_type = _infer_type_from_label(label_text)
                    if inferred_type == "signature":
                        rect = make_signature_field_rect_from_underline(
                            seg_bbox, calibration, page_width, page_height, label_bboxes
                        )
                        field_type = "signature"
                    else:
                        rect = make_text_field_rect_from_underline(
                            seg_bbox, calibration, page_width, page_height, label_bboxes
                        )
                        field_type = "date" if inferred_type == "date" else "text"
                    base = _to_snake_case(label_text) if label_text else "line"
                    name = _next_name(name_counts, base)
                    fields.append(
                        {
                            "name": name,
                            "type": field_type,
                            "page": page_idx,
                            "candidateId": cid,
                            "rect": rect,
                            "confidence": 0.72,
                            "category": _category_for_confidence(0.72, thresholds),
                        }
                    )
                    used_label_bboxes.add(tuple(float(v) for v in lbbox))
                    line_used = True
                if line_used:
                    used_ids.add(cid)

        # Fallback: some forms place signature/date labels BELOW their underline.
        # If a long, unused line sits just above one or more such labels, split the line
        # into segments and emit fields anchored to those segments.
        if underline_candidates:
            below_labels = [
                lb
                for lb in page_labels
                if _label_supports_line_above((lb.get("text") or "").strip())
                and isinstance(lb.get("bbox"), list)
                and len(lb.get("bbox")) == 4
            ]
            if below_labels:
                max_dy = max(12.0, median_label_height * 2.2)
                # Signature/date blanks are often shorter than 30% width, so keep this
                # threshold looser to avoid missing right-aligned date lines.
                min_line_len = max(120.0, page_width * 0.25)
                min_segment_width = max(60.0, median_label_height * 5.5)
                for ln in underline_candidates:
                    cid = ln.get("id")
                    bbox = ln.get("bbox")
                    if not cid or cid in used_ids or not bbox or len(bbox) != 4:
                        continue
                    if table_region and _rects_intersect(bbox, table_region):
                        continue
                    line_len = float(ln.get("length") or (float(bbox[2]) - float(bbox[0])))
                    if line_len < min_line_len:
                        continue

                    matches: List[Dict] = []
                    for lb in below_labels:
                        lbbox = lb.get("bbox") or []
                        dy = float(lbbox[1]) - float(bbox[3])
                        if dy < -1.0 or dy > max_dy:
                            continue
                        overlap = min(float(bbox[2]), float(lbbox[2])) - max(
                            float(bbox[0]), float(lbbox[0])
                        )
                        if overlap <= 0:
                            continue
                        label_width = max(1.0, float(lbbox[2]) - float(lbbox[0]))
                        if (overlap / label_width) < 0.35:
                            continue
                        matches.append(lb)

                    if not matches:
                        continue

                    if full_width_line_ids and cid in full_width_line_ids:
                        filtered_matches = []
                        for lb in matches:
                            label_text = (lb.get("text") or "").strip()
                            if _label_supports_full_width_line(label_text):
                                filtered_matches.append(lb)
                        if not filtered_matches:
                            continue
                        matches = filtered_matches

                    matches.sort(key=lambda lb: _bbox_mid(lb.get("bbox") or [0, 0, 0, 0])[0])
                    centers = [
                        _bbox_mid(lb.get("bbox") or [0, 0, 0, 0])[0] for lb in matches
                    ]
                    boundaries = [float(bbox[0])]
                    for left, right in zip(centers, centers[1:]):
                        boundaries.append((left + right) / 2.0)
                    boundaries.append(float(bbox[2]))

                    line_used = False
                    for idx, lb in enumerate(matches):
                        seg_x1 = max(float(bbox[0]), boundaries[idx])
                        seg_x2 = min(float(bbox[2]), boundaries[idx + 1])
                        if (seg_x2 - seg_x1) < min_segment_width:
                            continue
                        seg_bbox = [seg_x1, float(bbox[1]), seg_x2, float(bbox[3])]
                        label_text = (lb.get("text") or "").strip()
                        inferred_type = _infer_type_from_label(label_text)
                        if inferred_type == "signature":
                            rect = make_signature_field_rect_from_underline(
                                seg_bbox, calibration, page_width, page_height, label_bboxes
                            )
                            field_type = "signature"
                        else:
                            rect = make_text_field_rect_from_underline(
                                seg_bbox, calibration, page_width, page_height, label_bboxes
                            )
                            field_type = "date" if inferred_type == "date" else "text"

                        base = f"i_{_to_snake_case(label_text)}" if label_text else "footer_line"
                        name = _next_name(name_counts, base)
                        fields.append(
                            {
                                "name": name,
                                "type": field_type,
                                "page": page_idx,
                                "candidateId": cid,
                                "rect": rect,
                                "confidence": 0.72,
                                "category": _category_for_confidence(0.72, thresholds),
                            }
                        )
                        line_used = True
                    if line_used:
                        used_ids.add(cid)

        # Fallback: "Other/specify" blanks inside option lists.
        # These labels can be suppressed as option groups, but the trailing underline is a real input.
        if underline_candidates:
            other_labels = [
                lb
                for lb in page_labels
                if _label_supports_other_blank((lb.get("text") or "").strip())
                and isinstance(lb.get("bbox"), list)
                and len(lb.get("bbox")) == 4
            ]
            for label in other_labels:
                label_text = (label.get("text") or "").strip()
                label_bbox = label.get("bbox") or []
                best_line, best_score, second_best_score, _ = _pick_best_underline(
                    label_bbox,
                    underline_candidates,
                    used_ids,
                    expected_offset=expected_offset,
                    label_text=label_text,
                    footer_bands=footer_bands,
                    blocked_line_ids=blocked_line_ids,
                    paragraph_bands=paragraph_bands,
                    full_width_line_ids=full_width_line_ids,
                    page_width=page_width,
                    page_labels=page_labels,
                    page_checkboxes=checkbox_candidates,
                    median_label_height=median_label_height,
                    split_line_ids=split_line_ids,
                )
                if best_line is None:
                    continue
                line_bbox = best_line.get("bbox") or []
                if len(line_bbox) != 4:
                    continue
                line_len = float(best_line.get("length") or (line_bbox[2] - line_bbox[0]))
                max_other_len = max(220.0, page_width * 0.95)
                if line_len > max_other_len:
                    continue
                if best_score is None:
                    confidence = 0.72
                else:
                    confidence = max(0.5, min(0.9, 1.0 - (best_score / 260.0)))
                    if second_best_score is not None and abs(second_best_score - best_score) < 10:
                        confidence = min(confidence, 0.7)
                if confidence < (min_confidence - 0.05):
                    continue
                lower = label_text.lower()
                base = "other" if "other" in lower else "specify"
                rect = make_text_field_rect_from_underline(
                    line_bbox, calibration, page_width, page_height, label_bboxes
                )
                used_ids.add(best_line.get("id"))
                fields.append(
                    {
                        "name": _next_name(name_counts, base),
                        "type": "text",
                        "page": page_idx,
                        "candidateId": best_line.get("id"),
                        "rect": rect,
                        "confidence": float(confidence),
                        "category": _category_for_confidence(float(confidence), thresholds),
                    }
                )

        # Prune any remaining short lines that sit on dense paragraph/footnote bands
        # without a nearby label prompt. These are usually text baselines, not inputs.
        if paragraph_bands:
            pruned_ids = set()
            for ln in underline_candidates:
                cid = ln.get("id")
                bbox = ln.get("bbox")
                if not cid or not bbox or len(bbox) != 4:
                    continue
                if cid in used_ids:
                    continue
                if ln.get("detector") not in ("morph_short", "morph_long"):
                    continue
                if not _in_footer_band(bbox, paragraph_bands):
                    continue
                if _line_has_prompt_label_nearby(
                    bbox,
                    page_labels,
                    max_dx=page_width * 0.45,
                    max_dy=max(10.0, median_label_height * 1.8),
                ):
                    continue
                pruned_ids.add(cid)
            if pruned_ids:
                used_ids.update(pruned_ids)

        # Recover prompt-aligned underlines that were not matched to a usable label.
        # This favors recall over precision; OpenAI filtering is expected to prune false positives.
        if not noisy_checkbox_page:
            recovered_prompt = 0
            prompt_min_len = max(12.0, median_label_height * 1.4)
            prompt_y_tol = max(10.0, min(36.0, median_label_height * 2.2))
            for ln in underline_candidates:
                cid = ln.get("id")
                bbox = ln.get("bbox")
                if not cid or not bbox or len(bbox) != 4:
                    continue
                if cid in used_ids or cid in blocked_line_ids:
                    continue
                if full_width_line_ids and cid in full_width_line_ids:
                    continue
                if table_region and _rects_intersect(bbox, table_region):
                    continue
                length = float(ln.get("length") or (float(bbox[2]) - float(bbox[0])))
                if length < prompt_min_len:
                    continue
                if not _line_has_prompt_label_nearby(
                    bbox,
                    page_labels,
                    max_dx=page_width * 0.5,
                    max_dy=prompt_y_tol,
                ):
                    continue
                rect = make_text_field_rect_from_underline(
                    bbox, calibration, page_width, page_height, label_bboxes
                )
                used_ids.add(cid)
                recovered_prompt += 1
                fields.append(
                    {
                        "name": _next_name(name_counts, f"line_p{page_idx}"),
                        "type": "text",
                        "page": page_idx,
                        "candidateId": cid,
                        "rect": rect,
                        "confidence": 0.68,
                        "category": _category_for_confidence(0.68, thresholds),
                    }
                )
            if recovered_prompt:
                logger.debug(
                    "Recovered %s prompt-aligned underlines on page %s",
                    recovered_prompt,
                    page_idx,
                )

        # Recover any remaining short underlines on form-heavy pages. This is intentionally
        # recall-focused and still honors the noise/blocking filters.
        if not noisy_checkbox_page and not non_form_page:
            short_min_len = max(8.0, median_label_height * 0.9)
            short_max_len = max(140.0, median_label_height * 12.0)
            short_y_tol = max(8.0, median_label_height * 1.4)
            recovered_short = 0
            for ln in underline_candidates:
                cid = ln.get("id")
                bbox = ln.get("bbox")
                if not cid or not bbox or len(bbox) != 4:
                    continue
                if cid in used_ids or cid in blocked_line_ids:
                    continue
                if full_width_line_ids and cid in full_width_line_ids:
                    continue
                if table_region and _rects_intersect(bbox, table_region):
                    continue
                length = float(ln.get("length") or (float(bbox[2]) - float(bbox[0])))
                if length < short_min_len or length > short_max_len:
                    continue
                if _line_has_yes_no_tokens(
                    bbox,
                    page_labels,
                    max_dy=short_y_tol,
                ):
                    continue
                rect = make_text_field_rect_from_underline(
                    bbox, calibration, page_width, page_height, label_bboxes
                )
                used_ids.add(cid)
                recovered_short += 1
                fields.append(
                    {
                        "name": _next_name(name_counts, f"short_p{page_idx}"),
                        "type": "text",
                        "page": page_idx,
                        "candidateId": cid,
                        "rect": rect,
                        "confidence": 0.62,
                        "category": _category_for_confidence(0.62, thresholds),
                    }
                )
            if recovered_short:
                logger.debug(
                    "Recovered %s short underlines on page %s",
                    recovered_short,
                    page_idx,
                )

        # Short underlines that sit to the LEFT of long paragraph labels are commonly used for
        # "initial here" blanks on consent forms. Those labels are filtered out as non-input
        # text, so the underline goes unmatched and we miss the field. Recover them with a
        # strict positional check against the full label set (not just usable_labels).
        if not noisy_checkbox_page:
            initials_max_len = max(40.0, min(160.0, page_width * 0.26))
            initials_left_margin = page_width * 0.30
            initials_sentence_margin = page_width * 0.22
            initials_left_gap = min(60.0, max(30.0, page_width * 0.08))
            initials_min_len = max(16.0, median_label_height * 2.0)
            initials_y_tol = max(10.0, min(36.0, median_label_height * 2.0))
            for ln in underline_candidates:
                cid = ln.get("id")
                bbox = ln.get("bbox")
                if not cid or not bbox or len(bbox) != 4:
                    continue
                if cid in used_ids:
                    continue
                if ln.get("detector") != "morph_short":
                    continue
                if ln.get("id") in short_line_text_ids:
                    continue
                if table_region and _rects_intersect(bbox, table_region):
                    continue
                if _line_has_yes_no_tokens(
                    bbox,
                    page_labels,
                    max_dy=max(8.0, median_label_height * 1.2),
                ):
                    continue
                footer_hit = _in_footer_band(bbox, footer_bands)
                length = float(ln.get("length") or (float(bbox[2]) - float(bbox[0])))
                if length <= 0.0 or length > initials_max_len:
                    continue
                if _line_has_left_blocking_label(
                    bbox,
                    page_labels,
                    max_dx=initials_left_gap,
                    max_dy=initials_y_tol,
                ):
                    continue
                aligned_label = False
                if label_index and len(label_index):
                    line_left_near_margin = float(bbox[0]) <= initials_sentence_margin
                    mid_x, mid_y = _bbox_mid(bbox)
                    for lb in label_index.iter_candidates(
                        mid_x, mid_y, k=20, y_range=initials_y_tol
                    ):
                        lb_bbox = lb.get("bbox") or []
                        if len(lb_bbox) != 4:
                            continue
                        if abs(_bbox_mid(lb_bbox)[1] - mid_y) > initials_y_tol:
                            continue
                        if float(lb_bbox[0]) < (float(bbox[2]) - 6.0):
                            continue
                        lb_text = (lb.get("text") or "").strip()
                        explicit_initial = any(
                            key in lb_text.lower() for key in ("initial", "sign", "signature")
                        )
                        if not explicit_initial and not line_left_near_margin:
                            continue
                        if not _label_supports_initials_blank(lb_text):
                            continue
                        if footer_hit and not _label_supports_footer_short_line(lb_text):
                            continue
                        if len(lb_text) < 6:
                            continue
                        aligned_label = True
                        if DEBUG_INITIALS_FALLBACK:
                            logger.debug(
                                "Initials fallback aligned line %s with label '%s' (explicit=%s)",
                                cid,
                                lb_text,
                                explicit_initial,
                            )
                        break
                if footer_hit and not aligned_label:
                    continue
                if not aligned_label and length < initials_min_len:
                    continue
                if not aligned_label and float(bbox[0]) > initials_left_margin:
                    continue
                rect = make_text_field_rect_from_underline(
                    bbox, calibration, page_width, page_height, label_bboxes
                )
                used_ids.add(cid)
                fields.append(
                    {
                        "name": _next_name(name_counts, f"initials_p{page_idx}"),
                        "type": "text",
                        "page": page_idx,
                        "candidateId": cid,
                        "rect": rect,
                        "confidence": 0.72,
                        "category": _category_for_confidence(0.72, thresholds),
                    }
                )

        # Table-derived text-entry cells: always generate fields for them.
        if allow_table_text_cells:
            for bx in box_candidates:
                cid = bx.get("id")
                bbox = bx.get("bbox")
                if not cid or not bbox or len(bbox) != 4:
                    continue
                if cid in used_ids:
                    continue
                if bx.get("detector") != "table_text_cell":
                    continue
                # Skip header/example cells that contain printed text. We only want blank cells to
                # become text-entry fields.
                if _table_cell_contains_text(bbox, page_labels):
                    continue
                if _table_cell_is_checkbox(
                    bbox, checkbox_header_labels, median_label_height=median_label_height
                ):
                    rect = make_checkbox_rect(
                        bbox,
                        page_width,
                        page_height,
                        median_label_height=median_label_height,
                        target_size=checkbox_size_hint,
                        force_size=True,
                    )
                    field_type = "checkbox"
                else:
                    rect = make_box_field_rect(bbox, page_width, page_height)
                    field_type = "text"
                used_ids.add(cid)
                fields.append(
                    {
                        "name": _next_name(
                            name_counts,
                            f"i_checkbox_p{page_idx}" if field_type == "checkbox" else f"table_cell_p{page_idx}",
                        ),
                        "type": field_type,
                        "page": page_idx,
                        "candidateId": cid,
                        "rect": rect,
                        "confidence": 0.72,
                        "category": _category_for_confidence(0.72, thresholds),
                    }
                )

        # Label-poor fallback:
        # For pages where we could not extract any *usable* labels (scanned-only pages or
        # OCR failures), create fields directly from geometry candidates.
        if not usable_labels:
            # Table-derived cells: these are true interactive areas even without text.
            if allow_table_text_cells:
                for bx in box_candidates:
                    cid = bx.get("id")
                    bbox = bx.get("bbox")
                    if not cid or not bbox or len(bbox) != 4 or cid in used_ids:
                        continue
                    if bx.get("detector") != "table_text_cell":
                        continue
                    if _table_cell_contains_text(bbox, page_labels):
                        continue
                    if _table_cell_is_checkbox(
                        bbox, checkbox_header_labels, median_label_height=median_label_height
                    ):
                        rect = make_checkbox_rect(
                            bbox,
                            page_width,
                            page_height,
                            median_label_height=median_label_height,
                            target_size=checkbox_size_hint,
                            force_size=True,
                        )
                        field_type = "checkbox"
                    else:
                        rect = make_box_field_rect(bbox, page_width, page_height)
                        field_type = "text"
                    used_ids.add(cid)
                    fields.append(
                        {
                            "name": _next_name(
                                name_counts,
                                f"i_checkbox_p{page_idx}"
                                if field_type == "checkbox"
                                else f"table_cell_p{page_idx}",
                            ),
                            "type": field_type,
                            "page": page_idx,
                            "candidateId": cid,
                            "rect": rect,
                            "confidence": 0.72,
                            "category": _category_for_confidence(0.72, thresholds),
                        }
                    )

            # Free-form underlines: treat as text fields, but avoid table grid regions and
            # page-wide divider rules.
            for ln in underline_candidates:
                cid = ln.get("id")
                bbox = ln.get("bbox")
                if not cid or not bbox or len(bbox) != 4 or cid in used_ids:
                    continue
                if cid in blocked_line_ids:
                    continue
                if cid in short_line_text_ids:
                    continue
                if table_region and _rects_intersect(bbox, table_region):
                    continue
                length = float(ln.get("length") or (float(bbox[2]) - float(bbox[0])))
                if length >= 560:
                    continue
                rect = make_text_field_rect_from_underline(bbox, calibration, page_width, page_height, [])
                used_ids.add(cid)
                fields.append(
                    {
                        "name": _next_name(name_counts, f"line_p{page_idx}"),
                        "type": "text",
                        "page": page_idx,
                        "candidateId": cid,
                        "rect": rect,
                        "confidence": 0.72,
                        "category": _category_for_confidence(0.72, thresholds),
                    }
                )

            # Checkboxes: treat all checkbox candidates as fields.
            if not suppress_checkbox_fields:
                for cb in checkbox_candidates:
                    cid = cb.get("id")
                    bbox = cb.get("bbox")
                    if not cid or not bbox or len(bbox) != 4 or cid in used_ids:
                        continue
                    detector = str(cb.get("detector") or "").lower()
                    if detector == "table_cells" and not allow_table_cells_checkboxes:
                        continue
                    snap_y = None
                    if detector not in {"vector_rect", "glyph", "table_cells", "grid_complete", "table_text_cell"}:
                        snap_y = _snap_checkbox_row(
                            _bbox_mid(bbox)[1],
                            checkbox_row_centers,
                            tolerance=checkbox_snap_tol,
                        )
                        if snap_y is not None:
                            cb_mid_y = _bbox_mid(bbox)[1]
                            if abs(float(snap_y) - float(cb_mid_y)) < 1.0:
                                snap_y = None
                    force_size = detector in {"table_cells", "grid_complete"}
                    rect = make_checkbox_rect(
                        bbox,
                        page_width,
                        page_height,
                        snap_y=snap_y,
                        median_label_height=median_label_height,
                        target_size=checkbox_size_hint,
                        force_size=force_size,
                    )
                    used_ids.add(cid)
                    fields.append(
                        {
                            "name": _next_name(name_counts, f"i_checkbox_p{page_idx}"),
                            "type": "checkbox",
                            "page": page_idx,
                            "candidateId": cid,
                            "rect": rect,
                            "confidence": 0.72,
                            "category": _category_for_confidence(0.72, thresholds),
                        }
                    )

    logger.info(
        "Heuristic resolver created %s fields (pages=%s)",
        len(fields),
        len(candidates_json),
    )

    return {
        "sourcePdf": meta.get("source_pdf", "upload.pdf"),
        "sessionId": meta.get("session_id", "heuristic"),
        "coordinateSystem": "originTop",
        "thresholds": thresholds,
        "generatedAt": datetime.now(tz=timezone.utc).isoformat(),
        "fields": fields,
    }
