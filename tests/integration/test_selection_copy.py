"""Auto-copy screen-level and TextArea selection to system clipboard on mouse-up."""

from __future__ import annotations

import asyncio

from lyrsmith.ui.prompt_modal import PromptModal


class TestSelectionCopy:
    """Screen-level drag and TextArea selections are copied via system clipboard
    tools (wl-copy / xclip / xsel) on mouse release, with a toast notification."""

    # ------------------------------------------------------------------
    # Screen-level selection (LRC list, labels, etc.)
    # ------------------------------------------------------------------

    def test_drag_selection_copies_to_system_clipboard(self, make_app, monkeypatch):
        """When get_selected_text returns text, _copy_to_system_clipboard is called."""
        _factory, _ = make_app
        copied: list[str] = []
        monkeypatch.setattr("lyrsmith.app._copy_to_system_clipboard", copied.append)

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                app = pilot.app
                monkeypatch.setattr(
                    app.screen,
                    "get_selected_text",
                    lambda: "selected lyrics line",
                )
                app.on_text_selected()
                await pilot.pause()
                assert copied == ["selected lyrics line"]

        asyncio.run(_impl())

    def test_plain_click_does_not_copy(self, make_app, monkeypatch):
        """When get_selected_text returns None (plain click), nothing is copied."""
        _factory, _ = make_app
        copied: list[str] = []
        monkeypatch.setattr("lyrsmith.app._copy_to_system_clipboard", copied.append)

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                app = pilot.app
                monkeypatch.setattr(
                    app.screen,
                    "get_selected_text",
                    lambda: None,
                )
                app.on_text_selected()
                await pilot.pause()
                assert copied == []

        asyncio.run(_impl())

    def test_empty_selection_does_not_copy(self, make_app, monkeypatch):
        """Empty string from get_selected_text is also treated as no-op."""
        _factory, _ = make_app
        copied: list[str] = []
        monkeypatch.setattr("lyrsmith.app._copy_to_system_clipboard", copied.append)

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                app = pilot.app
                monkeypatch.setattr(
                    app.screen,
                    "get_selected_text",
                    lambda: "",
                )
                app.on_text_selected()
                await pilot.pause()
                assert copied == []

        asyncio.run(_impl())

    # ------------------------------------------------------------------
    # TextArea selection (prompt modal, edit modal, etc.)
    # ------------------------------------------------------------------

    def test_textarea_selection_copied_on_mouse_up(self, make_app, monkeypatch, tmp_path):
        """Releasing the mouse inside a focused TextArea with selected text
        calls _copy_to_system_clipboard via on_mouse_up."""
        from textual.widgets import TextArea

        _factory, _ = make_app
        copied: list[str] = []
        monkeypatch.setattr("lyrsmith.app._copy_to_system_clipboard", copied.append)

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                app = pilot.app
                app._loaded_path = tmp_path / "dummy.mp3"
                app.action_show_prompt()
                await pilot.pause()
                assert isinstance(app.screen, PromptModal)

                ta = app.screen.query_one("#prompt-area", TextArea)
                ta.load_text("Hello World")
                await pilot.pause()
                ta.select_all()
                await pilot.pause()

                app.on_mouse_up()
                await pilot.pause()
                assert copied == ["Hello World"]

        asyncio.run(_impl())

    def test_textarea_empty_selection_does_not_copy(self, make_app, monkeypatch, tmp_path):
        """on_mouse_up with a TextArea cursor (no selection) does not copy."""
        from textual.widgets import TextArea

        _factory, _ = make_app
        copied: list[str] = []
        monkeypatch.setattr("lyrsmith.app._copy_to_system_clipboard", copied.append)

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                app = pilot.app
                app._loaded_path = tmp_path / "dummy.mp3"
                app.action_show_prompt()
                await pilot.pause()
                assert isinstance(app.screen, PromptModal)

                ta = app.screen.query_one("#prompt-area", TextArea)
                ta.load_text("Hello World")
                await pilot.pause()
                ta.move_cursor((0, 0))
                await pilot.pause()

                app.on_mouse_up()
                await pilot.pause()
                assert copied == []

        asyncio.run(_impl())

    def test_mouse_up_outside_textarea_does_not_use_textarea_path(self, make_app, monkeypatch):
        """on_mouse_up when focused widget is not a TextArea must not copy."""
        _factory, _ = make_app
        copied: list[str] = []
        monkeypatch.setattr("lyrsmith.app._copy_to_system_clipboard", copied.append)

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                # Default focus is on FileBrowser — not a TextArea
                pilot.app.on_mouse_up()
                await pilot.pause()
                assert copied == []

        asyncio.run(_impl())
