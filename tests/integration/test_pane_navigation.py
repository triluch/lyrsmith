"""Tab/Shift+Tab pane focus cycling; bottom bar context tracking."""

from __future__ import annotations

import asyncio

from lyrsmith.ui.bottom_bar import BottomBar
from lyrsmith.ui.lyrics_editor import LyricsEditor

from ._helpers import _SAMPLE_LRC


class TestPaneNavigation:
    """Tab/Shift+Tab cycle focus; bottom bar context tracks the active pane."""

    def test_initial_context_is_browser(self, make_app):
        _factory, _ = make_app

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                await pilot.pause()
                pilot.app._poll_focus()
                assert pilot.app.query_one(BottomBar).context == "browser"

        asyncio.run(_impl())

    def test_tab_moves_focus_to_waveform(self, make_app):
        _factory, _ = make_app

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                await pilot.pause()
                await pilot.press("tab")
                await pilot.pause()
                pilot.app._poll_focus()
                assert pilot.app.query_one(BottomBar).context == "waveform"

        asyncio.run(_impl())

    def test_two_tabs_reach_lrc_editor(self, make_app):
        """Tab twice: browser → waveform → lrc-list (LRC mode required so the
        list widget is visible and in the focus chain)."""
        _factory, _ = make_app

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                await pilot.pause()
                pilot.app.query_one(LyricsEditor).load_lrc(_SAMPLE_LRC)
                await pilot.pause()
                await pilot.press("tab")  # → WaveformPane
                await pilot.pause()
                await pilot.press("tab")  # → #lrc-list
                await pilot.pause()
                pilot.app._poll_focus()
                assert pilot.app.query_one(BottomBar).context == "lyrics-lrc"

        asyncio.run(_impl())

    def test_shift_tab_reverses_direction(self, make_app):
        _factory, _ = make_app

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                await pilot.pause()
                await pilot.press("tab")  # browser → waveform
                await pilot.pause()
                await pilot.press("shift+tab")  # waveform → browser
                await pilot.pause()
                pilot.app._poll_focus()
                assert pilot.app.query_one(BottomBar).context == "browser"

        asyncio.run(_impl())

    def test_tab_wraps_back_to_browser_in_empty_mode(self, make_app):
        """In empty mode #lrc-list is hidden, so Tab wraps after waveform."""
        _factory, _ = make_app

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                await pilot.pause()
                assert pilot.app.query_one(LyricsEditor).mode == "empty"
                await pilot.press("tab")  # → waveform
                await pilot.pause()
                await pilot.press("tab")  # wraps back to browser
                await pilot.pause()
                pilot.app._poll_focus()
                assert pilot.app.query_one(BottomBar).context == "browser"

        asyncio.run(_impl())
