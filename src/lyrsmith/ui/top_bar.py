"""Top info bar: song title, whisper model/language, status, F-key shortcuts."""

from __future__ import annotations

import re

from rich.style import Style
from rich.text import Text as RichText
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Label

from .. import keybinds
from .bottom_bar import fmt_key

# Full widget width — padding is removed from CSS and handled manually in content
_STATUS_CONTENT_W = 24
# Background style for the filled (progress) portion
_FILL_STYLE = Style(bgcolor="rgb(0,75,120)")
# Matches "42%" anywhere in a status string
_PCT_RE = re.compile(r"(\d+)%")


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
        width: 24;
        background: $boost;
        color: $text-muted;
        padding: 0 0;
        overflow: hidden hidden;
    }
    TopBar #model-label {
        width: auto;
        color: $text-muted;
    }
    TopBar #lang-label {
        width: auto;
        color: $text-muted;
    }
    TopBar #fn-keys {
        width: auto;
        height: 1;
        background: $primary-darken-2;
        border-left: tall $primary-darken-1;
    }
    TopBar #fn-keys Label {
        height: 1;
        content-align: left middle;
        padding: 0 2;
        color: $primary-lighten-2;
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
        with Horizontal(id="fn-keys"):
            yield Label(f"{fmt_key(keybinds.KB_HELP)} Help", id="f1-label")
            yield Label(f"{fmt_key(keybinds.KB_CONFIG)} Config", id="f2-label")

    def watch_song_title(self, value: str) -> None:
        self.query_one("#song-title", Label).update(value)

    def watch_status(self, value: str) -> None:
        lbl = self.query_one("#status", Label)
        m = _PCT_RE.search(value) if "Transcribing" in value else None
        if m:
            pct = min(100, int(m.group(1)))
            filled = int(_STATUS_CONTENT_W * pct / 100)
            # Prepend a space so the text has a slight left indent; the fill
            # background starts from position 0, covering that space too.
            padded = (" " + value).ljust(_STATUS_CONTENT_W)[:_STATUS_CONTENT_W]
            t = RichText(no_wrap=True, overflow="crop")
            if filled:
                t.append(padded[:filled], style=_FILL_STYLE)
            t.append(padded[filled:])
            lbl.update(t)
        else:
            lbl.update(" " + value)

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
