"""Tests for pure LRC editing ops in lyrics_editor.py."""

from __future__ import annotations

import pytest

from lyrsmith.lrc import LRCLine, WordTiming
from lyrsmith.ui.lyrics_editor import (
    _op_delete,
    _op_insert_blank,
    _op_merge,
    _op_nudge,
)


def _make(specs: list[tuple[float, str]]) -> list[LRCLine]:
    return [LRCLine(ts, text) for ts, text in specs]


def _wt(word: str, start: float, end: float) -> WordTiming:
    return WordTiming(word=word, start=start, end=end)


# ---------------------------------------------------------------------------
# _op_nudge
# ---------------------------------------------------------------------------


class TestOpNudge:
    def test_nudge_forward(self):
        lines = _make([(1.0, "A"), (3.0, "B")])
        result, cursor = _op_nudge(lines, 0, 0.5)
        assert result[0].timestamp == pytest.approx(1.5)
        assert cursor == 0

    def test_nudge_backward(self):
        lines = _make([(1.0, "A"), (3.0, "B")])
        result, cursor = _op_nudge(lines, 1, -0.5)
        assert result[1].timestamp == pytest.approx(2.5)
        assert cursor == 1

    def test_nudge_clamps_to_zero(self):
        lines = _make([(1.0, "A")])
        result, _ = _op_nudge(lines, 0, -99.0)
        assert result[0].timestamp == pytest.approx(0.0)

    def test_nudge_reorders_when_overtaking_next(self):
        lines = _make([(1.0, "A"), (2.0, "B")])
        result, cursor = _op_nudge(lines, 0, 5.0)  # A jumps past B
        assert result[0].text == "B"
        assert result[1].text == "A"
        assert cursor == 1  # cursor follows A to its new position

    def test_nudge_cursor_follows_to_earlier_position(self):
        lines = _make([(5.0, "A"), (10.0, "B"), (15.0, "C")])
        # Nudge C backwards until it lands between A and B
        result, cursor = _op_nudge(lines, 2, -7.0)  # 15 - 7 = 8.0 → between A and B
        assert result[1].text == "C"
        assert cursor == 1

    def test_nudge_preserves_other_lines(self):
        lines = _make([(1.0, "A"), (3.0, "B"), (5.0, "C")])
        result, _ = _op_nudge(lines, 1, 0.1)
        assert result[0].text == "A"
        assert result[2].text == "C"

    def test_nudge_out_of_bounds_is_noop(self):
        lines = _make([(1.0, "A")])
        result, cursor = _op_nudge(lines, 5, 0.5)
        assert len(result) == 1
        assert result[0].timestamp == pytest.approx(1.0)
        assert cursor == 5

    def test_nudge_empty_list_is_noop(self):
        lines: list[LRCLine] = []
        result, cursor = _op_nudge(lines, 0, 1.0)
        assert result == []
        assert cursor == 0

    def test_nudge_shifts_end_timestamp(self):
        line = LRCLine(2.0, "A", end=4.0)
        result, _ = _op_nudge([line], 0, 0.5)
        assert result[0].end == pytest.approx(4.5)

    def test_nudge_shifts_word_timings(self):
        line = LRCLine(2.0, "A", words=[_wt(" hello", 2.1, 2.6), _wt(" world", 2.7, 3.2)])
        result, _ = _op_nudge([line], 0, 1.0)
        assert result[0].words[0].start == pytest.approx(3.1)
        assert result[0].words[0].end == pytest.approx(3.6)
        assert result[0].words[1].start == pytest.approx(3.7)
        assert result[0].words[1].end == pytest.approx(4.2)

    def test_nudge_clamps_end_and_words_to_zero(self):
        line = LRCLine(1.0, "A", end=2.0, words=[_wt(" hi", 1.1, 1.5)])
        result, _ = _op_nudge([line], 0, -99.0)
        assert result[0].timestamp == pytest.approx(0.0)
        assert result[0].end == pytest.approx(0.0)
        assert result[0].words[0].start == pytest.approx(0.0)
        assert result[0].words[0].end == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# _op_delete
# ---------------------------------------------------------------------------


class TestOpDelete:
    def test_delete_first(self):
        lines = _make([(1.0, "A"), (2.0, "B"), (3.0, "C")])
        result, cursor = _op_delete(lines, 0)
        assert len(result) == 2
        assert result[0].text == "B"
        assert cursor == 0

    def test_delete_last(self):
        lines = _make([(1.0, "A"), (2.0, "B"), (3.0, "C")])
        result, cursor = _op_delete(lines, 2)
        assert len(result) == 2
        assert result[-1].text == "B"
        assert cursor == 1  # clamped to new last index

    def test_delete_middle(self):
        lines = _make([(1.0, "A"), (2.0, "B"), (3.0, "C")])
        result, cursor = _op_delete(lines, 1)
        assert len(result) == 2
        assert result[0].text == "A"
        assert result[1].text == "C"
        assert cursor == 1

    def test_delete_only_line(self):
        lines = _make([(1.0, "Only")])
        result, cursor = _op_delete(lines, 0)
        assert result == []
        assert cursor == 0

    def test_delete_out_of_bounds_is_noop(self):
        lines = _make([(1.0, "A"), (2.0, "B")])
        result, cursor = _op_delete(lines, 10)
        assert len(result) == 2
        assert cursor == 10

    def test_delete_negative_index_is_noop(self):
        lines = _make([(1.0, "A")])
        result, cursor = _op_delete(lines, -1)
        assert len(result) == 1
        assert cursor == -1


# ---------------------------------------------------------------------------
# _op_merge
# ---------------------------------------------------------------------------


class TestOpMerge:
    def test_merge_first_two(self):
        lines = _make([(1.0, "Hello"), (2.0, "World")])
        result, cursor = _op_merge(lines, 0)
        assert len(result) == 1
        assert result[0].text == "Hello world"  # second word lowercased
        assert result[0].timestamp == pytest.approx(1.0)
        assert cursor == 0

    def test_merge_uses_first_line_timestamp(self):
        lines = _make([(2.0, "A"), (8.0, "B"), (12.0, "C")])
        result, cursor = _op_merge(lines, 1)
        assert result[1].timestamp == pytest.approx(8.0)
        assert cursor == 1

    def test_merge_three_to_two(self):
        lines = _make([(1.0, "A"), (2.0, "B"), (3.0, "C")])
        result, _ = _op_merge(lines, 0)
        assert len(result) == 2
        assert result[1].text == "C"

    def test_merge_last_line_is_noop(self):
        lines = _make([(1.0, "A"), (2.0, "B")])
        result, cursor = _op_merge(lines, 1)
        assert len(result) == 2
        assert cursor == 1

    def test_merge_out_of_bounds_is_noop(self):
        lines = _make([(1.0, "A"), (2.0, "B")])
        result, cursor = _op_merge(lines, 5)
        assert len(result) == 2
        assert cursor == 5

    def test_merge_single_line_is_noop(self):
        lines = _make([(1.0, "Alone")])
        result, cursor = _op_merge(lines, 0)
        assert len(result) == 1
        assert cursor == 0

    def test_merge_preserves_acronym_capitalisation(self):
        lines = _make([(1.0, "Hello"), (2.0, "USA today")])
        result, _ = _op_merge(lines, 0)
        assert "USA" in result[0].text  # all-caps preserved

    def test_merge_preserves_pronoun_i(self):
        lines = _make([(1.0, "Hello"), (2.0, "I am here")])
        result, _ = _op_merge(lines, 0)
        assert " I " in result[0].text

    def test_merge_concatenates_words(self):
        """Merged line should carry words from both original lines in order."""
        w1 = _wt(" Hello", 1.0, 1.3)
        w2 = _wt(" world", 2.0, 2.4)
        lines = [
            LRCLine(1.0, "Hello", words=[w1]),
            LRCLine(2.0, "World", words=[w2]),
        ]
        result, _ = _op_merge(lines, 0)
        assert result[0].words == [w1, w2]

    def test_merge_words_empty_when_neither_has_words(self):
        lines = _make([(1.0, "Hello"), (2.0, "World")])
        result, _ = _op_merge(lines, 0)
        assert result[0].words == []

    def test_merge_partial_words_combined(self):
        """One line has words, the other doesn't — they still concatenate."""
        w1 = _wt(" Hello", 1.0, 1.3)
        lines = [
            LRCLine(1.0, "Hello", words=[w1]),
            LRCLine(2.0, "World", words=[]),
        ]
        result, _ = _op_merge(lines, 0)
        assert result[0].words == [w1]

    def test_merge_end_comes_from_second_line(self):
        """Merged line's end must be taken from the second (later) line."""
        lines = [LRCLine(1.0, "Hello", end=None), LRCLine(2.0, "World", end=3.5)]
        result, _ = _op_merge(lines, 0)
        assert result[0].end == pytest.approx(3.5)

    def test_merge_end_is_none_when_second_line_has_no_end(self):
        """If the second line has no end, merged line's end is also None."""
        lines = [LRCLine(1.0, "Hello", end=2.0), LRCLine(2.0, "World", end=None)]
        result, _ = _op_merge(lines, 0)
        assert result[0].end is None

    def test_merge_blank_first_line_keeps_second_unchanged(self):
        """Blank first line is deleted; second line's timestamp, end and words are untouched."""
        w = _wt(" World", 2.0, 2.5)
        lines = [LRCLine(1.0, "", end=None), LRCLine(2.0, "World", end=3.0, words=[w])]
        result, _ = _op_merge(lines, 0)
        assert len(result) == 1
        assert result[0].timestamp == pytest.approx(2.0)  # b's timestamp, not a's
        assert result[0].text == "World"
        assert result[0].end == pytest.approx(3.0)
        assert result[0].words == [w]

    def test_merge_blank_second_line_keeps_first_unchanged(self):
        """Blank second line is deleted; first line's timestamp, end and words are untouched."""
        w = _wt(" Hello", 1.0, 1.4)
        lines = [LRCLine(1.0, "Hello", end=2.0, words=[w]), LRCLine(3.0, "", end=4.0)]
        result, _ = _op_merge(lines, 0)
        assert len(result) == 1
        assert result[0].timestamp == pytest.approx(1.0)
        assert result[0].text == "Hello"
        assert result[0].end == pytest.approx(2.0)  # a's end, not extended to b's
        assert result[0].words == [w]

    def test_merge_both_blank_keeps_first_unchanged(self):
        """Two blank lines merge into the first one unchanged."""
        lines = [LRCLine(1.0, "", end=None), LRCLine(2.0, "", end=3.0)]
        result, _ = _op_merge(lines, 0)
        assert len(result) == 1
        assert result[0].timestamp == pytest.approx(1.0)
        assert result[0].end is None  # a's end preserved, not extended


# ---------------------------------------------------------------------------
# _op_insert_blank
# ---------------------------------------------------------------------------


class TestOpInsertBlank:
    def test_inserts_after_cursor(self):
        lines = _make([(1.0, "A"), (3.0, "B")])
        result, cursor = _op_insert_blank(lines, 0)
        assert len(result) == 3
        assert cursor == 1
        assert result[1].text == ""

    def test_timestamp_uses_current_end(self):
        lines = [LRCLine(1.0, "A", end=2.0), LRCLine(3.0, "B")]
        result, _ = _op_insert_blank(lines, 0)
        assert result[1].timestamp == pytest.approx(2.0)

    def test_timestamp_midpoint_when_no_end(self):
        lines = _make([(1.0, "A"), (3.0, "B")])
        result, _ = _op_insert_blank(lines, 0)
        assert result[1].timestamp == pytest.approx(2.0)

    def test_timestamp_plus_two_at_last_line(self):
        lines = _make([(1.0, "A")])
        result, _ = _op_insert_blank(lines, 0)
        assert result[1].timestamp == pytest.approx(3.0)

    def test_end_set_to_next_line_timestamp(self):
        lines = _make([(1.0, "A"), (3.0, "B")])
        result, _ = _op_insert_blank(lines, 0)
        assert result[1].end == pytest.approx(3.0)

    def test_end_none_when_last_line(self):
        lines = _make([(1.0, "A")])
        result, _ = _op_insert_blank(lines, 0)
        assert result[1].end is None

    def test_words_empty(self):
        lines = [LRCLine(1.0, "A", words=[_wt(" A", 1.0, 1.3)])]
        result, _ = _op_insert_blank(lines, 0)
        assert result[1].words == []

    def test_out_of_bounds_is_noop(self):
        lines = _make([(1.0, "A")])
        result, cursor = _op_insert_blank(lines, 5)
        assert len(result) == 1
        assert cursor == 5
