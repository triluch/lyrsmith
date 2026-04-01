"""Undo tests: single-level (current), then multi-level (after deque refactor)."""

from __future__ import annotations

import asyncio

import pytest

from lyrsmith.ui.lyrics_editor import LyricsEditor

from ._helpers import _SAMPLE_LRC


class TestUndoChain:
    """Single-level undo behaviour — must pass before and after the refactor."""

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


# ---------------------------------------------------------------------------
# Multi-level undo — these FAIL with the current single-snapshot implementation
# and must GREEN after the deque refactor.
# ---------------------------------------------------------------------------


def _ts_of(ed, text: str) -> float:
    """Return the timestamp of the first line whose text matches."""
    return next(l.timestamp for l in ed._lines if l.text == text)


class TestMultiLevelUndo:
    """Multi-level undo: each Ctrl+Z undoes one step back through history."""

    async def _setup(self, pilot):
        ed = pilot.app.query_one(LyricsEditor)
        ed.load_lrc(_SAMPLE_LRC)
        await pilot.pause()
        pilot.app.query_one("#lrc-list").focus()
        await pilot.pause()
        return ed

    def test_all_undo_saving_operations_are_individually_undoable(self, make_app):
        """stamp → delete → insert → merge: each ctrl+z undoes exactly one step.

        Covers all four operations that call _save_undo() and verifies that
        the undo stack correctly restores each intermediate state in reverse.

        Trace (_SAMPLE_LRC: lines at 1, 3, 5, 7, 9 s):
          start   : [1.0(First), 3.0(Second), 5.0(Third), 7.0(Fourth), 9.0(Fifth)]  5 lines
          stamp   : [3.0(Second), 4.0(First), 5.0(Third), 7.0(Fourth), 9.0(Fifth)]  5 lines
          delete  : [3.0(Second), 5.0(Third), 7.0(Fourth), 9.0(Fifth)]               4 lines
          insert  : [3.0(Second), 5.0(Third), 6.0(blank), 7.0(Fourth), 9.0(Fifth)]  5 lines
          merge   : [3.0(Second), 5.0(Third), 7.0(Fourth), 9.0(Fifth)]               4 lines
          undo×1  : [3.0(Second), 5.0(Third), 6.0(blank), 7.0(Fourth), 9.0(Fifth)]  5 lines
          undo×2  : [3.0(Second), 5.0(Third), 7.0(Fourth), 9.0(Fifth)]               4 lines
          undo×3  : [3.0(Second), 4.0(First), 5.0(Third), 7.0(Fourth), 9.0(Fifth)]  5 lines
          undo×4  : [1.0(First),  3.0(Second), 5.0(Third), 7.0(Fourth), 9.0(Fifth)] 5 lines
          undo×5  : (empty stack — no-op)
        """
        _factory, _ = make_app

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                ed = await self._setup(pilot)

                assert len(ed._lines) == 5
                assert _ts_of(ed, "First line") == pytest.approx(1.0)

                # ── stamp ─────────────────────────────────────────────────
                ed._current_position = 4.0
                await pilot.press("t")
                await pilot.pause()
                assert len(ed._lines) == 5
                assert _ts_of(ed, "First line") == pytest.approx(4.0)

                # ── delete (First line is now at cursor index 1) ──────────
                await pilot.press("ctrl+d")
                await pilot.pause()
                assert len(ed._lines) == 4
                assert not any(l.text == "First line" for l in ed._lines)

                # ── insert blank ──────────────────────────────────────────
                await pilot.press("i")
                await pilot.pause()
                assert len(ed._lines) == 5
                assert any(l.text == "" for l in ed._lines)

                # ── merge blank with next ─────────────────────────────────
                await pilot.press("m")
                await pilot.pause()
                assert len(ed._lines) == 4

                # ── undo merge ────────────────────────────────────────────
                await pilot.press("ctrl+z")
                await pilot.pause()
                assert len(ed._lines) == 5, "undo merge should restore 5 lines"
                assert any(l.text == "" for l in ed._lines), (
                    "undo merge should restore the blank line"
                )

                # ── undo insert ───────────────────────────────────────────
                await pilot.press("ctrl+z")
                await pilot.pause()
                assert len(ed._lines) == 4, "undo insert should restore 4 lines"
                assert not any(l.text == "" for l in ed._lines)

                # ── undo delete ───────────────────────────────────────────
                await pilot.press("ctrl+z")
                await pilot.pause()
                assert len(ed._lines) == 5, "undo delete should restore 5 lines"
                assert _ts_of(ed, "First line") == pytest.approx(4.0), (
                    "undo delete should restore First line at stamp timestamp"
                )

                # ── undo stamp ────────────────────────────────────────────
                await pilot.press("ctrl+z")
                await pilot.pause()
                assert len(ed._lines) == 5
                assert _ts_of(ed, "First line") == pytest.approx(1.0), (
                    "undo stamp should restore original timestamp"
                )

                # ── stack now empty — extra ctrl+z is a no-op ─────────────
                await pilot.press("ctrl+z")
                await pilot.pause()
                assert _ts_of(ed, "First line") == pytest.approx(1.0)

        asyncio.run(_impl())

    def test_cursor_position_restored_per_step(self, make_app):
        """Cursor index is restored correctly at each undo step.

        Uses stamp (moves cursor 0→1 after sort) then delete (cursor stays at 1
        or adjusts) — both operations save undo snapshots with their cursor state.
        """
        _factory, _ = make_app

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                ed = await self._setup(pilot)

                assert ed._cursor_idx == 0

                # stamp line 0 to 4.0 → sorts to index 1, cursor follows
                ed._current_position = 4.0
                await pilot.press("t")
                await pilot.pause()
                await pilot.pause()
                assert ed._cursor_idx == 1

                # delete at cursor=1 → cursor adjusts (still 1 or 0)
                await pilot.press("ctrl+d")
                await pilot.pause()
                await pilot.pause()
                cursor_after_delete = ed._cursor_idx

                # undo delete → cursor restored to pre-delete state (1)
                await pilot.press("ctrl+z")
                await pilot.pause()
                await pilot.pause()
                assert ed._cursor_idx == 1, (
                    "undo delete should restore cursor to index 1 (where First line was)"
                )

                # undo stamp → cursor restored to pre-stamp state (0)
                await pilot.press("ctrl+z")
                await pilot.pause()
                await pilot.pause()
                assert ed._cursor_idx == 0, (
                    "undo stamp should restore cursor to index 0 (original position)"
                )

                _ = cursor_after_delete  # used for context; exact value varies

        asyncio.run(_impl())
