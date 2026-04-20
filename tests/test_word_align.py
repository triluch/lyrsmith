"""Unit tests for lyrsmith.word_align.reconcile_word_timings.

Each class covers one transformation type.  All tests use invented words
so no real lyrics are included.
"""

from __future__ import annotations

import pytest

from lyrsmith.lrc import WordTiming
from lyrsmith.word_align import reconcile_word_timings

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def wt(word: str, start: float, end: float) -> WordTiming:
    return WordTiming(word=word, start=start, end=end)


def _monotonic(words: list[WordTiming]) -> bool:
    """Return True if timing is non-decreasing and each word start ≤ end."""
    for i, w in enumerate(words):
        if w.start > w.end + 1e-6:
            return False
        if i > 0 and words[i - 1].end > w.start + 1e-6:
            return False
    return True


# ---------------------------------------------------------------------------
# Edge cases / empty inputs
# ---------------------------------------------------------------------------


class TestReconcileEdgeCases:
    def test_empty_old_words_returns_empty(self):
        result = reconcile_word_timings([], "hello world")
        assert result == []

    def test_empty_new_text_returns_empty(self):
        result = reconcile_word_timings([wt(" hello", 0.0, 1.0)], "")
        assert result == []

    def test_both_empty_returns_empty(self):
        result = reconcile_word_timings([], "")
        assert result == []

    def test_single_word_unchanged(self):
        result = reconcile_word_timings([wt(" test", 0.0, 1.0)], "test")
        assert len(result) == 1
        assert result[0].start == pytest.approx(0.0)
        assert result[0].end == pytest.approx(1.0)

    def test_output_word_count_matches_new_text_tokens(self):
        old = [wt(" a", 0.0, 0.5), wt(" b", 0.5, 1.0), wt(" c", 1.0, 1.5)]
        result = reconcile_word_timings(old, "x y z w")
        assert len(result) == 4


# ---------------------------------------------------------------------------
# Equal / unchanged words — timing copied verbatim
# ---------------------------------------------------------------------------


class TestReconcileEqual:
    def test_all_words_identical(self):
        old = [wt(" foo", 0.0, 0.5), wt(" bar", 0.5, 1.0)]
        result = reconcile_word_timings(old, "foo bar")
        assert result[0].start == pytest.approx(0.0)
        assert result[0].end == pytest.approx(0.5)
        assert result[1].start == pytest.approx(0.5)
        assert result[1].end == pytest.approx(1.0)

    def test_case_change_preserves_timing(self):
        """A word that only changes case should keep its original timing."""
        old = [wt(" HELLO", 0.0, 0.4), wt(" WORLD", 0.4, 1.0)]
        result = reconcile_word_timings(old, "hello world")
        assert result[0].start == pytest.approx(0.0)
        assert result[0].end == pytest.approx(0.4)
        assert result[1].start == pytest.approx(0.4)
        assert result[1].end == pytest.approx(1.0)

    def test_equal_anchors_preserved_around_change(self):
        """Words before and after an edit keep their timings unchanged."""
        old = [
            wt(" anchor", 0.0, 0.3),
            wt(" middle", 0.3, 0.7),
            wt(" end", 0.7, 1.0),
        ]
        result = reconcile_word_timings(old, "anchor changed end")
        assert result[0].start == pytest.approx(0.0)
        assert result[0].end == pytest.approx(0.3)
        assert result[2].start == pytest.approx(0.7)
        assert result[2].end == pytest.approx(1.0)

    def test_word_text_updated_timing_kept(self):
        """Same count, minor text change — new word text used, timing kept."""
        old = [wt(" graet", 0.0, 0.5), wt(" stuff", 0.5, 1.0)]
        result = reconcile_word_timings(old, "great stuff")
        assert "great" in result[0].word
        assert result[0].start == pytest.approx(0.0, abs=0.1)
        assert result[1].end == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Join — multiple old words merge into fewer new words
# ---------------------------------------------------------------------------


class TestReconcileJoin:
    def test_two_words_join_to_one_uses_outer_times(self):
        """start of first old word, end of last old word."""
        old = [wt(" black", 0.0, 0.4), wt(" board", 0.4, 1.0)]
        result = reconcile_word_timings(old, "blackboard")
        assert len(result) == 1
        assert result[0].start == pytest.approx(0.0)
        assert result[0].end == pytest.approx(1.0)

    def test_three_words_join_to_one(self):
        old = [wt(" a", 0.0, 0.3), wt(" b", 0.3, 0.6), wt(" c", 0.6, 1.0)]
        result = reconcile_word_timings(old, "abc")
        assert len(result) == 1
        assert result[0].start == pytest.approx(0.0)
        assert result[0].end == pytest.approx(1.0)

    def test_join_in_middle_anchors_intact(self):
        """Two words merge; surrounding equal words keep original timing."""
        old = [
            wt(" first", 0.0, 0.2),
            wt(" mid", 0.2, 0.5),
            wt(" point", 0.5, 0.8),
            wt(" last", 0.8, 1.0),
        ]
        result = reconcile_word_timings(old, "first midpoint last")
        assert len(result) == 3
        assert result[0].start == pytest.approx(0.0)
        assert result[0].end == pytest.approx(0.2)
        assert result[1].start == pytest.approx(0.2)
        assert result[1].end == pytest.approx(0.8)
        assert result[2].start == pytest.approx(0.8)
        assert result[2].end == pytest.approx(1.0)

    def test_join_preserves_word_text(self):
        old = [wt(" sun", 0.0, 0.5), wt(" shine", 0.5, 1.0)]
        result = reconcile_word_timings(old, "sunshine")
        assert "sunshine" in result[0].word


# ---------------------------------------------------------------------------
# Split — one old word becomes multiple new words
# ---------------------------------------------------------------------------


class TestReconcileSplit:
    def test_split_boundary_times_correct(self):
        """Start of first result == old.start; end of last == old.end."""
        old = [wt(" notebook", 0.0, 1.0)]
        result = reconcile_word_timings(old, "note book")
        assert len(result) == 2
        assert result[0].start == pytest.approx(0.0, abs=0.01)
        assert result[-1].end == pytest.approx(1.0, abs=0.01)

    def test_split_contiguous(self):
        """result[i].end == result[i+1].start (no gaps or overlaps)."""
        old = [wt(" something", 0.0, 1.0)]
        result = reconcile_word_timings(old, "some thing")
        assert len(result) == 2
        assert result[0].end == pytest.approx(result[1].start, abs=0.01)

    def test_split_into_three_contiguous(self):
        old = [wt(" abcdefgh", 0.0, 1.0)]
        result = reconcile_word_timings(old, "ab cd efgh")
        assert len(result) == 3
        assert result[0].start == pytest.approx(0.0, abs=0.01)
        assert result[-1].end == pytest.approx(1.0, abs=0.01)
        for i in range(len(result) - 1):
            assert result[i].end == pytest.approx(result[i + 1].start, abs=0.01)

    def test_split_proportional_longer_part_gets_more_time(self):
        """The longer (more syllables) part should receive more time."""
        old = [wt(" extraordinary", 0.0, 1.0)]
        result = reconcile_word_timings(old, "extra ordinary", lang="en")
        # "extra" = 2 syllables, "ordinary" = 4 syllables
        # ordinary should get at least twice as much time as extra
        assert len(result) == 2
        assert result[1].end - result[1].start > result[0].end - result[0].start


# ---------------------------------------------------------------------------
# Delete — words removed from the line
# ---------------------------------------------------------------------------


class TestReconcileDelete:
    def test_last_word_deleted(self):
        old = [wt(" one", 0.0, 0.3), wt(" two", 0.3, 0.7), wt(" three", 0.7, 1.0)]
        result = reconcile_word_timings(old, "one two")
        assert len(result) == 2
        assert result[0].start == pytest.approx(0.0)
        assert result[1].end == pytest.approx(0.7)

    def test_middle_word_deleted(self):
        """Deleting a middle word: surrounding words keep exact timings."""
        old = [wt(" alpha", 0.0, 0.3), wt(" beta", 0.3, 0.7), wt(" gamma", 0.7, 1.0)]
        result = reconcile_word_timings(old, "alpha gamma")
        assert len(result) == 2
        assert result[0].start == pytest.approx(0.0)
        assert result[0].end == pytest.approx(0.3)
        assert result[1].start == pytest.approx(0.7)
        assert result[1].end == pytest.approx(1.0)

    def test_first_word_deleted(self):
        old = [wt(" drop", 0.0, 0.4), wt(" keep", 0.4, 1.0)]
        result = reconcile_word_timings(old, "keep")
        assert len(result) == 1
        assert result[0].start == pytest.approx(0.4)
        assert result[0].end == pytest.approx(1.0)

    def test_multiple_words_deleted_at_end(self):
        old = [wt(" a", 0.0, 0.2), wt(" b", 0.2, 0.5), wt(" c", 0.5, 0.8), wt(" d", 0.8, 1.0)]
        result = reconcile_word_timings(old, "a b")
        assert len(result) == 2
        assert result[0].start == pytest.approx(0.0)
        assert result[1].end == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# Insert — new words appear with no corresponding old timing
# ---------------------------------------------------------------------------


class TestReconcileInsert:
    def test_inserted_word_is_in_result(self):
        """An inserted word with no old match still appears in the output."""
        old = [wt(" start", 0.0, 0.5), wt(" end", 1.0, 1.5)]
        result = reconcile_word_timings(old, "start middle end")
        assert len(result) == 3
        assert "middle" in result[1].word

    def test_inserted_word_timing_between_neighbors(self):
        """Inserted word timing is interpolated between adjacent anchors."""
        old = [wt(" first", 0.0, 0.4), wt(" last", 0.8, 1.2)]
        result = reconcile_word_timings(old, "first added last")
        assert len(result) == 3
        # "added" must fit between first.end and last.start
        assert result[1].start >= result[0].end - 0.01
        assert result[1].end <= result[2].start + 0.01

    def test_inserted_words_anchor_times_unchanged(self):
        """Equal anchors on both sides keep exact timings even with insertion."""
        old = [wt(" open", 0.0, 0.3), wt(" close", 0.9, 1.2)]
        result = reconcile_word_timings(old, "open x y z close")
        assert result[0].start == pytest.approx(0.0)
        assert result[0].end == pytest.approx(0.3)
        assert result[-1].start == pytest.approx(0.9)
        assert result[-1].end == pytest.approx(1.2)

    def test_leading_insert_respects_line_start(self):
        """A new first word must not be backfilled before the line timestamp."""
        old = [wt(" world", 205.82, 207.22)]
        result = reconcile_word_timings(old, "Oh world", line_start=205.82)
        assert len(result) == 2
        assert result[0].start >= 205.82 - 1e-6
        assert result[0].end >= result[0].start
        assert result[1].start == pytest.approx(205.82)
        assert result[1].end == pytest.approx(207.22)


# ---------------------------------------------------------------------------
# N:M alignment — multiple old words → multiple new words (not 1:1)
# ---------------------------------------------------------------------------


class TestReconcileNM:
    def test_two_words_split_into_four_by_chars(self):
        """Two old words perfectly split into four new words by character position."""
        # old: " abcde" [0, 0.5], " fghij" [0.5, 1.0]
        # new: "ab", "cde", "fgh", "ij"
        # old normalized concat: "abcdefghij" (10 chars)
        # "ab" → chars 0-1 (within "abcde"), "cde" → chars 2-4 (within "abcde")
        # "fgh" → chars 5-7 (within "fghij"), "ij" → chars 8-9 (within "fghij")
        old = [wt(" abcde", 0.0, 0.5), wt(" fghij", 0.5, 1.0)]
        result = reconcile_word_timings(old, "ab cde fgh ij")
        assert len(result) == 4
        # First two results must come from the first old word's time range
        assert result[0].start == pytest.approx(0.0, abs=0.05)
        assert result[1].end == pytest.approx(0.5, abs=0.05)
        # Last two from the second old word's time range
        assert result[2].start == pytest.approx(0.5, abs=0.05)
        assert result[3].end == pytest.approx(1.0, abs=0.05)
        assert _monotonic(result)

    def test_concatenation_match_uses_character_positions(self):
        """When old and new concatenate to the same string, timings are
        assigned by character position within the original word boundaries."""
        # "xyz" [0, 0.3] + "abc" [0.3, 0.6] → "xy", "za", "bc"
        # concat: "xyzabc" (6 chars) → "xy"=0-1, "za"=2-3, "bc"=4-5
        old = [wt(" xyz", 0.0, 0.3), wt(" abc", 0.3, 0.6)]
        result = reconcile_word_timings(old, "xy za bc")
        assert len(result) == 3
        # "xy" is fully within " xyz" range
        assert result[0].start == pytest.approx(0.0, abs=0.05)
        # "bc" is fully within " abc" range
        assert result[2].end == pytest.approx(0.6, abs=0.05)
        assert _monotonic(result)

    def test_nm_result_spans_full_time_range(self):
        """First result starts at first old word start; last ends at last old end."""
        old = [wt(" pq", 0.0, 0.4), wt(" rs", 0.4, 0.7), wt(" tuv", 0.7, 1.0)]
        result = reconcile_word_timings(old, "p qr st uv")
        assert len(result) == 4
        assert result[0].start == pytest.approx(0.0, abs=0.05)
        assert result[-1].end == pytest.approx(1.0, abs=0.05)
        assert _monotonic(result)


# ---------------------------------------------------------------------------
# Invariants — hold for any non-trivial input
# ---------------------------------------------------------------------------


class TestReconcileInvariants:
    @pytest.mark.parametrize(
        "old,new_text",
        [
            # join
            ([wt(" ab", 0.0, 0.5), wt(" cd", 0.5, 1.0)], "abcd"),
            # split
            ([wt(" hello", 0.0, 1.0)], "hel lo"),
            # delete
            ([wt(" x", 0.0, 0.3), wt(" y", 0.3, 0.7), wt(" z", 0.7, 1.0)], "x z"),
            # insert
            ([wt(" first", 0.0, 0.5), wt(" last", 0.8, 1.0)], "first new last"),
            # N:M
            ([wt(" abc", 0.0, 0.5), wt(" def", 0.5, 1.0)], "ab cd ef"),
        ],
    )
    def test_timing_is_monotonic(self, old, new_text):
        result = reconcile_word_timings(old, new_text)
        assert _monotonic(result), f"Non-monotonic timing: {result}"

    @pytest.mark.parametrize(
        "old,new_text",
        [
            ([wt(" a", 0.0, 0.5), wt(" b", 0.5, 1.0)], "ab"),
            ([wt(" ab", 0.0, 1.0)], "a b"),
            ([wt(" p", 0.0, 0.4), wt(" q", 0.4, 0.8), wt(" r", 0.8, 1.2)], "pq r"),
        ],
    )
    def test_result_words_cover_original_time_span(self, old, new_text):
        """The output must span from first old start to last old end."""
        result = reconcile_word_timings(old, new_text)
        if result:
            assert result[0].start == pytest.approx(old[0].start, abs=0.05)
            assert result[-1].end == pytest.approx(old[-1].end, abs=0.05)

    def test_space_prefix_applied_to_new_words(self):
        """New WordTiming entries should carry a space prefix when old ones do."""
        old = [wt(" foo", 0.0, 0.5), wt(" bar", 0.5, 1.0)]
        result = reconcile_word_timings(old, "foo baz bar")
        for w in result:
            assert w.word.startswith(" "), f"Missing space prefix: {w.word!r}"
