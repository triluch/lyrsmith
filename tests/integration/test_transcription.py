"""Transcription worker: no-file guard, stub run, language detection, E2E."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from lyrsmith.config import Config
from lyrsmith.lrc import LRCLine
from lyrsmith.ui.lyrics_editor import LyricsEditor
from lyrsmith.ui.top_bar import TopBar

from ._helpers import _fake_info, _make_mp3


class TestTranscription:
    """Ctrl+T triggers transcription worker; result populates the LRC editor.

    Transcription output in production is non-deterministic.  All tests here
    use a deterministic stub so assertions are stable across runs.
    """

    def test_transcribe_with_no_file_loaded_is_noop(self, make_app):
        _factory, _ = make_app

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                app = pilot.app
                assert app._loaded_path is None
                ed = app.query_one(LyricsEditor)
                assert ed.mode == "empty"
                app.action_transcribe()
                await pilot.pause()
                assert ed.mode == "empty"

        asyncio.run(_impl())

    def test_transcribe_populates_lrc_editor(self, make_app, monkeypatch, tmp_path):
        from lyrsmith.lrc import parse
        from lyrsmith.transcribe.whisper import transcriber as _tr

        _factory, _ = make_app
        audio = _make_mp3(tmp_path / "vocal.mp3")

        stub_lines = [
            LRCLine(1.0, "Hello world"),
            LRCLine(3.5, "Goodbye world"),
            LRCLine(6.0, "See you later"),
        ]
        monkeypatch.setattr(_tr, "transcribe", lambda *a, **kw: stub_lines)
        monkeypatch.setattr(_tr, "load_model", lambda *a, **kw: None)

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                app = pilot.app
                app._loaded_path = audio
                ed = app.query_one(LyricsEditor)
                await pilot.pause()
                app.action_transcribe()
                await pilot.app.workers.wait_for_complete()
                await pilot.pause()
                assert ed.mode == "lrc"
                assert len(ed._lines) == 3
                assert ed.is_dirty
                _, parsed = parse(ed.current_text())
                assert [l.text for l in parsed] == [
                    "Hello world",
                    "Goodbye world",
                    "See you later",
                ]
                ed.clear_dirty()
                await pilot.press("ctrl+q")

        asyncio.run(_impl())

    def test_auto_language_updates_top_bar_after_transcription(
        self, make_app, monkeypatch, tmp_path
    ):
        from lyrsmith.transcribe.whisper import transcriber as _tr

        _factory, _ = make_app
        audio = _make_mp3(tmp_path / "vocal.mp3")
        stub_lines = [LRCLine(1.0, "Hello")]

        def _stub_transcribe(*a, **kw):
            cb = kw.get("on_language_detected")
            if cb:
                cb("en")
            return stub_lines

        monkeypatch.setattr(_tr, "transcribe", _stub_transcribe)
        monkeypatch.setattr(_tr, "load_model", lambda *a, **kw: None)

        async def _impl():
            async with _factory(config=Config(whisper_language="auto")).run_test(
                headless=True
            ) as pilot:
                app = pilot.app
                app._loaded_path = audio
                await pilot.pause()
                app.action_transcribe()
                await pilot.app.workers.wait_for_complete()
                await pilot.pause()
                assert app.query_one(TopBar).language == "auto (en)"
                await pilot.press("ctrl+q")

        asyncio.run(_impl())

    def test_explicit_language_does_not_change_top_bar_label(
        self, make_app, monkeypatch, tmp_path
    ):
        from lyrsmith.transcribe.whisper import transcriber as _tr

        _factory, _ = make_app
        audio = _make_mp3(tmp_path / "vocal.mp3")
        stub_lines = [LRCLine(1.0, "Witaj")]

        def _stub_transcribe(*a, **kw):
            cb = kw.get("on_language_detected")
            if cb:
                cb("pl")
            return stub_lines

        monkeypatch.setattr(_tr, "transcribe", _stub_transcribe)
        monkeypatch.setattr(_tr, "load_model", lambda *a, **kw: None)

        async def _impl():
            async with _factory(config=Config(whisper_language="pl")).run_test(
                headless=True
            ) as pilot:
                app = pilot.app
                app._loaded_path = audio
                await pilot.pause()
                app.action_transcribe()
                await pilot.app.workers.wait_for_complete()
                await pilot.pause()
                assert app.query_one(TopBar).language == "pl"
                await pilot.press("ctrl+q")

        asyncio.run(_impl())

    def test_loading_new_file_resets_detected_language(self, make_app, monkeypatch, tmp_path):
        from lyrsmith.transcribe.whisper import transcriber as _tr

        _factory, _ = make_app
        audio1 = _make_mp3(tmp_path / "first.mp3")
        audio2 = _make_mp3(tmp_path / "second.mp3")
        stub_lines = [LRCLine(1.0, "Hello")]

        def _stub_transcribe(*a, **kw):
            cb = kw.get("on_language_detected")
            if cb:
                cb("en")
            return stub_lines

        monkeypatch.setattr(_tr, "transcribe", _stub_transcribe)
        monkeypatch.setattr(_tr, "load_model", lambda *a, **kw: None)
        monkeypatch.setattr("lyrsmith.app.read_info", _fake_info)
        monkeypatch.setattr("lyrsmith.app.read_lyrics", lambda _p: None)

        async def _impl():
            async with _factory(config=Config(whisper_language="auto")).run_test(
                headless=True
            ) as pilot:
                app = pilot.app
                app._loaded_path = audio1
                await pilot.pause()
                app.action_transcribe()
                await pilot.app.workers.wait_for_complete()
                await pilot.pause()
                assert app.query_one(TopBar).language == "auto (en)"

                app._do_load(audio2)
                await pilot.pause()
                assert app.query_one(TopBar).language == "auto"
                await pilot.press("ctrl+q")

        asyncio.run(_impl())


# ---------------------------------------------------------------------------
# E2E — real model, real audio (marked slow)
# ---------------------------------------------------------------------------

_E2E_FIXTURE = Path(__file__).parent.parent / "fixtures" / "tts_sample.flac"


@pytest.mark.slow
class TestE2EPilotTranscription:
    """Full load → waveform → transcription path through Pilot with real I/O."""

    def test_load_generates_waveform_and_transcription_populates_lrc(self, make_app_real_decode):
        from lyrsmith.ui.waveform_pane import WaveformPane

        _factory, _ = make_app_real_decode

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                app = pilot.app
                wf = app.query_one(WaveformPane)
                ed = app.query_one(LyricsEditor)

                app._do_load(_E2E_FIXTURE)
                await pilot.app.workers.wait_for_complete()
                await pilot.pause()

                assert wf._pcm is not None
                assert len(wf._pcm) > 0
                assert wf._sample_rate > 0

                app.action_transcribe()
                await pilot.app.workers.wait_for_complete()
                await pilot.pause()

                assert ed.mode == "lrc"
                assert len(ed._lines) >= 1
                assert ed.is_dirty

                total_words = sum(len(line.words) for line in ed._lines)
                assert total_words > 0

                ts = [line.timestamp for line in ed._lines]
                assert ts == sorted(ts)

                assert all(line.end is not None for line in ed._lines)

                await pilot.press("ctrl+q")

        asyncio.run(_impl())
