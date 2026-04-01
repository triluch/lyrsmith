"""Waveform pane: play/pause, seek, zoom, and volume controls."""

from __future__ import annotations

import asyncio

import pytest

from lyrsmith.ui.waveform_pane import VOL_MAX, ZOOM_MIN, WaveformPane

from ._helpers import _SAMPLE_LRC, _fake_info, _make_mp3


class TestWaveformPane:
    """Key handling on the waveform pane: play/pause, seek, zoom."""

    async def _focus_waveform(self, pilot):
        await pilot.press("tab")  # browser → waveform
        await pilot.pause()

    def test_space_toggles_play_pause(self, make_app):
        _factory, _ = make_app

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                await self._focus_waveform(pilot)
                player = pilot.app._player
                assert not player.is_playing
                await pilot.press("space")
                await pilot.pause()
                assert player.is_playing
                await pilot.press("space")
                await pilot.pause()
                assert not player.is_playing
                await pilot.press("ctrl+q")

        asyncio.run(_impl())

    def test_right_arrow_seeks_forward(self, make_app):
        _factory, _ = make_app

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                await self._focus_waveform(pilot)
                player = pilot.app._player
                assert player.position == pytest.approx(0.0)
                await pilot.press("right")  # +5 s
                await pilot.pause()
                assert player.position == pytest.approx(5.0)

        asyncio.run(_impl())

    def test_left_arrow_seeks_backward(self, make_app):
        _factory, _ = make_app

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                await self._focus_waveform(pilot)
                wf = pilot.app.query_one(WaveformPane)
                wf._position = 20.0
                await pilot.press("left")  # −5 s → 15.0
                await pilot.pause()
                assert pilot.app._player.position == pytest.approx(15.0)

        asyncio.run(_impl())

    def test_shift_right_seeks_large_forward(self, make_app):
        _factory, _ = make_app

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                await self._focus_waveform(pilot)
                await pilot.press("shift+right")  # +30 s
                await pilot.pause()
                assert pilot.app._player.position == pytest.approx(30.0)

        asyncio.run(_impl())

    def test_plus_zooms_in(self, make_app):
        _factory, _ = make_app

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                await self._focus_waveform(pilot)
                wf = pilot.app.query_one(WaveformPane)
                initial_zoom = wf.zoom
                await pilot.press("plus")
                await pilot.pause()
                assert wf.zoom < initial_zoom
                await pilot.press("ctrl+q")

        asyncio.run(_impl())

    def test_minus_zooms_out(self, make_app):
        _factory, _ = make_app

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                await self._focus_waveform(pilot)
                wf = pilot.app.query_one(WaveformPane)
                initial_zoom = wf.zoom
                await pilot.press("minus")
                await pilot.pause()
                assert wf.zoom > initial_zoom

        asyncio.run(_impl())

    def test_zoom_clamped_at_minimum(self, make_app):
        _factory, _ = make_app

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                await self._focus_waveform(pilot)
                wf = pilot.app.query_one(WaveformPane)
                for _ in range(50):
                    await pilot.press("plus")
                await pilot.pause()
                assert wf.zoom == pytest.approx(ZOOM_MIN)

        asyncio.run(_impl())

    def test_up_increases_volume(self, make_app):
        _factory, _ = make_app

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                await self._focus_waveform(pilot)
                wf = pilot.app.query_one(WaveformPane)
                wf.set_volume(50.0)
                await pilot.press("up")
                await pilot.pause()
                assert wf.volume > 50.0

        asyncio.run(_impl())

    def test_down_decreases_volume(self, make_app):
        _factory, _ = make_app

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                await self._focus_waveform(pilot)
                wf = pilot.app.query_one(WaveformPane)
                wf.set_volume(50.0)
                await pilot.press("down")
                await pilot.pause()
                assert wf.volume < 50.0

        asyncio.run(_impl())

    def test_volume_clamped_at_zero(self, make_app):
        _factory, _ = make_app

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                await self._focus_waveform(pilot)
                wf = pilot.app.query_one(WaveformPane)
                for _ in range(30):
                    await pilot.press("down")
                await pilot.pause()
                assert wf.volume == pytest.approx(0.0)

        asyncio.run(_impl())

    def test_volume_clamped_at_max(self, make_app):
        _factory, _ = make_app

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                await self._focus_waveform(pilot)
                wf = pilot.app.query_one(WaveformPane)
                for _ in range(30):
                    await pilot.press("up")
                await pilot.pause()
                assert wf.volume == pytest.approx(VOL_MAX)

        asyncio.run(_impl())

    def test_volume_change_saved_to_config(self, make_app):
        _factory, _ = make_app

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                await self._focus_waveform(pilot)
                wf = pilot.app.query_one(WaveformPane)
                wf.set_volume(40.0)
                await pilot.press("up")  # → 45%
                await pilot.pause()
                assert pilot.app._config.volume == pytest.approx(45.0)


class TestWaveformTimestampSync:
    """Waveform LRC timestamp markers are populated when a file is loaded."""

    def test_lrc_timestamps_populated_after_file_load(self, make_app, monkeypatch):
        """Loading an LRC file sets waveform timestamp markers for all lines."""
        _factory, tmp_path = make_app
        _make_mp3(tmp_path / "song.mp3")
        monkeypatch.setattr("lyrsmith.app.read_info", _fake_info)
        monkeypatch.setattr("lyrsmith.app.read_lyrics", lambda _p: _SAMPLE_LRC)

        async def _impl():
            async with _factory(path=tmp_path).run_test(headless=True) as pilot:
                await pilot.pause()
                # Entry order: ".." (0), song.mp3 (1). Two downs to reach the file.
                await pilot.press("down")
                await pilot.pause()
                await pilot.press("down")
                await pilot.pause()
                await pilot.press("enter")
                await pilot.pause()

                wf = pilot.app.query_one(WaveformPane)
                assert wf._lrc_timestamps == pytest.approx([1.0, 3.0, 5.0, 7.0, 9.0])

        asyncio.run(_impl())

        asyncio.run(_impl())
