"""Modal for shifting all LRC timestamps together."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Label

from .. import keybinds
from .bottom_bar import fmt_key

_KEY_NUDGE: dict[str, float] = {
    keybinds.KB_NUDGE_FINE_BACK: -keybinds.NUDGE_FINE,
    keybinds.KB_NUDGE_FINE_FWD: +keybinds.NUDGE_FINE,
    keybinds.KB_NUDGE_MED_BACK: -keybinds.NUDGE_MED,
    keybinds.KB_NUDGE_MED_FWD: +keybinds.NUDGE_MED,
    keybinds.KB_NUDGE_ROUGH_BACK: -keybinds.NUDGE_ROUGH,
    keybinds.KB_NUDGE_ROUGH_FWD: +keybinds.NUDGE_ROUGH,
}

_KC = "#d0d0d0"
_DC = "#909090"
_SC = "#606060"


def _fmt_offset(value: float) -> str:
    if abs(value) < 1e-9:
        return "0.0s"
    return f"{value:+.1f}s"


def _fmt_pair(back: str, fwd: str, desc: str) -> str:
    return f"[{_KC}]{fmt_key(back)}[/][{_SC}]/[/][{_KC}]{fmt_key(fwd)}[/] [{_DC}]{desc}[/]"


def _fmt_action(key: str, desc: str) -> str:
    return f"[{_KC}]{fmt_key(key)}[/] [{_DC}]{desc}[/]"


class GlobalOffsetModal(ModalScreen[float | None]):
    DEFAULT_CSS = """
    GlobalOffsetModal {
        align: center middle;
    }
    GlobalOffsetModal #dialog {
        width: 66;
        height: auto;
        border: solid $accent;
        background: $surface;
        padding: 1 2;
    }
    GlobalOffsetModal #offset-title {
        height: 1;
        text-style: bold;
        margin-bottom: 1;
    }
    GlobalOffsetModal #offset-row {
        width: 1fr;
        height: 1;
        margin-bottom: 1;
    }
    GlobalOffsetModal #offset-earlier {
        width: 1fr;
        content-align: left middle;
        color: $text-muted;
    }
    GlobalOffsetModal #offset-value {
        width: auto;
        min-width: 8;
        content-align: center middle;
        text-style: bold;
    }
    GlobalOffsetModal #offset-later {
        width: 1fr;
        content-align: right middle;
        color: $text-muted;
    }
    GlobalOffsetModal #nudge-row,
    GlobalOffsetModal #action-row {
        width: 1fr;
        height: 1;
    }
    GlobalOffsetModal #nudge-left,
    GlobalOffsetModal #nudge-center,
    GlobalOffsetModal #nudge-right,
    GlobalOffsetModal #action-left,
    GlobalOffsetModal #action-center,
    GlobalOffsetModal #action-right {
        height: 1;
    }
    GlobalOffsetModal #nudge-left,
    GlobalOffsetModal #action-left {
        width: 1fr;
        content-align: left middle;
    }
    GlobalOffsetModal #nudge-center {
        width: 1fr;
        content-align: center middle;
    }
    GlobalOffsetModal #action-center {
        width: 1fr;
    }
    GlobalOffsetModal #nudge-right,
    GlobalOffsetModal #action-right {
        width: 1fr;
        content-align: right middle;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", priority=True),
        Binding("enter", "apply_offset", "Apply", priority=True),
        Binding(keybinds.KB_NUDGE_FINE_BACK, "nudge(-0.01)", show=False, priority=True),
        Binding(keybinds.KB_NUDGE_FINE_FWD, "nudge(0.01)", show=False, priority=True),
        Binding(keybinds.KB_NUDGE_MED_BACK, "nudge(-0.1)", show=False, priority=True),
        Binding(keybinds.KB_NUDGE_MED_FWD, "nudge(0.1)", show=False, priority=True),
        Binding(keybinds.KB_NUDGE_ROUGH_BACK, "nudge(-1.0)", show=False, priority=True),
        Binding(keybinds.KB_NUDGE_ROUGH_FWD, "nudge(1.0)", show=False, priority=True),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._offset = 0.0

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label("Global line offset", id="offset-title")
            with Horizontal(id="offset-row"):
                yield Label("[- Earlier]", id="offset-earlier")
                yield Label(_fmt_offset(self._offset), id="offset-value")
                yield Label("[Later +]", id="offset-later")
            with Horizontal(id="nudge-row"):
                yield Label(
                    _fmt_pair(
                        keybinds.KB_NUDGE_FINE_BACK,
                        keybinds.KB_NUDGE_FINE_FWD,
                        "fine",
                    ),
                    id="nudge-left",
                )
                yield Label(
                    _fmt_pair(
                        keybinds.KB_NUDGE_MED_BACK,
                        keybinds.KB_NUDGE_MED_FWD,
                        "medium",
                    ),
                    id="nudge-center",
                )
                yield Label(
                    _fmt_pair(
                        keybinds.KB_NUDGE_ROUGH_BACK,
                        keybinds.KB_NUDGE_ROUGH_FWD,
                        "rough",
                    ),
                    id="nudge-right",
                )
            with Horizontal(id="action-row"):
                yield Label(_fmt_action("escape", "Cancel"), id="action-left")
                yield Label("", id="action-center")
                yield Label(_fmt_action("enter", "Apply"), id="action-right")

    def action_nudge(self, delta: float) -> None:
        self._offset = round(self._offset + delta, 3)
        self.query_one("#offset-value", Label).update(_fmt_offset(self._offset))

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_apply_offset(self) -> None:
        self.dismiss(self._offset)
