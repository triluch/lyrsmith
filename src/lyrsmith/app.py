"""Main Textual application."""

from __future__ import annotations

import asyncio
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal

from .audio.decoder import decode_to_pcm
from .audio.player import Player
from .config import Config, save as save_config
from .keybinds import (
    KB_DISCARD_RELOAD,
    KB_NEXT_LANG,
    KB_NEXT_MODEL,
    KB_QUIT,
    KB_SAVE,
    KB_TRANSCRIBE,
)
from .lrc import serialize
from .metadata.tags import read_info, read_lyrics, write_lyrics
from .transcribe.whisper import AVAILABLE_MODELS, transcriber
from .ui.bottom_bar import BottomBar
from .ui.file_browser import FileBrowser
from .ui.left_pane import LeftPane
from .ui.lyrics_editor import LyricsEditor
from .ui.top_bar import TopBar
from .ui.unsaved_modal import UnsavedModal
from .ui.waveform_pane import WaveformPane


class LyrsmithApp(App):
    CSS = """
    Screen {
        layout: vertical;
    }
    #content {
        height: 1fr;
    }
    LeftPane {
        width: 25%;
        min-width: 22;
        max-width: 42;
    }
    WaveformPane {
        width: 14;
    }
    LyricsEditor {
        width: 1fr;
    }
    """

    BINDINGS = [
        Binding(KB_QUIT, "quit_app", "Quit", show=False),
        Binding(KB_SAVE, "save", "Save", show=False),
        Binding(KB_DISCARD_RELOAD, "discard_reload", "Reload", show=False),
        Binding(KB_TRANSCRIBE, "transcribe", "Transcribe", show=False),
        Binding(KB_NEXT_MODEL, "next_model", "Model", show=False),
        Binding(KB_NEXT_LANG, "next_lang", "Language", show=False),
    ]

    def __init__(self, initial_dir: Path, config: Config) -> None:
        super().__init__()
        self._config = config
        self._initial_dir = initial_dir
        self._loaded_path: Path | None = None
        self._pending_load: Path | None = None
        self._pending_quit: bool = False
        self._player = Player(on_position=self._on_position_cb)

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield TopBar()
        with Horizontal(id="content"):
            yield LeftPane(self._initial_dir)
            yield WaveformPane(self._player)
            yield LyricsEditor()
        yield BottomBar()

    def on_mount(self) -> None:
        wfp = self.query_one(WaveformPane)
        wfp.set_zoom(self._config.waveform_zoom)

        top = self.query_one(TopBar)
        top.set_model(self._config.whisper_model)
        top.set_language(self._config.whisper_language)

        # Focus the file browser on startup
        self.query_one(FileBrowser).focus()

        # Poll focus changes to keep bottom bar in sync.
        # on_focus doesn't reliably bubble to App level in Textual v8.
        self._last_focused: object = None
        self.set_interval(0.15, self._poll_focus)

    # ------------------------------------------------------------------
    # Playback tick (comes from mpv thread via call_from_thread)
    # ------------------------------------------------------------------

    def _on_position_cb(self, position: float) -> None:
        self.call_from_thread(self._handle_tick, position)

    def _handle_tick(self, position: float) -> None:
        playing = self._player.is_playing
        self.query_one(WaveformPane).update_position(position)
        editor = self.query_one(LyricsEditor)
        editor.set_playing(
            playing
        )  # keep editor in sync regardless of which pane initiated play
        editor.update_position(position)

    # ------------------------------------------------------------------
    # File loading
    # ------------------------------------------------------------------

    def on_file_browser_file_selected(self, event: FileBrowser.FileSelected) -> None:
        event.stop()
        editor = self.query_one(LyricsEditor)
        if editor.is_dirty:
            self._pending_load = event.path
            self._pending_quit = False
            self.push_screen(
                UnsavedModal(context="load"),
                callback=self._unsaved_modal_done,
            )
        else:
            self._do_load(event.path)

    def _do_load(self, path: Path) -> None:
        self._loaded_path = path
        info = read_info(path)
        lyrics_text = read_lyrics(path)

        # Determine lyrics type
        from .lrc import is_lrc as _is_lrc

        lyrics_type: str | None = None
        if lyrics_text is not None:
            lyrics_type = "lrc" if _is_lrc(lyrics_text) else "plain"

        # Update player
        self._player.load(path)

        # Update top bar
        top = self.query_one(TopBar)
        top.set_song(info.display_title())

        # Update file browser marker
        self.query_one(LeftPane).set_loaded(path)

        # Update bottom bar context
        self._update_bottom_bar()

        # Decode PCM for waveform (run in thread to avoid blocking)
        self.run_worker(
            self._decode_and_update(path),
            name="decode",
            exclusive=True,
        )

        # Load lyrics into editor
        editor = self.query_one(LyricsEditor)
        if lyrics_type == "lrc" and lyrics_text:
            editor.load_lrc(lyrics_text)
        else:
            # Plain text for existing plain lyrics or empty string for no lyrics —
            # always gives an editable area, never a dead hint screen.
            editor.load_plain(lyrics_text or "")

        # Save last directory
        self._config.last_directory = str(path.parent)
        save_config(self._config)

    async def _decode_and_update(self, path: Path) -> None:
        loop = asyncio.get_running_loop()
        pcm, sr = await loop.run_in_executor(None, decode_to_pcm, path)
        if len(pcm) == 0:
            self.query_one(TopBar).set_status("Waveform unavailable")
            return
        self.query_one(WaveformPane).load_pcm(pcm, sr)

    # ------------------------------------------------------------------
    # Unsaved modal callback
    # ------------------------------------------------------------------

    def _unsaved_modal_done(self, choice: str | None) -> None:
        if choice is None or choice == "back":
            self._pending_load = None
            self._pending_quit = False
            return
        if choice == "save":
            if not self._do_save():
                # Save failed (empty content or write error) — abort and let
                # the user see the status bar message before deciding next step.
                self._pending_load = None
                self._pending_quit = False
                return
        # 'discard' or after successful 'save': proceed
        if self._pending_quit:
            self._pending_quit = False
            self._player.terminate()
            self._save_config_with_dir()
            self.exit()
        elif self._pending_load:
            path = self._pending_load
            self._pending_load = None
            self._do_load(path)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def action_quit_app(self) -> None:
        editor = self.query_one(LyricsEditor)
        if editor.is_dirty:
            self._pending_quit = True
            self._pending_load = None
            self.push_screen(
                UnsavedModal(context="quit"),
                callback=self._unsaved_modal_done,
            )
        else:
            self._player.terminate()
            self._save_config_with_dir()
            self.exit()

    def action_save(self) -> None:
        self._do_save()

    def action_discard_reload(self) -> None:
        if self._loaded_path is None:
            return
        lyrics_text = read_lyrics(self._loaded_path)
        editor = self.query_one(LyricsEditor)
        if lyrics_text is None:
            editor.load_empty()
        else:
            from .lrc import is_lrc as _is_lrc

            if _is_lrc(lyrics_text):
                editor.load_lrc(lyrics_text)
            else:
                editor.load_plain(lyrics_text)
        self.query_one(TopBar).set_status("Reloaded from file")

    def action_transcribe(self) -> None:
        if self._loaded_path is None:
            self.query_one(TopBar).set_status("No file loaded")
            return
        self.run_worker(
            self._run_transcription(self._loaded_path),
            name="transcribe",
            exclusive=True,
        )

    def action_next_model(self) -> None:
        models = AVAILABLE_MODELS
        try:
            idx = models.index(self._config.whisper_model)
        except ValueError:
            idx = -1
        self._config.whisper_model = models[(idx + 1) % len(models)]
        self.query_one(TopBar).set_model(self._config.whisper_model)
        save_config(self._config)

    def action_next_lang(self) -> None:
        # Build the cycling list with "auto" always present without mutating
        # self._config — we don't want to write "auto" back if the user omitted
        # it from their config file.
        stored = self._config.whisper_languages or []
        langs = stored if "auto" in stored else ["auto", *stored]
        try:
            idx = langs.index(self._config.whisper_language)
        except ValueError:
            idx = -1
        self._config.whisper_language = langs[(idx + 1) % len(langs)]
        self.query_one(TopBar).set_language(self._config.whisper_language)
        save_config(self._config)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _save_config_with_dir(self) -> None:
        """Update last_directory to the current browser position then save."""
        self._config.last_directory = str(self.query_one(LeftPane).current_directory)
        save_config(self._config)

    def _do_save(self) -> bool:
        """Write current lyrics to the loaded file. Returns True on success."""
        if self._loaded_path is None:
            return False
        editor = self.query_one(LyricsEditor)
        text = editor.current_text()
        if not text:
            self.query_one(TopBar).set_status("Nothing to save")
            return False
        try:
            write_lyrics(self._loaded_path, text)
            self.query_one(TopBar).set_status("Saved")
            # Clear dirty flag without reloading — avoids resetting editor
            # position and losing the active lyric highlight during playback.
            self.query_one(LyricsEditor).clear_dirty()
            return True
        except Exception as e:
            self.query_one(TopBar).set_status(f"Save failed: {e}")
            return False

    async def _run_transcription(self, path: Path) -> None:
        top = self.query_one(TopBar)
        loop = asyncio.get_running_loop()

        def _progress(msg: str) -> None:
            self.call_from_thread(top.set_status, msg)

        model = self._config.whisper_model
        language = self._config.whisper_language

        try:
            # Load model (may be a no-op if already loaded)
            await loop.run_in_executor(
                None,
                lambda: transcriber.load_model(model, on_progress=_progress),
            )

            # Transcribe
            lines = await loop.run_in_executor(
                None,
                lambda: transcriber.transcribe(
                    path, language=language, on_progress=_progress
                ),
            )
        except Exception as e:
            top.set_status(f"Transcription failed: {e}")
            return

        lrc_text = serialize({}, lines)
        editor = self.query_one(LyricsEditor)
        editor.load_lrc(lrc_text)
        editor.mark_dirty()
        top.set_status(f"Transcribed — {len(lines)} lines (unsaved)")

    # ------------------------------------------------------------------
    # Focus tracking for bottom bar context
    # ------------------------------------------------------------------

    def _poll_focus(self) -> None:
        focused = self.focused
        if focused is not self._last_focused:
            self._last_focused = focused
            self._update_bottom_bar()

    @staticmethod
    def _in_widget(focused, cls) -> bool:
        """Return True if focused is an instance of cls or any ancestor is."""
        if isinstance(focused, cls):
            return True
        return any(isinstance(a, cls) for a in focused.ancestors)

    def _update_bottom_bar(self) -> None:
        bar = self.query_one(BottomBar)
        editor = self.query_one(LyricsEditor)

        focused = self.focused
        if focused is None:
            bar.set_context("empty")
            return

        if self._in_widget(focused, WaveformPane):
            bar.set_context("waveform")
        elif self._in_widget(focused, LyricsEditor):
            if editor.mode == "lrc":
                bar.set_context("lyrics-lrc")
            elif editor.mode == "plain":
                bar.set_context("lyrics-plain")
            else:
                bar.set_context("empty")
        elif self._in_widget(focused, LeftPane):
            bar.set_context("browser")
        else:
            bar.set_context("empty")

    # ------------------------------------------------------------------
    # Waveform seek → sync player
    # ------------------------------------------------------------------

    def on_waveform_pane_seek_requested(
        self, event: WaveformPane.SeekRequested
    ) -> None:
        self.query_one(LyricsEditor).update_position(event.position)

    def on_lyrics_editor_seek_requested(
        self, event: LyricsEditor.SeekRequested
    ) -> None:
        self._player.seek(event.position)
        self.query_one(WaveformPane).update_position(event.position)

    def on_lyrics_editor_stop_playback_requested(
        self, _event: LyricsEditor.StopPlaybackRequested
    ) -> None:
        self._player.pause()
        self.query_one(LyricsEditor).set_playing(False)

    def on_lyrics_editor_play_pause_requested(
        self, _event: LyricsEditor.PlayPauseRequested
    ) -> None:
        self._player.toggle()
        self.query_one(LyricsEditor).set_playing(self._player.is_playing)

    # ------------------------------------------------------------------
    # Zoom sync → save to config
    # ------------------------------------------------------------------

    def on_waveform_pane_zoom_changed(self, event: WaveformPane.ZoomChanged) -> None:
        self._config.waveform_zoom = event.zoom
        save_config(self._config)

    # ------------------------------------------------------------------
    # Transcribe from left pane key
    # ------------------------------------------------------------------

    def on_left_pane_transcribe_requested(
        self, _event: LeftPane.TranscribeRequested
    ) -> None:
        self.action_transcribe()
