"""Tests for PromptModal and the Ctrl+U whisper-prompt workflow.

Coverage:
  - PromptModal unit: escape → None, ctrl+t/ctrl+u submit, existing text
    pre-filled, plain Enter inserts newline (does not submit).
  - App integration: no-file guard, ctrl+u opens modal, esc skips
    transcription, submit triggers transcription with initial_prompt kwarg,
    prompt stored between invocations, prompt cleared on new file load,
    empty prompt normalised to None.
"""

from __future__ import annotations

import asyncio

from lyrsmith.lrc import LRCLine
from lyrsmith.ui.lyrics_editor import LyricsEditor
from lyrsmith.ui.prompt_modal import PromptModal

from ._helpers import _fake_info, _make_mp3

_STUB_LINES = [LRCLine(1.0, "Hello"), LRCLine(2.0, "World")]


# ---------------------------------------------------------------------------
# TestPromptModalUnit — PromptModal driven via a lightweight host app
# ---------------------------------------------------------------------------


class TestPromptModalUnit:
    """Push PromptModal onto a running app and drive it with Pilot."""

    def _push(self, pilot) -> None:
        pilot.app._modal_result = "unset"

        def _cb(r: str | None) -> None:
            pilot.app._modal_result = r

        pilot.app.push_screen(PromptModal(""), callback=_cb)

    def _push_with(self, pilot, text: str) -> None:
        pilot.app._modal_result = "unset"

        def _cb(r: str | None) -> None:
            pilot.app._modal_result = r

        pilot.app.push_screen(PromptModal(text), callback=_cb)

    def test_escape_dismisses_with_none(self, make_app):
        _factory, _ = make_app

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                self._push(pilot)
                await pilot.pause()
                assert isinstance(pilot.app.screen, PromptModal)
                await pilot.press("escape")
                await pilot.pause()
                assert not isinstance(pilot.app.screen, PromptModal)
                assert pilot.app._modal_result is None

        asyncio.run(_impl())

    def test_ctrl_t_returns_typed_text(self, make_app):
        from textual.widgets import TextArea as _TA

        _factory, _ = make_app

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                self._push(pilot)
                await pilot.pause()
                ta = pilot.app.screen.query_one("#prompt-area", _TA)
                ta.load_text("My prompt text")
                await pilot.pause()
                await pilot.press("ctrl+t")
                await pilot.pause()
                assert not isinstance(pilot.app.screen, PromptModal)
                assert pilot.app._modal_result == "My prompt text"

        asyncio.run(_impl())

    def test_ctrl_u_returns_typed_text(self, make_app):
        from textual.widgets import TextArea as _TA

        _factory, _ = make_app

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                self._push(pilot)
                await pilot.pause()
                ta = pilot.app.screen.query_one("#prompt-area", _TA)
                ta.load_text("ctrl-u submit")
                await pilot.pause()
                await pilot.press("ctrl+u")
                await pilot.pause()
                assert not isinstance(pilot.app.screen, PromptModal)
                assert pilot.app._modal_result == "ctrl-u submit"

        asyncio.run(_impl())

    def test_ctrl_t_with_empty_area_returns_empty_string(self, make_app):
        _factory, _ = make_app

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                self._push(pilot)
                await pilot.pause()
                await pilot.press("ctrl+t")
                await pilot.pause()
                assert not isinstance(pilot.app.screen, PromptModal)
                assert pilot.app._modal_result == ""

        asyncio.run(_impl())

    def test_existing_prompt_prefills_textarea(self, make_app):
        from textual.widgets import TextArea as _TA

        _factory, _ = make_app

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                self._push_with(pilot, "prefilled text")
                await pilot.pause()
                ta = pilot.app.screen.query_one("#prompt-area", _TA)
                assert ta.text == "prefilled text"
                await pilot.press("escape")
                await pilot.pause()

        asyncio.run(_impl())

    def test_enter_inserts_newline_not_submit(self, make_app):
        from textual.widgets import TextArea as _TA

        _factory, _ = make_app

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                self._push(pilot)
                await pilot.pause()
                ta = pilot.app.screen.query_one("#prompt-area", _TA)
                ta.load_text("line one")
                ta.move_cursor(ta.document.end)
                await pilot.pause()
                await pilot.press("enter")
                await pilot.pause()
                assert isinstance(pilot.app.screen, PromptModal)
                assert "\n" in ta.text
                await pilot.press("escape")
                await pilot.pause()

        asyncio.run(_impl())


# ---------------------------------------------------------------------------
# TestPromptWorkflow — integration with LyrsmithApp
# ---------------------------------------------------------------------------


class TestPromptWorkflow:
    """Ctrl+U opens PromptModal; submitting triggers transcription with prompt."""

    def test_no_file_loaded_does_not_open_modal(self, make_app):
        _factory, _ = make_app

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                app = pilot.app
                assert app._loaded_path is None
                app.action_show_prompt()
                await pilot.pause()
                assert not isinstance(app.screen, PromptModal)

        asyncio.run(_impl())

    def test_ctrl_u_opens_modal_when_file_loaded(self, make_app, tmp_path):
        _factory, _ = make_app
        audio = _make_mp3(tmp_path / "song.mp3")

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                app = pilot.app
                app._loaded_path = audio
                app.action_show_prompt()
                await pilot.pause()
                assert isinstance(app.screen, PromptModal)
                await pilot.press("escape")
                await pilot.pause()

        asyncio.run(_impl())

    def test_escape_does_not_trigger_transcription(self, make_app, monkeypatch, tmp_path):
        from lyrsmith.transcribe.whisper import transcriber as _tr

        _factory, _ = make_app
        audio = _make_mp3(tmp_path / "song.mp3")
        calls: list = []
        monkeypatch.setattr(_tr, "transcribe", lambda *a, **kw: calls.append(kw) or [])
        monkeypatch.setattr(_tr, "load_model", lambda *a, **kw: None)

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                app = pilot.app
                app._loaded_path = audio
                ed = app.query_one(LyricsEditor)
                assert ed.mode == "empty"
                app.action_show_prompt()
                await pilot.pause()
                assert isinstance(app.screen, PromptModal)
                await pilot.press("escape")
                await pilot.pause()
                assert not isinstance(app.screen, PromptModal)
                await app.workers.wait_for_complete()
                assert calls == []
                assert ed.mode == "empty"

        asyncio.run(_impl())

    def test_submit_passes_prompt_to_transcriber(self, make_app, monkeypatch, tmp_path):
        from textual.widgets import TextArea as _TA

        from lyrsmith.transcribe.whisper import transcriber as _tr

        _factory, _ = make_app
        audio = _make_mp3(tmp_path / "song.mp3")
        captured: dict = {}

        def _stub(*a, **kw):
            captured.update(kw)
            return _STUB_LINES

        monkeypatch.setattr(_tr, "transcribe", _stub)
        monkeypatch.setattr(_tr, "load_model", lambda *a, **kw: None)

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                app = pilot.app
                app._loaded_path = audio
                app.action_show_prompt()
                await pilot.pause()
                assert isinstance(app.screen, PromptModal)
                ta = app.screen.query_one("#prompt-area", _TA)
                ta.load_text("Radiohead – Creep")
                await pilot.pause()
                await pilot.press("ctrl+t")
                await pilot.pause()
                assert not isinstance(app.screen, PromptModal)
                await app.workers.wait_for_complete()
                await pilot.pause()
                assert captured.get("initial_prompt") == "Radiohead – Creep"
                assert app.query_one(LyricsEditor).mode == "lrc"

        asyncio.run(_impl())

    def test_prompt_stored_after_submit(self, make_app, monkeypatch, tmp_path):
        from textual.widgets import TextArea as _TA

        from lyrsmith.transcribe.whisper import transcriber as _tr

        _factory, _ = make_app
        audio = _make_mp3(tmp_path / "song.mp3")
        monkeypatch.setattr(_tr, "transcribe", lambda *a, **kw: _STUB_LINES)
        monkeypatch.setattr(_tr, "load_model", lambda *a, **kw: None)

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                app = pilot.app
                app._loaded_path = audio
                app.action_show_prompt()
                await pilot.pause()
                ta = app.screen.query_one("#prompt-area", _TA)
                ta.load_text("stored text")
                await pilot.pause()
                await pilot.press("ctrl+t")
                await pilot.pause()
                await app.workers.wait_for_complete()
                assert app._whisper_prompt == "stored text"

        asyncio.run(_impl())

    def test_prompt_prefilled_on_second_open(self, make_app, monkeypatch, tmp_path):
        from textual.widgets import TextArea as _TA

        from lyrsmith.transcribe.whisper import transcriber as _tr

        _factory, _ = make_app
        audio = _make_mp3(tmp_path / "song.mp3")
        monkeypatch.setattr(_tr, "transcribe", lambda *a, **kw: _STUB_LINES)
        monkeypatch.setattr(_tr, "load_model", lambda *a, **kw: None)

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                app = pilot.app
                app._loaded_path = audio
                app.action_show_prompt()
                await pilot.pause()
                ta = app.screen.query_one("#prompt-area", _TA)
                ta.load_text("my hint")
                await pilot.pause()
                await pilot.press("ctrl+t")
                await pilot.pause()
                await app.workers.wait_for_complete()
                app.action_show_prompt()
                await pilot.pause()
                ta2 = app.screen.query_one("#prompt-area", _TA)
                assert ta2.text == "my hint"
                await pilot.press("escape")
                await pilot.pause()

        asyncio.run(_impl())

    def test_prompt_cleared_on_new_file_load(self, make_app, monkeypatch, tmp_path):
        from textual.widgets import TextArea as _TA

        from lyrsmith.transcribe.whisper import transcriber as _tr

        _factory, _ = make_app
        audio1 = _make_mp3(tmp_path / "a.mp3")
        audio2 = _make_mp3(tmp_path / "b.mp3")
        monkeypatch.setattr(_tr, "transcribe", lambda *a, **kw: _STUB_LINES)
        monkeypatch.setattr(_tr, "load_model", lambda *a, **kw: None)
        monkeypatch.setattr("lyrsmith.app.read_info", _fake_info)
        monkeypatch.setattr("lyrsmith.app.read_lyrics", lambda _p: None)

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                app = pilot.app
                app._loaded_path = audio1
                app.action_show_prompt()
                await pilot.pause()
                ta = app.screen.query_one("#prompt-area", _TA)
                ta.load_text("my hint")
                await pilot.pause()
                await pilot.press("ctrl+t")
                await pilot.pause()
                await app.workers.wait_for_complete()
                assert app._whisper_prompt == "my hint"
                app._do_load(audio2)
                await pilot.pause()
                assert app._whisper_prompt == ""

        asyncio.run(_impl())

    def test_empty_prompt_passes_none_to_transcriber(self, make_app, monkeypatch, tmp_path):
        from lyrsmith.transcribe.whisper import transcriber as _tr

        _factory, _ = make_app
        audio = _make_mp3(tmp_path / "song.mp3")
        captured: dict = {}

        def _stub(*a, **kw):
            captured.update(kw)
            return _STUB_LINES

        monkeypatch.setattr(_tr, "transcribe", _stub)
        monkeypatch.setattr(_tr, "load_model", lambda *a, **kw: None)

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                app = pilot.app
                app._loaded_path = audio
                app.action_show_prompt()
                await pilot.pause()
                await pilot.press("ctrl+t")
                await pilot.pause()
                await app.workers.wait_for_complete()
                await pilot.pause()
                assert captured.get("initial_prompt") is None

        asyncio.run(_impl())

    def test_regular_transcribe_ignores_stored_prompt(self, make_app, monkeypatch, tmp_path):
        from lyrsmith.transcribe.whisper import transcriber as _tr

        _factory, _ = make_app
        audio = _make_mp3(tmp_path / "song.mp3")
        captured: dict = {}

        def _stub(*a, **kw):
            captured.update(kw)
            return _STUB_LINES

        monkeypatch.setattr(_tr, "transcribe", _stub)
        monkeypatch.setattr(_tr, "load_model", lambda *a, **kw: None)

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                app = pilot.app
                app._loaded_path = audio
                app._whisper_prompt = "previously stored hint"
                app.action_transcribe()
                await app.workers.wait_for_complete()
                await pilot.pause()
                assert captured.get("initial_prompt") is None

        asyncio.run(_impl())

    def test_ctrl_u_submit_also_works(self, make_app, monkeypatch, tmp_path):
        from textual.widgets import TextArea as _TA

        from lyrsmith.transcribe.whisper import transcriber as _tr

        _factory, _ = make_app
        audio = _make_mp3(tmp_path / "song.mp3")
        captured: dict = {}

        def _stub(*a, **kw):
            captured.update(kw)
            return _STUB_LINES

        monkeypatch.setattr(_tr, "transcribe", _stub)
        monkeypatch.setattr(_tr, "load_model", lambda *a, **kw: None)

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                app = pilot.app
                app._loaded_path = audio
                app.action_show_prompt()
                await pilot.pause()
                ta = app.screen.query_one("#prompt-area", _TA)
                ta.load_text("via ctrl-u")
                await pilot.pause()
                await pilot.press("ctrl+u")
                await pilot.pause()
                assert not isinstance(app.screen, PromptModal)
                await app.workers.wait_for_complete()
                await pilot.pause()
                assert captured.get("initial_prompt") == "via ctrl-u"

        asyncio.run(_impl())
