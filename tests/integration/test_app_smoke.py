"""Smoke tests: app mounts cleanly, core widgets present, modals open/close."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

import lyrsmith.config as config_module
from lyrsmith.app import LyrsmithApp
from lyrsmith.config import Config
from lyrsmith.ui.bottom_bar import BottomBar
from lyrsmith.ui.help_modal import HelpModal
from lyrsmith.ui.lyrics_editor import LyricsEditor
from lyrsmith.ui.top_bar import TopBar
from lyrsmith.ui.waveform_pane import WaveformPane


def test_action_next_lang_cycles_with_auto_when_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """action_next_lang always includes 'auto' in the cycle even if the stored
    whisper_languages list doesn't contain it, and must NOT write 'auto' back."""
    monkeypatch.setattr(config_module, "_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(config_module, "_CONFIG_FILE", tmp_path / "config.yaml")

    cfg = Config(whisper_languages=["en", "pl"], whisper_language="en")

    async def _run() -> None:
        app = LyrsmithApp(initial_dir=tmp_path, config=cfg)
        async with app.run_test(headless=True) as pilot:
            # Cycle once: "en" → "pl" (both in stored list; "auto" prepended in view)
            app.action_next_lang()
            assert app._config.whisper_language == "pl"
            # Cycle again: "pl" → "auto" (wraps around the prepended "auto")
            app.action_next_lang()
            assert app._config.whisper_language == "auto"
            # "auto" must NOT have been written into the stored list
            assert "auto" not in app._config.whisper_languages
            await pilot.press("ctrl+q")

    asyncio.run(_run())


def test_app_mounts_and_core_widgets_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """App starts without crashing and all primary widgets are queryable."""
    monkeypatch.setattr(config_module, "_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(config_module, "_CONFIG_FILE", tmp_path / "config.yaml")

    async def _run() -> None:
        app = LyrsmithApp(initial_dir=tmp_path, config=Config())
        async with app.run_test(headless=True) as pilot:
            assert app.query_one(TopBar) is not None
            assert app.query_one(BottomBar) is not None
            assert app.query_one(LyricsEditor) is not None
            assert app.query_one(WaveformPane) is not None
            assert app.query_one(LyricsEditor).mode == "empty"
            await pilot.press("ctrl+q")

    asyncio.run(_run())


def test_help_modal_opens_and_closes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """F1 opens HelpModal; Escape closes it."""
    monkeypatch.setattr(config_module, "_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(config_module, "_CONFIG_FILE", tmp_path / "config.yaml")

    async def _run() -> None:
        app = LyrsmithApp(initial_dir=tmp_path, config=Config())
        async with app.run_test(headless=True) as pilot:
            assert len(app.query(HelpModal)) == 0
            app.action_show_help()
            await pilot.pause()
            assert isinstance(app.screen, HelpModal)
            await pilot.press("escape")
            await pilot.pause()
            assert not isinstance(app.screen, HelpModal)
            await pilot.press("ctrl+q")

    asyncio.run(_run())
