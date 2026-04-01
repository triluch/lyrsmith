"""Left pane: file browser (top) + file info panel (bottom)."""

from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.message import Message
from textual.timer import Timer
from textual.widget import Widget
from textual.worker import get_current_worker

from .. import keybinds
from ..metadata.tags import read_info
from .file_browser import FileBrowser
from .file_info import FileInfoPanel

# How long the cursor must rest on a file before we do a tag read.
# Eliminates I/O on every keystroke during rapid arrow-key navigation.
_INFO_DEBOUNCE_S = 0.15


class LeftPane(Widget):
    DEFAULT_CSS = """
    LeftPane {
        border: solid $panel-darken-2;
        layout: vertical;
    }
    """

    class TranscribeRequested(Message):
        """User pressed Ctrl+T to transcribe the currently loaded file."""

    def __init__(self, initial_path: Path) -> None:
        super().__init__()
        self._initial_path = initial_path
        self._info_timer: Timer | None = None

    def compose(self) -> ComposeResult:
        yield FileBrowser(self._initial_path)
        yield FileInfoPanel()

    def on_unmount(self) -> None:
        if self._info_timer is not None:
            self._info_timer.stop()
            self._info_timer = None

    # ------------------------------------------------------------------
    # Bubble file-browser events upward, updating FileInfoPanel en route
    # ------------------------------------------------------------------

    def on_file_browser_file_highlighted(self, event: FileBrowser.FileHighlighted) -> None:
        # Debounce: cancel any pending read and reschedule.
        # During rapid keyboard navigation no I/O happens; read fires only
        # once the cursor settles.
        if self._info_timer is not None:
            self._info_timer.stop()
        path = event.path
        self._info_timer = self.set_timer(_INFO_DEBOUNCE_S, lambda: self._update_file_info(path))

    def _update_file_info(self, path: Path) -> None:
        self._info_timer = None
        try:
            info = read_info(path)
        except Exception:
            info = None
        self.query_one(FileInfoPanel).show(info)

    def on_file_browser_dir_changed(self, event: FileBrowser.DirChanged) -> None:
        event.stop()
        # Clear stale info immediately.
        self.query_one(FileInfoPanel).show(None)
        # Cancel any pending info timer — cursor position is now undefined.
        if self._info_timer is not None:
            self._info_timer.stop()
            self._info_timer = None
        # Warm the cache for all audio files in the new directory in the
        # background so subsequent cursor moves are instant cache hits.
        if event.audio_files:
            self.query_one(FileBrowser).set_warming(True)
            self.run_worker(
                lambda: self._warm_cache(event.audio_files),
                name="cache-warm",
                exclusive=True,
                thread=True,
            )

    def _warm_cache(self, files: list[Path]) -> None:
        """Run in a thread: pre-populate the SQLite metadata cache for all files.

        On first run each file needs a full tag read; on subsequent runs the
        SQLite cache returns immediately for unchanged files.  After all files
        are warm, FileBrowser.set_warming(False) is called on the UI thread so
        the in-progress indicator is removed and any items that were shown
        conservatively (cache miss during filter) get re-evaluated.
        """
        worker = get_current_worker()
        for path in files:
            if worker.is_cancelled:
                return
            try:
                read_info(path)
            except Exception:
                pass
        # Clear the in-progress indicator and re-evaluate the filter.
        # Guard against cancelled workers: a stale warm-up must not clear a
        # freshly-started indicator for a new directory.
        if not worker.is_cancelled:
            self.app.call_from_thread(lambda: self.query_one(FileBrowser).set_warming(False))

    # ------------------------------------------------------------------

    def on_key(self, event) -> None:
        if event.key == keybinds.KB_TRANSCRIBE:
            event.stop()
            self.post_message(self.TranscribeRequested())

    def set_loaded(self, path: Path | None) -> None:
        self.query_one(FileBrowser).set_loaded(path)

    @property
    def current_directory(self) -> Path:
        return self.query_one(FileBrowser).current_path
