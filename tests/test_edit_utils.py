"""Tests for edit utility functions: _split_at_cursor and _join_lines."""

from lyrsmith.ui.edit_line_modal import _split_at_cursor
from lyrsmith.ui.lyrics_editor import _join_lines


# ---------------------------------------------------------------------------
# _split_at_cursor
# ---------------------------------------------------------------------------


class TestSplitAtCursor:
    def test_basic_split(self):
        first, second = _split_at_cursor("Hello World", 5)
        assert first == "Hello"
        assert second == "World"

    def test_capitalises_second_part(self):
        first, second = _split_at_cursor("hello world", 6)
        assert second[0].isupper()

    def test_keeps_already_capitalised(self):
        first, second = _split_at_cursor("hello World", 6)
        assert second[0].isupper()

    def test_strips_whitespace_around_cut(self):
        first, second = _split_at_cursor("Hello   World", 8)
        assert not first.endswith(" ")
        assert not second.startswith(" ")

    def test_split_at_start(self):
        first, second = _split_at_cursor("Hello World", 0)
        assert first == ""
        assert second == "Hello World"

    def test_split_at_end(self):
        first, second = _split_at_cursor("Hello World", 11)
        assert first == "Hello World"
        assert second == ""

    def test_empty_string(self):
        first, second = _split_at_cursor("", 0)
        assert first == ""
        assert second == ""

    def test_multiple_spaces_stripped(self):
        first, second = _split_at_cursor("One   Two", 6)
        assert first == "One"
        assert second == "Two"

    def test_col_is_offset_into_full_text(self):
        # _split_at_cursor treats col as a raw offset into the full text string,
        # not as a (row, col) cursor. This is correct for single-line text.
        # For multi-line text (if the user presses Enter in the TextArea),
        # the Textual cursor column would refer to the current row only — the
        # caller is responsible for computing the full-text offset in that case.
        text = "Hello World"
        first, second = _split_at_cursor(text, 5)
        assert first == "Hello"
        assert second == "World"


# ---------------------------------------------------------------------------
# _join_lines
# ---------------------------------------------------------------------------


class TestJoinLines:
    def test_lowercases_sentence_start(self):
        result = _join_lines("Hello there,", "How are you")
        assert "how are you" in result

    def test_keeps_pronoun_i(self):
        result = _join_lines("Hello there,", "I am fine")
        assert " I am fine" in result

    def test_keeps_all_caps_word(self):
        result = _join_lines("Hello", "USA rocks")
        assert "USA rocks" in result

    def test_keeps_multichar_all_caps(self):
        result = _join_lines("Visit", "NYC today")
        assert "NYC today" in result

    def test_empty_b_returns_a(self):
        result = _join_lines("Hello", "")
        assert result == "Hello"

    def test_joins_with_space(self):
        result = _join_lines("Hello", "World")
        assert " " in result
        assert result.startswith("Hello")

    def test_already_lowercase_stays(self):
        result = _join_lines("abc", "def")
        assert "def" in result  # no case change needed for already-lowercase

    def test_single_uppercase_letter_not_i(self):
        # "A" alone is a single uppercase letter but not "I" — should lowercase
        result = _join_lines("Hello", "A song")
        assert "a song" in result
