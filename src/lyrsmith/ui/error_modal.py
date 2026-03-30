"""Modal for displaying error details with full traceback."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Label, TextArea


class ErrorModal(ModalScreen[None]):
    """Full-screen error detail view — shows title and complete traceback."""

    BINDINGS = [
        Binding("escape", "dismiss", "Close"),
        Binding("enter", "dismiss", "Close"),
    ]

    DEFAULT_CSS = """
    ErrorModal {
        align: center middle;
    }
    ErrorModal #outer {
        width: 88;
        max-height: 80%;
        background: $surface;
    }
    ErrorModal #title-bar {
        width: 1fr;
        height: 1;
        background: $error;
        color: $background;
        content-align: left middle;
        text-style: bold;
        padding: 0 1;
    }
    ErrorModal #hint {
        height: 1;
        width: 1fr;
        text-align: right;
        color: #606060;
        padding: 0 1;
    }
    ErrorModal TextArea {
        height: 1fr;
        border: none;
        padding: 0;
    }
    """

    def __init__(self, title: str, detail: str) -> None:
        super().__init__()
        self._title = title
        self._detail = detail

    def compose(self) -> ComposeResult:
        with Vertical(id="outer"):
            yield Label(self._title, id="title-bar")
            yield TextArea(
                self._detail,
                read_only=True,
                show_line_numbers=False,
                id="traceback",
            )
            yield Label("enter/esc  close", id="hint")

    def action_dismiss(self) -> None:
        self.dismiss()
