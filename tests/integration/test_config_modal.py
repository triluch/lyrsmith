"""Config modal: F2 opens, cancel is safe, save validates and updates config."""

from __future__ import annotations

import asyncio

from textual.widgets import Label

from lyrsmith.config import Config
from lyrsmith.ui.config_modal import ConfigModal


class TestConfigModal:
    """F2 config editor: open, cancel, and save with validation."""

    def test_f2_key_press_opens_modal(self, make_app):
        _factory, _ = make_app

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                await pilot.pause()
                await pilot.press("f2")
                await pilot.pause()
                assert isinstance(pilot.app.screen, ConfigModal)
                await pilot.press("f2")  # f2 also cancels
                await pilot.pause()
                assert not isinstance(pilot.app.screen, ConfigModal)

        asyncio.run(_impl())

    def test_cancel_leaves_config_unchanged(self, make_app):
        _factory, _ = make_app

        async def _impl():
            async with _factory(config=Config(whisper_model="base")).run_test(
                headless=True
            ) as pilot:
                app = pilot.app
                await pilot.pause()
                app.action_show_config()
                await pilot.pause()
                await pilot.press("escape")
                await pilot.pause()
                assert app._config.whisper_model == "base"

        asyncio.run(_impl())

    def test_save_updates_whisper_model(self, make_app):
        _factory, _ = make_app

        async def _impl():
            async with _factory(config=Config(whisper_model="base")).run_test(
                headless=True
            ) as pilot:
                from textual.widgets import Input as _Input

                app = pilot.app
                await pilot.pause()
                app.action_show_config()
                await pilot.pause()
                assert isinstance(app.screen, ConfigModal)

                inp = app.screen.query_one("#f-whisper-model", _Input)
                inp.value = "tiny"
                await pilot.pause()
                await pilot.press("ctrl+s")
                await pilot.pause()
                assert not isinstance(app.screen, ConfigModal)
                assert app._config.whisper_model == "tiny"
                await pilot.press("ctrl+q")

        asyncio.run(_impl())

    def test_save_with_invalid_threads_shows_error(self, make_app):
        """Non-integer intra_threads value triggers error label instead of dismissing."""
        _factory, _ = make_app

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                from textual.widgets import Input as _Input

                app = pilot.app
                await pilot.pause()
                app.action_show_config()
                await pilot.pause()
                assert isinstance(app.screen, ConfigModal)

                app.screen.query_one("#f-intra-threads", _Input).value = "not_a_number"
                await pilot.pause()
                await pilot.press("ctrl+s")
                await pilot.pause()
                assert isinstance(app.screen, ConfigModal)
                await pilot.press("escape")
                await pilot.pause()
                assert not isinstance(app.screen, ConfigModal)
                await pilot.press("ctrl+q")

        asyncio.run(_impl())

    def test_help_area_populated_on_open(self, make_app):
        _factory, _ = make_app

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                app = pilot.app
                await pilot.pause()
                app.action_show_config()
                await pilot.pause()
                assert isinstance(app.screen, ConfigModal)
                help_text = str(app.screen.query_one("#help-area", Label).content)
                assert "model size" in help_text.lower()
                await pilot.press("escape")
                await pilot.pause()

        asyncio.run(_impl())

    def test_tab_updates_help_text(self, make_app):
        _factory, _ = make_app

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                app = pilot.app
                await pilot.pause()
                app.action_show_config()
                await pilot.pause()
                assert isinstance(app.screen, ConfigModal)
                modal = app.screen

                first_help = str(modal.query_one("#help-area", Label).content)
                await pilot.press("tab")
                await pilot.pause()
                second_help = str(modal.query_one("#help-area", Label).content)

                assert first_help != second_help
                assert "quantis" in second_help.lower()
                await pilot.press("escape")
                await pilot.pause()

        asyncio.run(_impl())

    def test_each_field_shows_its_own_description(self, make_app):
        _factory, _ = make_app

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                from textual.widgets import Input as _Input

                from lyrsmith.ui.config_modal import _FIELD_DESCRIPTIONS

                app = pilot.app
                await pilot.pause()
                app.action_show_config()
                await pilot.pause()
                assert isinstance(app.screen, ConfigModal)
                modal = app.screen

                for field_id, expected_desc in _FIELD_DESCRIPTIONS.items():
                    modal.query_one(f"#{field_id}", _Input).focus()
                    await pilot.pause()
                    help_text = str(modal.query_one("#help-area", Label).content)
                    assert help_text == expected_desc, (
                        f"{field_id}: expected {expected_desc!r}, got {help_text!r}"
                    )

                await pilot.press("escape")
                await pilot.pause()

        asyncio.run(_impl())
