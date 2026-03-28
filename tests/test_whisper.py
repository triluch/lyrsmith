"""Tests for transcribe/whisper.py — uses mocks, no real model is loaded."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from lyrsmith.transcribe.whisper import AVAILABLE_MODELS, Transcriber

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


class TestTranscribe:
    def _transcriber_with_mock_model(self) -> tuple[Transcriber, MagicMock]:
        """Return a Transcriber whose WhisperModel is mocked out."""
        t = Transcriber()
        with patch(_PATCH) as MockModel:
            t.load_model("base")
        # t._model is now MockModel's return_value; re-wrap so calls can be inspected
        mock_model = t._model
        return t, mock_model  # type: ignore[return-value]

    def test_raises_if_no_model_loaded(self):
        t = Transcriber()
        with pytest.raises(RuntimeError, match="Model not loaded"):
            t.transcribe(Path("test.mp3"))

    def test_language_auto_passes_none(self):
        t, mock_model = self._transcriber_with_mock_model()
        mock_model.transcribe.return_value = ([], MagicMock())
        t.transcribe(Path("test.mp3"), language="auto")
        _, kwargs = mock_model.transcribe.call_args
        assert kwargs.get("language") is None

    def test_language_none_passes_none(self):
        t, mock_model = self._transcriber_with_mock_model()
        mock_model.transcribe.return_value = ([], MagicMock())
        t.transcribe(Path("test.mp3"), language=None)
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
        seg1.start, seg1.text = 1.5, "  Hello world  "
        seg2.start, seg2.text = 3.0, "Goodbye"
        mock_model.transcribe.return_value = ([seg1, seg2], MagicMock())
        result = t.transcribe(Path("test.mp3"))
        assert len(result) == 2
        assert result[0].timestamp == pytest.approx(1.5)
        assert result[0].text == "Hello world"  # stripped
        assert result[1].timestamp == pytest.approx(3.0)
        assert result[1].text == "Goodbye"

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


class TestAvailableModels:
    def test_not_empty(self):
        assert len(AVAILABLE_MODELS) > 0

    def test_all_strings(self):
        assert all(isinstance(m, str) for m in AVAILABLE_MODELS)

    def test_base_present(self):
        # 'base' is the default model; must always be in the list
        assert "base" in AVAILABLE_MODELS
