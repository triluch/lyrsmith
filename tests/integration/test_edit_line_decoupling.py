"""Verify that LyricsEditor posts EditLineRequested instead of pushing EditLineModal directly."""

from __future__ import annotations

import asyncio

from textual.app import App, ComposeResult

from lyrsmith.ui.edit_line_modal import EditLineModal
from lyrsmith.ui.lyrics_editor import LyricsEditor

from ._helpers import _SAMPLE_LRC


class _CaptureApp(App):
    """Minimal app that hosts LyricsEditor and captures EditLineRequested messages.

    It intentionally does NOT push EditLineModal — if the old coupling is still
    present, pressing 'e' will push the modal directly (bypassing this handler)
    and the assertions below will catch it.
    """

    def __init__(self) -> None:
        super().__init__()
        self.edit_requests: list[LyricsEditor.EditLineRequested] = []

    def compose(self) -> ComposeResult:
        yield LyricsEditor()

    def on_lyrics_editor_edit_line_requested(self, event: LyricsEditor.EditLineRequested) -> None:
        self.edit_requests.append(event)
        # Deliberately do NOT push EditLineModal here.


class TestEditLineDecoupling:
    """LyricsEditor must post EditLineRequested rather than calling push_screen."""

    def test_e_key_posts_edit_line_requested_not_push_screen(self):
        """Pressing 'e' posts EditLineRequested with correct idx and text.

        If the old coupling is present, EditLineModal will appear on the screen
        and no message will be in edit_requests — both assertions would fail.
        """

        async def _impl():
            async with _CaptureApp().run_test(headless=True) as pilot:
                ed = pilot.app.query_one(LyricsEditor)
                ed.load_lrc(_SAMPLE_LRC)
                await pilot.pause()
                ed.query_one("#lrc-list").focus()
                await pilot.pause()

                # Cursor is at index 0 ("First line") after load.
                await pilot.press("e")
                await pilot.pause()

                # Message must have been posted.
                assert len(pilot.app.edit_requests) == 1
                req = pilot.app.edit_requests[0]
                assert req.idx == 0
                assert req.text == "First line"

                # No modal should have been pushed — the screen stack is still
                # the default screen, not an EditLineModal.
                assert not isinstance(pilot.app.screen, EditLineModal)

                await pilot.press("ctrl+q")

        asyncio.run(_impl())

    def test_edit_line_requested_carries_correct_idx_for_non_zero_cursor(self):
        """EditLineRequested reflects whichever line the cursor is on."""

        async def _impl():
            async with _CaptureApp().run_test(headless=True) as pilot:
                ed = pilot.app.query_one(LyricsEditor)
                ed.load_lrc(_SAMPLE_LRC)
                await pilot.pause()
                ed.query_one("#lrc-list").focus()
                await pilot.pause()

                # Move cursor to the second line. lv.index starts as None so
                # the first down goes None→0, second goes 0→1.
                await pilot.press("down")
                await pilot.pause()
                await pilot.press("down")
                await pilot.pause()
                await pilot.press("e")
                await pilot.pause()

                assert len(pilot.app.edit_requests) == 1
                req = pilot.app.edit_requests[0]
                assert req.idx == 1
                assert req.text == "Second line"

                assert not isinstance(pilot.app.screen, EditLineModal)

                await pilot.press("ctrl+q")

        asyncio.run(_impl())
