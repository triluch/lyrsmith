"""Active-line highlight and label-update behavior in the LRC editor.

Covers the two distinct responsibilities of _refresh_active_style:
  1. Toggling the "active-line" CSS class when the playback position advances.
  2. Updating list item label text after mutations that change timestamps
     (stamp, nudge).
"""

from __future__ import annotations

import asyncio

import pytest
from textual.widgets import Label, ListItem, ListView

from ._helpers import _load_and_focus


def _list_items(pilot) -> list[ListItem]:
    lv = pilot.app.query_one("#lrc-list", ListView)
    return [c for c in lv.children if isinstance(c, ListItem)]


def _label_text(item: ListItem) -> str:
    return item.query_one(".line-text", Label).content


class TestActiveLineHighlight:
    async def _setup(self, pilot):
        return await _load_and_focus(pilot)

    # ------------------------------------------------------------------
    # CSS class toggling via update_position
    # ------------------------------------------------------------------

    def test_active_line_class_applied_on_position_update(self, make_app):
        """update_position past a line's timestamp marks it active-line."""
        _factory, _ = make_app

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                ed = await self._setup(pilot)
                # _SAMPLE_LRC: lines at 1, 3, 5, 7, 9 s.
                # At 2.0 s the first line (ts=1.0) is active.
                ed.update_position(2.0)
                await pilot.pause()

                items = _list_items(pilot)
                assert items[0].has_class("active-line")
                assert not items[1].has_class("active-line")
                assert not items[2].has_class("active-line")

        asyncio.run(_impl())

    def test_active_line_class_advances_when_position_passes_next_timestamp(self, make_app):
        """active-line class moves from one item to the next as position advances."""
        _factory, _ = make_app

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                ed = await self._setup(pilot)

                ed.update_position(2.0)
                await pilot.pause()
                items = _list_items(pilot)
                assert items[0].has_class("active-line")
                assert not items[1].has_class("active-line")

                # Advance past the second line's timestamp (3.0 s).
                ed.update_position(4.0)
                await pilot.pause()
                items = _list_items(pilot)
                assert not items[0].has_class("active-line")
                assert items[1].has_class("active-line")

        asyncio.run(_impl())

    def test_no_active_line_before_first_timestamp(self, make_app):
        """Position before the first line leaves every item without active-line."""
        _factory, _ = make_app

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                ed = await self._setup(pilot)

                ed.update_position(0.5)
                await pilot.pause()

                for item in _list_items(pilot):
                    assert not item.has_class("active-line")

        asyncio.run(_impl())

    # ------------------------------------------------------------------
    # Label text updates after mutations
    # ------------------------------------------------------------------

    def test_stamp_updates_list_item_label(self, make_app):
        """After stamping a line, its list item label reflects the new timestamp."""
        _factory, _ = make_app

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                ed = await self._setup(pilot)

                ed._current_position = 4.5
                await pilot.press("t")
                await pilot.pause()

                # Cursor follows the stamped line after sort.
                cursor = ed._cursor_idx
                expected = ed._lines[cursor].display_str()
                assert _label_text(_list_items(pilot)[cursor]) == expected
                assert "[00:04.50]" in expected

                ed.clear_dirty()
                await pilot.press("ctrl+q")

        asyncio.run(_impl())

    def test_nudge_updates_list_item_label(self, make_app):
        """After nudging a line forward, its list item label reflects the new timestamp."""
        _factory, _ = make_app

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                ed = await self._setup(pilot)

                original_ts = ed._lines[0].timestamp  # 1.0 s
                await pilot.press("period")  # +0.01 s fine nudge
                await pilot.pause()

                cursor = ed._cursor_idx
                expected = ed._lines[cursor].display_str()
                assert _label_text(_list_items(pilot)[cursor]) == expected
                assert ed._lines[cursor].timestamp == pytest.approx(original_ts + 0.010, abs=1e-4)

                ed.clear_dirty()
                await pilot.press("ctrl+q")

        asyncio.run(_impl())
