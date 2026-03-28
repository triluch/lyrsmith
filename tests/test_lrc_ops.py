"""Tests for pure LRC editing ops in lyrics_editor.py, plus undo via Pilot."""

from __future__ import annotations

import asyncio

import pytest

from lyrsmith.lrc import LRCLine
from lyrsmith.ui.lyrics_editor import (
    LyricsEditor,
    _op_delete,
    _op_merge,
    _op_nudge,
)


def _make(specs: list[tuple[float, str]]) -> list[LRCLine]:
    return [LRCLine(ts, text) for ts, text in specs]


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


# ---------------------------------------------------------------------------
# Undo sequence — requires a mounted widget; use Textual Pilot via asyncio.run
# ---------------------------------------------------------------------------


from textual.app import App, ComposeResult  # noqa: E402  (after heavy imports)


class _EditorApp(App):
    def compose(self) -> ComposeResult:
        yield LyricsEditor()


def _run(coro):
    return asyncio.run(coro)


class TestUndo:
    def test_undo_restores_after_delete(self):
        async def _impl():
            async with _EditorApp().run_test(headless=True) as pilot:
                ed = pilot.app.query_one(LyricsEditor)
                ed.load_lrc("[00:01.00]First\n[00:02.00]Second\n[00:03.00]Third")
                assert len(ed._lines) == 3
                # _delete calls _save_undo internally — no manual snapshot needed
                ed._delete(0)
                assert len(ed._lines) == 2
                assert ed._lines[0].text == "Second"
                ed._apply_undo()
                assert len(ed._lines) == 3
                assert ed._lines[0].text == "First"

        _run(_impl())

    def test_undo_restores_after_merge(self):
        async def _impl():
            async with _EditorApp().run_test(headless=True) as pilot:
                ed = pilot.app.query_one(LyricsEditor)
                ed.load_lrc("[00:01.00]Hello\n[00:02.00]World")
                # _merge calls _save_undo internally — no manual snapshot needed
                ed._merge(0)
                assert len(ed._lines) == 1
                ed._apply_undo()
                assert len(ed._lines) == 2
                assert ed._lines[0].text == "Hello"
                assert ed._lines[1].text == "World"

        _run(_impl())

    def test_undo_restores_after_nudge(self):
        async def _impl():
            async with _EditorApp().run_test(headless=True) as pilot:
                ed = pilot.app.query_one(LyricsEditor)
                ed.load_lrc("[00:01.00]A\n[00:03.00]B")
                # Wait for Textual to mount ListView children before _nudge
                # calls _refresh_active_style → item.query_one(Label).
                await pilot.pause()
                ed._save_undo()
                ed._nudge(0, 0.5)
                assert ed._lines[0].timestamp == pytest.approx(1.5)
                ed._apply_undo()
                assert ed._lines[0].timestamp == pytest.approx(1.0)

        _run(_impl())

    def test_undo_noop_when_no_snapshot(self):
        async def _impl():
            async with _EditorApp().run_test(headless=True) as pilot:
                ed = pilot.app.query_one(LyricsEditor)
                ed.load_lrc("[00:01.00]Only")
                assert ed._undo_lines is None
                ed._apply_undo()  # must not crash
                assert len(ed._lines) == 1

        _run(_impl())

    def test_undo_snapshot_consumed_once(self):
        """Applying undo twice should not restore to original on the second call."""

        async def _impl():
            async with _EditorApp().run_test(headless=True) as pilot:
                ed = pilot.app.query_one(LyricsEditor)
                ed.load_lrc("[00:01.00]X\n[00:02.00]Y")
                ed._save_undo()
                ed._delete(0)
                ed._apply_undo()  # restores to 2 lines
                ed._apply_undo()  # second call: snapshot is None, should be a no-op
                assert len(ed._lines) == 2  # still restored; nothing happened

        _run(_impl())
