"""Left pane: file browser (top) + file info panel (bottom)."""

from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.message import Message
from textual.widget import Widget

from .file_browser import FileBrowser
from .file_info import FileInfoPanel
from ..keybinds import KB_TRANSCRIBE
from ..metadata.tags import read_info


class LeftPane(Widget):
    DEFAULT_CSS = """
    LeftPane {
        border: solid $panel-darken-2;
        layout: vertical;
    }
    LeftPane:focus-within {
        border: solid $accent;
    }
    """

    class TranscribeRequested(Message):
        """User pressed Ctrl+T to transcribe the currently loaded file."""

    def __init__(self, initial_path: Path) -> None:
        super().__init__()
        self._initial_path = initial_path

    def compose(self) -> ComposeResult:
        yield FileBrowser(self._initial_path)
        yield FileInfoPanel()

    # ------------------------------------------------------------------
    # Bubble file-browser events upward, updating FileInfoPanel en route
    # ------------------------------------------------------------------

    def on_file_browser_file_highlighted(
        self, event: FileBrowser.FileHighlighted
    ) -> None:
        # Update the info panel; let the event continue bubbling to App.
        try:
            info = read_info(event.path)
        except Exception:
            info = None
        self.query_one(FileInfoPanel).show(info)

    def on_file_browser_dir_changed(self, event: FileBrowser.DirChanged) -> None:
        event.stop()

    def on_key(self, event) -> None:
        if event.key == KB_TRANSCRIBE:
            event.stop()
            self.post_message(self.TranscribeRequested())

    def set_loaded(self, path: Path | None) -> None:
        self.query_one(FileBrowser).set_loaded(path)

    @property
    def current_directory(self) -> Path:
        return self.query_one(FileBrowser).current_path
