"""Tests for audio/decoder.py — decode_to_pcm."""

import math
import struct
import wave
from pathlib import Path

import numpy as np
import pytest

from lyrsmith.audio.decoder import WAVEFORM_SAMPLE_RATE, decode_to_pcm

_SR = 44100  # source sample rate used to create test WAVs


def _make_wav(path: Path, sample_rate: int = _SR, duration: float = 0.1) -> Path:
    """Write a minimal mono 16-bit WAV with a 440 Hz sine wave."""
    n = int(sample_rate * duration)
    frames = struct.pack(
        f"{n}h",
        *(int(32767 * math.sin(2 * math.pi * 440 * i / sample_rate)) for i in range(n)),
    )
    with wave.open(str(path), "w") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(sample_rate)
        f.writeframes(frames)
    return path


@pytest.fixture
def wav_file(tmp_path) -> Path:
    return _make_wav(tmp_path / "test.wav")


class TestDecodeToPcm:
    def test_returns_float32_array(self, wav_file):
        pcm, sr = decode_to_pcm(wav_file)
        assert pcm.dtype == np.float32

    def test_returns_waveform_sample_rate(self, wav_file):
        # Decoder always downsamples to WAVEFORM_SAMPLE_RATE regardless of source.
        _, sr = decode_to_pcm(wav_file)
        assert sr == WAVEFORM_SAMPLE_RATE

    def test_output_is_1d(self, wav_file):
        pcm, _ = decode_to_pcm(wav_file)
        assert pcm.ndim == 1

    def test_approximate_sample_count(self, wav_file):
        # 0.1 s at 44100 Hz → ~4410 samples; allow small rounding tolerance
        pcm, sr = decode_to_pcm(wav_file)
        expected = int(sr * 0.1)
        assert abs(len(pcm) - expected) <= 10

    def test_amplitude_within_range(self, wav_file):
        pcm, _ = decode_to_pcm(wav_file)
        assert np.max(np.abs(pcm)) <= 1.0 + 1e-5

    def test_non_silent(self, wav_file):
        pcm, _ = decode_to_pcm(wav_file)
        assert np.max(np.abs(pcm)) > 0.5

    def test_downsamples_high_rate_source(self, tmp_path):
        # 48000 Hz source → must be downsampled to WAVEFORM_SAMPLE_RATE
        wav = _make_wav(tmp_path / "48k.wav", sample_rate=48000, duration=0.2)
        pcm, sr = decode_to_pcm(wav)
        assert sr == WAVEFORM_SAMPLE_RATE
        # Sample count should reflect the TARGET rate, not the source rate
        expected = int(WAVEFORM_SAMPLE_RATE * 0.2)
        assert abs(len(pcm) - expected) <= 10

    def test_empty_file_returns_empty_array(self, tmp_path):
        # Minimal valid ID3 header (no audio) — av finds no audio stream
        bad = tmp_path / "bad.wav"
        bad.write_bytes(b"ID3\x03\x00\x00\x00\x00\x00\x00")
        pcm, _ = decode_to_pcm(bad)
        assert len(pcm) == 0
