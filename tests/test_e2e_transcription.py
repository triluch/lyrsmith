"""End-to-end transcription tests using the real faster-whisper tiny model.

Requires the model to be downloaded on first run (~75 MB, cached by
faster-whisper in the HuggingFace cache directory).  Marked `slow` so it
can be excluded from quick test runs with: pytest -m 'not slow'

Fixtures:
  tests/fixtures/tts_sample.flac  — ~8 s mono 16 kHz FLAC, TTS speech
  tests/fixtures/tts_sample2.mp3  — ~13 s mono MP3, TTS speech (different voice/text)

The module-scoped `transcribed_lines` fixture loads the tiny model and
transcribes each file once; all test methods share the cached result, so the
model is initialised at most twice per test run (once per fixture file).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lyrsmith.transcribe.whisper import Transcriber

_FIXTURES_DIR = Path(__file__).parent / "fixtures"

_AUDIO_FIXTURES = [
    pytest.param(_FIXTURES_DIR / "tts_sample.flac", id="flac"),
    pytest.param(_FIXTURES_DIR / "tts_sample2.mp3", id="mp3"),
]


@pytest.fixture(scope="module", params=_AUDIO_FIXTURES)
def transcription_result(request):
    """Load tiny model and transcribe once; returns (lines, detected_lang)."""
    t = Transcriber()
    t.load_model("tiny")
    detected: list[str] = []
    lines = t.transcribe(request.param, on_language_detected=detected.append)
    return lines, detected[0] if detected else ""


@pytest.fixture(scope="module")
def transcribed_lines(transcription_result):
    return transcription_result[0]


@pytest.mark.slow
class TestE2ETranscription:
    """Real-model transcription smoke tests — no mocking."""

    def test_produces_multiple_lines(self, transcribed_lines):
        lines = transcribed_lines
        assert len(lines) > 1, f"Expected >1 lines, got {len(lines)}"

    def test_lines_have_text(self, transcribed_lines):
        assert all(line.text.strip() for line in transcribed_lines), "Some lines have empty text"

    def test_lines_have_timestamps(self, transcribed_lines):
        assert all(line.timestamp >= 0.0 for line in transcribed_lines)
        ts = [line.timestamp for line in transcribed_lines]
        assert ts == sorted(ts), f"Timestamps not sorted: {ts}"

    def test_lines_have_word_data(self, transcribed_lines):
        total_words = sum(len(line.words) for line in transcribed_lines)
        assert total_words > 0, "No word-level timing data populated"

    def test_word_timestamps_are_ordered_within_line(self, transcribed_lines):
        for line in transcribed_lines:
            starts = [w.start for w in line.words]
            assert starts == sorted(starts), (
                f"Word timestamps not sorted in line {line.text!r}: {starts}"
            )

    def test_lines_have_end_timestamps(self, transcribed_lines):
        assert all(line.end is not None for line in transcribed_lines), (
            "Some transcribed lines are missing end timestamps"
        )

    def test_detects_english_language(self, transcription_result):
        _, detected_lang = transcription_result
        assert detected_lang == "en"
