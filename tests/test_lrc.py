"""Tests for lrc.py — pure data, no I/O."""

import pytest

from lyrsmith.lrc import (
    LRCLine,
    active_line_index,
    is_lrc,
    parse,
    serialize,
)


# ---------------------------------------------------------------------------
# LRCLine
# ---------------------------------------------------------------------------


class TestLRCLine:
    def test_timestamp_str_basic(self):
        assert LRCLine(65.32, "").timestamp_str() == "[01:05.32]"

    def test_timestamp_str_zero(self):
        assert LRCLine(0.0, "").timestamp_str() == "[00:00.00]"

    def test_timestamp_str_under_minute(self):
        assert LRCLine(3.5, "").timestamp_str() == "[00:03.50]"

    def test_timestamp_str_over_hour(self):
        # 75 minutes = [75:00.00] — LRC has no hour field
        assert LRCLine(75 * 60.0, "").timestamp_str() == "[75:00.00]"

    def test_str_combines_timestamp_and_text(self):
        assert str(LRCLine(3.5, "Hello")) == "[00:03.50]Hello"

    def test_display_str_has_space(self):
        assert LRCLine(3.5, "Hello").display_str() == "[00:03.50] Hello"


# ---------------------------------------------------------------------------
# parse
# ---------------------------------------------------------------------------


class TestParse:
    def test_empty_string(self):
        meta, lines = parse("")
        assert lines == []
        assert meta == {}

    def test_basic_lines(self):
        meta, lines = parse("[00:01.00]First\n[00:02.50]Second")
        assert len(lines) == 2
        assert lines[0].timestamp == pytest.approx(1.0)
        assert lines[0].text == "First"
        assert lines[1].timestamp == pytest.approx(2.5)
        assert lines[1].text == "Second"

    def test_metadata_tags(self):
        meta, lines = parse("[ar:The Artist]\n[ti:The Title]\n[00:01.00]Line")
        assert meta["ar"] == "The Artist"
        assert meta["ti"] == "The Title"
        assert len(lines) == 1

    def test_sorts_by_timestamp(self):
        text = "[00:03.00]Third\n[00:01.00]First\n[00:02.00]Second"
        _, lines = parse(text)
        assert [l.text for l in lines] == ["First", "Second", "Third"]

    def test_millisecond_format(self):
        # 3-digit centiseconds/milliseconds
        _, lines = parse("[00:01.500]Line")
        assert lines[0].timestamp == pytest.approx(1.5)

    def test_centisecond_format(self):
        _, lines = parse("[00:01.50]Line")
        assert lines[0].timestamp == pytest.approx(1.5)

    def test_blank_lines_ignored(self):
        _, lines = parse("[00:01.00]A\n\n[00:02.00]B\n")
        assert len(lines) == 2

    def test_multiple_timestamps_same_line(self):
        _, lines = parse("[00:01.00][00:02.00]Shared text")
        assert len(lines) == 2
        assert all(l.text == "Shared text" for l in lines)

    def test_whitespace_stripped_from_text(self):
        _, lines = parse("[00:01.00]  Hello World  ")
        assert lines[0].text == "Hello World"


# ---------------------------------------------------------------------------
# serialize
# ---------------------------------------------------------------------------


class TestSerialize:
    def test_roundtrip(self):
        original = "[00:01.00]Hello\n[00:02.50]World"
        meta, lines = parse(original)
        result = serialize(meta, lines)
        _, lines2 = parse(result)
        assert len(lines2) == len(lines)
        for a, b in zip(lines, lines2):
            assert a.timestamp == pytest.approx(b.timestamp, abs=0.01)
            assert a.text == b.text

    def test_meta_appears_before_lines(self):
        meta = {"ar": "Artist"}
        lines = [LRCLine(1.0, "Hello")]
        result = serialize(meta, lines)
        meta_pos = result.index("[ar:Artist]")
        line_pos = result.index("[00:01.00]")
        assert meta_pos < line_pos

    def test_sorts_lines_by_timestamp(self):
        lines = [LRCLine(3.0, "C"), LRCLine(1.0, "A"), LRCLine(2.0, "B")]
        result = serialize({}, lines)
        positions = [result.index(t) for t in ["A", "B", "C"]]
        assert positions == sorted(positions)

    def test_empty_lines(self):
        result = serialize({}, [])
        assert result == ""


# ---------------------------------------------------------------------------
# is_lrc
# ---------------------------------------------------------------------------


class TestIsLrc:
    def test_true_for_lrc_content(self):
        assert is_lrc("[00:01.00]Hello") is True

    def test_false_for_plain_text(self):
        assert is_lrc("Just some plain lyrics\nNo timestamps here") is False

    def test_false_for_empty(self):
        assert is_lrc("") is False

    def test_false_for_metadata_only(self):
        assert is_lrc("[ar:Artist]\n[ti:Title]") is False


# ---------------------------------------------------------------------------
# active_line_index
# ---------------------------------------------------------------------------


class TestActiveLineIndex:
    def _lines(self):
        return [LRCLine(1.0, "A"), LRCLine(3.0, "B"), LRCLine(5.0, "C")]

    def test_before_first_line(self):
        assert active_line_index(self._lines(), 0.5) == -1

    def test_at_first_line(self):
        assert active_line_index(self._lines(), 1.0) == 0

    def test_between_lines(self):
        assert active_line_index(self._lines(), 2.0) == 0
        assert active_line_index(self._lines(), 4.0) == 1

    def test_at_last_line(self):
        assert active_line_index(self._lines(), 5.0) == 2

    def test_after_last_line(self):
        assert active_line_index(self._lines(), 99.0) == 2

    def test_empty_list(self):
        assert active_line_index([], 5.0) == -1

    def test_unsorted_input_returns_correct_result(self):
        # After a nudge or stamp, _lines may be temporarily out of order.
        # active_line_index must still find the correct active line — it
        # must NOT use an early-exit that assumes sorted order.
        lines = [
            LRCLine(3.0, "B"),  # out of order
            LRCLine(1.0, "A"),
            LRCLine(5.0, "C"),
        ]
        # Position 2.0: the last line with timestamp <= 2.0 is "A" at index 1
        assert active_line_index(lines, 2.0) == 1

    def test_unsorted_input_last_eligible(self):
        # Even when the list is shuffled, the LAST eligible line is returned.
        lines = [LRCLine(5.0, "C"), LRCLine(1.0, "A"), LRCLine(3.0, "B")]
        # All three are <= 6.0; the last one in list order with ts <= 6 is B at idx 2
        assert active_line_index(lines, 6.0) == 2

    def test_unsorted_none_eligible(self):
        lines = [LRCLine(5.0, "C"), LRCLine(3.0, "B")]
        assert active_line_index(lines, 2.0) == -1
