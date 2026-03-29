"""Tests for transcribe/whisper.py — uses mocks, no real model is loaded."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from lyrsmith.lrc import WordTiming
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
        """Long segments must be split at the largest gap when limit is set."""
        t, mock_model = self._transcriber_with_mock_model()
        # Gap between w2 (end 0.3) and w3 (start 1.0) = 0.7 — largest
        w1 = self._make_word(" a", 0.0, 0.1)
        w2 = self._make_word(" b", 0.2, 0.3)
        w3 = self._make_word(" c", 1.0, 1.1)
        w4 = self._make_word(" d", 1.2, 1.3)
        seg = self._make_seg(0.0, 1.3, " a b c d", [w1, w2, w3, w4])
        mock_model.transcribe.return_value = ([seg], MagicMock())
        result = t.transcribe(Path("test.mp3"), max_words_per_line=2)
        assert len(result) == 2
        assert result[0].text == "a b"
        assert result[1].text == "c d"
        assert result[1].timestamp == pytest.approx(1.0)  # word-precise


class TestSplitSegment:
    """Unit tests for the _split_segment post-processor."""

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
        assert _split_segment(seg, 0) == [seg]

    def test_no_op_when_within_limit(self):
        seg = self._seg([(" a", 0.0, 0.2), (" b", 0.3, 0.5)])
        assert _split_segment(seg, 3) == [seg]

    def test_no_op_when_exactly_at_limit(self):
        seg = self._seg([(" a", 0.0, 0.2), (" b", 0.3, 0.5)])
        assert _split_segment(seg, 2) == [seg]

    def test_no_op_for_single_word_cannot_split(self):
        seg = self._seg([(" onlyone", 1.0, 1.5)])
        assert _split_segment(seg, 0) == [seg]

    def test_splits_at_largest_gap(self):
        # gap after " space": 2.5 - 2.0 = 0.5  (largest)
        # gap after " Hello": 1.4 - 1.3 = 0.1
        specs = [
            (" Hello", 1.0, 1.3),
            (" space", 1.4, 2.0),
            (" and", 2.5, 2.8),
            (" world", 2.9, 3.2),
        ]
        result = _split_segment(self._seg(specs, start=0.9, end=3.2), 2)
        assert len(result) == 2
        assert result[0].words[0].word == " Hello"
        assert result[0].words[-1].word == " space"
        assert result[1].words[0].word == " and"
        assert result[1].words[-1].word == " world"

    def test_split_timestamps_correct(self):
        specs = [
            (" Hello", 1.0, 1.3),
            (" space", 1.4, 2.0),
            (" and", 2.5, 2.8),
            (" world", 2.9, 3.2),
        ]
        result = _split_segment(self._seg(specs, start=0.9, end=3.2), 2)
        assert result[0].start == pytest.approx(0.9)  # original seg start
        assert result[0].end == pytest.approx(2.0)  # last word of first half
        assert result[1].start == pytest.approx(2.5)  # first word of second half
        assert result[1].end == pytest.approx(3.2)  # original seg end

    def test_split_text_reconstructed_from_words(self):
        specs = [
            (" Hello", 1.0, 1.3),
            (" space", 1.4, 2.0),
            (" and", 2.5, 2.8),
            (" world", 2.9, 3.2),
        ]
        result = _split_segment(self._seg(specs, start=0.9, end=3.2), 2)
        assert result[0].text == "Hello space"
        assert result[1].text == "and world"

    def test_recursive_split_all_within_limit(self):
        specs = [
            (" a", 0.0, 0.2),
            (" b", 0.3, 0.5),
            (" c", 0.6, 0.8),
            (" d", 1.0, 1.2),
            (" e", 1.3, 1.5),
            (" f", 1.6, 1.8),
        ]
        result = _split_segment(self._seg(specs), 2)
        assert all(len(s.words) <= 2 for s in result)
        assert sum(len(s.words) for s in result) == 6  # no words lost

    def test_equal_gaps_terminates_and_splits_fully(self):
        # All gaps equal — algorithm must still terminate and produce correct segments.
        specs = [(" a", 0.0, 0.1), (" b", 0.2, 0.3), (" c", 0.4, 0.5)]
        result = _split_segment(self._seg(specs), 1)
        assert all(len(s.words) == 1 for s in result)
        assert len(result) == 3

    def test_phrase_gap_in_middle_wins_over_edge_gap(self):
        # 9-word phrase with a large pause after the 5th word ("roof") and a
        # slightly-elevated-but-smaller gap after the 1st word ("rain").
        # sqrt(gap) × min(i,n-i)² scoring for n=9:
        #   gap after "rain" = 0.3 s → sqrt(0.3) × 1²  ≈  0.55
        #   phrase gap       = 0.5 s → sqrt(0.5) × 16  ≈ 11.3  ← winner by 20×
        # max_words=5 means only one split is needed.
        specs = [
            (" rain", 0.0, 0.1),  # slightly larger gap after this word
            (" fell", 0.4, 0.6),
            (" upon", 0.65, 0.9),
            (" the", 0.95, 1.15),
            (" roof", 1.2, 1.7),  # phrase gap after this word
            (" and", 2.2, 2.4),
            (" stopped", 2.45, 2.65),
            (" at", 2.7, 2.85),
            (" dawn", 2.9, 3.1),
        ]
        result = _split_segment(self._seg(specs), 5)
        # "rain" must stay with its phrase — the phrase boundary wins.
        assert result[0].words[0].word == " rain"
        assert len(result[0].words) > 1
        assert result[-1].words[0].word == " and"
        assert all(len(s.words) <= 5 for s in result)

    def test_no_words_in_segment_is_noop(self):
        seg = _SegmentLike(start=1.0, end=2.0, text="silence", words=[])
        assert _split_segment(seg, 5) == [seg]


class TestAvailableModels:
    def test_base_present(self):
        # 'base' is the default model; must always be in the list
        assert "base" in AVAILABLE_MODELS
