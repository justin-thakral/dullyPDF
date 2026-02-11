from backend.fieldDetecting.rename_pipeline.combinedSrc import checkbox_glyphs as glyphs


def test_font_looks_symbol_and_private_use_helpers() -> None:
    assert glyphs._font_looks_symbol(None) is False
    assert glyphs._font_looks_symbol("Wingdings-Regular") is True

    assert glyphs._is_private_use("\ue000") is True
    assert glyphs._is_private_use("ab") is False


def test_is_checkbox_glyph_handles_symbol_and_plain_paths() -> None:
    assert glyphs.is_checkbox_glyph("☐") is True
    assert glyphs.is_checkbox_glyph("\uf0a8", fontname="Helvetica") is False
    assert glyphs.is_checkbox_glyph("\uf0a8", fontname="Wingdings") is True

    assert glyphs.is_checkbox_glyph("\ue010", fontname="Wingdings") is True
    assert glyphs.is_checkbox_glyph("\ue010", fontname="Helvetica") is False

    assert glyphs.is_checkbox_glyph("(cid:42)", fontname="ZapfDingbats") is True
    assert glyphs.is_checkbox_glyph("", fontname="Wingdings") is False


# ---------------------------------------------------------------------------
# Edge-case tests added below
# ---------------------------------------------------------------------------


def test_is_checkbox_glyph_with_none_text_returns_false() -> None:
    """Passing None as text should be handled gracefully via the
    (text or '').strip() guard, returning False rather than raising."""
    assert glyphs.is_checkbox_glyph(None) is False
    assert glyphs.is_checkbox_glyph(None, fontname="Wingdings") is False


def test_is_checkbox_glyph_with_whitespace_only_text_returns_false() -> None:
    """Whitespace-only strings should be stripped to empty by the guard,
    resulting in an early False return."""
    assert glyphs.is_checkbox_glyph("   ") is False
    assert glyphs.is_checkbox_glyph("\t\n") is False
    assert glyphs.is_checkbox_glyph("   ", fontname="Wingdings") is False


def test_is_private_use_at_upper_boundary() -> None:
    """The upper boundary of the Private Use Area is U+F8FF.
    _is_private_use should return True for this codepoint and False for
    the codepoint immediately above it (U+F900)."""
    assert glyphs._is_private_use("\uF8FF") is True
    # One codepoint past the upper boundary should be outside the range.
    assert glyphs._is_private_use("\uF900") is False
