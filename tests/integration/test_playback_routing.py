"""Full-path playback routing tests.

Verifies that key presses in LyricsEditor (LRC mode) correctly propagate
through the app.py message handlers and reach the audio player.  Tests are
intentionally end-to-end: they care only that the FakePlayer's state changes
correctly, not how the path is wired internally.

WaveformPane → player routing is covered in test_waveform.py.
"""

from __future__ import annotations

import asyncio

import pytest

from lyrsmith.ui.lyrics_editor import LyricsEditor

from ._helpers import _SAMPLE_LRC

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _focus_lrc_editor(pilot) -> None:
    ed = pilot.app.query_one(LyricsEditor)
    ed.load_lrc(_SAMPLE_LRC)
    await pilot.pause()
    await pilot.press("tab")  # browser → waveform
    await pilot.pause()
    await pilot.press("tab")  # waveform → lrc-list
    await pilot.pause()


# ---------------------------------------------------------------------------
# LyricsEditor → player routing
# ---------------------------------------------------------------------------


class TestLyricsEditorPlayerRouting:
    """Pressing keys in LyricsEditor (LRC mode) must end up changing FakePlayer
    state via the PlayPauseRequested / SeekRequested message handlers in app.py.

    These should pass both now and after the WaveformPane refactor — they cover
    the lyrics-editor path that must not regress.
    """

    def test_space_toggles_player(self, make_app):
        """space in LRC editor → player.is_playing flips."""
        _factory, _ = make_app

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                await _focus_lrc_editor(pilot)
                player = pilot.app._player
                assert not player.is_playing
                await pilot.press("space")
                await pilot.pause()
                assert player.is_playing
                await pilot.press("space")
                await pilot.pause()
                assert not player.is_playing

        asyncio.run(_impl())

    def test_seek_fwd_moves_player(self, make_app):
        """right in LRC editor → player.position advances."""
        _factory, _ = make_app

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                await _focus_lrc_editor(pilot)
                player = pilot.app._player
                assert player.position == pytest.approx(0.0)
                await pilot.press("right")
                await pilot.pause()
                assert player.position == pytest.approx(5.0)

        asyncio.run(_impl())

    def test_seek_bwd_moves_player(self, make_app):
        """left in LRC editor → player.position decreases."""
        _factory, _ = make_app

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                await _focus_lrc_editor(pilot)
                player = pilot.app._player
                player.seek(20.0)
                # Sync editor's internal position so backward seek is relative to 20 s
                pilot.app.query_one(LyricsEditor).update_position(20.0)
                await pilot.press("left")
                await pilot.pause()
                assert player.position == pytest.approx(15.0)

        asyncio.run(_impl())

    def test_seek_large_fwd_moves_player(self, make_app):
        """shift+right in LRC editor → player.position advances by SEEK_LARGE."""
        _factory, _ = make_app

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                await _focus_lrc_editor(pilot)
                player = pilot.app._player
                await pilot.press("shift+right")
                await pilot.pause()
                assert player.position == pytest.approx(30.0)

        asyncio.run(_impl())

    def test_seek_large_bwd_moves_player(self, make_app):
        """shift+left in LRC editor → player.position decreases by SEEK_LARGE."""
        _factory, _ = make_app

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                await _focus_lrc_editor(pilot)
                player = pilot.app._player
                player.seek(40.0)
                pilot.app.query_one(LyricsEditor).update_position(40.0)
                await pilot.press("shift+left")
                await pilot.pause()
                assert player.position == pytest.approx(10.0)

        asyncio.run(_impl())

    def test_seek_to_line_moves_player_to_timestamp(self, make_app):
        """enter on a line with a timestamp → player.position = line.timestamp."""
        _factory, _ = make_app

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                await _focus_lrc_editor(pilot)
                player = pilot.app._player
                ed = pilot.app.query_one(LyricsEditor)
                # Cursor is at index 0, timestamp 1.0 s (from _SAMPLE_LRC)
                assert ed._cursor_idx == 0
                expected_ts = ed._lines[0].timestamp
                await pilot.press("enter")
                await pilot.pause()
                assert player.position == pytest.approx(expected_ts)

        asyncio.run(_impl())

    def test_stop_on_edit_pauses_player(self, make_app):
        """KB_EDIT_LINE while playing emits StopPlaybackRequested → player pauses."""
        _factory, _ = make_app

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                await _focus_lrc_editor(pilot)
                player = pilot.app._player
                # Start playing first
                await pilot.press("space")
                await pilot.pause()
                assert player.is_playing
                # Open edit modal (KB_EDIT_LINE = "e") while playing → stop
                await pilot.press("e")
                await pilot.pause()
                assert not player.is_playing
                # Dismiss the modal
                await pilot.press("escape")
                await pilot.pause()

        asyncio.run(_impl())
