"""Tests for audio/waveform.py — pure computation."""

import numpy as np
import pytest

from lyrsmith.audio.waveform import (
    PLAYHEAD_RESET,
    PLAYHEAD_THRESHOLD,
    compute_view_start,
    render,
)

_HALFBLOCK_CHARS = set("▀▄█")


def _sine(duration=10.0, sr=44100) -> tuple[np.ndarray, int]:
    t = np.linspace(0, duration, int(duration * sr), endpoint=False)
    return (np.sin(2 * np.pi * 440 * t) * 0.8).astype(np.float32), sr


# ---------------------------------------------------------------------------
# compute_view_start
# ---------------------------------------------------------------------------


class TestComputeViewStart:
    def test_no_change_within_threshold(self):
        result = compute_view_start(0.0, position=5.0, zoom=30.0)
        assert result == pytest.approx(0.0)

    def test_pages_at_threshold(self):
        zoom = 30.0
        position = zoom * PLAYHEAD_THRESHOLD
        result = compute_view_start(0.0, position, zoom)
        expected = position - PLAYHEAD_RESET * zoom
        assert result == pytest.approx(expected)

    def test_resets_when_position_behind_view(self):
        # position < view_start → relative < 0 → must page
        result = compute_view_start(current_view_start=20.0, position=5.0, zoom=30.0)
        assert result != pytest.approx(20.0)

    def test_zero_zoom_returns_unchanged(self):
        result = compute_view_start(5.0, position=5.0, zoom=0.0)
        assert result == pytest.approx(5.0)

    def test_position_just_below_threshold_unchanged(self):
        zoom = 30.0
        position = zoom * (PLAYHEAD_THRESHOLD - 0.01)
        result = compute_view_start(0.0, position, zoom)
        assert result == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# render
# ---------------------------------------------------------------------------


class TestRender:
    def test_line_count(self):
        pcm, sr = _sine()
        result = render(
            pcm, sr, position=2.0, view_start=0.0, zoom=10.0, width=12, height=5
        )
        assert str(result).count("\n") == 4  # 5 lines → 4 newlines

    def test_line_width(self):
        pcm, sr = _sine()
        result = render(
            pcm, sr, position=2.0, view_start=0.0, zoom=10.0, width=12, height=5
        )
        for line in str(result).split("\n"):
            assert len(line) == 12, f"Expected width 12, got {len(line)!r}"

    def test_playhead_row_contains_arrow(self):
        pcm, sr = _sine()
        result = render(
            pcm, sr, position=0.1, view_start=0.0, zoom=10.0, width=10, height=8
        )
        assert "▶" in str(result)

    def test_playhead_full_width(self):
        pcm, sr = _sine()
        width = 10
        result = render(
            pcm, sr, position=0.1, view_start=0.0, zoom=10.0, width=width, height=8
        )
        for line in str(result).split("\n"):
            if line.startswith("▶"):
                assert len(line) == width
                break
        else:
            pytest.fail("No playhead line found")

    def test_halfblock_chars_present(self):
        pcm, sr = _sine()
        result = render(
            pcm, sr, position=5.0, view_start=0.0, zoom=10.0, width=8, height=10
        )
        text = str(result)
        assert any(c in text for c in _HALFBLOCK_CHARS), (
            "No halfblock chars in waveform"
        )

    def test_empty_pcm(self):
        pcm = np.zeros(0, dtype=np.float32)
        result = render(
            pcm, 44100, position=0.0, view_start=0.0, zoom=10.0, width=8, height=4
        )
        lines = str(result).split("\n")
        assert len(lines) == 4
        for line in lines:
            assert len(line) == 8

    def test_silent_pcm(self):
        # All-zero PCM should not crash
        pcm = np.zeros(44100 * 5, dtype=np.float32)
        result = render(
            pcm, 44100, position=1.0, view_start=0.0, zoom=5.0, width=8, height=4
        )
        assert str(result).count("\n") == 3

    def test_single_row(self):
        pcm, sr = _sine()
        result = render(
            pcm, sr, position=1.0, view_start=0.0, zoom=5.0, width=6, height=1
        )
        lines = str(result).split("\n")
        assert len(lines) == 1
        assert len(lines[0]) == 6

    def test_view_outside_audio_does_not_crash(self):
        pcm, sr = _sine(duration=5.0)
        # View starts well past the end of the audio
        result = render(
            pcm, sr, position=100.0, view_start=90.0, zoom=10.0, width=8, height=4
        )
        assert str(result).count("\n") == 3

    def test_upper_halfblock_char_present(self):
        """▀ appears when the top virtual slice of a row has amplitude but the bottom is silent."""
        # Setup: sr=100, zoom=1s, height=3, width=10.
        # vrows=6, secs_per_vrow=1/6. Playhead at row 1 (position=0.5).
        # Row 0: vrow-0 [samples 0..15] gets amplitude, vrow-1 [16..32] stays silent → top only → ▀
        sr = 100
        pcm = np.zeros(sr, dtype=np.float32)
        pcm[0:16] = 1.0
        result = render(
            pcm, sr, position=0.5, view_start=0.0, zoom=1.0, width=10, height=3
        )
        assert "▀" in result.plain

    def test_lower_halfblock_char_present(self):
        """▄ appears when the bottom virtual slice of a row has amplitude but the top is silent."""
        # Row 2: vrow-4 [samples 66..82] stays silent, vrow-5 [83..99] gets amplitude → bottom only → ▄
        sr = 100
        pcm = np.zeros(sr, dtype=np.float32)
        pcm[83:100] = 1.0
        result = render(
            pcm, sr, position=0.5, view_start=0.0, zoom=1.0, width=10, height=3
        )
        assert "▄" in result.plain
