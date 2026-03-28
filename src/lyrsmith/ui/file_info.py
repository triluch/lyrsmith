"""Left pane bottom: tag summary for the currently highlighted file."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Label

from ..metadata.cache import FileInfo as FileInfoData


class FileInfoPanel(Widget):
    DEFAULT_CSS = """
    FileInfoPanel {
        height: 7;
        border-top: solid $panel-darken-2;
        padding: 0 1;
        background: $panel;
    }
    FileInfoPanel Label {
        height: 1;
    }
    FileInfoPanel #fi-title  { color: $text; text-style: bold; }
    FileInfoPanel #fi-artist { color: $text-muted; }
    FileInfoPanel #fi-album  { color: $text-muted; }
    FileInfoPanel #fi-lyrics { color: $accent; }
    """

    def compose(self) -> ComposeResult:
        yield Label("", id="fi-title")
        yield Label("", id="fi-artist")
        yield Label("", id="fi-album")
        yield Label("", id="fi-lyrics")

    def show(self, info: FileInfoData | None) -> None:
        if info is None:
            self.query_one("#fi-title", Label).update("")
            self.query_one("#fi-artist", Label).update("")
            self.query_one("#fi-album", Label).update("")
            self.query_one("#fi-lyrics", Label).update("")
            return

        self.query_one("#fi-title", Label).update(info.title or info.path.name)
        self.query_one("#fi-artist", Label).update(info.artist or "—")
        self.query_one("#fi-album", Label).update(info.album or "—")
        self.query_one("#fi-lyrics", Label).update(info.lyrics_label())
