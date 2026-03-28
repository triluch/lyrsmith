"""Bottom info bar: context-sensitive keyhints, built from keybind constants."""

from __future__ import annotations

from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Label

from ..keybinds import (
    KB_BACK,
    KB_DISCARD_RELOAD,
    KB_DELETE_LINE,
    KB_DOWN,
    KB_EDIT_LINE,
    KB_MERGE_LINE,
    KB_NEXT_LANG,
    KB_NEXT_MODEL,
    KB_NUDGE_FINE_BACK,
    KB_NUDGE_FINE_FWD,
    KB_NUDGE_MED_BACK,
    KB_NUDGE_MED_FWD,
    KB_NUDGE_ROUGH_BACK,
    KB_NUDGE_ROUGH_FWD,
    KB_PLAY_PAUSE,
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
    KB_LINE_UP,
    SEEK_SMALL,
    SEEK_LARGE,
    KB_LINE_DOWN,
)

# ------------------------------------------------------------------
# Key-name → display string translation
# ------------------------------------------------------------------

_DISPLAY: dict[str, str] = {
    "space": "Space",
    "enter": "Enter",
    "backspace": "Bksp",
    "tab": "Tab",
    "escape": "Esc",
    "up": "↑",
    "down": "↓",
    "left": "←",
    "right": "→",
    "period": ".",
    "comma": ",",
    "apostrophe": "'",
    "semicolon": ";",
    "left_square_bracket": "\\[",  # escaped for Rich markup
    "right_square_bracket": "]",
    "plus": "+",
    "minus": "-",
    "slash": "/",
    "f1": "F1",
    "f2": "F2",
    "f3": "F3",
    "f4": "F4",
    "f5": "F5",
    "f6": "F6",
    "f7": "F7",
    "f8": "F8",
}


def fmt_key(key: str) -> str:
    """Convert a Textual key string to a short human-readable display form."""
    if key in _DISPLAY:
        return _DISPLAY[key]

    if key.startswith("ctrl+"):
        inner = fmt_key(key[5:])
        return f"Ctrl+{inner.upper() if len(inner) == 1 else inner}"

    if key.startswith("shift+"):
        inner = fmt_key(key[6:])
        return f"⇧{inner}"

    if len(key) == 1:
        return key.upper()

    return key.replace("_", " ").title()


# ------------------------------------------------------------------
# Hint builders — produce Rich markup strings
# ------------------------------------------------------------------

_SEP = "  "
_KC = "#d0d0d0"  # key colour:  light, near-white
_DC = "#707070"  # desc colour: muted gray


def _k(key: str, desc: str) -> str:
    """Single key + description, colour-coded."""
    return f"[{_KC}]{fmt_key(key)}[/] [{_DC}]{desc}[/]"


def _kk(k1: str, k2: str, desc: str, between: str = "") -> str:
    """Two keys (optionally with separator) + description.
    Shared modifier prefixes (ctrl+, shift+) are shown only once."""
    for pfx in ("ctrl+", "shift+"):
        if k1.startswith(pfx) and k2.startswith(pfx):
            sym = "⇧" if pfx == "shift+" else "Ctrl+"
            inner = fmt_key(k1[len(pfx) :]) + between + fmt_key(k2[len(pfx) :])
            return f"[{_KC}]{sym}{inner}[/] [{_DC}]{desc}[/]"
    keys = fmt_key(k1) + between + fmt_key(k2)
    return f"[{_KC}]{keys}[/] [{_DC}]{desc}[/]"


def _build_hints() -> dict[str, str]:
    return {
        "browser": _SEP.join(
            [
                _kk(KB_UP, KB_DOWN, "Navigate"),
                _k(KB_SELECT, "Load"),
                _k(KB_BACK, "Parent"),
                _k(KB_TRANSCRIBE, "Transcribe"),
                _k(KB_NEXT_MODEL, "Model"),
                _k(KB_NEXT_LANG, "Lang"),
                _k(KB_SAVE, "Save"),
                _k(KB_QUIT, "Quit"),
            ]
        ),
        "waveform": _SEP.join(
            [
                _k(KB_PLAY_PAUSE, "Play/Pause"),
                _kk(KB_SEEK_BACK, KB_SEEK_FWD, f"Seek {int(SEEK_SMALL)}s"),
                _kk(KB_SEEK_BACK_LARGE, KB_SEEK_FWD_LARGE, f"Seek {int(SEEK_LARGE)}s"),
                _kk(KB_ZOOM_IN, KB_ZOOM_OUT, "Zoom", "/"),
                _k(KB_SAVE, "Save"),
                _k(KB_QUIT, "Quit"),
            ]
        ),
        "lyrics-lrc": _SEP.join(
            [
                _k(KB_PLAY_PAUSE, "Play/Pause"),
                _kk(KB_SEEK_BACK, KB_SEEK_FWD, f"Seek {int(SEEK_SMALL)}s"),
                _kk(KB_SEEK_BACK_LARGE, KB_SEEK_FWD_LARGE, f"{int(SEEK_LARGE)}s"),
                _kk(KB_LINE_UP, KB_LINE_DOWN, "Navigate"),
                _k(KB_SEEK_TO_LINE, "Seek"),
                _k(KB_STAMP_LINE, "Stamp"),
                _k(KB_UNDO, "Undo"),
                _kk(KB_NUDGE_FINE_BACK, KB_NUDGE_FINE_FWD, "Fine±"),
                _kk(KB_NUDGE_MED_BACK, KB_NUDGE_MED_FWD, "Med±"),
                _kk(KB_NUDGE_ROUGH_BACK, KB_NUDGE_ROUGH_FWD, "Rough±"),
                _k(KB_EDIT_LINE, "Edit/Split"),
                _k(KB_MERGE_LINE, "Merge"),
                _k(KB_DELETE_LINE, "Delete"),
                _k(KB_SAVE, "Save"),
            ]
        ),
        "lyrics-plain": _SEP.join(
            [
                f"[{_DC}]Edit freely[/]",
                _k(KB_SAVE, "Save"),
                _k(KB_DISCARD_RELOAD, "Reload"),
                _k(KB_QUIT, "Quit"),
            ]
        ),
        "empty": _SEP.join(
            [
                f"[{_DC}]Browse to a file and press [{_KC}]{fmt_key(KB_SELECT)}[/][{_DC}] to load[/]",
                _k(KB_QUIT, "Quit"),
            ]
        ),
    }


HINTS = _build_hints()


# ------------------------------------------------------------------
# Widget
# ------------------------------------------------------------------


class BottomBar(Widget):
    DEFAULT_CSS = """
    BottomBar {
        height: 1;
        background: $panel;
        padding: 0 1;
    }
    """

    context: reactive[str] = reactive("empty")

    def compose(self):
        yield Label("", id="hint-label")

    def watch_context(self, value: str) -> None:
        text = HINTS.get(value, "")
        self.query_one("#hint-label", Label).update(text)

    def set_context(self, ctx: str) -> None:
        self.context = ctx
