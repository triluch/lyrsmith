"""LRC editor interactions: stamp, nudge, delete, merge, edit modal, undo, blank lines."""

from __future__ import annotations

import asyncio

import pytest

from lyrsmith.lrc import WordTiming
from lyrsmith.ui.edit_line_modal import EditLineModal
from lyrsmith.ui.lyrics_editor import LyricsEditor

from ._helpers import _SAMPLE_LRC


class TestLrcEditorInteractions:
    """Key-driven LRC editing: stamp, nudge, delete, merge, edit modal."""

    async def _setup(self, pilot):
        """Load _SAMPLE_LRC and focus the lrc-list. Returns the editor."""
        ed = pilot.app.query_one(LyricsEditor)
        ed.load_lrc(_SAMPLE_LRC)
        await pilot.pause()
        pilot.app.query_one("#lrc-list").focus()
        await pilot.pause()
        return ed

    def test_stamp_updates_timestamp_to_playback_position(self, make_app):
        _factory, _ = make_app

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                ed = await self._setup(pilot)
                original_ts = ed._lines[ed._cursor_idx].timestamp
                ed._current_position = 4.5
                await pilot.press("t")
                await pilot.pause()
                assert ed._lines[ed._cursor_idx].timestamp == pytest.approx(4.5)
                assert ed._lines[ed._cursor_idx].timestamp != pytest.approx(original_ts)
                assert ed.is_dirty
                ed.clear_dirty()
                await pilot.press("ctrl+q")

        asyncio.run(_impl())

    def test_nudge_fine_forward_shifts_timestamp(self, make_app):
        _factory, _ = make_app

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                ed = await self._setup(pilot)
                original_ts = ed._lines[ed._cursor_idx].timestamp
                await pilot.press("period")  # +0.01 s
                await pilot.pause()
                assert ed._lines[ed._cursor_idx].timestamp == pytest.approx(
                    original_ts + 0.010, abs=1e-4
                )
                assert ed.is_dirty

        asyncio.run(_impl())

    def test_nudge_med_backward_shifts_timestamp(self, make_app):
        _factory, _ = make_app

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                ed = await self._setup(pilot)
                await pilot.press("down")
                await pilot.pause()
                await pilot.press("down")
                await pilot.pause()
                original_ts = ed._lines[1].timestamp
                await pilot.press("semicolon")  # -0.1 s
                await pilot.pause()
                assert ed._lines[ed._cursor_idx].timestamp == pytest.approx(
                    original_ts - 0.100, abs=1e-4
                )

        asyncio.run(_impl())

    def test_nudge_cursor_follows_line_after_reorder(self, make_app):
        """Cursor and ListView highlight follow the nudged line when it changes position."""
        # _SAMPLE_LRC: lines at 1, 3, 5, 7, 9 s.  Nudge line-0 (+1s × 3) to
        # 4 s → it should sort to index 1 (after 3 s, before 5 s).
        _factory, _ = make_app

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                ed = await self._setup(pilot)
                assert ed._cursor_idx == 0
                line_identity = ed._lines[0]

                await pilot.press("right_square_bracket")  # +1 s → 2 s
                await pilot.press("right_square_bracket")  # +1 s → 3.01 s (past 3 s)
                await pilot.press("right_square_bracket")  # +1 s → 4.01 s
                await pilot.pause()
                await pilot.pause()  # second pause lets call_after_refresh fire

                # The nudged line is now at a higher index
                assert ed._lines[ed._cursor_idx] is line_identity
                self._assert_highlight_on(pilot, ed)

        asyncio.run(_impl())

    def test_stamp_cursor_follows_line_after_reorder(self, make_app):
        """Cursor and ListView highlight follow the stamped line when it changes position."""
        # Stamp line-0 (1 s) to 4.5 s → it should sort to index 1 (after 3 s, before 5 s).
        _factory, _ = make_app

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                ed = await self._setup(pilot)
                assert ed._cursor_idx == 0
                line_identity = ed._lines[0]

                ed._current_position = 4.5
                await pilot.press("t")
                await pilot.pause()
                await pilot.pause()

                assert ed._lines[ed._cursor_idx] is line_identity
                assert ed._lines[ed._cursor_idx].timestamp == pytest.approx(4.5)
                self._assert_highlight_on(pilot, ed)

        asyncio.run(_impl())

    def test_delete_removes_line_and_marks_dirty(self, make_app):
        _factory, _ = make_app

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                ed = await self._setup(pilot)
                assert len(ed._lines) == 5
                assert not ed.is_dirty
                await pilot.press("ctrl+d")
                await pilot.pause()
                assert len(ed._lines) == 4
                assert ed.is_dirty

        asyncio.run(_impl())

    def test_merge_joins_adjacent_lines(self, make_app):
        _factory, _ = make_app

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                ed = await self._setup(pilot)
                assert len(ed._lines) == 5
                await pilot.press("m")
                await pilot.pause()
                assert len(ed._lines) == 4
                assert ed._lines[0].text == "First line second line"
                assert ed.is_dirty

        asyncio.run(_impl())

    def test_edit_modal_opens_on_e_and_escape_cancels(self, make_app):
        _factory, _ = make_app

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                ed = await self._setup(pilot)
                original_text = ed._lines[0].text
                await pilot.press("e")
                await pilot.pause()
                assert isinstance(pilot.app.screen, EditLineModal)
                await pilot.press("escape")
                await pilot.pause()
                assert not isinstance(pilot.app.screen, EditLineModal)
                assert ed._lines[0].text == original_text

        asyncio.run(_impl())

    def test_edit_modal_enter_saves_modified_text(self, make_app):
        _factory, _ = make_app

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                from textual.widgets import TextArea as _TA

                ed = await self._setup(pilot)
                await pilot.press("e")
                await pilot.pause()
                assert isinstance(pilot.app.screen, EditLineModal)
                ta = pilot.app.screen.query_one("#edit-area", _TA)
                ta.load_text("Edited text")
                await pilot.pause()
                await pilot.press("enter")
                await pilot.pause()
                assert not isinstance(pilot.app.screen, EditLineModal)
                assert ed._lines[0].text == "Edited text"
                assert ed.is_dirty
                ed.clear_dirty()
                await pilot.press("ctrl+q")

        asyncio.run(_impl())

    def test_edit_modal_ctrl_k_splits_line(self, make_app):
        _factory, _ = make_app

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                from textual.widgets import TextArea as _TA

                ed = await self._setup(pilot)
                original_count = len(ed._lines)
                await pilot.press("e")
                await pilot.pause()
                assert isinstance(pilot.app.screen, EditLineModal)
                ta = pilot.app.screen.query_one("#edit-area", _TA)
                ta.load_text("Hello World")
                await pilot.pause()
                ta.move_cursor((0, 5))
                await pilot.pause()
                await pilot.press("ctrl+k")
                await pilot.pause()
                assert not isinstance(pilot.app.screen, EditLineModal)
                assert len(ed._lines) == original_count + 1
                ed.clear_dirty()
                await pilot.press("ctrl+q")

        asyncio.run(_impl())

    def test_split_with_words_updates_first_half_end(self, make_app):
        _factory, _ = make_app

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                from textual.widgets import TextArea as _TA

                ed = await self._setup(pilot)
                w_hello = WordTiming(word=" Hello", start=1.0, end=1.4)
                w_world = WordTiming(word=" World", start=1.6, end=2.0)
                ed._lines[0].words = [w_hello, w_world]
                ed._lines[0].end = 2.0

                await pilot.press("e")
                await pilot.pause()
                ta = pilot.app.screen.query_one("#edit-area", _TA)
                ta.load_text("Hello World")
                await pilot.pause()
                ta.move_cursor((0, 5))
                await pilot.pause()
                await pilot.press("ctrl+k")
                await pilot.pause()

                assert ed._lines[0].end == pytest.approx(1.4)
                assert ed._lines[0].words == [w_hello]
                assert ed._lines[1].end == pytest.approx(2.0)
                assert ed._lines[1].timestamp == pytest.approx(1.6)
                assert ed._lines[1].words == [w_world]
                ed.clear_dirty()
                await pilot.press("ctrl+q")

        asyncio.run(_impl())

    def test_edit_save_clears_word_data_when_word_count_changes(self, make_app):
        _factory, _ = make_app

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                from textual.widgets import TextArea as _TA

                ed = await self._setup(pilot)
                ed._lines[0].words = [
                    WordTiming(" Hello", 1.0, 1.4),
                    WordTiming(" World", 1.6, 2.0),
                ]
                await pilot.press("e")
                await pilot.pause()
                ta = pilot.app.screen.query_one("#edit-area", _TA)
                ta.load_text("Hello beautiful world")
                await pilot.pause()
                await pilot.press("enter")
                await pilot.pause()
                assert ed._lines[0].text == "Hello beautiful world"
                assert ed._lines[0].words == []
                ed.clear_dirty()
                await pilot.press("ctrl+q")

        asyncio.run(_impl())

    def test_edit_noop_preserves_word_data(self, make_app):
        _factory, _ = make_app

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                ed = await self._setup(pilot)
                words = [WordTiming(" First", 1.0, 1.3), WordTiming(" line", 1.4, 1.7)]
                ed._lines[0].words = words
                await pilot.press("e")
                await pilot.pause()
                await pilot.press("enter")
                await pilot.pause()
                assert ed._lines[0].words == words
                await pilot.press("ctrl+q")

        asyncio.run(_impl())

    def test_edit_same_word_count_preserves_timing(self, make_app):
        _factory, _ = make_app

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                from textual.widgets import TextArea as _TA

                ed = await self._setup(pilot)
                ed._lines[0].words = [
                    WordTiming(" First", 1.0, 1.3),
                    WordTiming(" line", 1.4, 1.7),
                ]
                await pilot.press("e")
                await pilot.pause()
                ta = pilot.app.screen.query_one("#edit-area", _TA)
                ta.load_text("Fist line")
                await pilot.pause()
                await pilot.press("enter")
                await pilot.pause()
                assert ed._lines[0].text == "Fist line"
                assert len(ed._lines[0].words) == 2
                assert ed._lines[0].words[0].word == " Fist"
                assert ed._lines[0].words[0].start == pytest.approx(1.0)
                assert ed._lines[0].words[0].end == pytest.approx(1.3)
                ed.clear_dirty()
                await pilot.press("ctrl+q")

        asyncio.run(_impl())

    def test_split_after_edit_uses_heuristic_timestamp(self, make_app):
        _factory, _ = make_app

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                from textual.widgets import TextArea as _TA

                ed = await self._setup(pilot)
                ed._lines[0].words = []
                ed._lines[0].timestamp = 1.0
                ed._current_position = 3.5
                await pilot.press("e")
                await pilot.pause()
                ta = pilot.app.screen.query_one("#edit-area", _TA)
                ta.load_text("Hello World")
                await pilot.pause()
                ta.move_cursor((0, 5))
                await pilot.pause()
                await pilot.press("ctrl+k")
                await pilot.pause()
                assert ed._lines[1].timestamp == pytest.approx(3.5)
                assert ed._lines[1].words == []
                ed.clear_dirty()
                await pilot.press("ctrl+q")

        asyncio.run(_impl())

    def test_merge_then_split_preserves_words_single_word_first_line(self, make_app):
        _factory, _ = make_app

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                from textual.widgets import TextArea as _TA

                ed = await self._setup(pilot)
                w_first = WordTiming(word=" First", start=1.0, end=1.3)
                w_line = WordTiming(word=" line", start=1.4, end=1.7)
                ed._lines[0].text = "First"
                ed._lines[0].words = [w_first]
                ed._lines[1].text = "Line two"
                ed._lines[1].words = [w_line, WordTiming(word=" two", start=1.8, end=2.1)]

                await pilot.press("m")
                await pilot.pause()
                assert len(ed._lines) == 4
                assert ed._lines[0].text == "First line two"

                await pilot.press("e")
                await pilot.pause()
                ta = pilot.app.screen.query_one("#edit-area", _TA)
                ta.load_text("First")
                await pilot.pause()
                ta.move_cursor((0, 5))
                await pilot.pause()
                await pilot.press("ctrl+k")
                await pilot.pause()

                assert ed._lines[0].text == "First"
                assert ed._lines[0].words == [w_first]
                assert ed._lines[1].words[0].word == " line"
                ed.clear_dirty()
                await pilot.press("ctrl+q")

        asyncio.run(_impl())

    def test_merge_then_split_one_sided_words_preserves_first_half(self, make_app):
        _factory, _ = make_app

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                from textual.widgets import TextArea as _TA

                ed = await self._setup(pilot)
                w_first = WordTiming(word=" First", start=1.0, end=1.3)
                ed._lines[0].text = "First"
                ed._lines[0].words = [w_first]
                ed._lines[1].text = "line"
                ed._lines[1].words = []

                await pilot.press("m")
                await pilot.pause()

                await pilot.press("e")
                await pilot.pause()
                ta = pilot.app.screen.query_one("#edit-area", _TA)
                ta.load_text("First")
                await pilot.pause()
                ta.move_cursor((0, 5))
                await pilot.pause()
                await pilot.press("ctrl+k")
                await pilot.pause()

                assert ed._lines[0].words == [w_first]
                assert ed._lines[1].words == []
                ed.clear_dirty()
                await pilot.press("ctrl+q")

        asyncio.run(_impl())

    def test_merge_then_split_duplicate_word_at_boundary(self, make_app):
        _factory, _ = make_app

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                from textual.widgets import TextArea as _TA

                ed = await self._setup(pilot)
                w_the_a = WordTiming(word=" the", start=1.0, end=1.1)
                w_the_b = WordTiming(word=" the", start=2.0, end=2.1)
                w_end = WordTiming(word=" end", start=2.2, end=2.5)
                ed._lines[0].text = "the"
                ed._lines[0].words = [w_the_a]
                ed._lines[1].text = "the end"
                ed._lines[1].words = [w_the_b, w_end]

                await pilot.press("m")
                await pilot.pause()

                await pilot.press("e")
                await pilot.pause()
                ta = pilot.app.screen.query_one("#edit-area", _TA)
                ta.load_text("the")
                await pilot.pause()
                ta.move_cursor((0, 3))
                await pilot.pause()
                await pilot.press("ctrl+k")
                await pilot.pause()

                assert ed._lines[0].words == [w_the_a]
                assert ed._lines[1].words[0] is w_the_b
                ed.clear_dirty()
                await pilot.press("ctrl+q")

        asyncio.run(_impl())

    def test_merge_line_cleared_via_edit_modal_is_deleted(self, make_app):
        _factory, _ = make_app

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                from textual.widgets import TextArea as _TA

                ed = await self._setup(pilot)
                w = WordTiming(word=" line", start=2.0, end=2.5)
                ed._lines[0].text = "First line"
                ed._lines[0].end = 1.8
                ed._lines[0].words = [WordTiming(word=" First", start=1.0, end=1.4), w]
                ed._lines[1].text = "Second line"
                ed._lines[1].timestamp = 2.0
                ed._lines[1].end = 3.0
                ed._lines[1].words = [WordTiming(word=" Second", start=2.0, end=2.6)]

                await pilot.press("e")
                await pilot.pause()
                ta = pilot.app.screen.query_one("#edit-area", _TA)
                ta.load_text("")
                await pilot.pause()
                await pilot.press("enter")
                await pilot.pause()
                assert ed._lines[0].text == ""

                await pilot.press("m")
                await pilot.pause()
                assert ed._lines[0].text == "Second line"
                assert ed._lines[0].timestamp == pytest.approx(2.0)
                assert ed._lines[0].end == pytest.approx(3.0)
                assert ed._lines[0].words[0].word == " Second"
                ed.clear_dirty()
                await pilot.press("ctrl+q")

        asyncio.run(_impl())

    def test_blank_line_edited_to_content_then_merged(self, make_app):
        _factory, _ = make_app

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                from textual.widgets import TextArea as _TA

                ed = await self._setup(pilot)
                ed._lines[0].timestamp = 1.0
                ed._lines[0].end = 2.0
                ed._lines[0].text = ""
                ed._lines[0].words = []
                ed._lines[1].timestamp = 2.0
                ed._lines[1].end = 3.0
                ed._lines[1].text = "world"
                ed._lines[1].words = []

                await pilot.press("e")
                await pilot.pause()
                ta = pilot.app.screen.query_one("#edit-area", _TA)
                ta.load_text("Hello")
                await pilot.pause()
                await pilot.press("enter")
                await pilot.pause()
                assert ed._lines[0].text == "Hello"

                await pilot.press("m")
                await pilot.pause()
                assert ed._lines[0].timestamp == pytest.approx(1.0)
                assert ed._lines[0].end == pytest.approx(3.0)
                assert "Hello" in ed._lines[0].text
                assert "world" in ed._lines[0].text.lower()
                ed.clear_dirty()
                await pilot.press("ctrl+q")

        asyncio.run(_impl())

    def _assert_highlight_on(self, pilot, ed) -> None:
        from textual.widgets import ListItem, ListView

        lv = pilot.app.query_one("#lrc-list", ListView)
        items = [c for c in lv.children if isinstance(c, ListItem)]
        highlighted = [i for i, item in enumerate(items) if item.has_class("-highlight")]
        assert highlighted == [ed._cursor_idx], (
            f"expected only [{ed._cursor_idx}] highlighted, got {highlighted}"
        )
        assert lv.index == ed._cursor_idx

    def test_cursor_highlight_visible_after_merge(self, make_app):
        _factory, _ = make_app

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                ed = await self._setup(pilot)
                for _ in range(4):
                    await pilot.press("down")
                    await pilot.pause()
                await pilot.press("m")
                await pilot.pause()
                self._assert_highlight_on(pilot, ed)
                ed.clear_dirty()
                await pilot.press("ctrl+q")

        asyncio.run(_impl())

    def test_cursor_highlight_visible_after_delete(self, make_app):
        _factory, _ = make_app

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                ed = await self._setup(pilot)
                for _ in range(4):
                    await pilot.press("down")
                    await pilot.pause()
                await pilot.press("ctrl+d")
                await pilot.pause()
                self._assert_highlight_on(pilot, ed)
                ed.clear_dirty()
                await pilot.press("ctrl+q")

        asyncio.run(_impl())

    def test_cursor_highlight_visible_after_insert_blank(self, make_app):
        _factory, _ = make_app

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                ed = await self._setup(pilot)
                for _ in range(4):
                    await pilot.press("down")
                    await pilot.pause()
                await pilot.press("i")
                await pilot.pause()
                self._assert_highlight_on(pilot, ed)
                ed.clear_dirty()
                await pilot.press("ctrl+q")

        asyncio.run(_impl())
