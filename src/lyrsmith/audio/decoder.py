"""Decode audio file to mono float32 PCM via PyAV. One-shot, for waveform use."""

from __future__ import annotations

from pathlib import Path

import av
import av.audio
import numpy as np

# Target sample rate for waveform display. 22050 Hz is more than enough
# resolution for a visual waveform and avoids huge arrays for hi-res files.
WAVEFORM_SAMPLE_RATE = 22050


def decode_to_pcm(path: Path) -> tuple[np.ndarray, int]:
    """
    Decode audio file to mono float32 PCM downsampled to WAVEFORM_SAMPLE_RATE.
    Returns (samples, WAVEFORM_SAMPLE_RATE). samples is a 1-D float32 ndarray.
    Returns an empty array on unreadable or non-audio files rather than raising.
    """
    _empty = np.zeros(0, dtype=np.float32)
    try:
        container = av.open(str(path))
    except Exception:
        return _empty, WAVEFORM_SAMPLE_RATE

    try:
        audio_stream = next((s for s in container.streams if s.type == "audio"), None)
        if audio_stream is None:
            return _empty, WAVEFORM_SAMPLE_RATE

        resampler = av.AudioResampler(
            format="fltp",
            layout="mono",
            rate=WAVEFORM_SAMPLE_RATE,
        )

        frames: list[np.ndarray] = []

        for packet in container.demux(audio_stream):
            for raw_frame in packet.decode():
                frame = raw_frame  # type: ignore[assignment]
                for resampled in resampler.resample(frame):  # type: ignore[arg-type]
                    arr = resampled.to_ndarray()  # shape (1, n) for mono fltp
                    frames.append(arr[0].copy())

        for resampled in resampler.resample(None):
            arr = resampled.to_ndarray()
            frames.append(arr[0].copy())

    finally:
        container.close()

    if not frames:
        return _empty, WAVEFORM_SAMPLE_RATE

    return np.concatenate(frames).astype(np.float32), WAVEFORM_SAMPLE_RATE
