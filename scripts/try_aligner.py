#!/usr/bin/env python3
"""
Proof-of-concept: forced alignment of lyrics read from an audio file's tags.

Reads USLT lyrics from the file tag, strips annotation/section-label lines
(e.g. [Zwrotka 1], [Refren]), runs Qwen3-ForcedAligner-0.6B, and prints
per-line word-level timestamps reconstructed from the flat alignment output.

NOTE — backend: Qwen3ForcedAligner uses the transformers backend only.
  There is no vLLM path for the aligner. vLLM exists only for the
  Qwen3-ASR transcription model (Qwen3ASRModel.LLM()).

NOTE — audio loading: audio is decoded via PyAV (same as lyrsmith) at 16 kHz
  and passed as a numpy array, bypassing qwen-asr's librosa-based MP3 loader.

Usage:
    uv run --with "qwen-asr" --with torch scripts/try_aligner.py FILE.mp3
    uv run --with "qwen-asr" --with torch scripts/try_aligner.py FILE.mp3 \\
        --start-sec 30 --end-sec 90          # align only this window
    uv run --with "qwen-asr" --with torch scripts/try_aligner.py FILE.mp3 \\
        --debug                              # print raw timestamp stats

    # device is auto-detected (cuda:0 if available, else cpu); override:
    uv run --with "qwen-asr" --with torch scripts/try_aligner.py FILE.mp3 \\
        --device cpu

Requirements (not in pyproject.toml):
    uv run --with "qwen-asr" --with torch ...
    # optional for speed on GPU:
    uv run --with "qwen-asr" --with torch --with flash-attn ...
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import av
import numpy as np

# Allow running directly from repo root without installing the package
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from lyrsmith.metadata.tags import read_lyrics  # noqa: E402

# ---------------------------------------------------------------------------
# Audio decode
# ---------------------------------------------------------------------------

_ALIGNER_SR = 16_000


def _decode_audio_16k(
    path: Path,
    start_sec: float = 0.0,
    end_sec: float | None = None,
) -> np.ndarray:
    """Decode audio to mono float32 at 16 kHz via PyAV, trimmed to the window."""
    container = av.open(str(path))
    try:
        stream = next(s for s in container.streams if s.type == "audio")
        resampler = av.AudioResampler(format="fltp", layout="mono", rate=_ALIGNER_SR)
        frames: list[np.ndarray] = []
        for packet in container.demux(stream):
            for raw in packet.decode():
                for rs in resampler.resample(raw):  # type: ignore[arg-type]
                    frames.append(rs.to_ndarray()[0].copy())
        for rs in resampler.resample(None):
            frames.append(rs.to_ndarray()[0].copy())
    finally:
        container.close()

    if not frames:
        return np.zeros(0, dtype=np.float32)

    pcm = np.concatenate(frames).astype(np.float32)

    # Trim to requested window
    start_s = int(start_sec * _ALIGNER_SR)
    end_s = int(end_sec * _ALIGNER_SR) if end_sec is not None else len(pcm)
    pcm = pcm[start_s:end_s]

    # Normalise to [-1, 1]
    peak = float(np.max(np.abs(pcm)))
    if peak > 0:
        pcm /= peak

    return pcm


# ---------------------------------------------------------------------------
# Lyrics pre-processing
# ---------------------------------------------------------------------------

_ANNOTATION_RE = re.compile(r"\[[^\]]*\]|\([^)]*\)")


def _is_annotation_line(line: str) -> bool:
    """True if the line is a section label or has no speakable content."""
    cleaned = _ANNOTATION_RE.sub("", line)
    return not any(ch.isalpha() or ch.isdigit() for ch in cleaned)


def _build_word_stream(lines: list[str]) -> tuple[list[str], list[int | None]]:
    """Split lyric lines into a flat word list.

    Returns
    -------
    words
        Flat list of every word passed to the aligner.
    words_per_line
        Parallel to *lines*. ``None`` for annotation/blank lines,
        word count (≥ 0) for lyric lines.
    """
    words: list[str] = []
    words_per_line: list[int | None] = []
    for line in lines:
        if _is_annotation_line(line):
            words_per_line.append(None)
        else:
            lw = line.split()
            words.extend(lw)
            words_per_line.append(len(lw))
    return words, words_per_line


def _redistribute(aligned_items, lines: list[str], words_per_line: list[int | None]) -> list[dict]:
    result = []
    pos = 0
    for line, count in zip(lines, words_per_line):
        if count is None:
            result.append({"line": line, "annotation": True, "words": []})
        else:
            result.append(
                {
                    "line": line,
                    "annotation": False,
                    "words": list(aligned_items[pos : pos + count]),
                }
            )
            pos += count
    return result


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def _fmt(seconds: float) -> str:
    total_cs = round(seconds * 100)
    cs = total_cs % 100
    total_s = total_cs // 100
    s = total_s % 60
    m = total_s // 60
    return f"{m:02d}:{s:02d}.{cs:02d}"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Forced-align lyrics from an audio file's tags using Qwen3-ForcedAligner"
    )
    parser.add_argument("audio", help="Path to audio file (must have USLT lyrics tag)")
    parser.add_argument(
        "--language",
        default="Polish",
        help="Language hint for the aligner tokeniser (default: Polish)",
    )
    parser.add_argument("--device", default=None, help="Torch device (auto: cuda:0 or cpu)")
    parser.add_argument("--model", default="Qwen/Qwen3-ForcedAligner-0.6B")
    parser.add_argument(
        "--start-sec",
        type=float,
        default=0.0,
        help="Start of audio window in seconds (default: 0)",
    )
    parser.add_argument(
        "--end-sec",
        type=float,
        default=None,
        help="End of audio window in seconds (default: full file)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Print raw timestamp statistics before fix_timestamp smoothing",
    )
    args = parser.parse_args()

    audio_path = Path(args.audio)
    if not audio_path.exists():
        print(f"error: file not found: {audio_path}", file=sys.stderr)
        sys.exit(1)

    # -------------------------------------------------------------- decode audio
    print(f"Decoding audio via PyAV at {_ALIGNER_SR} Hz ...")
    pcm = _decode_audio_16k(audio_path, start_sec=args.start_sec, end_sec=args.end_sec)
    if len(pcm) == 0:
        print("error: audio decode produced empty array", file=sys.stderr)
        sys.exit(1)

    duration_sec = len(pcm) / _ALIGNER_SR
    if args.start_sec > 0 or args.end_sec is not None:
        window_desc = (
            f"{args.start_sec:.1f}s – {args.start_sec + duration_sec:.1f}s ({duration_sec:.1f}s)"
        )
    else:
        window_desc = f"{duration_sec:.1f}s"
    print(f"Audio        : {window_desc}  ({len(pcm):,} samples)")

    if duration_sec > 180:
        print(
            f"  ⚠  {duration_sec:.0f}s exceeds the aligner's recommended ≤ 180s limit.\n"
            "     Use --start-sec / --end-sec to trim to the sung portion."
        )

    # --------------------------------------------------------------- lyrics
    raw = read_lyrics(audio_path)
    if not raw:
        print("error: no lyrics found in file tags", file=sys.stderr)
        sys.exit(1)

    lines = raw.splitlines()
    words, words_per_line = _build_word_stream(lines)

    if not words:
        print("error: no words left after annotation filtering", file=sys.stderr)
        sys.exit(1)

    n_lyric = sum(1 for c in words_per_line if c is not None)
    n_annot = sum(1 for c in words_per_line if c is None)
    print(f"Lines        : {len(lines)} total  ({n_lyric} lyric, {n_annot} annotation/blank)")
    print(f"Word stream  : {len(words)} words")
    print(f"Language     : {args.language}")
    print()

    joined_text = " ".join(words)

    # --------------------------------------------------------------- model load
    import torch  # noqa: PLC0415
    from qwen_asr import Qwen3ForcedAligner  # noqa: PLC0415

    device = args.device or ("cuda:0" if torch.cuda.is_available() else "cpu")
    dtype = torch.bfloat16 if "cuda" in device else torch.float32

    print(f"Loading {args.model} on {device} ({dtype}) ...")
    aligner = Qwen3ForcedAligner.from_pretrained(
        args.model,
        dtype=dtype,
        device_map=device,
    )
    print("Model loaded.\n")

    # ---------------------------------------------------------- debug hook
    _raw_ts: list[float] = []
    if args.debug:
        _orig_parse = aligner.aligner_processor.parse_timestamp

        def _patched_parse(word_list, timestamp):
            arr = timestamp.tolist() if hasattr(timestamp, "tolist") else list(timestamp)
            _raw_ts.extend(arr)
            return _orig_parse(word_list, timestamp)

        aligner.aligner_processor.parse_timestamp = _patched_parse

    # --------------------------------------------------------------- align
    print("Aligning ...")
    results = aligner.align(
        audio=(pcm, _ALIGNER_SR),  # pre-decoded numpy array — bypasses librosa
        text=joined_text,
        language=args.language,
    )
    aligned = results[0]

    if args.debug and _raw_ts:
        ts_arr = np.array(_raw_ts)
        print("\n--- raw timestamps (ms, before fix_timestamp smoothing) ---")
        print(f"  count  : {len(ts_arr)}")
        print(f"  min    : {ts_arr.min():.1f} ms")
        print(f"  max    : {ts_arr.max():.1f} ms")
        print(f"  mean   : {ts_arr.mean():.1f} ms")
        print(f"  zeros  : {int((ts_arr == 0).sum())} / {len(ts_arr)}")
        print(f"  unique : {len(np.unique(ts_arr))}")
        print()

    if len(aligned) != len(words):
        print(
            f"WARNING: aligner returned {len(aligned)} items for {len(words)} words "
            f"— count mismatch, per-line mapping may be off.\n"
        )

    # --------------------------------------------------- redistribute & print
    per_line = _redistribute(aligned, lines, words_per_line)
    offset = args.start_sec  # add back the window offset to reported timestamps

    print("=== Alignment results ===\n")
    for entry in per_line:
        line_text = entry["line"]
        if entry["annotation"]:
            print(f"  {line_text}" if line_text.strip() else "")
        elif not entry["words"]:
            print(f"[??:??.??] {line_text}")
        else:
            first = entry["words"][0]
            ts = _fmt(first.start_time + offset)
            word_detail = "  ".join(
                f"{w.text}({_fmt(w.start_time + offset)}-{_fmt(w.end_time + offset)})"
                for w in entry["words"]
            )
            print(f"[{ts}] {line_text}")
            print(f"         {word_detail}")


if __name__ == "__main__":
    main()
