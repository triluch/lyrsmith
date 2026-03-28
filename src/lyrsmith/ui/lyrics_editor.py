"""
Lyrics editor widget.

Three modes:
  empty  — placeholder, nothing loaded
  plain  — USLT plain text, full TextArea
  lrc    — LRC line list with timestamp editing
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Label, ListItem, ListView, TextArea

from ..lrc import LRCLine, active_line_index, parse, serialize
from .edit_line_modal import EditLineModal, EditLineResult
from ..keybinds import (
    NUDGE_FINE,
    NUDGE_MED,
    NUDGE_ROUGH,
    SEEK_SMALL,
    SEEK_LARGE,
    KB_DELETE_LINE,
    KB_EDIT_LINE,
    KB_MERGE_LINE,
    KB_NUDGE_FINE_FWD,
    KB_NUDGE_FINE_BACK,
    KB_NUDGE_MED_FWD,
    KB_NUDGE_MED_BACK,
    KB_NUDGE_ROUGH_FWD,
    KB_NUDGE_ROUGH_BACK,
    KB_PLAY_PAUSE,
    KB_SEEK_TO_LINE,
    KB_SEEK_FWD,
    KB_SEEK_BACK,
    KB_SEEK_FWD_LARGE,
    KB_SEEK_BACK_LARGE,
    KB_STAMP_LINE,
    KB_UNDO,
)

# key name → nudge delta mapping (uses event.key, consistent with all other bindings).
_KEY_NUDGE: dict[str, float] = {
    KB_NUDGE_FINE_BACK: -NUDGE_FINE,
    KB_NUDGE_FINE_FWD: +NUDGE_FINE,
    KB_NUDGE_MED_BACK: -NUDGE_MED,
    KB_NUDGE_MED_FWD: +NUDGE_MED,
    KB_NUDGE_ROUGH_BACK: -NUDGE_ROUGH,
    KB_NUDGE_ROUGH_FWD: +NUDGE_ROUGH,
}

_EMPTY_HINT = "Select a file and press Enter to load"


# ---------------------------------------------------------------------------
# Pure data operations — no widget dependency, importable for testing
# ---------------------------------------------------------------------------


def _op_nudge(
    lines: list[LRCLine], idx: int, delta: float
) -> tuple[list[LRCLine], int]:
    """Nudge timestamp of line at idx by delta seconds.

    Mutates the list and LRCLine objects in place, re-sorts, and returns
    (lines, new_cursor_idx) so the caller's cursor follows the nudged line.
    Returns (lines, idx) unchanged when idx is out of range.
    """
    if not (0 <= idx < len(lines)):
        return lines, idx
    line = lines[idx]
    line.timestamp = max(0.0, line.timestamp + delta)
    lines.sort(key=lambda l: l.timestamp)
    new_idx = next((i for i, l in enumerate(lines) if l is line), idx)
    return lines, new_idx


def _op_delete(lines: list[LRCLine], idx: int) -> tuple[list[LRCLine], int]:
    """Remove line at idx. Returns (lines, new_cursor_idx).

    Mutates the list in place. Cursor is clamped to the new last index.
    Returns (lines, idx) unchanged when idx is out of range.
    """
    if not (0 <= idx < len(lines)):
        return lines, idx
    lines.pop(idx)
    new_cursor = min(idx, len(lines) - 1) if lines else 0
    return lines, new_cursor


def _op_merge(lines: list[LRCLine], idx: int) -> tuple[list[LRCLine], int]:
    """Merge line at idx with the following line.

    Mutates the list in place; the merged line keeps idx's timestamp.
    Returns (lines, idx) unchanged when idx is the last line or out of range.
    """
    if not (0 <= idx < len(lines) - 1):
        return lines, idx
    merged = _join_lines(lines[idx].text, lines[idx + 1].text)
    lines[idx] = LRCLine(lines[idx].timestamp, merged)
    lines.pop(idx + 1)
    return lines, idx


def _join_lines(a: str, b: str) -> str:
    """Join two lyric parts for merge, lowercasing b's first char when appropriate.

    Rules for b's first character:
    - Keep uppercase if the first word is all-caps (acronym/abbreviation: USA, OK)
    - Keep uppercase if it's the single-letter pronoun "I"
    - Lowercase otherwise (sentence-start capital that no longer starts a sentence)
    """
    if not b:
        return a
    bwords = b.split()
    first_word = bwords[0] if bwords else ""
    if first_word == "I" or (len(first_word) > 1 and first_word.isupper()):
        return f"{a} {b}"
    return f"{a} {b[0].lower()}{b[1:]}"


class LyricsEditor(Widget):
    DEFAULT_CSS = """
    LyricsEditor {
        width: 1fr;
        border: solid $panel-darken-2;
        layout: vertical;
    }
    LyricsEditor:focus-within {
        border: solid $accent;
    }
    LyricsEditor #empty-hint {
        width: 1fr;
        height: 1fr;
        content-align: center middle;
        color: $text-muted;
    }
    LyricsEditor #lrc-list {
        height: 1fr;
    }
    LyricsEditor #plain-area {
        height: 1fr;
    }
    LyricsEditor ListItem {
        padding: 0 1;
    }
    LyricsEditor ListItem.active-line Label {
        text-style: bold;
        color: $accent;
    }
    """

    # ------------------------------------------------------------------
    # Messages
    # ------------------------------------------------------------------

    class SeekRequested(Message):
        def __init__(self, position: float) -> None:
            super().__init__()
            self.position = position

    class StopPlaybackRequested(Message):
        """Editor wants playback stopped (e.g. before entering edit mode)."""

    class PlayPauseRequested(Message):
        """Editor wants playback toggled."""

    # ------------------------------------------------------------------

    def __init__(self) -> None:
        super().__init__()
        self._mode: str = "empty"
        self._lines: list[LRCLine] = []
        self._meta: dict[str, str] = {}
        self._plain_text: str = ""
        self._active_idx: int = -1
        self._cursor_idx: int = 0
        self._is_playing: bool = False
        self._is_dirty: bool = False
        self._loading: bool = False  # suppresses TextArea.Changed during load_text()
        self._current_position: float = 0.0
        self._undo_lines: list[LRCLine] | None = None
        self._undo_cursor: int = 0

    # ------------------------------------------------------------------
    # Compose
    # ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Label(_EMPTY_HINT, id="empty-hint")
        lv = ListView(id="lrc-list")
        lv.display = False
        yield lv
        ta = TextArea(id="plain-area")
        ta.display = False
        yield ta

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_lrc(self, text: str) -> None:
        """Load LRC lyrics text into editor."""
        meta, lines = parse(text)
        self._meta = meta
        self._lines = lines
        self._mode = "lrc"
        self._is_dirty = False
        self._cursor_idx = 0
        self._active_idx = -1
        self._refresh_list()
        self._switch_mode("lrc")

    def load_plain(self, text: str) -> None:
        """Load plain text lyrics into editor."""
        self._loading = True
        self._plain_text = text
        self._mode = "plain"
        self._is_dirty = False
        ta = self.query_one("#plain-area", TextArea)
        ta.load_text(text)
        self._switch_mode("plain")
        # Reset after the queued TextArea.Changed has been processed.
        self.call_after_refresh(self._finish_plain_load)

    def _finish_plain_load(self) -> None:
        self._loading = False
        self._is_dirty = False  # belt-and-suspenders: ensure clean after load

    def load_empty(self) -> None:
        self._mode = "empty"
        self._lines = []
        self._plain_text = ""
        self._is_dirty = False
        self._switch_mode("empty")

    def set_playing(self, playing: bool) -> None:
        self._is_playing = playing

    def clear_dirty(self) -> None:
        """Mark editor as clean without reloading content (used after save)."""
        self._is_dirty = False

    def current_text(self) -> str:
        """Return current work-copy as a string."""
        if self._mode == "lrc":
            return serialize(self._meta, self._lines)
        elif self._mode == "plain":
            return self.query_one("#plain-area", TextArea).text
        return ""

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def is_dirty(self) -> bool:
        return self._is_dirty

    def mark_dirty(self) -> None:
        self._is_dirty = True

    # ------------------------------------------------------------------
    # Playback sync
    # ------------------------------------------------------------------

    def update_position(self, position: float) -> None:
        """Called by app on every playback tick."""
        self._current_position = position
        if self._mode != "lrc":
            return
        idx = active_line_index(self._lines, position)
        if idx == self._active_idx:
            return
        self._active_idx = idx
        self._refresh_active_style()
        if idx >= 0:
            self._jump_to_line(idx)

    # ------------------------------------------------------------------
    # Internals — mode switching
    # ------------------------------------------------------------------

    def _switch_mode(self, mode: str) -> None:
        self.query_one("#empty-hint", Label).display = mode == "empty"
        self.query_one("#lrc-list", ListView).display = mode == "lrc"
        self.query_one("#plain-area", TextArea).display = mode == "plain"

    def _refresh_list(self) -> None:
        lv = self.query_one("#lrc-list", ListView)
        lv.clear()
        for i, line in enumerate(self._lines):
            classes = "active-line" if i == self._active_idx else ""
            lv.append(ListItem(Label(line.display_str()), classes=classes))

    def _refresh_active_style(self) -> None:
        lv = self.query_one("#lrc-list", ListView)
        for i, item in enumerate(lv.children):
            if not isinstance(item, ListItem):
                continue
            if i == self._active_idx:
                item.add_class("active-line")
            else:
                item.remove_class("active-line")
            # Update label text (timestamp may have changed)
            label = item.query_one(Label)
            if i < len(self._lines):
                label.update(self._lines[i].display_str())

    def _jump_to_line(self, idx: int) -> None:
        """80/20 paged scroll: if idx is past 80% of visible rows, jump to 20%."""
        lv = self.query_one("#lrc-list", ListView)
        visible_h = lv.size.height
        if visible_h <= 0:
            return

        # Where is idx relative to current scroll?
        item_h = 1  # each LRC line is 1 row
        current_top = int(lv.scroll_y)
        item_pos = idx * item_h
        relative = (item_pos - current_top) / visible_h

        if relative >= 0.8 or relative < 0:
            # Snap so idx lands at 20%
            new_top = max(0, item_pos - int(0.2 * visible_h))
            lv.scroll_y = new_top

    def _save_undo(self) -> None:
        """Snapshot current lines + cursor for single-level undo."""
        self._undo_lines = [LRCLine(l.timestamp, l.text) for l in self._lines]
        self._undo_cursor = self._cursor_idx

    def _apply_undo(self) -> None:
        if self._undo_lines is None:
            return
        self._lines = self._undo_lines
        self._undo_lines = None
        self._refresh_list()
        self._set_cursor(self._undo_cursor)
        self._mark_dirty()

    def _set_cursor(self, idx: int) -> None:
        """Move ListView cursor to idx and update internal tracking."""
        self._cursor_idx = idx
        lv = self.query_one("#lrc-list", ListView)
        lv.index = idx
        lv.refresh()  # force the highlight CSS to apply in this render frame

    # ------------------------------------------------------------------
    # Keyboard handling (LRC mode)
    # ------------------------------------------------------------------

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        if event.item is None:
            return
        lv = self.query_one("#lrc-list", ListView)
        for i, child in enumerate(lv.children):
            if child is event.item:
                self._cursor_idx = i
                break

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        """Track dirty state for plain text mode. Ignored during initial load."""
        if self._mode == "plain" and not self._loading:
            self._mark_dirty()

    def on_key(self, event) -> None:
        if self._mode != "lrc":
            return

        key = event.key

        # Playback controls — mirror waveform pane so you don't have to switch panes
        if key == KB_PLAY_PAUSE:
            event.stop()
            self.post_message(self.PlayPauseRequested())
            return
        elif key == KB_SEEK_FWD:
            event.stop()
            self.post_message(
                self.SeekRequested(max(0.0, self._current_position + SEEK_SMALL))
            )
            return
        elif key == KB_SEEK_BACK:
            event.stop()
            self.post_message(
                self.SeekRequested(max(0.0, self._current_position - SEEK_SMALL))
            )
            return
        elif key == KB_SEEK_FWD_LARGE:
            event.stop()
            self.post_message(
                self.SeekRequested(max(0.0, self._current_position + SEEK_LARGE))
            )
            return
        elif key == KB_SEEK_BACK_LARGE:
            event.stop()
            self.post_message(
                self.SeekRequested(max(0.0, self._current_position - SEEK_LARGE))
            )
            return

        if key == KB_SEEK_TO_LINE:
            event.stop()
            if 0 <= self._cursor_idx < len(self._lines):
                ts = self._lines[self._cursor_idx].timestamp
                self.post_message(self.SeekRequested(ts))

        elif key == KB_STAMP_LINE:
            event.stop()
            if 0 <= self._cursor_idx < len(self._lines):
                self._save_undo()
                line = self._lines[self._cursor_idx]
                line.timestamp = self._current_position
                self._lines.sort(key=lambda l: l.timestamp)
                self._cursor_idx = next(
                    (i for i, l in enumerate(self._lines) if l is line),
                    self._cursor_idx,
                )
                self._mark_dirty()
                self._refresh_active_style()

        elif key == KB_UNDO:
            event.stop()
            self._apply_undo()

        elif key in _KEY_NUDGE:
            event.stop()
            self._nudge(self._cursor_idx, _KEY_NUDGE[key])

        elif key == KB_DELETE_LINE:
            event.stop()
            self._delete(self._cursor_idx)

        elif key == KB_MERGE_LINE:
            event.stop()
            self._merge(self._cursor_idx)

        elif key == KB_EDIT_LINE:
            event.stop()
            if self._is_playing:
                self.post_message(self.StopPlaybackRequested())
            self._start_edit(self._cursor_idx)

    def _nudge(self, idx: int, delta: float) -> None:
        if not (0 <= idx < len(self._lines)):
            return
        self._lines, self._cursor_idx = _op_nudge(self._lines, idx, delta)
        self._mark_dirty()
        self._refresh_active_style()

    def _delete(self, idx: int) -> None:
        if not (0 <= idx < len(self._lines)):
            return
        self._save_undo()
        self._lines, new_cursor = _op_delete(self._lines, idx)
        self._mark_dirty()
        self._refresh_list()
        if self._lines:
            self._set_cursor(new_cursor)
        else:
            self._cursor_idx = 0

    def _merge(self, idx: int) -> None:
        if not (0 <= idx < len(self._lines) - 1):
            return
        self._save_undo()
        self._lines, _ = _op_merge(self._lines, idx)
        self._mark_dirty()
        self._refresh_list()
        self._set_cursor(idx)

    def _start_edit(self, idx: int) -> None:
        if not (0 <= idx < len(self._lines)):
            return

        def _handle(result: EditLineResult | None) -> None:
            if result is None or result.action == "cancel":
                return

            if result.action == "save":
                if result.text == self._lines[idx].text:
                    return  # nothing changed — leave undo buffer intact
                self._save_undo()
                self._lines[idx].text = result.text
                self._mark_dirty()
                self._refresh_list()
                self._set_cursor(idx)

            elif result.action == "split":
                self._save_undo()
                self._lines[idx].text = result.text
                # Second half timestamp: use current playback position when it
                # falls after the current line; otherwise use the midpoint to the
                # next line (avoids hardcoded offset colliding with neighbour).
                first_ts = self._lines[idx].timestamp
                next_ts = (
                    self._lines[idx + 1].timestamp
                    if idx + 1 < len(self._lines)
                    else first_ts + 2.0
                )
                new_ts = (
                    self._current_position
                    if self._current_position > first_ts
                    else (first_ts + next_ts) / 2
                )
                self._lines.insert(idx + 1, LRCLine(new_ts, result.second))
                self._mark_dirty()
                self._refresh_list()
                self._set_cursor(idx)

        self.app.push_screen(
            EditLineModal(self._lines[idx].text, idx),
            callback=_handle,
        )

    def _mark_dirty(self) -> None:
        self._is_dirty = True
