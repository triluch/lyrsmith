"""Dirty-flag tracking, Ctrl+S save, and UnsavedModal interactions."""

from __future__ import annotations

import asyncio
from pathlib import Path

from lyrsmith.lrc import LRCLine, WordTiming
from lyrsmith.metadata.tags import read_word_data, write_word_data
from lyrsmith.ui.file_browser import FileBrowser
from lyrsmith.ui.lyrics_editor import LyricsEditor
from lyrsmith.ui.unsaved_modal import UnsavedModal

from ._helpers import _SAMPLE_LRC, _fake_info, _make_mp3


class TestSaveFlow:
    """Dirty-flag tracking, ctrl+s save, and UnsavedModal interactions."""

    def test_dirty_flag_set_after_delete(self, make_app):
        _factory, _ = make_app

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                ed = pilot.app.query_one(LyricsEditor)
                ed.load_lrc(_SAMPLE_LRC)
                await pilot.pause()
                assert not ed.is_dirty
                pilot.app.query_one("#lrc-list").focus()
                await pilot.pause()
                await pilot.press("ctrl+d")
                await pilot.pause()
                assert ed.is_dirty
                ed.clear_dirty()
                await pilot.press("ctrl+q")

        asyncio.run(_impl())

    def test_ctrl_s_calls_write_lyrics(self, make_app, monkeypatch, tmp_path):
        _factory, _ = make_app
        audio = _make_mp3(tmp_path / "track.mp3")
        saved_calls: list[tuple[Path, str]] = []

        monkeypatch.setattr(
            "lyrsmith.app.write_lyrics",
            lambda path, text: saved_calls.append((path, text)),
        )
        monkeypatch.setattr("lyrsmith.app.read_info", _fake_info)
        monkeypatch.setattr("lyrsmith.app.read_lyrics", lambda _p: _SAMPLE_LRC)

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                app = pilot.app
                app._loaded_path = audio
                ed = app.query_one(LyricsEditor)
                ed.load_lrc(_SAMPLE_LRC)
                ed.mark_dirty()
                await pilot.pause()
                await pilot.press("ctrl+s")
                await pilot.pause()
                assert len(saved_calls) == 1
                assert saved_calls[0][0] == audio
                assert not ed.is_dirty
                await pilot.press("ctrl+q")

        asyncio.run(_impl())

    def test_ctrl_s_noop_when_no_file_loaded(self, make_app):
        _factory, _ = make_app

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                assert pilot.app._loaded_path is None
                await pilot.press("ctrl+s")
                await pilot.pause()
                await pilot.press("ctrl+q")

        asyncio.run(_impl())

    def test_unsaved_modal_appears_when_loading_over_dirty(self, make_app, monkeypatch, tmp_path):
        _factory, _ = make_app
        audio1 = _make_mp3(tmp_path / "a.mp3")
        audio2 = _make_mp3(tmp_path / "b.mp3")
        monkeypatch.setattr("lyrsmith.app.read_info", _fake_info)
        monkeypatch.setattr("lyrsmith.app.read_lyrics", lambda _p: None)
        monkeypatch.setattr("lyrsmith.app.write_lyrics", lambda *_: None)

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                app = pilot.app
                app._loaded_path = audio1
                ed = app.query_one(LyricsEditor)
                ed.load_lrc(_SAMPLE_LRC)
                ed.mark_dirty()
                await pilot.pause()

                app.on_file_browser_file_selected(FileBrowser.FileSelected(audio2))
                await pilot.pause()
                assert isinstance(app.screen, UnsavedModal)

                await pilot.press("escape")
                await pilot.pause()
                assert not isinstance(app.screen, UnsavedModal)
                assert app._loaded_path == audio1
                ed.clear_dirty()

        asyncio.run(_impl())

    def test_unsaved_modal_discard_proceeds_with_load(self, make_app, monkeypatch, tmp_path):
        _factory, _ = make_app
        audio1 = _make_mp3(tmp_path / "a.mp3")
        audio2 = _make_mp3(tmp_path / "b.mp3")
        monkeypatch.setattr("lyrsmith.app.read_info", _fake_info)
        monkeypatch.setattr("lyrsmith.app.read_lyrics", lambda _p: None)
        monkeypatch.setattr("lyrsmith.app.write_lyrics", lambda *_: None)

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                app = pilot.app
                app._loaded_path = audio1
                ed = app.query_one(LyricsEditor)
                ed.load_lrc(_SAMPLE_LRC)
                ed.mark_dirty()
                await pilot.pause()

                app.on_file_browser_file_selected(FileBrowser.FileSelected(audio2))
                await pilot.pause()
                assert isinstance(app.screen, UnsavedModal)

                await pilot.press("2")  # discard
                await pilot.pause()
                assert not isinstance(app.screen, UnsavedModal)
                assert app._loaded_path == audio2

        asyncio.run(_impl())

    def test_unsaved_modal_save_writes_then_loads(self, make_app, monkeypatch, tmp_path):
        _factory, _ = make_app
        audio1 = _make_mp3(tmp_path / "a.mp3")
        audio2 = _make_mp3(tmp_path / "b.mp3")
        saved_calls: list = []
        monkeypatch.setattr(
            "lyrsmith.app.write_lyrics",
            lambda path, text: saved_calls.append((path, text)),
        )
        monkeypatch.setattr("lyrsmith.app.read_info", _fake_info)
        monkeypatch.setattr("lyrsmith.app.read_lyrics", lambda _p: None)

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                app = pilot.app
                app._loaded_path = audio1
                ed = app.query_one(LyricsEditor)
                ed.load_lrc(_SAMPLE_LRC)
                ed.mark_dirty()
                await pilot.pause()

                app.on_file_browser_file_selected(FileBrowser.FileSelected(audio2))
                await pilot.pause()
                assert isinstance(app.screen, UnsavedModal)

                await pilot.press("3")  # save and proceed
                await pilot.pause()
                assert not isinstance(app.screen, UnsavedModal)
                assert any(c[0] == audio1 for c in saved_calls)
                assert app._loaded_path == audio2
                await pilot.press("ctrl+q")

        asyncio.run(_impl())

    def test_ctrl_s_also_calls_write_word_data(self, make_app, monkeypatch, tmp_path):
        _factory, _ = make_app
        audio = _make_mp3(tmp_path / "track.mp3")
        word_write_calls: list = []
        monkeypatch.setattr("lyrsmith.app.write_lyrics", lambda *_: None)
        monkeypatch.setattr(
            "lyrsmith.app.write_word_data",
            lambda path, lines: word_write_calls.append((path, lines)),
        )
        monkeypatch.setattr("lyrsmith.app.read_info", _fake_info)
        monkeypatch.setattr("lyrsmith.app.read_lyrics", lambda _p: _SAMPLE_LRC)

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                app = pilot.app
                app._loaded_path = audio
                ed = app.query_one(LyricsEditor)
                ed.load_lrc(_SAMPLE_LRC)
                ed._lines[0].words = [WordTiming(" First", 1.0, 1.3)]
                ed.mark_dirty()
                await pilot.pause()
                await pilot.press("ctrl+s")
                await pilot.pause()
                assert len(word_write_calls) == 1
                assert word_write_calls[0][0] == audio
                assert any(l.words for l in word_write_calls[0][1])
                await pilot.press("ctrl+q")

        asyncio.run(_impl())

    def test_save_plain_mode_removes_word_data_tag(self, make_app, monkeypatch, tmp_path):
        """Saving in plain-text mode must delete the LYRSMITH_WORDS tag."""
        _factory, _ = make_app
        audio = _make_mp3(tmp_path / "track.mp3")
        write_word_data(audio, [LRCLine(1.0, "Hello", words=[WordTiming(" Hello", 1.0, 1.3)])])
        assert read_word_data(audio) != {}

        monkeypatch.setattr("lyrsmith.app.read_info", _fake_info)
        monkeypatch.setattr("lyrsmith.app.read_lyrics", lambda _p: "Just plain lyrics")

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                app = pilot.app
                app._do_load(audio)
                await pilot.pause()
                ed = app.query_one(LyricsEditor)
                assert ed.mode == "plain"
                ed.mark_dirty()
                await pilot.press("ctrl+s")
                await pilot.pause()
                assert read_word_data(audio) == {}
                await pilot.press("ctrl+q")

        asyncio.run(_impl())

    def test_stamp_then_undo_returns_to_clean(self, make_app):
        """Undoing a stamp back to the saved state must clear the dirty flag."""
        _factory, _ = make_app

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                ed = pilot.app.query_one(LyricsEditor)
                ed.load_lrc(_SAMPLE_LRC)
                await pilot.pause()
                pilot.app.query_one("#lrc-list").focus()
                await pilot.pause()

                ed.update_position(4.5)
                await pilot.press("t")
                await pilot.pause()
                assert ed.is_dirty

                await pilot.press("ctrl+z")
                await pilot.pause()
                assert not ed.is_dirty

                await pilot.press("ctrl+q")

        asyncio.run(_impl())

    def test_nudge_forward_then_back_returns_to_clean(self, make_app):
        """Nudging a line forward then back to its original timestamp must clear dirty."""
        _factory, _ = make_app

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                ed = pilot.app.query_one(LyricsEditor)
                ed.load_lrc(_SAMPLE_LRC)
                await pilot.pause()
                pilot.app.query_one("#lrc-list").focus()
                await pilot.pause()

                await pilot.press("period")  # +10 ms
                await pilot.pause()
                assert ed.is_dirty

                await pilot.press("comma")  # −10 ms — back to original
                await pilot.pause()
                assert not ed.is_dirty

                await pilot.press("ctrl+q")

        asyncio.run(_impl())

    def test_undo_to_saved_state_suppresses_unsaved_modal(self, make_app):
        """ctrl+q after undo to saved state quits without showing UnsavedModal."""
        _factory, _ = make_app

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                app = pilot.app
                ed = app.query_one(LyricsEditor)
                ed.load_lrc(_SAMPLE_LRC)
                await pilot.pause()
                app.query_one("#lrc-list").focus()
                await pilot.pause()

                ed.update_position(4.5)
                await pilot.press("t")
                await pilot.pause()
                assert ed.is_dirty

                await pilot.press("ctrl+z")
                await pilot.pause()
                assert not ed.is_dirty

                # action_quit_app would push UnsavedModal if dirty — it must not.
                app.action_quit_app()
                await pilot.pause()
                assert not isinstance(app.screen, UnsavedModal)

        asyncio.run(_impl())
