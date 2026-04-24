"""Integration tests for the global LRC offset modal."""

from __future__ import annotations

import asyncio

import pytest

from lyrsmith.lrc import WordTiming
from lyrsmith.ui.lyrics_editor import LyricsEditor

from ._helpers import _load_and_focus


class TestGlobalOffsetModal:
    async def _setup(self, pilot):
        return await _load_and_focus(pilot)

    def test_ctrl_o_opens_modal_and_applies_offset(self, make_app):
        _factory, _ = make_app

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                from lyrsmith.ui.global_offset_modal import GlobalOffsetModal

                ed = await self._setup(pilot)
                ed._lines[0].end = 2.0
                ed._lines[0].words = [WordTiming(" First", 1.1, 1.4)]

                await pilot.press("ctrl+o")
                await pilot.pause()

                modal = pilot.app.screen
                assert isinstance(modal, GlobalOffsetModal)
                assert modal.query_one("#offset-value").render().plain == "0.0s"

                await pilot.press("apostrophe")
                await pilot.pause()
                assert modal.query_one("#offset-value").render().plain == "+0.1s"

                await pilot.press("enter")
                await pilot.pause()
                await pilot.pause()

                assert pilot.app.screen is pilot.app.screen_stack[0]
                assert [line.timestamp for line in ed.lrc_lines] == pytest.approx(
                    [1.1, 3.1, 5.1, 7.1, 9.1]
                )
                assert ed.lrc_lines[0].end == pytest.approx(2.1)
                assert ed.lrc_lines[0].words[0].start == pytest.approx(1.2)
                assert ed.is_dirty

                await pilot.press("ctrl+z")
                await pilot.pause()

                assert [line.timestamp for line in ed.lrc_lines] == pytest.approx(
                    [1.0, 3.0, 5.0, 7.0, 9.0]
                )
                assert ed.lrc_lines[0].end == pytest.approx(2.0)
                assert ed.lrc_lines[0].words[0].start == pytest.approx(1.1)

        asyncio.run(_impl())

    def test_escape_cancels_without_changes(self, make_app):
        _factory, _ = make_app

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                from lyrsmith.ui.global_offset_modal import GlobalOffsetModal

                ed = await self._setup(pilot)
                before = [line.timestamp for line in ed.lrc_lines]

                await pilot.press("ctrl+o")
                await pilot.pause()
                assert isinstance(pilot.app.screen, GlobalOffsetModal)

                await pilot.press("escape")
                await pilot.pause()

                assert pilot.app.screen is pilot.app.screen_stack[0]
                assert [line.timestamp for line in ed.lrc_lines] == pytest.approx(before)
                assert not ed.is_dirty

        asyncio.run(_impl())

    def test_ctrl_o_ignored_in_plain_mode(self, make_app):
        _factory, _ = make_app

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                from textual.widgets import TextArea

                ed = pilot.app.query_one(LyricsEditor)
                ed.load_plain("one\ntwo")
                await pilot.pause()
                pilot.app.query_one("#plain-area", TextArea).focus()
                await pilot.pause()

                await pilot.press("ctrl+o")
                await pilot.pause()

                assert pilot.app.screen is pilot.app.screen_stack[0]
                assert ed.mode == "plain"

        asyncio.run(_impl())
