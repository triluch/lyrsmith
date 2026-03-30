"""
faster-whisper wrapper.

Transcription runs synchronously — callers should run it in a thread executor
to avoid blocking the event loop. The transcriber is a singleton that holds
the loaded model and re-loads only when model/device changes.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import ctranslate2
from faster_whisper import WhisperModel

from ..lrc import LRCLine, WordTiming
from .splitter import best_split_index

# Silence noisy loggers from HuggingFace / ctranslate2 that would
# otherwise leak through to the terminal and corrupt the TUI.
for _noisy in ("transformers", "huggingface_hub", "ctranslate2", "faster_whisper"):
    logging.getLogger(_noisy).setLevel(logging.ERROR)

# Models available for selection in the UI (faster-whisper names)
AVAILABLE_MODELS = [
    "tiny",
    "base",
    "small",
    "medium",
    "large-v3",
    "large-v3-turbo",
]


# ---------------------------------------------------------------------------
# Segment post-processing
# ---------------------------------------------------------------------------


@dataclass
class _SegmentLike:
    """Minimal segment shape used internally by the split post-processor.

    Mirrors the fields we consume from faster-whisper Segment objects so
    that split sub-segments can flow through the same LRCLine-building code
    as real Whisper segments.
    """

    start: float
    end: float
    text: str
    words: list = field(default_factory=list)  # faster-whisper Word objects


def _split_segment(seg: _SegmentLike, max_words: int, lang: str = "") -> list[_SegmentLike]:
    """Recursively split *seg* at the most natural phrase boundary.

    Returns a list of one or more sub-segments each containing at most
    *max_words* words.  When *max_words* is 0, or the segment is already
    within the limit, or the segment has fewer than 2 words, returns
    ``[seg]`` unchanged.

    The split point is chosen by best_split_index() in splitter.py:
    inter-word gaps and conjunction positions are used as candidates, scored
    by syllable balance.  Falls back to pure syllable balance when no
    gap/conjunction candidates exist.
    """
    if max_words <= 0 or not seg.words or len(seg.words) <= max_words:
        return [seg]
    if len(seg.words) < 2:
        return [seg]

    split_i = best_split_index(seg.words, lang)
    first_words = seg.words[: split_i + 1]
    second_words = seg.words[split_i + 1 :]

    def _cap(t: str) -> str:
        return t[:1].upper() + t[1:]

    first = _SegmentLike(
        start=seg.start,
        end=first_words[-1].end,
        text=_cap("".join(w.word for w in first_words).strip()),
        words=first_words,
    )
    second = _SegmentLike(
        start=second_words[0].start,
        end=seg.end,
        text=_cap("".join(w.word for w in second_words).strip()),
        words=second_words,
    )

    return _split_segment(first, max_words, lang) + _split_segment(second, max_words, lang)


# ---------------------------------------------------------------------------
# Transcriber
# ---------------------------------------------------------------------------


class Transcriber:
    def __init__(self) -> None:
        self._model: WhisperModel | None = None
        # Full key: (name, device, compute_type, cpu_threads, num_workers).
        # Any change to any element triggers a reload on the next call.
        self._model_key: tuple = ()

    def load_model(
        self,
        name: str,
        device: str = "auto",
        compute_type: str = "default",
        cpu_threads: int = 0,
        num_workers: int = 1,
        on_progress: Callable[[str], None] | None = None,
    ) -> None:
        """Load (or reload) model. Emits status strings via on_progress.

        Skips loading when the model is already loaded with identical
        configuration (name, device, compute type, and thread counts).
        """
        new_key = (name, device, compute_type, cpu_threads, num_workers)
        if self._model is not None and self._model_key == new_key:
            return

        if on_progress:
            on_progress("Loading model…")

        # Suppress the benign ctranslate2 C++ warning about falling back from
        # float16 to float32 on CPU — it goes to the C++ logger (not Python's
        # logging module) and would otherwise bleed into the terminal.
        # Raise the C++ log level to ERROR for the duration of the load only.
        _prev_level = ctranslate2.get_log_level()
        ctranslate2.set_log_level(logging.ERROR)
        try:
            # faster-whisper downloads to ~/.cache/huggingface if not present.
            self._model = WhisperModel(
                name,
                device=device,
                compute_type=compute_type,
                cpu_threads=cpu_threads,
                num_workers=num_workers,
            )
        finally:
            ctranslate2.set_log_level(_prev_level)
        self._model_key = new_key

        if on_progress:
            on_progress("Model ready")

    def transcribe(
        self,
        path: Path,
        language: str | None = None,
        on_progress: Callable[[str], None] | None = None,
        max_words_per_line: int = 0,
        on_language_detected: Callable[[str], None] | None = None,
        vad_threshold: float = 0.0001,
        vad_min_silence_ms: int = 500,
    ) -> list[LRCLine]:
        """Transcribe *path* and return one LRCLine per (post-processed) segment.

        language=None / 'auto' — auto-detect.
        max_words_per_line — when > 0, long segments are recursively split at
            the largest inter-word pause gap until each segment has at most
            this many words.  0 disables splitting.
        vad_threshold — Silero VAD speech probability threshold; 0 disables VAD.
        """
        if self._model is None:
            raise RuntimeError("Model not loaded. Call load_model() first.")

        if on_progress:
            on_progress("Transcribing…")

        lang = None if (language is None or language == "auto") else language
        raw_segments, info = self._model.transcribe(
            str(path),
            language=lang,
            word_timestamps=True,
            vad_filter=vad_threshold > 0,
            vad_parameters=(
                {"threshold": vad_threshold, "min_silence_duration_ms": vad_min_silence_ms}
                if vad_threshold > 0
                else None
            ),
        )
        detected_lang: str = info.language if isinstance(info.language, str) else ""
        if on_language_detected:
            on_language_detected(detected_lang)

        # Materialise the lazy iterator, wrap each segment in _SegmentLike,
        # then apply the word-count splitter before any further processing.
        # Emit percentage progress via on_progress as each segment arrives —
        # seg.end / info.duration gives position in the audio.
        segs: list[_SegmentLike] = []
        for seg in raw_segments:
            if on_progress and info.duration > 0:
                pct = min(100, int(seg.end / info.duration * 100))
                on_progress(f"Transcribing… {pct}%")
            wrapped = _SegmentLike(
                start=seg.start,
                end=seg.end,
                text=seg.text,
                words=list(seg.words or []),
            )
            segs.extend(_split_segment(wrapped, max_words_per_line, detected_lang))

        lines: list[LRCLine] = []
        for seg in segs:
            words = [WordTiming(word=w.word, start=w.start, end=w.end) for w in seg.words]
            # Use the first word's start time — it's more accurate than the
            # segment start, which often includes leading silence or is
            # anchored to the previous segment boundary rather than the actual
            # vocal onset.  Fall back to seg.start when no words are available.
            ts = words[0].start if words else seg.start
            lines.append(LRCLine(timestamp=ts, text=seg.text.strip(), end=seg.end, words=words))

        return lines

    @property
    def loaded_model(self) -> str:
        return self._model_key[0] if self._model_key else ""


# Module-level shared transcriber
transcriber = Transcriber()
