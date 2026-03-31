"""Load→save→reload round-trips for word timing data."""

from __future__ import annotations

import asyncio

import pytest

from lyrsmith.lrc import LRCLine, WordTiming
from lyrsmith.metadata.tags import write_word_data
from lyrsmith.ui.lyrics_editor import LyricsEditor

from ._helpers import _SAMPLE_LRC, _fake_info, _make_mp3


class TestWordDataPersistence:
    """Load→save→reload round-trips for word timing data."""

    def _prep_file(self, tmp_path, monkeypatch, *, word_lines):
        audio = _make_mp3(tmp_path / "track.mp3")
        write_word_data(audio, word_lines)
        monkeypatch.setattr("lyrsmith.app.read_info", _fake_info)
        return audio

    def test_word_data_attached_on_load(self, make_app, monkeypatch, tmp_path):
        _factory, _ = make_app
        w = WordTiming(" First", 1.0, 1.3)
        audio = self._prep_file(
            tmp_path,
            monkeypatch,
            word_lines=[LRCLine(1.0, "First line", end=3.0, words=[w])],
        )
        monkeypatch.setattr("lyrsmith.app.read_lyrics", lambda _p: _SAMPLE_LRC)

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                app = pilot.app
                app._do_load(audio)
                await pilot.pause()
                ed = app.query_one(LyricsEditor)
                assert ed.mode == "lrc"
                line_1 = next(l for l in ed._lines if abs(l.timestamp - 1.0) < 0.01)
                assert len(line_1.words) == 1
                assert line_1.words[0].word == " First"
                assert line_1.end == pytest.approx(3.0)
                ed.clear_dirty()
                await pilot.press("ctrl+q")

        asyncio.run(_impl())

    def test_word_data_survives_save_then_reload(self, make_app, monkeypatch, tmp_path):
        _factory, _ = make_app
        w = WordTiming(" First", 1.0, 1.3)
        audio = self._prep_file(
            tmp_path,
            monkeypatch,
            word_lines=[LRCLine(1.0, "First line", end=3.0, words=[w])],
        )
        monkeypatch.setattr("lyrsmith.app.read_lyrics", lambda _p: _SAMPLE_LRC)

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                app = pilot.app
                app._do_load(audio)
                await pilot.pause()
                ed = app.query_one(LyricsEditor)
                assert ed._lines[0].words

                ed.mark_dirty()
                await pilot.press("ctrl+s")
                await pilot.pause()

                app.action_discard_reload()
                await pilot.pause()

                line_1 = next(l for l in ed._lines if abs(l.timestamp - 1.0) < 0.01)
                assert line_1.words[0].word == " First"
                assert line_1.end == pytest.approx(3.0)
                await pilot.press("ctrl+q")

        asyncio.run(_impl())

    def test_discard_reload_reattaches_word_data(self, make_app, monkeypatch, tmp_path):
        _factory, _ = make_app
        w = WordTiming(" Second", 3.0, 3.4)
        audio = self._prep_file(
            tmp_path,
            monkeypatch,
            word_lines=[LRCLine(3.0, "Second line", end=5.0, words=[w])],
        )
        monkeypatch.setattr("lyrsmith.app.read_lyrics", lambda _p: _SAMPLE_LRC)

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                app = pilot.app
                app._do_load(audio)
                await pilot.pause()
                ed = app.query_one(LyricsEditor)

                line_3 = next(l for l in ed._lines if abs(l.timestamp - 3.0) < 0.01)
                assert line_3.words[0].word == " Second"

                for l in ed._lines:
                    l.words = []
                    l.end = None

                app.action_discard_reload()
                await pilot.pause()

                line_3_after = next(l for l in ed._lines if abs(l.timestamp - 3.0) < 0.01)
                assert line_3_after.words[0].word == " Second"
                assert line_3_after.end == pytest.approx(5.0)
                await pilot.press("ctrl+q")

        asyncio.run(_impl())
