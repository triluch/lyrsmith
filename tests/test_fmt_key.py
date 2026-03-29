"""Tests for bottom_bar.py — fmt_key translation and _kk prefix collapsing."""

from lyrsmith.ui.bottom_bar import _kk, fmt_key


class TestFmtKey:
    def test_arrows(self):
        assert fmt_key("up") == "↑"
        assert fmt_key("down") == "↓"
        assert fmt_key("left") == "←"
        assert fmt_key("right") == "→"

    def test_named_specials(self):
        assert fmt_key("space") == "Space"
        assert fmt_key("enter") == "Enter"
        assert fmt_key("backspace") == "Bksp"
        assert fmt_key("escape") == "Esc"
        assert fmt_key("tab") == "Tab"

    def test_ctrl_combinations(self):
        assert fmt_key("ctrl+s") == "Ctrl+S"
        assert fmt_key("ctrl+q") == "Ctrl+Q"
        assert fmt_key("ctrl+z") == "Ctrl+Z"
        assert fmt_key("ctrl+enter") == "Ctrl+Enter"

    def test_shift_arrow(self):
        assert fmt_key("shift+left") == "⇧←"
        assert fmt_key("shift+right") == "⇧→"
        assert fmt_key("shift+tab") == "⇧Tab"

    def test_punctuation_display(self):
        assert fmt_key("period") == "."
        assert fmt_key("comma") == ","
        assert fmt_key("apostrophe") == "'"
        assert fmt_key("semicolon") == ";"
        assert fmt_key("plus") == "+"
        assert fmt_key("minus") == "-"

    def test_brackets_escaped_for_rich(self):
        # left bracket must be escaped so Rich doesn't parse it as markup
        assert fmt_key("left_square_bracket") == "\\["
        assert fmt_key("right_square_bracket") == "]"

    def test_single_letter_uppercased(self):
        assert fmt_key("e") == "E"
        assert fmt_key("t") == "T"
        assert fmt_key("m") == "M"
        assert fmt_key("s") == "S"

    def test_unknown_key_falls_back(self):
        # Falls back to key.replace("_", " ").title()
        assert fmt_key("some_unknown_key") == "Some Unknown Key"


class TestKkPrefixCollapsing:
    def test_shared_shift_shows_once(self):
        result = _kk("shift+left", "shift+right", "Seek 30s")
        assert result.count("⇧") == 1

    def test_shared_ctrl_shows_once(self):
        result = _kk("ctrl+a", "ctrl+b", "desc")
        # Only one "Ctrl+" should appear
        assert result.count("Ctrl+") == 1

    def test_no_shared_prefix_shows_both(self):
        result = _kk("up", "down", "Navigate")
        assert "↑" in result
        assert "↓" in result

    def test_description_included(self):
        result = _kk("left", "right", "Seek 5s")
        assert "Seek 5s" in result

    def test_between_separator(self):
        result = _kk("plus", "minus", "Zoom", "/")
        assert "+/-" in result or "+/−" in result or ("+" in result and "-" in result)
