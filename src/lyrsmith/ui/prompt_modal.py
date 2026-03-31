"""Whisper prompt editor modal.

Opens with Ctrl+U. The user types an initial prompt to guide Whisper's
transcription (e.g. song title, artist, common words). Submit with Ctrl+T
or Ctrl+U; Esc discards without transcribing. The prompt is kept in memory
only and wiped when a new file is loaded.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Label, TextArea


class PromptModal(ModalScreen[str | None]):
    """Edit the Whisper initial prompt.

    Returns the prompt string on submit, None on cancel.
    """

    DEFAULT_CSS = """
    PromptModal {
        align: center middle;
    }
    PromptModal Vertical {
        width: 102;
        height: auto;
        border: solid $accent;
        background: $surface;
        padding: 1 2;
    }
    PromptModal #prompt-title {
        text-style: bold;
        margin-bottom: 1;
    }
    PromptModal #prompt-desc {
        height: 2;
        color: $text-muted;
        margin-bottom: 1;
    }
    PromptModal TextArea {
        height: 14;
        border: solid $panel-darken-2;
    }
    PromptModal #prompt-hint {
        color: $text-muted;
        margin-top: 1;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", priority=True),
        # ctrl+t and ctrl+u are the primary submit keys — reliably distinct in
        # all terminals.  ctrl+enter is kept as a convenience for terminals
        # that support the kitty keyboard protocol.
        Binding("ctrl+t", "submit", "Transcribe", priority=True),
        Binding("ctrl+u", "submit", "Transcribe", priority=True),
        Binding("ctrl+enter", "submit", "Transcribe", priority=True),
    ]

    def __init__(self, current_prompt: str = "") -> None:
        super().__init__()
        self._current_prompt = current_prompt

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("Whisper prompt", id="prompt-title")
            yield Label(
                "Hint text passed to Whisper before transcription. Helps with"
                " spelling, style, and domain-specific words.",
                id="prompt-desc",
            )
            yield TextArea(self._current_prompt, id="prompt-area")
            yield Label(
                "Ctrl+T / Ctrl+U  Transcribe now    Esc  Cancel",
                id="prompt-hint",
            )

    def on_mount(self) -> None:
        ta = self.query_one("#prompt-area", TextArea)
        ta.focus()
        ta.move_cursor(ta.document.end)

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_submit(self) -> None:
        ta = self.query_one("#prompt-area", TextArea)
        self.dismiss(ta.text)
