"""Top info bar: song title, whisper model/language, status."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Label


class TopBar(Widget):
    DEFAULT_CSS = """
    TopBar {
        height: 1;
        layout: horizontal;
        background: $panel;
        color: $text;
    }
    TopBar Label {
        height: 1;
        content-align: left middle;
        padding: 0 1;
    }
    TopBar #song-title {
        width: 1fr;
        text-style: bold;
    }
    TopBar #status {
        width: auto;
        color: $text-muted;
        padding: 0 1;
    }
    TopBar #model-label {
        width: auto;
        color: $text-muted;
    }
    TopBar #lang-label {
        width: auto;
        color: $text-muted;
    }
    """

    song_title: reactive[str] = reactive("No file loaded")
    status: reactive[str] = reactive("")
    model_name: reactive[str] = reactive("base")
    language: reactive[str] = reactive("auto")

    def compose(self) -> ComposeResult:
        yield Label("", id="song-title")
        yield Label("", id="model-label")
        yield Label("", id="lang-label")
        yield Label("", id="status")

    def watch_song_title(self, value: str) -> None:
        self.query_one("#song-title", Label).update(value)

    def watch_status(self, value: str) -> None:
        self.query_one("#status", Label).update(value)

    def watch_model_name(self, value: str) -> None:
        self.query_one("#model-label", Label).update(f" model:{value}")

    def watch_language(self, value: str) -> None:
        self.query_one("#lang-label", Label).update(f" lang:{value}")

    def set_song(self, title: str) -> None:
        self.song_title = title

    def set_status(self, text: str) -> None:
        self.status = text

    def set_model(self, name: str) -> None:
        self.model_name = name

    def set_language(self, lang: str) -> None:
        self.language = lang
