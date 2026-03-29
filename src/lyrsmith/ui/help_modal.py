"""Help screen modal — full keybind reference grouped by pane."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Label, Static

from ..keybinds import (
    KB_BACK,
    KB_DELETE_LINE,
    KB_DISCARD_RELOAD,
    KB_DOWN,
    KB_EDIT_LINE,
    KB_CONFIG,
    KB_HELP,
    KB_LINE_DOWN,
    KB_LINE_UP,
    KB_MERGE_LINE,
    KB_NEXT_LANG,
    KB_NEXT_MODEL,
    KB_NEXT_PANE,
    KB_NUDGE_FINE_BACK,
    KB_NUDGE_FINE_FWD,
    KB_NUDGE_MED_BACK,
    KB_NUDGE_MED_FWD,
    KB_NUDGE_ROUGH_BACK,
    KB_NUDGE_ROUGH_FWD,
    KB_PLAY_PAUSE,
    KB_PREV_PANE,
    KB_QUIT,
    KB_SAVE,
    KB_SEEK_BACK,
    KB_SEEK_BACK_LARGE,
    KB_SEEK_FWD,
    KB_SEEK_FWD_LARGE,
    KB_SEEK_TO_LINE,
    KB_SELECT,
    KB_STAMP_LINE,
    KB_TRANSCRIBE,
    KB_UNDO,
    KB_UP,
    KB_ZOOM_IN,
    KB_ZOOM_OUT,
    NUDGE_FINE,
    NUDGE_MED,
    NUDGE_ROUGH,
    SEEK_LARGE,
    SEEK_SMALL,
)
from .bottom_bar import fmt_key

_KC = "#d0d0d0"  # key colour
_DC = "#909090"  # description colour
_SEC = "#87ceeb"  # section header colour

# Left column: global + navigation panes
_LEFT_SECTIONS: list[tuple[str, list[tuple[str, str]]]] = [
    (
        "Global",
        [
            (KB_QUIT, "Quit"),
            (KB_SAVE, "Save lyrics to file"),
            (KB_UNDO, "Undo last edit"),
            (KB_DISCARD_RELOAD, "Discard changes and reload"),
            (KB_TRANSCRIBE, "Transcribe with Whisper"),
            (KB_NEXT_MODEL, "Cycle Whisper model"),
            (KB_NEXT_LANG, "Cycle Whisper language"),
            (KB_NEXT_PANE, "Focus next pane"),
            (KB_PREV_PANE, "Focus previous pane"),
            (KB_HELP, "This help screen"),
            (KB_CONFIG, "Config editor"),
        ],
    ),
    (
        "File Browser",
        [
            (KB_UP, "Move selection up"),
            (KB_DOWN, "Move selection down"),
            (KB_SELECT, "Load selected file"),
            (KB_BACK, "Go up one directory (or trim filter)"),
            ("a-z", "Filter list by name, Esc to clear"),
        ],
    ),
    (
        "Waveform Pane",
        [
            (KB_PLAY_PAUSE, "Play / Pause"),
            (KB_SEEK_FWD, f"Seek forward {int(SEEK_SMALL)}s"),
            (KB_SEEK_BACK, f"Seek back {int(SEEK_SMALL)}s"),
            (KB_SEEK_FWD_LARGE, f"Seek forward {int(SEEK_LARGE)}s"),
            (KB_SEEK_BACK_LARGE, f"Seek back {int(SEEK_LARGE)}s"),
            (KB_ZOOM_IN, "Zoom in"),
            (KB_ZOOM_OUT, "Zoom out"),
        ],
    ),
]

# Right column: lyrics editor
_RIGHT_SECTIONS: list[tuple[str, list[tuple[str, str]]]] = [
    (
        "Lyrics Editor — LRC mode",
        [
            (KB_LINE_UP, "Move selection up"),
            (KB_LINE_DOWN, "Move selection down"),
            (KB_PLAY_PAUSE, "Play / Pause"),
            (KB_SEEK_TO_LINE, "Seek to line timestamp"),
            (KB_STAMP_LINE, "Stamp time to line"),
            (KB_EDIT_LINE, "Edit / split line (Ctrl+K to split)"),
            (KB_MERGE_LINE, "Merge line with next"),
            (KB_DELETE_LINE, "Delete line"),
            (KB_UNDO, "Undo"),
            (KB_SEEK_FWD, f"Seek forward {int(SEEK_SMALL)}s"),
            (KB_SEEK_BACK, f"Seek back {int(SEEK_SMALL)}s"),
            (KB_SEEK_FWD_LARGE, f"Seek forward {int(SEEK_LARGE)}s"),
            (KB_SEEK_BACK_LARGE, f"Seek back {int(SEEK_LARGE)}s"),
            (KB_NUDGE_FINE_FWD, f"Nudge +{int(NUDGE_FINE * 1000)}ms"),
            (KB_NUDGE_FINE_BACK, f"Nudge \u2212{int(NUDGE_FINE * 1000)}ms"),
            (KB_NUDGE_MED_FWD, f"Nudge +{int(NUDGE_MED * 1000)}ms"),
            (KB_NUDGE_MED_BACK, f"Nudge \u2212{int(NUDGE_MED * 1000)}ms"),
            (KB_NUDGE_ROUGH_FWD, f"Nudge +{int(NUDGE_ROUGH)}s"),
            (KB_NUDGE_ROUGH_BACK, f"Nudge \u2212{int(NUDGE_ROUGH)}s"),
        ],
    ),
]


def _vis_width(s: str) -> int:
    """Visible terminal width of a fmt_key() result.

    Rich markup escapes '\\[' as a two-char sequence that renders as one '[',
    so we strip the backslash before measuring.  All other characters in our
    key strings are single-width ASCII or single-width Unicode symbols (⇧ ↑
    ↓ ← →), so plain len() is accurate after that substitution.
    """
    return len(s.replace("\\[", "["))


def _render_col(sections: list[tuple[str, list[tuple[str, str]]]]) -> str:
    """Build Rich markup string with descriptions aligned in a fixed column."""
    # Pre-render key strings so we can measure their visible widths.
    rows: list[tuple[str, str, str]] = []  # (title_or_"", key_display, desc)
    for title, binds in sections:
        rows.append((title, "", ""))
        for key, desc in binds:
            rows.append(("", fmt_key(key), desc))

    max_kw = max((_vis_width(k) for _, k, _ in rows if k), default=0)

    lines: list[str] = []
    section_idx = -1
    for title, key_display, desc in rows:
        if title:
            section_idx += 1
            if section_idx > 0:
                lines.append("")
            lines.append(f"[bold {_SEC}]{title}[/]")
        else:
            pad = " " * (max_kw - _vis_width(key_display))
            lines.append(f"  [{_KC}]{key_display}{pad}[/]  [{_DC}]{desc}[/]")
    return "\n".join(lines)


_LEFT_TEXT = _render_col(_LEFT_SECTIONS)
_RIGHT_TEXT = _render_col(_RIGHT_SECTIONS)


class HelpModal(ModalScreen):
    """Full keybind reference. Dismiss with Escape or F1."""

    DEFAULT_CSS = """
    HelpModal {
        align: center middle;
    }
    HelpModal #outer {
        width: 100;
        height: auto;
        max-height: 90%;
        border: solid $accent;
        background: $surface;
    }
    HelpModal #title-bar {
        width: 1fr;
        height: 1;
        background: $accent;
        color: $background;
        content-align: center middle;
        text-style: bold;
        padding: 0 1;
    }
    HelpModal #close-hint {
        height: 1;
        width: 1fr;
        text-align: right;
        color: #606060;
        padding: 0 1;
    }
    HelpModal #columns {
        height: auto;
        padding: 0 2 1 2;
    }
    HelpModal .col {
        width: 1fr;
    }
    HelpModal #col-left {
        padding-right: 2;
        border-right: solid #333333;
    }
    HelpModal #col-right {
        padding-left: 2;
    }
    """

    BINDINGS = [
        Binding("escape", "dismiss", "Close", priority=True),
        Binding(KB_HELP, "dismiss", "", priority=True, show=False),
        Binding(KB_CONFIG, "dismiss", "", priority=True, show=False),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(id="outer"):
            yield Label("Keybindings", id="title-bar")
            yield Label(
                f"[#606060]Esc / {fmt_key(KB_HELP)} / {fmt_key(KB_CONFIG)} to close[/]",
                id="close-hint",
            )
            with Horizontal(id="columns"):
                yield Static(_LEFT_TEXT, classes="col", id="col-left")
                yield Static(_RIGHT_TEXT, classes="col", id="col-right")

    def on_mount(self) -> None:
        self.query_one("#col-left", Static).focus()
