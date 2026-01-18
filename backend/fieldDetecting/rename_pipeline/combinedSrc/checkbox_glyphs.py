"""
Utilities for recognizing checkbox glyphs in text layers.
"""

from __future__ import annotations

import re
from typing import Iterable

CHECKBOX_GLYPHS = {
    "☐",
    "☑",
    "☒",
    "□",
    "■",
    "▢",
    "▣",
    "◻",
    "◼",
    "◽",
    "◾",
    "▪",
    "▫",
}

# Private-use glyphs commonly used by symbol fonts to render empty checkbox squares.
CHECKBOX_SYMBOL_GLYPHS = {
    "\uf0a8",
}

CHECKBOX_GLYPH_STR = "".join(sorted(CHECKBOX_GLYPHS | CHECKBOX_SYMBOL_GLYPHS))

CHECKBOX_CID_RE = re.compile(r"^\(cid:\d+\)$")

_SYMBOL_FONT_HINTS: Iterable[str] = (
    "wingdings",
    "webdings",
    "zapfdingbats",
    "dingbats",
    "symbol",
)


def _font_looks_symbol(fontname: str | None) -> bool:
    if not fontname:
        return False
    lower = fontname.lower()
    return any(token in lower for token in _SYMBOL_FONT_HINTS)


def _is_private_use(text: str) -> bool:
    if len(text) != 1:
        return False
    return 0xE000 <= ord(text) <= 0xF8FF


def is_checkbox_glyph(text: str, fontname: str | None = None) -> bool:
    """
    Return True if the text-layer glyph is likely a checkbox square.

    We allow standard Unicode squares unconditionally, but require symbol-font
    evidence for private-use or cid-mapped glyphs to avoid random icon matches.
    """
    token = (text or "").strip()
    if not token:
        return False
    if token in CHECKBOX_GLYPHS:
        return True
    if token in CHECKBOX_SYMBOL_GLYPHS:
        return _font_looks_symbol(fontname)
    if not _font_looks_symbol(fontname):
        return False
    if _is_private_use(token):
        return True
    if CHECKBOX_CID_RE.fullmatch(token):
        return True
    return False
