"""Dirty-flag tracking, Ctrl+S save, and UnsavedModal interactions."""

from __future__ import annotations

import asyncio
from pathlib import Path

from lyrsmith.lrc import LRCLine, WordTiming
from lyrsmith.metadata.tags import read_word_data, write_word_data
from lyrsmith.ui.file_browser import FileBrowser
from lyrsmith.ui.lyrics_editor import LyricsEditor
from lyrsmith.ui.unsaved_modal import UnsavedModal

from ._helpers import _SAMPLE_LRC, _fake_info, _load_and_focus, _make_mp3


class TestSaveFlow:
    """Dirty-flag tracking, ctrl+s save, and UnsavedModal interactions."""

    def test_ctrl_s_calls_write_lyrics(self, make_app, monkeypatch, tmp_path):
        _factory, _ = make_app
        audio = _make_mp3(tmp_path / "track.mp3")
        saved_calls: list[tuple[Path, str]] = []

        monkeypatch.setattr(
            "lyrsmith.app.write_lyrics",
            lambda path, text, **_kw: saved_calls.append((path, text)),
        )
        monkeypatch.setattr("lyrsmith.app.read_info", _fake_info)
        monkeypatch.setattr("lyrsmith.app.read_lyrics", lambda _p, **_kw: _SAMPLE_LRC)

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
        monkeypatch.setattr("lyrsmith.app.read_lyrics", lambda _p, **_kw: None)
        monkeypatch.setattr("lyrsmith.app.write_lyrics", lambda *_, **__: None)

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
        monkeypatch.setattr("lyrsmith.app.read_lyrics", lambda _p, **_kw: None)
        monkeypatch.setattr("lyrsmith.app.write_lyrics", lambda *_, **__: None)

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
            lambda path, text, **_kw: saved_calls.append((path, text)),
        )
        monkeypatch.setattr("lyrsmith.app.read_info", _fake_info)
        monkeypatch.setattr("lyrsmith.app.read_lyrics", lambda _p, **_kw: None)

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
        monkeypatch.setattr("lyrsmith.app.write_lyrics", lambda *_, **__: None)
        monkeypatch.setattr(
            "lyrsmith.app.write_word_data",
            lambda path, lines: word_write_calls.append((path, lines)),
        )
        monkeypatch.setattr("lyrsmith.app.read_info", _fake_info)
        monkeypatch.setattr("lyrsmith.app.read_lyrics", lambda _p, **_kw: _SAMPLE_LRC)

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
        monkeypatch.setattr("lyrsmith.app.read_lyrics", lambda _p, **_kw: "Just plain lyrics")

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
                ed = await _load_and_focus(pilot)

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
                ed = await _load_and_focus(pilot)

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
                ed = await _load_and_focus(pilot)

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

    def test_rapid_load_plain_does_not_leave_dirty(self, make_app):
        """Two back-to-back load_plain calls must not leave the editor dirty.

        Regression for the _loading flag race: a callback from the first load
        fires after the second load has started and clears _loading prematurely,
        letting a TextArea.Changed event mark the editor dirty.
        """
        _factory, _ = make_app

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                ed = pilot.app.query_one(LyricsEditor)
                # Two loads without awaiting between them — both call_after_refresh
                # callbacks are now queued.
                ed.load_plain("first version of lyrics")
                ed.load_plain("second version of lyrics")
                # Allow all queued callbacks and events to process.
                await pilot.pause()
                await pilot.pause()
                assert not ed.is_dirty

                await pilot.press("ctrl+q")

        asyncio.run(_impl())


# ---------------------------------------------------------------------------
# Save language tracking
# ---------------------------------------------------------------------------


class TestSaveLang:
    """_lyrics_lang is set from the file tag on load and used when saving.

    Three paths:
    1. File had no USLT frame  → _lyrics_lang = "und"
    2. File had USLT lang=X    → _lyrics_lang = X  (preserved)
    3. After transcription     → _lyrics_lang = ISO 639-2 of detected lang
    """

    def _setup(self, monkeypatch, tmp_path):
        """Return (factory, mp3_path) with waveform decode and word-data patched out."""
        import numpy as np

        from tests.integration._helpers import _fake_info

        monkeypatch.setattr("lyrsmith.app.read_info", _fake_info)
        _empty_pcm = np.zeros(0, dtype=np.float32)
        monkeypatch.setattr("lyrsmith.app.decode_to_pcm", lambda _: (_empty_pcm, 22050))
        monkeypatch.setattr("lyrsmith.app.read_word_data", lambda _: {})
        return tmp_path / "track.mp3"

    def test_load_file_with_no_tag_sets_und(self, make_app, monkeypatch, tmp_path):
        """File with no USLT frame → _lyrics_lang = 'und' after load."""
        _factory, _ = make_app
        audio = _make_mp3(tmp_path / "track.mp3")
        self._setup(monkeypatch, tmp_path)
        monkeypatch.setattr("lyrsmith.app.read_lyrics", lambda _p, **_kw: None)

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                app = pilot.app
                app._do_load(audio)
                await pilot.pause()
                assert app._lyrics_lang == "und"
                await pilot.press("ctrl+q")

        asyncio.run(_impl())

    def test_load_file_with_uslt_preserves_lang(self, make_app, monkeypatch, tmp_path):
        """File with USLT lang='pol' → _lyrics_lang = 'pol' after load."""
        from mutagen.id3 import ID3, USLT

        _factory, _ = make_app
        audio = _make_mp3(tmp_path / "track.mp3")
        # Write a USLT frame with lang="pol" directly.
        tags = ID3(str(audio))
        tags.add(USLT(encoding=3, lang="pol", desc="", text=_SAMPLE_LRC))
        tags.save(str(audio))
        self._setup(monkeypatch, tmp_path)
        monkeypatch.setattr("lyrsmith.app.read_lyrics", lambda _p, **_kw: _SAMPLE_LRC)

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                app = pilot.app
                app._do_load(audio)
                await pilot.pause()
                assert app._lyrics_lang == "pol"
                await pilot.press("ctrl+q")

        asyncio.run(_impl())

    def test_save_preserves_original_lang_in_file(self, make_app, monkeypatch, tmp_path):
        """Saving after loading a 'pol' file writes USLT with lang='pol'."""
        from mutagen.id3 import ID3, USLT

        _factory, _ = make_app
        audio = _make_mp3(tmp_path / "track.mp3")
        tags = ID3(str(audio))
        tags.add(USLT(encoding=3, lang="pol", desc="", text=_SAMPLE_LRC))
        tags.save(str(audio))
        self._setup(monkeypatch, tmp_path)
        monkeypatch.setattr("lyrsmith.app.read_lyrics", lambda _p, **_kw: _SAMPLE_LRC)

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                app = pilot.app
                app._do_load(audio)
                await pilot.pause()
                ed = app.query_one(LyricsEditor)
                ed.mark_dirty()
                await pilot.press("ctrl+s")
                await pilot.pause()
                result_tags = ID3(str(audio))
                frames = [v for k, v in result_tags.items() if k.startswith("USLT")]
                assert len(frames) == 1
                assert frames[0].lang == "pol"
                await pilot.press("ctrl+q")

        asyncio.run(_impl())

    def test_save_new_file_with_no_tag_writes_und(self, make_app, monkeypatch, tmp_path):
        """Saving to a file that had no USLT frame writes lang='und'."""
        from mutagen.id3 import ID3

        _factory, _ = make_app
        audio = _make_mp3(tmp_path / "track.mp3")
        self._setup(monkeypatch, tmp_path)
        monkeypatch.setattr("lyrsmith.app.read_lyrics", lambda _p, **_kw: None)

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                app = pilot.app
                app._do_load(audio)
                await pilot.pause()
                ed = app.query_one(LyricsEditor)
                ed.load_lrc(_SAMPLE_LRC)
                ed.mark_dirty()
                await pilot.press("ctrl+s")
                await pilot.pause()
                result_tags = ID3(str(audio))
                frames = [v for k, v in result_tags.items() if k.startswith("USLT")]
                assert len(frames) == 1
                assert frames[0].lang == "und"
                await pilot.press("ctrl+q")

        asyncio.run(_impl())

    def test_transcription_lang_overrides_original_tag(self, make_app, monkeypatch, tmp_path):
        """After transcription detects 'en', save writes 'eng' even if tag was 'pol'."""
        from mutagen.id3 import ID3, USLT

        from lyrsmith.metadata.tags import _lang_to_id3

        _factory, _ = make_app
        audio = _make_mp3(tmp_path / "track.mp3")
        tags = ID3(str(audio))
        tags.add(USLT(encoding=3, lang="pol", desc="", text=_SAMPLE_LRC))
        tags.save(str(audio))
        self._setup(monkeypatch, tmp_path)
        monkeypatch.setattr("lyrsmith.app.read_lyrics", lambda _p, **_kw: _SAMPLE_LRC)

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                app = pilot.app
                app._do_load(audio)
                await pilot.pause()
                assert app._lyrics_lang == "pol"

                # Simulate transcription completing with detected language "en".
                app._lyrics_lang = _lang_to_id3("en")
                assert app._lyrics_lang == "eng"

                ed = app.query_one(LyricsEditor)
                ed.mark_dirty()
                await pilot.press("ctrl+s")
                await pilot.pause()
                result_tags = ID3(str(audio))
                frames = [v for k, v in result_tags.items() if k.startswith("USLT")]
                assert len(frames) == 1
                assert frames[0].lang == "eng"
                await pilot.press("ctrl+q")

        asyncio.run(_impl())
