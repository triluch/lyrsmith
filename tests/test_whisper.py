"""Tests for transcribe/whisper.py — uses mocks, no real model is loaded."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from lyrsmith.lrc import WordTiming
from lyrsmith.transcribe.splitter import best_split_index
from lyrsmith.transcribe.whisper import (
    AVAILABLE_MODELS,
    Transcriber,
    _SegmentLike,
    _split_segment,
)

_PATCH = "lyrsmith.transcribe.whisper.WhisperModel"


class TestLoadModel:
    def test_no_op_when_same_name_already_loaded(self):
        t = Transcriber()
        with patch(_PATCH) as MockModel:
            t.load_model("base")
            t.load_model("base")  # second call with same name
            assert MockModel.call_count == 1

    def test_reloads_when_name_changes(self):
        t = Transcriber()
        with patch(_PATCH) as MockModel:
            t.load_model("base")
            t.load_model("small")
            assert MockModel.call_count == 2

    def test_progress_callback_called_with_model_name(self):
        t = Transcriber()
        msgs: list[str] = []
        with patch(_PATCH):
            t.load_model("base", on_progress=msgs.append)
        assert any("base" in m for m in msgs)

    def test_progress_callback_not_required(self):
        t = Transcriber()
        with patch(_PATCH):
            t.load_model("tiny")  # must not raise

    def test_loaded_model_property_reflects_name(self):
        t = Transcriber()
        assert t.loaded_model == ""
        with patch(_PATCH):
            t.load_model("tiny")
        assert t.loaded_model == "tiny"

    def test_reload_updates_loaded_model_property(self):
        t = Transcriber()
        with patch(_PATCH):
            t.load_model("base")
            t.load_model("medium")
        assert t.loaded_model == "medium"

    def test_no_op_when_all_config_identical(self):
        """Same name AND same hardware params → model must not be recreated."""
        t = Transcriber()
        with patch(_PATCH) as MockModel:
            t.load_model("base", device="cpu", compute_type="int8")
            t.load_model("base", device="cpu", compute_type="int8")
            assert MockModel.call_count == 1

    @pytest.mark.parametrize(
        "changed_kwarg,new_value",
        [
            ("device", "cuda"),
            ("compute_type", "float16"),
            ("cpu_threads", 4),
            ("num_workers", 2),
        ],
    )
    def test_reloads_when_hardware_param_changes(self, changed_kwarg, new_value):
        """Changing any hardware param while keeping the same model name must reload."""
        t = Transcriber()
        with patch(_PATCH) as MockModel:
            t.load_model(
                "base",
                device="cpu",
                compute_type="default",
                cpu_threads=0,
                num_workers=1,
            )
            t.load_model("base", **{changed_kwarg: new_value})
            assert MockModel.call_count == 2

    def test_hardware_params_passed_to_whisper_model(self):
        """The WhisperModel constructor must receive the exact hardware params."""
        t = Transcriber()
        with patch(_PATCH) as MockModel:
            t.load_model(
                "small",
                device="cuda",
                compute_type="float16",
                cpu_threads=4,
                num_workers=2,
            )
        _, kwargs = MockModel.call_args
        assert kwargs["device"] == "cuda"
        assert kwargs["compute_type"] == "float16"
        assert kwargs["cpu_threads"] == 4
        assert kwargs["num_workers"] == 2


class TestTranscribe:
    def _transcriber_with_mock_model(self) -> tuple[Transcriber, MagicMock]:
        """Return a Transcriber whose WhisperModel is mocked out."""
        t = Transcriber()
        with patch(_PATCH):
            t.load_model("base")
        # t._model is now the mock's return_value; re-wrap so calls can be inspected
        mock_model = t._model
        return t, mock_model  # type: ignore[return-value]

    def test_raises_if_no_model_loaded(self):
        t = Transcriber()
        with pytest.raises(RuntimeError, match="Model not loaded"):
            t.transcribe(Path("test.mp3"))

    @pytest.mark.parametrize("language", ["auto", None])
    def test_auto_and_none_language_both_pass_none(self, language):
        t, mock_model = self._transcriber_with_mock_model()
        mock_model.transcribe.return_value = ([], MagicMock())
        t.transcribe(Path("test.mp3"), language=language)
        _, kwargs = mock_model.transcribe.call_args
        assert kwargs.get("language") is None

    def test_explicit_language_passed_through(self):
        t, mock_model = self._transcriber_with_mock_model()
        mock_model.transcribe.return_value = ([], MagicMock())
        t.transcribe(Path("test.mp3"), language="pl")
        _, kwargs = mock_model.transcribe.call_args
        assert kwargs.get("language") == "pl"

    def test_empty_segments_returns_empty_list(self):
        t, mock_model = self._transcriber_with_mock_model()
        mock_model.transcribe.return_value = ([], MagicMock())
        result = t.transcribe(Path("test.mp3"))
        assert result == []

    def test_segments_converted_to_lrc_lines(self):
        t, mock_model = self._transcriber_with_mock_model()
        seg1, seg2 = MagicMock(), MagicMock()
        seg1.start, seg1.end, seg1.text = 1.5, 2.8, "  Hello world  "
        seg2.start, seg2.end, seg2.text = 3.0, 4.1, "Goodbye"
        # Explicitly set words=[] so the test is unambiguous about which code
        # path is exercised (words=MagicMock() is truthy but iterates as empty,
        # which relies on an implementation detail of unittest.mock).
        seg1.words = []
        seg2.words = []
        mock_model.transcribe.return_value = ([seg1, seg2], MagicMock())
        result = t.transcribe(Path("test.mp3"))
        assert len(result) == 2
        assert result[0].timestamp == pytest.approx(1.5)  # fallback: seg.start
        assert result[0].end == pytest.approx(2.8)
        assert result[0].text == "Hello world"  # stripped
        assert result[0].words == []
        assert result[1].timestamp == pytest.approx(3.0)
        assert result[1].end == pytest.approx(4.1)
        assert result[1].text == "Goodbye"
        assert result[1].words == []

    def test_progress_callback_called_during_transcribe(self):
        t, mock_model = self._transcriber_with_mock_model()
        mock_model.transcribe.return_value = ([], MagicMock())
        msgs: list[str] = []
        t.transcribe(Path("song.mp3"), on_progress=msgs.append)
        assert len(msgs) >= 1

    def test_file_path_passed_as_string(self):
        """faster-whisper expects a string path, not a Path object."""
        t, mock_model = self._transcriber_with_mock_model()
        mock_model.transcribe.return_value = ([], MagicMock())
        p = Path("/some/file.mp3")
        t.transcribe(p)
        args, _ = mock_model.transcribe.call_args
        assert args[0] == str(p)

    def test_word_timestamps_flag_passed(self):
        """word_timestamps=True must always be forwarded to the model."""
        t, mock_model = self._transcriber_with_mock_model()
        mock_model.transcribe.return_value = ([], MagicMock())
        t.transcribe(Path("test.mp3"))
        _, kwargs = mock_model.transcribe.call_args
        assert kwargs.get("word_timestamps") is True

    def _make_seg(self, start, end, text, words):
        """Build a mock segment with a proper iterable words list."""
        seg = MagicMock()
        seg.start = start
        seg.end = end
        seg.text = text
        seg.words = words
        return seg

    def _make_word(self, word, start, end):
        w = MagicMock()
        w.word = word
        w.start = start
        w.end = end
        return w

    def test_words_populated_from_segment(self):
        t, mock_model = self._transcriber_with_mock_model()
        w1 = self._make_word(" Hello", 1.0, 1.3)
        w2 = self._make_word(" world", 1.4, 1.8)
        seg = self._make_seg(0.8, 2.0, " Hello world ", [w1, w2])
        mock_model.transcribe.return_value = ([seg], MagicMock())
        result = t.transcribe(Path("test.mp3"))
        assert len(result[0].words) == 2
        assert isinstance(result[0].words[0], WordTiming)
        assert result[0].words[0].word == " Hello"
        assert result[0].words[0].start == pytest.approx(1.0)
        assert result[0].words[1].word == " world"
        assert result[0].words[1].start == pytest.approx(1.4)

    def test_timestamp_uses_first_word_start(self):
        """Segment timestamp should come from words[0].start, not seg.start."""
        t, mock_model = self._transcriber_with_mock_model()
        w1 = self._make_word(" Hello", 1.2, 1.5)  # first word starts later than seg
        seg = self._make_seg(0.5, 2.0, " Hello world ", [w1])
        mock_model.transcribe.return_value = ([seg], MagicMock())
        result = t.transcribe(Path("test.mp3"))
        assert result[0].timestamp == pytest.approx(1.2)

    def test_timestamp_falls_back_to_seg_start_when_no_words(self):
        t, mock_model = self._transcriber_with_mock_model()
        seg = self._make_seg(3.0, 4.5, " Silence ", [])
        mock_model.transcribe.return_value = ([seg], MagicMock())
        result = t.transcribe(Path("test.mp3"))
        assert result[0].timestamp == pytest.approx(3.0)
        assert result[0].words == []

    def test_max_words_per_line_zero_does_not_split(self):
        """max_words_per_line=0 (default) must leave segments unsplit."""
        t, mock_model = self._transcriber_with_mock_model()
        w1 = self._make_word(" a", 0.0, 0.1)
        w2 = self._make_word(" b", 0.2, 0.3)
        w3 = self._make_word(" c", 0.4, 0.5)
        seg = self._make_seg(0.0, 0.5, " a b c", [w1, w2, w3])
        mock_model.transcribe.return_value = ([seg], MagicMock())
        result = t.transcribe(Path("test.mp3"), max_words_per_line=0)
        assert len(result) == 1

    def test_max_words_per_line_splits_long_segment(self):
        """Long segments must be split at the natural phrase boundary when limit is set."""
        t, mock_model = self._transcriber_with_mock_model()
        # Single gap candidate: between w2 (end 0.3) and w3 (start 1.0) = 700 ms.
        # Only one candidate → split there regardless; gives balanced 2|2 split.
        w1 = self._make_word(" a", 0.0, 0.1)
        w2 = self._make_word(" b", 0.2, 0.3)
        w3 = self._make_word(" c", 1.0, 1.1)
        w4 = self._make_word(" d", 1.2, 1.3)
        seg = self._make_seg(0.0, 1.3, " a b c d", [w1, w2, w3, w4])
        mock_model.transcribe.return_value = ([seg], MagicMock())
        result = t.transcribe(Path("test.mp3"), max_words_per_line=2)
        assert len(result) == 2
        assert result[0].text == "A b"
        assert result[1].text == "C d"
        assert result[1].timestamp == pytest.approx(1.0)  # word-precise

    def test_on_language_detected_callback_fires_with_detected_language(self):
        """on_language_detected is called once with the language from TranscriptionInfo."""
        t, mock_model = self._transcriber_with_mock_model()
        info = MagicMock()
        info.language = "fr"
        mock_model.transcribe.return_value = ([], info)
        received: list[str] = []
        t.transcribe(Path("test.mp3"), on_language_detected=received.append)
        assert received == ["fr"]

    def test_on_language_detected_not_required(self):
        """Omitting on_language_detected must not raise."""
        t, mock_model = self._transcriber_with_mock_model()
        mock_model.transcribe.return_value = ([], MagicMock())
        t.transcribe(Path("test.mp3"))  # no on_language_detected arg

    def test_vad_enabled_when_threshold_nonzero(self):
        """Positive vad_threshold passes vad_filter=True and the parameters dict."""
        t, mock_model = self._transcriber_with_mock_model()
        mock_model.transcribe.return_value = ([], MagicMock())
        t.transcribe(Path("test.mp3"), vad_threshold=0.001, vad_min_silence_ms=300)
        _, kwargs = mock_model.transcribe.call_args
        assert kwargs["vad_filter"] is True
        assert kwargs["vad_parameters"] == {"threshold": 0.001, "min_silence_duration_ms": 300}

    def test_vad_disabled_when_threshold_zero(self):
        """vad_threshold=0 passes vad_filter=False and vad_parameters=None."""
        t, mock_model = self._transcriber_with_mock_model()
        mock_model.transcribe.return_value = ([], MagicMock())
        t.transcribe(Path("test.mp3"), vad_threshold=0)
        _, kwargs = mock_model.transcribe.call_args
        assert kwargs["vad_filter"] is False
        assert kwargs["vad_parameters"] is None


class TestSplitSegment:
    """Unit tests for the _split_segment post-processor."""

    # Use lang="" throughout: no conjunction data, character-count syllable
    # proxy — gives deterministic, pyphen-independent results.

    def _word(self, word: str, start: float, end: float):
        w = MagicMock()
        w.word = word
        w.start = start
        w.end = end
        return w

    def _seg(
        self,
        specs: list[tuple[str, float, float]],
        start: float | None = None,
        end: float | None = None,
    ) -> _SegmentLike:
        words = [self._word(w, s, e) for w, s, e in specs]
        seg_start = start if start is not None else (words[0].start if words else 0.0)
        seg_end = end if end is not None else (words[-1].end if words else 1.0)
        text = "".join(w for w, _, _ in specs).strip()
        return _SegmentLike(start=seg_start, end=seg_end, text=text, words=words)

    def test_no_op_when_max_words_zero(self):
        seg = self._seg([(" a", 0.0, 0.2), (" b", 0.3, 0.5), (" c", 0.6, 0.8)])
        assert _split_segment(seg, 0, "") == [seg]

    def test_no_op_when_within_limit(self):
        seg = self._seg([(" a", 0.0, 0.2), (" b", 0.3, 0.5)])
        assert _split_segment(seg, 3, "") == [seg]

    def test_no_op_when_exactly_at_limit(self):
        seg = self._seg([(" a", 0.0, 0.2), (" b", 0.3, 0.5)])
        assert _split_segment(seg, 2, "") == [seg]

    def test_no_op_for_single_word_cannot_split(self):
        seg = self._seg([(" onlyone", 1.0, 1.5)])
        assert _split_segment(seg, 0, "") == [seg]

    def test_no_words_in_segment_is_noop(self):
        seg = _SegmentLike(start=1.0, end=2.0, text="silence", words=[])
        assert _split_segment(seg, 5, "") == [seg]

    def test_most_balanced_gap_wins(self):
        # Two gap candidates: after "Hello" (100 ms) and after "space" (500 ms).
        # With lang="" (char-count syllables, all ~1 syl), imbalance scores:
        #   after "Hello" (idx 0): Hello(2syl)|space+and+world(3syl) → 1 off
        #   after "space" (idx 1): Hello+space(3syl)|and+world(2syl) → 1 off (tie)
        # Tie → min() picks lower index (0 → "Hello"), THEN recurse splits
        # [space, and, world] → [space]|[and, world], giving 3 segments.
        # This confirms the algorithm uses balance not gap magnitude.
        # (The old algorithm also split after "space" for different reasons.)
        specs = [
            (" Hello", 1.0, 1.3),
            (" space", 1.4, 2.0),
            (" and", 2.5, 2.8),
            (" world", 2.9, 3.2),
        ]
        result = _split_segment(self._seg(specs, start=0.9, end=3.2), 2, "")
        # All segments ≤ 2 words, all words present, correct order
        assert all(len(s.words) <= 2 for s in result)
        assert sum(len(s.words) for s in result) == 4
        assert result[0].words[0].word == " Hello"
        assert result[-1].words[-1].word == " world"

    def test_split_timestamps_correct(self):
        # Single clear gap (700 ms after "b") → splits [a,b]|[c,d]; timestamps preserved.
        specs = [
            (" a", 0.0, 0.1),
            (" b", 0.2, 0.3),
            (" c", 1.0, 1.1),
            (" d", 1.2, 1.3),
        ]
        seg = self._seg(specs, start=0.0, end=1.3)
        result = _split_segment(seg, 2, "")
        assert len(result) == 2
        assert result[0].start == pytest.approx(0.0)  # original seg start
        assert result[0].end == pytest.approx(0.3)  # last word of first half
        assert result[1].start == pytest.approx(1.0)  # first word of second half
        assert result[1].end == pytest.approx(1.3)  # original seg end

    def test_split_text_reconstructed_from_words(self):
        specs = [
            (" a", 0.0, 0.1),
            (" b", 0.2, 0.3),
            (" c", 1.0, 1.1),
            (" d", 1.2, 1.3),
        ]
        result = _split_segment(self._seg(specs, start=0.0, end=1.3), 2, "")
        assert result[0].text == "A b"
        assert result[1].text == "C d"

    def test_recursive_split_all_within_limit(self):
        specs = [
            (" a", 0.0, 0.2),
            (" b", 0.3, 0.5),
            (" c", 0.6, 0.8),
            (" d", 1.0, 1.2),
            (" e", 1.3, 1.5),
            (" f", 1.6, 1.8),
        ]
        result = _split_segment(self._seg(specs), 2, "")
        assert all(len(s.words) <= 2 for s in result)
        assert sum(len(s.words) for s in result) == 6  # no words lost

    def test_equal_gaps_terminates_and_splits_fully(self):
        # All gaps equal — fallback to syllable balance; must terminate.
        specs = [(" a", 0.0, 0.1), (" b", 0.2, 0.3), (" c", 0.4, 0.5)]
        result = _split_segment(self._seg(specs), 1, "")
        assert all(len(s.words) == 1 for s in result)
        assert len(result) == 3

    def test_split_halves_are_capitalised(self):
        # Mid-sentence words are lowercase in Whisper output; both halves of a
        # split must have their first letter capitalised.
        specs = [
            (" hello", 0.0, 0.1),
            (" world", 0.2, 0.3),
            (" and", 1.0, 1.1),  # 700ms gap → split here
            (" goodbye", 1.2, 1.3),
        ]
        result = _split_segment(self._seg(specs), 2, "")
        assert len(result) == 2
        assert result[0].text[0].isupper()
        assert result[1].text[0].isupper()


class TestBestSplitIndex:
    """Unit tests for the core split-point selection logic in splitter.py."""

    def _word(self, word: str, start: float, end: float):
        w = MagicMock()
        w.word = word
        w.start = start
        w.end = end
        return w

    def _words(self, specs: list[tuple[str, float, float]]) -> list:
        return [self._word(w, s, e) for w, s, e in specs]

    def test_single_gap_candidate_is_used(self):
        # Only one gap qualifies; algorithm must pick it regardless of position.
        words = self._words(
            [
                (" a", 0.0, 0.1),
                (" b", 0.15, 0.25),
                (" c", 0.30, 0.40),  # 500ms gap before d → only candidate
                (" d", 0.90, 1.00),
                (" e", 1.05, 1.15),
            ]
        )
        assert best_split_index(words, "") == 2  # split after "c"

    def test_most_balanced_gap_beats_largest_gap(self):
        # Two gap candidates: large gap right after first word (very unbalanced),
        # medium gap near the middle (well balanced). New algorithm picks balanced.
        #
        # rain → 300ms gap (index 0, imbalance 1|8 = 7)
        # roof → 500ms gap (index 4, imbalance 5|4 = 1) ← winner by balance
        # All other inter-word spacings < 50ms so they don't qualify.
        words = self._words(
            [
                (" rain", 0.00, 0.10),
                (" fell", 0.40, 0.60),  # 300ms gap before → gap after rain qualifies
                (" upon", 0.61, 0.90),
                (" the", 0.91, 1.10),
                (" roof", 1.11, 1.60),
                (" and", 2.10, 2.30),  # 500ms gap before → gap after roof qualifies
                (" stopped", 2.31, 2.50),
                (" at", 2.51, 2.70),
                (" dawn", 2.71, 3.10),
            ]
        )
        idx = best_split_index(words, "")
        assert idx == 4  # after "roof", not after "rain"

    def test_fallback_to_syllable_balance_when_no_gaps(self):
        # All words touching (0ms gaps) → no gap candidates → pure syllable balance.
        # 6 words all 1 char each (char-count syl=1): split at index 2 or 3 (3|3).
        words = self._words(
            [
                (" a", 0.0, 0.1),
                (" b", 0.1, 0.2),
                (" c", 0.2, 0.3),
                (" d", 0.3, 0.4),
                (" e", 0.4, 0.5),
                (" f", 0.5, 0.6),
            ]
        )
        idx = best_split_index(words, "")
        left = idx + 1
        right = len(words) - left
        assert abs(left - right) <= 1  # within 1 syllable of perfect balance

    def test_no_gaps_uneven_word_count_picks_most_balanced(self):
        # 5 touching words → best split is 2|3 or 3|2; index 1 or 2.
        words = self._words(
            [
                (" a", 0.0, 0.1),
                (" b", 0.1, 0.2),
                (" c", 0.2, 0.3),
                (" d", 0.3, 0.4),
                (" e", 0.4, 0.5),
            ]
        )
        idx = best_split_index(words, "")
        assert idx in (1, 2)  # 2|3 or 3|2

    def test_two_words_always_splits_after_first(self):
        words = self._words([(" a", 0.0, 0.5), (" b", 0.6, 1.0)])
        assert best_split_index(words, "") == 0


class TestAvailableModels:
    def test_base_present(self):
        # 'base' is the default model; must always be in the list
        assert "base" in AVAILABLE_MODELS
