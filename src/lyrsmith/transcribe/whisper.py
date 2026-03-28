"""
faster-whisper wrapper.

Transcription runs synchronously — callers should run it in a thread executor
to avoid blocking the event loop. The transcriber is a singleton that holds
the loaded model and re-loads only when model/device changes.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable

from faster_whisper import WhisperModel

from ..lrc import LRCLine

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


class Transcriber:
    def __init__(self) -> None:
        self._model: WhisperModel | None = None
        self._model_name: str = ""

    def load_model(
        self,
        name: str,
        on_progress: Callable[[str], None] | None = None,
    ) -> None:
        """Load (or reload) model. Emits status strings via on_progress."""
        if self._model is not None and self._model_name == name:
            return

        if on_progress:
            on_progress(f"Loading model '{name}'…")

        # faster-whisper downloads to ~/.cache/huggingface if not present.
        # device="auto" picks CUDA if available, else CPU.
        self._model = WhisperModel(name, device="auto", compute_type="default")
        self._model_name = name

        if on_progress:
            on_progress(f"Model '{name}' ready")

    def transcribe(
        self,
        path: Path,
        language: str | None = None,
        on_progress: Callable[[str], None] | None = None,
    ) -> list[LRCLine]:
        """
        Transcribe audio file and return LRC lines (one per whisper segment).
        language=None or 'auto' means auto-detect.
        """
        if self._model is None:
            raise RuntimeError("Model not loaded. Call load_model() first.")

        if on_progress:
            on_progress(f"Transcribing {path.name}…")

        lang = None if (language is None or language == "auto") else language
        segments, _info = self._model.transcribe(str(path), language=lang)

        lines: list[LRCLine] = []
        for seg in segments:
            lines.append(LRCLine(timestamp=seg.start, text=seg.text.strip()))

        if on_progress:
            on_progress(f"Done — {len(lines)} lines")

        return lines

    @property
    def loaded_model(self) -> str:
        return self._model_name


# Module-level shared transcriber
transcriber = Transcriber()
