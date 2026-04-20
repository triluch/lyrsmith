"""Modal for editing a single LRC lyric line, with in-place split support."""

from __future__ import annotations

from dataclasses import dataclass

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.timer import Timer
from textual.widgets import Label, Static, TextArea

from ..lrc import WordTiming
from ..word_align import reconcile_word_timings


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


def _fmt_preview(words: list[WordTiming], line_ts: float = 0.0) -> Text:
    """Format reconciled word timings as compact relative-time annotations.

    Times are shown relative to *line_ts* and in seconds only (no minutes)
    to keep the preview short — if a line spans more than a minute the
    relative ordering of words still makes the timing obvious.
    """
    if not words:
        return Text("no timing data", style="dim")
    parts: list[str] = []
    for w in words:
        rel_s = w.start - line_ts
        rel_e = w.end - line_ts
        parts.append(f"{w.word.strip()} [{rel_s:.2f}→{rel_e:.2f}]")
    return Text("  ".join(parts))


# Debounce delay in seconds before the preview is recomputed
_PREVIEW_DELAY = 0.4


class EditLineModal(ModalScreen[EditLineResult]):
    """
    Tiny edit modal for a single LRC line.

    Enter        — save changes
    Ctrl+K       — split at cursor, exit with two lines
    Escape       — cancel, no change

    When word timing data is available for the line, a preview of the
    reconciled word timings appears below the edit field after the user
    stops typing for a moment.
    """

    DEFAULT_CSS = """
    EditLineModal {
        align: center middle;
    }
    EditLineModal Vertical {
        width: 90;
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
    EditLineModal #timing-preview {
        margin-top: 1;
        height: auto;
        max-height: 5;
        color: $text-muted;
        border-top: dashed $panel-darken-2;
        padding-top: 1;
    }
    EditLineModal #timing-preview.hidden {
        display: none;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", priority=True),
        Binding("enter", "save", "Save", priority=True),
        Binding("ctrl+k", "split", "Split here", priority=True),
    ]

    def __init__(
        self,
        text: str,
        line_idx: int,
        words: list[WordTiming] | None = None,
        lang: str = "",
        line_ts: float = 0.0,
    ) -> None:
        super().__init__()
        self._initial_text = text
        self._line_idx = line_idx
        self._words: list[WordTiming] = words or []
        self._lang = lang
        self._line_ts = line_ts
        self._debounce_timer: Timer | None = None

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label(f"Edit line {self._line_idx + 1}", id="edit-hint")
            yield TextArea(self._initial_text, id="edit-area")
            yield Label(
                "Enter  Save    Ctrl+K  Split here    Esc  Cancel",
                id="split-hint",
            )
            yield Static("", id="timing-preview", classes="hidden")

    def on_mount(self) -> None:
        ta = self.query_one("#edit-area", TextArea)
        ta.focus()
        ta.move_cursor(ta.document.end)
        # Show initial preview if word timing data is available
        if self._words:
            self._update_preview()

    # ------------------------------------------------------------------
    # Debounced preview update
    # ------------------------------------------------------------------

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        if not self._words:
            return
        if self._debounce_timer is not None:
            self._debounce_timer.stop()
        self._debounce_timer = self.set_timer(_PREVIEW_DELAY, self._update_preview)

    def _update_preview(self) -> None:
        self._debounce_timer = None
        preview = self.query_one("#timing-preview", Static)
        ta = self.query_one("#edit-area", TextArea)
        current_text = ta.text.strip()
        if not current_text or not self._words:
            preview.add_class("hidden")
            return
        new_words = reconcile_word_timings(
            self._words,
            current_text,
            self._lang,
            line_start=self._line_ts,
        )
        preview.update(_fmt_preview(new_words, self._line_ts))
        preview.remove_class("hidden")

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
