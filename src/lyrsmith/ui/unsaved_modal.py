"""Modal dialog for unsaved changes."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Label, ListItem, ListView

_CHOICES: dict[str, tuple[str, str, str]] = {
    # context → (message, discard label, save label)
    "load": (
        "You have unsaved changes.",
        "2  Discard changes and load anyway",
        "3  Save and load",
    ),
    "quit": (
        "You have unsaved changes.",
        "2  Discard changes and quit",
        "3  Save and quit",
    ),
}

# Maps ListView index → dismiss value
_IDX_TO_ACTION = ["back", "discard", "save"]


class UnsavedModal(ModalScreen[str]):
    """
    Returns one of: 'back', 'discard', 'save'.
    Navigate with ↑↓ or 1/2/3, confirm with Enter, cancel with Escape.
    """

    DEFAULT_CSS = """
    UnsavedModal {
        align: center middle;
    }
    UnsavedModal Vertical {
        width: 56;
        height: auto;
        border: solid $accent;
        background: $surface;
        padding: 1 2;
    }
    UnsavedModal #modal-message {
        width: 1fr;
        text-align: center;
        margin-bottom: 1;
        color: $text;
    }
    UnsavedModal ListView {
        height: auto;
        border: none;
        background: transparent;
    }
    UnsavedModal ListItem {
        padding: 0 1;
    }
    """

    BINDINGS = [
        Binding("escape", "back", "Back", priority=True),
        Binding("1", "pick_1", "", priority=True, show=False),
        Binding("2", "pick_2", "", priority=True, show=False),
        Binding("3", "pick_3", "", priority=True, show=False),
    ]

    def __init__(self, context: str = "load") -> None:
        super().__init__()
        self._ctx = context
        msg, discard_lbl, save_lbl = _CHOICES.get(context, _CHOICES["load"])
        self._message = msg
        self._discard_label = discard_lbl
        self._save_label = save_lbl

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label(self._message, id="modal-message")
            yield ListView(
                ListItem(Label("1  Go back to editing")),
                ListItem(Label(self._discard_label)),
                ListItem(Label(self._save_label)),
                id="modal-list",
            )

    def on_mount(self) -> None:
        self.query_one("#modal-list", ListView).focus()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        lv = self.query_one("#modal-list", ListView)
        idx = lv.index
        if idx is not None and 0 <= idx < len(_IDX_TO_ACTION):
            self.dismiss(_IDX_TO_ACTION[idx])

    def action_back(self) -> None:
        self.dismiss("back")

    def action_pick_1(self) -> None:
        self.dismiss("back")

    def action_pick_2(self) -> None:
        self.dismiss("discard")

    def action_pick_3(self) -> None:
        self.dismiss("save")
