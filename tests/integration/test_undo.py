"""Single-level undo: Ctrl+Z restores the most recent snapshot."""

from __future__ import annotations

import asyncio

import pytest

from lyrsmith.ui.lyrics_editor import LyricsEditor

from ._helpers import _SAMPLE_LRC


class TestUndoChain:
    """Single-level undo: Ctrl+Z restores the most recent snapshot."""

    def test_stamp_then_undo_restores_timestamp(self, make_app):
        _factory, _ = make_app

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                ed = pilot.app.query_one(LyricsEditor)
                ed.load_lrc(_SAMPLE_LRC)
                await pilot.pause()
                pilot.app.query_one("#lrc-list").focus()
                await pilot.pause()

                original_ts = ed._lines[0].timestamp  # 1.0
                ed._current_position = 8.0
                await pilot.press("t")  # stamp → saves undo snapshot
                await pilot.pause()
                assert ed._lines[ed._cursor_idx].timestamp == pytest.approx(8.0)

                await pilot.press("ctrl+z")  # undo
                await pilot.pause()
                ts = next(l.timestamp for l in ed._lines if l.text == "First line")
                assert ts == pytest.approx(original_ts)
                ed.clear_dirty()
                await pilot.press("ctrl+q")

        asyncio.run(_impl())

    def test_delete_then_undo_restores_line(self, make_app):
        _factory, _ = make_app

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                ed = pilot.app.query_one(LyricsEditor)
                ed.load_lrc(_SAMPLE_LRC)
                await pilot.pause()
                pilot.app.query_one("#lrc-list").focus()
                await pilot.pause()

                assert len(ed._lines) == 5
                deleted_text = ed._lines[0].text
                await pilot.press("ctrl+d")  # delete → saves undo
                await pilot.pause()
                assert len(ed._lines) == 4

                await pilot.press("ctrl+z")  # undo
                await pilot.pause()
                assert len(ed._lines) == 5
                assert any(l.text == deleted_text for l in ed._lines)
                ed.clear_dirty()
                await pilot.press("ctrl+q")

        asyncio.run(_impl())

    def test_stamp_nudge_delete_undo_chain(self, make_app):
        """Stamp then delete; only delete snapshot is available after ctrl+z
        (single-level undo — stamp's snapshot is overwritten by delete)."""
        _factory, _ = make_app

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                ed = pilot.app.query_one(LyricsEditor)
                ed.load_lrc(_SAMPLE_LRC)
                await pilot.pause()
                pilot.app.query_one("#lrc-list").focus()
                await pilot.pause()

                ed._current_position = 6.0
                await pilot.press("t")
                await pilot.pause()

                await pilot.press("period")
                await pilot.pause()

                count_before_delete = len(ed._lines)
                await pilot.press("ctrl+d")
                await pilot.pause()
                assert len(ed._lines) == count_before_delete - 1

                await pilot.press("ctrl+z")
                await pilot.pause()
                assert len(ed._lines) == count_before_delete

                await pilot.press("ctrl+z")
                await pilot.pause()
                assert len(ed._lines) == count_before_delete
                ed.clear_dirty()

        asyncio.run(_impl())
