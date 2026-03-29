"""Tests for lrc.py — pure data, no I/O."""

import pytest

from lyrsmith.lrc import (
    LineEnrichment,
    LRCLine,
    WordTiming,
    active_line_index,
    attach_word_data,
    is_lrc,
    parse,
    serialize,
    word_ts_for_split,
)

# ---------------------------------------------------------------------------
# WordTiming
# ---------------------------------------------------------------------------


class TestWordTiming:
    def test_basic_fields(self):
        w = WordTiming(word=" hello", start=1.2, end=1.8)
        assert w.word == " hello"
        assert w.start == pytest.approx(1.2)
        assert w.end == pytest.approx(1.8)

    def test_word_may_include_leading_space(self):
        # faster-whisper often returns " word" with a leading space
        w = WordTiming(word=" world", start=2.0, end=2.4)
        assert w.word.strip() == "world"


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

    def test_words_defaults_to_empty_list(self):
        line = LRCLine(1.0, "Hello")
        assert line.words == []

    def test_words_not_shared_between_instances(self):
        # Mutable default via field(default_factory=list) — each instance gets
        # its own list, not the same object.
        a = LRCLine(1.0, "A")
        b = LRCLine(2.0, "B")
        a.words.append(WordTiming(" hi", 1.0, 1.3))
        assert b.words == []

    def test_words_round_trip_not_persisted(self):
        # Words are in-memory only; serialization must not include them.
        words = [WordTiming(" Hello", 1.0, 1.3), WordTiming(" world", 1.4, 1.8)]
        line = LRCLine(1.0, "Hello world", words=words)
        assert str(line) == "[00:01.00]Hello world"  # no word data in output


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


# ---------------------------------------------------------------------------
# word_ts_for_split
# ---------------------------------------------------------------------------


def _words(*specs: tuple[str, float, float]) -> list[WordTiming]:
    return [WordTiming(word=w, start=s, end=e) for w, s, e in specs]


class TestWordTsForSplit:
    def test_empty_words_returns_none(self):
        ts, idx = word_ts_for_split([], "World")
        assert ts is None
        assert idx == 0

    def test_empty_second_half_returns_none(self):
        words = _words((" Hello", 1.0, 1.3), (" world", 1.4, 1.8))
        ts, idx = word_ts_for_split(words, "")
        assert ts is None
        assert idx == 0

    def test_blank_second_half_returns_none(self):
        words = _words((" Hello", 1.0, 1.3))
        ts, idx = word_ts_for_split(words, "   ")
        assert ts is None
        assert idx == 0

    def test_match_first_word(self):
        words = _words((" Hello", 1.0, 1.3), (" world", 1.4, 1.8))
        ts, idx = word_ts_for_split(words, "Hello world")
        assert ts == pytest.approx(1.0)
        assert idx == 0

    def test_match_second_word(self):
        words = _words((" Hello", 1.0, 1.3), (" world", 1.4, 1.8))
        ts, idx = word_ts_for_split(words, "World")
        assert ts == pytest.approx(1.4)
        assert idx == 1

    def test_match_middle_word(self):
        words = _words((" one", 0.5, 0.8), (" two", 1.0, 1.3), (" three", 1.5, 1.9))
        ts, idx = word_ts_for_split(words, "Two three")
        assert ts == pytest.approx(1.0)
        assert idx == 1

    def test_no_match_returns_none(self):
        words = _words((" Hello", 1.0, 1.3), (" world", 1.4, 1.8))
        ts, idx = word_ts_for_split(words, "Goodbye")
        assert ts is None
        assert idx == 0

    def test_leading_space_in_word_stripped(self):
        # faster-whisper words typically have " word" with a leading space
        words = _words((" World", 2.0, 2.5))
        ts, idx = word_ts_for_split(words, "World")
        assert ts == pytest.approx(2.0)
        assert idx == 0

    def test_case_insensitive_match(self):
        words = _words((" HELLO", 0.5, 0.9))
        ts, idx = word_ts_for_split(words, "hello")
        assert ts == pytest.approx(0.5)
        assert idx == 0

    def test_punctuation_stripped_from_word(self):
        # Whisper sometimes includes punctuation: "world,"
        words = _words(("world,", 1.4, 1.8))
        ts, idx = word_ts_for_split(words, "World")
        assert ts == pytest.approx(1.4)
        assert idx == 0

    def test_punctuation_stripped_from_second_half(self):
        words = _words((" world", 1.4, 1.8))
        ts, idx = word_ts_for_split(words, "World!")
        assert ts == pytest.approx(1.4)
        assert idx == 0

    def test_first_match_wins(self):
        # Both "world" entries share the same text; the first one is returned.
        words = _words((" world", 1.0, 1.3), (" world", 2.0, 2.3))
        ts, idx = word_ts_for_split(words, "world")
        assert ts == pytest.approx(1.0)
        assert idx == 0

    def test_all_punctuation_first_token_returns_none(self):
        # If every character in the first token is non-word, target becomes ""
        # and the function must fall back to (None, 0) rather than crash.
        words = _words((" Hello", 1.0, 1.3))
        ts, idx = word_ts_for_split(words, "!!! ???")
        assert ts is None
        assert idx == 0


# ---------------------------------------------------------------------------
# attach_word_data
# ---------------------------------------------------------------------------


class TestAttachWordData:
    def _make_words(self, *specs):
        return [WordTiming(word=w, start=s, end=e) for w, s, e in specs]

    def _enrich(self, end=None, words=None):
        return LineEnrichment(end=end, words=words or [])

    def test_attaches_words_to_matching_line(self):
        line = LRCLine(1.0, "Hello world")
        words = self._make_words((" Hello", 1.0, 1.3), (" world", 1.4, 1.8))
        attach_word_data([line], {"1.000": self._enrich(words=words)})
        assert line.words == words

    def test_attaches_end_to_matching_line(self):
        line = LRCLine(1.0, "Hello world")
        attach_word_data([line], {"1.000": self._enrich(end=2.5)})
        assert line.end == pytest.approx(2.5)

    def test_attaches_both_end_and_words(self):
        line = LRCLine(1.0, "Hello world")
        words = self._make_words((" Hello", 1.0, 1.3))
        attach_word_data([line], {"1.000": self._enrich(end=2.0, words=words)})
        assert line.end == pytest.approx(2.0)
        assert line.words == words

    def test_no_match_leaves_line_unchanged(self):
        line = LRCLine(1.0, "Hello")
        attach_word_data([line], {"2.000": self._enrich(end=3.0)})
        assert line.words == []
        assert line.end is None

    def test_none_end_in_enrichment_does_not_overwrite_line_end(self):
        # If the enrichment has end=None, the line's existing end is preserved.
        line = LRCLine(1.0, "Hello", end=5.0)
        attach_word_data([line], {"1.000": self._enrich(end=None)})
        assert line.end == pytest.approx(5.0)

    def test_partial_match_only_updates_matched_lines(self):
        line_a = LRCLine(1.0, "First")
        line_b = LRCLine(3.0, "Second")
        words_a = self._make_words((" First", 1.0, 1.4))
        attach_word_data([line_a, line_b], {"1.000": self._enrich(end=2.0, words=words_a)})
        assert line_a.words == words_a
        assert line_a.end == pytest.approx(2.0)
        assert line_b.words == []
        assert line_b.end is None

    def test_empty_enrichment_is_noop(self):
        line = LRCLine(1.0, "Hello")
        attach_word_data([line], {})
        assert line.words == []
        assert line.end is None

    def test_empty_lines_is_noop(self):
        attach_word_data([], {"1.000": self._enrich(end=2.0)})  # must not raise

    def test_key_format_is_three_decimal_places(self):
        line = LRCLine(1.5, "Mid")
        words = self._make_words((" Mid", 1.5, 1.8))
        attach_word_data([line], {"1.500": self._enrich(end=2.0, words=words)})
        assert line.words == words
        assert line.end == pytest.approx(2.0)

    def test_multiple_lines_all_matched(self):
        lines = [LRCLine(1.0, "A"), LRCLine(2.0, "B"), LRCLine(3.0, "C")]
        wa = self._make_words((" A", 1.0, 1.2))
        wb = self._make_words((" B", 2.0, 2.2))
        wc = self._make_words((" C", 3.0, 3.2))
        enrichment = {
            "1.000": self._enrich(end=1.9, words=wa),
            "2.000": self._enrich(end=2.9, words=wb),
            "3.000": self._enrich(end=3.9, words=wc),
        }
        attach_word_data(lines, enrichment)
        assert lines[0].words == wa
        assert lines[0].end == pytest.approx(1.9)
        assert lines[1].words == wb
        assert lines[2].words == wc
