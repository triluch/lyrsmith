"""Modal for editing a single LRC lyric line, with in-place split support."""

from __future__ import annotations

from dataclasses import dataclass

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Label, TextArea


@dataclass
class EditLineResult:
    action: str  # "save" | "split" | "cancel"
    text: str = ""  # updated text for current line
    second: str = ""  # second line text (only when action=="split")


def _split_at_cursor(text: str, col: int) -> tuple[str, str]:
    """
    Split text at col, strip whitespace around the cut, and capitalise the
    first letter of the second part (it's now a new line start).
    Mirrors the _join_lines() case rules in reverse.
    """
    first = text[:col].rstrip()
    second = text[col:].lstrip()
    if second and not second[0].isupper():
        second = second[0].upper() + second[1:]
    return first, second


class EditLineModal(ModalScreen[EditLineResult]):
    """
    Tiny edit modal for a single LRC line.

    Enter        — save changes
    Ctrl+Enter   — split at cursor, exit with two lines
    Escape       — cancel, no change
    """

    DEFAULT_CSS = """
    EditLineModal {
        align: center middle;
    }
    EditLineModal Vertical {
        width: 70;
        height: auto;
        border: solid $accent;
        background: $surface;
        padding: 1 2;
    }
    EditLineModal #edit-hint {
        color: $text-muted;
        margin-bottom: 1;
    }
    EditLineModal TextArea {
        height: 3;
        border: solid $panel-darken-2;
    }
    EditLineModal #split-hint {
        color: $text-muted;
        margin-top: 1;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", priority=True),
        Binding("enter", "save", "Save", priority=True),
        Binding("ctrl+k", "split", "Split here", priority=True),
    ]

    def __init__(self, text: str, line_idx: int) -> None:
        super().__init__()
        self._initial_text = text
        self._line_idx = line_idx

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label(f"Edit line {self._line_idx + 1}", id="edit-hint")
            yield TextArea(self._initial_text, id="edit-area")
            yield Label(
                "Enter  Save    Ctrl+K  Split here    Esc  Cancel",
                id="split-hint",
            )

    def on_mount(self) -> None:
        ta = self.query_one("#edit-area", TextArea)
        ta.focus()
        # Move cursor to end of text
        ta.move_cursor(ta.document.end)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def action_cancel(self) -> None:
        self.dismiss(EditLineResult(action="cancel"))

    def action_save(self) -> None:
        ta = self.query_one("#edit-area", TextArea)
        self.dismiss(EditLineResult(action="save", text=ta.text.strip()))

    def action_split(self) -> None:
        ta = self.query_one("#edit-area", TextArea)
        row, col = ta.cursor_location
        # col is the character offset within the current row, not into the full
        # string. Compute the absolute text offset to handle multi-row content.
        # splitlines(keepends=True) preserves actual line endings (\n or \r\n)
        # so len(line) accounts for the real separator without a hardcoded +1.
        lines = ta.text.splitlines(keepends=True)
        offset = sum(len(line) for line in lines[:row]) + col
        first, second = _split_at_cursor(ta.text, offset)
        self.dismiss(EditLineResult(action="split", text=first, second=second))
