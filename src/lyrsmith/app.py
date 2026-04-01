"""Main Textual application."""

from __future__ import annotations

import asyncio
import os
import subprocess
import threading
import traceback
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal

from . import keybinds
from .audio.decoder import decode_to_pcm
from .audio.player import Player
from .config import Config
from .config import save as save_config
from .lrc import attach_word_data, is_lrc
from .lrc import parse as parse_lrc
from .metadata.tags import (
    read_info,
    read_lyrics,
    read_word_data,
    write_lyrics,
    write_word_data,
)
from .transcribe.whisper import AVAILABLE_MODELS, transcriber
from .ui.bottom_bar import BottomBar
from .ui.config_modal import ConfigModal
from .ui.edit_line_modal import EditLineModal, EditLineResult
from .ui.error_modal import ErrorModal
from .ui.file_browser import FileBrowser
from .ui.help_modal import HelpModal
from .ui.indicator_segment import IndicatorSegment
from .ui.left_pane import LeftPane
from .ui.lyrics_editor import LyricsEditor
from .ui.prompt_modal import PromptModal
from .ui.top_bar import TopBar
from .ui.unsaved_modal import UnsavedModal
from .ui.waveform_pane import WaveformPane


def _copy_to_system_clipboard(text: str) -> None:
    """Copy *text* to the OS clipboard via system tools.

    Tries wl-copy (Wayland), then xclip and xsel (X11).  Silently ignores
    failures so a missing tool never crashes the UI.  Textual's built-in
    copy_to_clipboard uses OSC 52, which not all terminals honour.

    Best-effort: called in a daemon thread — the caller does not wait for
    completion.  Timeout is 1 s; a missing or hung tool is silently skipped.
    """
    if os.environ.get("WAYLAND_DISPLAY"):
        try:
            subprocess.run(
                ["wl-copy"],
                input=text.encode(),
                check=True,
                timeout=1,
                capture_output=True,
            )
            return
        except Exception:
            pass

    for cmd in (
        ["xclip", "-selection", "clipboard"],
        ["xsel", "--clipboard", "--input"],
    ):
        try:
            subprocess.run(
                cmd,
                input=text.encode(),
                check=True,
                timeout=1,
                capture_output=True,
            )
            return
        except Exception:
            pass


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
        width: 22;
    }
    LyricsEditor {
        width: 1fr;
    }

    /* Focus indicator row — sits between TopBar and content.
       ▀ half-block: upper half = foreground ($panel unlit / $accent lit),
       lower half = background ($background, matching content area) → thin
       accent stripe at the top edge when lit, invisible otherwise. */
    #indicator-top {
        height: 1;
        background: $panel;
    }
    .ind-left  { width: 25%; min-width: 22; max-width: 42; }
    .ind-wave  { width: 22; }
    .ind-edit  { width: 1fr; }

    /* Move toasts to top-right instead of the default bottom-right. */
    ToastRack {
        dock: top;
        align: right top;
        margin-top: 1;
        margin-bottom: 0;
    }
    """

    BINDINGS = [
        Binding(keybinds.KB_QUIT, "quit_app", "Quit", show=False),
        Binding(keybinds.KB_SAVE, "save", "Save", show=False),
        Binding(keybinds.KB_DISCARD_RELOAD, "discard_reload", "Reload", show=False),
        Binding(keybinds.KB_TRANSCRIBE, "transcribe", "Transcribe", show=False),
        Binding(keybinds.KB_PROMPT, "show_prompt", "Prompt", show=False, priority=True),
        Binding(keybinds.KB_NEXT_MODEL, "next_model", "Model", show=False),
        Binding(keybinds.KB_NEXT_LANG, "next_lang", "Language", show=False),
        Binding(keybinds.KB_HELP, "show_help", "Help", show=False),
        Binding(keybinds.KB_CONFIG, "show_config", "Config", show=False),
    ]

    def __init__(self, initial_dir: Path, config: Config) -> None:
        super().__init__()
        self._config = config
        self._initial_dir = initial_dir
        self._loaded_path: Path | None = None
        self._pending_load: Path | None = None
        self._pending_quit: bool = False
        self._whisper_prompt: str = ""
        self._player = Player(on_position=self._on_position_cb)

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield TopBar()
        with Horizontal(id="indicator-top"):
            yield IndicatorSegment(id="ind-left", classes="ind-left")
            yield IndicatorSegment(id="ind-wave", classes="ind-wave")
            yield IndicatorSegment(id="ind-edit", classes="ind-edit")
        with Horizontal(id="content"):
            yield LeftPane(self._initial_dir)
            yield WaveformPane()
            yield LyricsEditor()
        yield BottomBar()

    def on_mount(self) -> None:
        # Cache frequently accessed widgets to avoid O(n) DOM traversals in
        # hot paths (_poll_focus fires ~60/s, _handle_tick fires ~10/s during play).
        self._w_top = self.query_one(TopBar)
        self._w_bar = self.query_one(BottomBar)
        self._w_editor = self.query_one(LyricsEditor)
        self._w_waveform = self.query_one(WaveformPane)
        self._w_left = self.query_one(LeftPane)
        # Indicator segments — one per pane, top row only.
        self._ind = {
            "left": self.query_one("#ind-left", IndicatorSegment),
            "wave": self.query_one("#ind-wave", IndicatorSegment),
            "edit": self.query_one("#ind-edit", IndicatorSegment),
        }

        self._w_waveform.set_zoom(self._config.waveform_zoom)
        self._w_waveform.set_volume(self._config.volume)
        self._w_top.set_model(self._config.whisper_model)
        self._w_top.set_language(self._config.whisper_language)

        if self._config.startup_warning:
            self.notify(self._config.startup_warning, severity="warning", timeout=8)

        # Focus the file browser on startup; light its indicator immediately.
        self.query_one(FileBrowser).focus()
        self._light_indicator("left")

        # Poll focus changes at ~60fps.
        # on_focus doesn't reliably bubble to App level in Textual v8.
        # Running at 16ms means pane border switches (add + remove) always
        # land in the same tick — no two borders visible simultaneously.
        self._last_focused: object = None
        self.set_interval(1 / 60, self._poll_focus)

    # ------------------------------------------------------------------
    # Playback tick (comes from mpv thread via call_from_thread)
    # ------------------------------------------------------------------

    def _on_position_cb(self, position: float) -> None:
        self.call_from_thread(self._handle_tick, position)

    def _handle_tick(self, position: float) -> None:
        playing = self._player.is_playing
        self._w_waveform.update_position(position)
        self._w_editor.set_playing(playing)
        self._w_editor.update_position(position)

    # ------------------------------------------------------------------
    # File loading
    # ------------------------------------------------------------------

    def on_file_browser_file_selected(self, event: FileBrowser.FileSelected) -> None:
        event.stop()
        if self._w_editor.is_dirty:
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
        self._whisper_prompt = ""
        info = read_info(path)
        lyrics_text = read_lyrics(path)

        # Determine lyrics type
        lyrics_type: str | None = None
        if lyrics_text is not None:
            lyrics_type = "lrc" if is_lrc(lyrics_text) else "plain"

        # Update player
        self._player.load(path)

        # Update top bar
        self._w_top.set_song(info.display_title())
        self._w_top.set_language(self._config.whisper_language)

        # Update file browser marker
        self._w_left.set_loaded(path)

        # Update bottom bar context
        self._update_bottom_bar(self._classify_focus(self.focused))

        # Decode PCM for waveform (run in thread to avoid blocking)
        self.run_worker(
            self._decode_and_update(path),
            name="decode",
            exclusive=True,
        )

        # Load lyrics into editor
        if lyrics_type == "lrc" and lyrics_text:
            meta, lrc_lines = parse_lrc(lyrics_text)
            word_data = read_word_data(path)
            if word_data:
                attach_word_data(lrc_lines, word_data)
            self._w_editor.load_lines(meta, lrc_lines)
        else:
            # Plain text for existing plain lyrics or empty string for no lyrics —
            # always gives an editable area, never a dead hint screen.
            self._w_editor.load_plain(lyrics_text or "")

        # Save last directory
        self._config.last_directory = str(path.parent)
        save_config(self._config)

    async def _decode_and_update(self, path: Path) -> None:
        loop = asyncio.get_running_loop()
        pcm, sr = await loop.run_in_executor(None, decode_to_pcm, path)
        if len(pcm) == 0:
            self._w_top.set_status("Waveform N/A")
            return
        self._w_waveform.load_pcm(pcm, sr)

    # ------------------------------------------------------------------
    # Unsaved modal callback
    # ------------------------------------------------------------------

    def _unsaved_modal_done(self, choice: str) -> None:
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
        if self._w_editor.is_dirty:
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
        if lyrics_text is None:
            self._w_editor.load_empty()
        else:
            if is_lrc(lyrics_text):
                meta, lrc_lines = parse_lrc(lyrics_text)
                word_data = read_word_data(self._loaded_path)
                if word_data:
                    attach_word_data(lrc_lines, word_data)
                self._w_editor.load_lines(meta, lrc_lines)
            else:
                self._w_editor.load_plain(lyrics_text)
        self._w_top.set_status("Reloaded")

    def action_transcribe(self) -> None:
        if self._loaded_path is None:
            self._w_top.set_status("No file loaded")
            return
        self.run_worker(
            self._run_transcription(self._loaded_path),
            name="transcribe",
            exclusive=True,
        )

    def action_show_prompt(self) -> None:
        # priority=True on the binding means this fires even when a PromptModal
        # is already open and focus is in its TextArea. Forward to submit instead
        # of pushing a second modal on top.
        if isinstance(self.screen, PromptModal):
            self.screen.submit()
            return
        if self._loaded_path is None:
            self._w_top.set_status("No file loaded")
            return
        self.push_screen(
            PromptModal(self._whisper_prompt),
            callback=self._prompt_modal_done,
        )

    def _prompt_modal_done(self, prompt: str | None) -> None:
        """Called when PromptModal closes. None = cancelled; str = submit."""
        if prompt is None:
            return
        self._whisper_prompt = prompt
        if self._loaded_path is not None:
            self.run_worker(
                self._run_transcription(self._loaded_path, prompt=prompt or None),
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
        self._w_top.set_model(self._config.whisper_model)
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
        self._w_top.set_language(self._config.whisper_language)
        save_config(self._config)

    def action_show_help(self) -> None:
        self.push_screen(HelpModal())

    def action_show_config(self) -> None:
        self.push_screen(ConfigModal(self._config), callback=self._config_modal_done)

    def _config_modal_done(self, new_config: Config | None) -> None:
        if new_config is None:
            return
        self._config = new_config
        save_config(new_config)
        self._w_top.set_model(new_config.whisper_model)
        self._w_top.set_language(new_config.whisper_language)
        self._w_top.set_status("Config saved")
        # set_zoom posts ZoomChanged only if value changed, which triggers
        # on_waveform_pane_zoom_changed → save_config again.  The double write
        # is idempotent (same data) and only occurs when zoom actually changes.
        self._w_waveform.set_zoom(new_config.waveform_zoom)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _save_config_with_dir(self) -> None:
        """Update last_directory to the current browser position then save."""
        self._config.last_directory = str(self._w_left.current_directory)
        save_config(self._config)

    def _do_save(self) -> bool:
        """Write current lyrics to the loaded file. Returns True on success."""
        if self._loaded_path is None:
            return False
        text = self._w_editor.current_text()
        if not text:
            self._w_top.set_status("Nothing to save")
            return False
        try:
            write_lyrics(self._loaded_path, text)
            # Persist word timing data alongside lyrics.  write_word_data is
            # best-effort: errors are swallowed internally and never prevent save.
            write_word_data(self._loaded_path, self._w_editor.lrc_lines)
            self._w_top.set_status("Saved")
            # Clear dirty flag without reloading — avoids resetting editor
            # position and losing the active lyric highlight during playback.
            self._w_editor.clear_dirty()
            return True
        except Exception:
            self.push_screen(ErrorModal("Save failed", traceback.format_exc()))
            return False

    async def _run_transcription(self, path: Path, prompt: str | None = None) -> None:
        loop = asyncio.get_running_loop()

        def _progress(msg: str) -> None:
            self.call_from_thread(self._w_top.set_status, msg)

        model = self._config.whisper_model
        language = self._config.whisper_language
        max_words = self._config.whisper_max_words_per_line
        vad_threshold = self._config.vad_threshold
        vad_min_silence_ms = self._config.vad_min_silence_ms

        def _on_lang_detected(lang: str) -> None:
            if language in ("auto", None) and lang:
                self.call_from_thread(self._w_top.set_language, f"auto ({lang})")

        try:
            # Load model (no-op when name and all hardware params are unchanged)
            await loop.run_in_executor(
                None,
                lambda: transcriber.load_model(
                    model,
                    device=self._config.transcription_device,
                    compute_type=self._config.compute_type,
                    cpu_threads=self._config.intra_threads,
                    num_workers=self._config.inter_threads,
                    on_progress=_progress,
                ),
            )

            # Transcribe
            lines = await loop.run_in_executor(
                None,
                lambda: transcriber.transcribe(
                    path,
                    language=language,
                    on_progress=_progress,
                    max_words_per_line=max_words,
                    on_language_detected=_on_lang_detected,
                    vad_threshold=vad_threshold,
                    vad_min_silence_ms=vad_min_silence_ms,
                    initial_prompt=prompt,
                ),
            )
        except Exception:
            self.push_screen(ErrorModal("Transcription failed", traceback.format_exc()))
            return

        self._w_editor.load_lines({}, lines)
        self._w_editor.mark_dirty()
        self._w_top.set_status("Transcribed (unsaved)")

    # ------------------------------------------------------------------
    # Focus tracking for bottom bar context
    # ------------------------------------------------------------------

    def _classify_focus(self, focused: object) -> str:
        """Classify the focused widget into a pane name.

        Returns 'left' | 'wave' | 'edit' | '' (no focus / modal / unknown).
        Called once per focus change; result passed to both _update_bottom_bar
        and _update_indicators so the _in_widget checks run only once.
        """
        if focused is None:
            return ""
        if self._in_widget(focused, LeftPane):
            return "left"
        if self._in_widget(focused, WaveformPane):
            return "wave"
        if self._in_widget(focused, LyricsEditor):
            return "edit"
        return ""

    def _poll_focus(self) -> None:
        if not self.is_running:
            return
        focused = self.focused
        if focused is not self._last_focused:
            self._last_focused = focused
            pane = self._classify_focus(focused)
            self._update_bottom_bar(pane)
            self._update_indicators(pane)

    def _light_indicator(self, pane: str) -> None:
        """Light the given pane's indicator segment and unlit all others.

        pane: 'left' | 'wave' | 'edit' | '' (none — modal / unknown focus).
        Each segment is a childless IndicatorSegment; set_class is O(1).
        """
        for key, seg in self._ind.items():
            seg.set_class(key == pane, "lit")

    def _update_indicators(self, pane: str) -> None:
        """Light the correct indicator segment for *pane*."""
        self._light_indicator(pane)

    @staticmethod
    def _in_widget(focused, cls) -> bool:
        """Return True if focused is an instance of cls or any ancestor is."""
        if isinstance(focused, cls):
            return True
        return any(isinstance(a, cls) for a in focused.ancestors)

    def _update_bottom_bar(self, pane: str) -> None:
        if pane == "wave":
            self._w_bar.set_context("waveform")
        elif pane == "edit":
            mode = self._w_editor.mode
            if mode == "lrc":
                self._w_bar.set_context("lyrics-lrc")
            elif mode == "plain":
                self._w_bar.set_context("lyrics-plain")
            else:
                self._w_bar.set_context("empty")
        elif pane == "left":
            self._w_bar.set_context("browser")
        else:
            self._w_bar.set_context("empty")

    # ------------------------------------------------------------------
    # LRC timestamps → waveform markers
    # ------------------------------------------------------------------

    def _sync_waveform_timestamps(self) -> None:
        """Push current LRC line timestamps to the waveform for marker display."""
        self._w_waveform.set_lrc_timestamps([line.timestamp for line in self._w_editor.lrc_lines])

    # ------------------------------------------------------------------
    # Waveform messages → player + editor sync
    # ------------------------------------------------------------------

    def on_waveform_pane_play_pause_requested(
        self, _event: WaveformPane.PlayPauseRequested
    ) -> None:
        self._player.toggle()
        self._w_editor.set_playing(self._player.is_playing)

    def on_waveform_pane_seek_requested(self, event: WaveformPane.SeekRequested) -> None:
        self._player.seek(event.position)
        self._w_editor.update_position(event.position)

    def on_lyrics_editor_seek_requested(self, event: LyricsEditor.SeekRequested) -> None:
        self._player.seek(event.position)
        self._w_waveform.update_position(event.position)

    def on_lyrics_editor_stop_playback_requested(
        self, _event: LyricsEditor.StopPlaybackRequested
    ) -> None:
        self._player.pause()
        self._w_editor.set_playing(False)

    def on_lyrics_editor_lines_changed(self, _event: LyricsEditor.LinesChanged) -> None:
        self._sync_waveform_timestamps()

    def on_lyrics_editor_play_pause_requested(
        self, _event: LyricsEditor.PlayPauseRequested
    ) -> None:
        self._player.toggle()
        self._w_editor.set_playing(self._player.is_playing)

    def on_lyrics_editor_edit_line_requested(self, event: LyricsEditor.EditLineRequested) -> None:
        idx = event.idx

        def _handle(result: EditLineResult | None) -> None:
            self._w_editor.apply_edit(idx, result)

        self.push_screen(EditLineModal(event.text, idx), callback=_handle)

    # ------------------------------------------------------------------
    # Zoom sync → save to config
    # ------------------------------------------------------------------

    def on_waveform_pane_zoom_changed(self, event: WaveformPane.ZoomChanged) -> None:
        self._config.waveform_zoom = event.zoom
        save_config(self._config)

    def on_waveform_pane_volume_changed(self, event: WaveformPane.VolumeChanged) -> None:
        self._player.volume = event.volume
        self._config.volume = event.volume
        save_config(self._config)

    # ------------------------------------------------------------------
    # Transcribe from left pane key
    # ------------------------------------------------------------------

    def on_left_pane_transcribe_requested(self, _event: LeftPane.TranscribeRequested) -> None:
        self.action_transcribe()

    # ------------------------------------------------------------------
    # App focus — keep widget focus state intact when terminal background
    # ------------------------------------------------------------------

    async def _on_app_blur(self, event) -> None:
        """Suppress Textual's default blur behaviour.

        By default Textual clears the focused widget on AppBlur and tries to
        restore it on AppFocus.  For a music/lyrics editor that runs in the
        background this is unnecessary and causes a visible focus-loss flash
        every time the user alt-tabs or switches terminal tabs.

        prevent_default() stops the MRO walk in _get_dispatch_methods before
        App._on_app_blur runs, so app_focus is never set to False and the
        focused widget is never cleared.
        """
        event.prevent_default()

    # ------------------------------------------------------------------
    # Selection → clipboard
    # ------------------------------------------------------------------

    def on_text_selected(self) -> None:
        """Auto-copy screen-level drag selection to clipboard on mouse-up.

        TextSelected bubbles from Screen on every MouseUp.  The selection
        is populated by _watch__select_end during mouse-move events, so it
        is already settled by the time this handler fires.  Plain clicks
        clear the selection before the event is posted, so get_selected_text
        returns None for them.
        """
        text = self.screen.get_selected_text()
        if text:
            # Spawn and immediately notify — optimistic best-effort: the thread
            # may still fail silently, but we don't wait for it to complete.
            threading.Thread(target=_copy_to_system_clipboard, args=(text,), daemon=True).start()
            self.notify("Copied to clipboard", timeout=3)

    def on_mouse_up(self) -> None:
        """Copy TextArea selection to clipboard on mouse release.

        Screen-level selection is handled by on_text_selected + call_after_refresh.
        TextArea has its own selection mechanism and is explicitly excluded from
        TextSelected events, so we handle it here instead.
        """
        from textual.widgets import TextArea

        focused = self.focused
        if isinstance(focused, TextArea):
            text = focused.selected_text
            if text:
                # Spawn and immediately notify — optimistic best-effort: the thread
                # may still fail silently, but we don't wait for it to complete.
                threading.Thread(
                    target=_copy_to_system_clipboard, args=(text,), daemon=True
                ).start()
                self.notify("Copied to clipboard", timeout=3)
