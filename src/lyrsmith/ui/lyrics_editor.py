"""
Lyrics editor widget.

Three modes:
  empty  — placeholder, nothing loaded
  plain  — USLT plain text, full TextArea
  lrc    — LRC line list with timestamp editing
"""

from __future__ import annotations

from collections import deque

from textual.app import ComposeResult
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Label, ListItem, ListView, TextArea

from .. import keybinds
from ..debug import log_lrc_operation, snapshot_lrc_lines
from ..lrc import LRCLine, active_line_index, parse, serialize
from ..word_align import reconcile_word_timings
from ._fast_list_view import FastListView
from .edit_line_modal import EditLineResult

# key name → nudge delta mapping (uses event.key, consistent with all other bindings).
_KEY_NUDGE: dict[str, float] = {
    keybinds.KB_NUDGE_FINE_BACK: -keybinds.NUDGE_FINE,
    keybinds.KB_NUDGE_FINE_FWD: +keybinds.NUDGE_FINE,
    keybinds.KB_NUDGE_MED_BACK: -keybinds.NUDGE_MED,
    keybinds.KB_NUDGE_MED_FWD: +keybinds.NUDGE_MED,
    keybinds.KB_NUDGE_ROUGH_BACK: -keybinds.NUDGE_ROUGH,
    keybinds.KB_NUDGE_ROUGH_FWD: +keybinds.NUDGE_ROUGH,
}

_EMPTY_HINT = "Select a file and press Enter to load"


# ---------------------------------------------------------------------------
# Pure data operations — no widget dependency, importable for testing
# ---------------------------------------------------------------------------


def _op_nudge(lines: list[LRCLine], idx: int, delta: float) -> tuple[list[LRCLine], int]:
    """Nudge timestamp of line at idx by delta seconds.

    Mutates the list and LRCLine objects in place, re-sorts, and returns
    (lines, new_cursor_idx) so the caller's cursor follows the nudged line.
    Returns (lines, idx) unchanged when idx is out of range.
    """
    if not (0 <= idx < len(lines)):
        return lines, idx
    line = lines[idx]
    _shift_line_timing(line, delta)
    lines.sort(key=lambda l: l.timestamp)
    new_idx = next((i for i, l in enumerate(lines) if l is line), idx)
    return lines, new_idx


def _shift_line_timing(line: LRCLine, delta: float) -> None:
    """Shift a line timestamp and all attached timing data by *delta*."""
    line.timestamp = max(0.0, line.timestamp + delta)
    if line.end is not None:
        line.end = max(0.0, line.end + delta)
    for w in line.words:
        w.start = max(0.0, w.start + delta)
        w.end = max(0.0, w.end + delta)


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
    If either line has blank text it is absorbed cleanly without concatenation
    (avoids a leading space or spurious lower-casing from _join_lines).
    Returns (lines, idx) unchanged when idx is the last line or out of range.
    """
    if not (0 <= idx < len(lines) - 1):
        return lines, idx
    a, b = lines[idx], lines[idx + 1]
    if not b.text.strip():
        # Next line is blank (covers both-blank too) — just drop it; keep current as-is.
        pass
    elif not a.text.strip():
        # Current line is blank — replace with next line's content, then drop it.
        lines[idx] = b
    else:
        lines[idx] = LRCLine(
            a.timestamp,
            _join_lines(a.text, b.text),
            end=b.end,
            words=a.words + b.words,
        )
    lines.pop(idx + 1)
    return lines, idx


def _op_insert_blank(lines: list[LRCLine], idx: int) -> tuple[list[LRCLine], int]:
    """Insert a blank LRCLine immediately after idx.

    Timestamp: the current line's end, or midpoint to the next line if no
    end is set, or +2 s when there is no next line.
    End: the next line's timestamp if one exists, otherwise None.
    Returns (lines, new_cursor_idx) where new_cursor_idx points at the
    inserted line.  Returns unchanged when idx is out of range.
    """
    if not (0 <= idx < len(lines)):
        return lines, idx
    current = lines[idx]
    next_line = lines[idx + 1] if idx + 1 < len(lines) else None

    if current.end is not None:
        new_ts = current.end
    elif next_line is not None:
        new_ts = (current.timestamp + next_line.timestamp) / 2
    else:
        new_ts = current.timestamp + 2.0

    new_end = next_line.timestamp if next_line is not None else None
    lines.insert(idx + 1, LRCLine(timestamp=new_ts, text="", end=new_end, words=[]))
    return lines, idx + 1


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
    if first_word == "I" or (len(first_word) > 1 and first_word.rstrip(".,!?").isupper()):
        return f"{a} {b}"
    return f"{a} {b[0].lower()}{b[1:]}"


class LyricsEditor(Widget):
    DEFAULT_CSS = """
    LyricsEditor {
        width: 1fr;
        border: solid $panel-darken-2;
        layout: vertical;
    }
    LyricsEditor ListView:focus {
        background-tint: $foreground 0%;
    }
    /* Always-focused cursor — specificity 0,2,3 beats ListView:focus 0,2,2. */
    LyricsEditor ListView.always-focused-cursor ListItem.-highlight {
        color: $block-cursor-foreground;
        background: $block-cursor-background;
        text-style: $block-cursor-text-style;
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
        layout: horizontal;
    }
    LyricsEditor ListItem .line-text {
        width: 1fr;
    }
    LyricsEditor ListItem .end-ts {
        width: auto;
        color: #627080;
    }
    LyricsEditor ListItem.active-line .line-text {
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

    class LinesChanged(Message):
        """Emitted after any LRC mutation (stamp, nudge, delete, insert, merge, split, undo)."""

    class EditLineRequested(Message):
        """Editor wants to open the edit modal for a specific line.

        The app layer is responsible for pushing EditLineModal and calling
        ``apply_edit`` with the result.
        """

        def __init__(self, idx: int, text: str) -> None:
            super().__init__()
            self.idx = idx
            self.text = text

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
        self._saved_hash: int = 0  # hash of serialized content at last save/load
        self._loading: bool = False  # suppresses TextArea.Changed during load_text()
        self._load_gen: int = 0  # incremented on each load; callbacks self-cancel if stale
        self._current_position: float = 0.0
        self._undo_stack: deque[tuple[list[LRCLine], int]] = deque(maxlen=50)
        self._list_items: list[ListItem] = []

    # ------------------------------------------------------------------
    # Compose
    # ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Label(_EMPTY_HINT, id="empty-hint")
        lv = FastListView(id="lrc-list")
        lv.display = False
        yield lv
        ta = TextArea(id="plain-area")
        ta.display = False
        yield ta

    def on_mount(self) -> None:
        # Add class while ListView is empty → walk_children costs O(0).
        self.query_one("#lrc-list", ListView).add_class("always-focused-cursor")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_lrc(self, text: str) -> None:
        """Load LRC lyrics text into editor."""
        meta, lines = parse(text)
        self.load_lines(meta, lines, source="load_lrc")

    def load_lines(
        self,
        meta: dict[str, str],
        lines: list[LRCLine],
        *,
        source: str = "unknown",
        source_path: str | None = None,
    ) -> None:
        """Load pre-parsed LRC lines directly, preserving any extra fields
        (e.g. end timestamps from transcription) that the text round-trip drops."""
        self._meta = meta
        self._lines = lines
        self._mode = "lrc"
        self._is_dirty = False
        self._saved_hash = hash(serialize(meta, lines))
        self._cursor_idx = 0
        self._active_idx = -1
        self._refresh_list()
        self._switch_mode("lrc")
        self.post_message(self.LinesChanged())
        self._log_lrc_operation("load_lines", source=source, source_path=source_path)

    def load_plain(self, text: str) -> None:
        """Load plain text lyrics into editor."""
        self._load_gen += 1
        gen = self._load_gen
        self._loading = True
        self._plain_text = text
        self._mode = "plain"
        self._is_dirty = False
        self._saved_hash = hash(text)
        ta = self.query_one("#plain-area", TextArea)
        ta.load_text(text)
        self._switch_mode("plain")
        # Reset after the queued TextArea.Changed has been processed.
        # Capture gen so a superseded callback from a previous load is a no-op.
        self.call_after_refresh(lambda: self._finish_plain_load(gen))
        self.post_message(self.LinesChanged())

    def _finish_plain_load(self, gen: int) -> None:
        if gen != self._load_gen:
            return  # superseded by a newer load — don't touch _loading or dirty
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
        if self._mode == "lrc":
            self._saved_hash = hash(serialize(self._meta, self._lines))
        else:
            self._saved_hash = hash(self._plain_text)
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
    def lrc_lines(self) -> list[LRCLine]:
        """Current LRC lines. Empty list when not in LRC mode."""
        return self._lines if self._mode == "lrc" else []

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
        self._refresh_active_highlight()
        if idx >= 0:
            self._jump_to_line(idx)

    def _seek(self, delta: float) -> None:
        self.post_message(self.SeekRequested(max(0.0, self._current_position + delta)))

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
        self._list_items = []
        for i, line in enumerate(self._lines):
            classes = "active-line" if i == self._active_idx else ""
            end_str = line.end_timestamp_str() or ""
            item = ListItem(
                Label(line.display_str(), classes="line-text"),
                Label(end_str, classes="end-ts"),
                classes=classes,
            )
            lv.append(item)
            self._list_items.append(item)

    def _refresh_active_highlight(self) -> None:
        """Toggle the active-line CSS class. No DOM text changes — safe at 10 Hz."""
        for i, item in enumerate(self._list_items):
            item.set_class(i == self._active_idx, "active-line")

    def _refresh_all_labels(self) -> None:
        """Update every list item's line-text label to match current line data.

        Called after mutations that change timestamp or text (stamp, nudge).
        Not called during playback ticks.
        """
        for item, line in zip(self._list_items, self._lines):
            item.query_one(".line-text", Label).update(line.display_str())

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
        """Push a snapshot of current lines + cursor onto the undo stack (maxlen=50).

        list(l.words) is a shallow copy: WordTiming contains only immutable
        primitive fields (str, float) and is never mutated in place — only
        the list itself is ever replaced.  Shared WordTiming references are
        therefore safe and a deep copy would be wasteful.
        """
        snapshot = [
            LRCLine(l.timestamp, l.text, end=l.end, words=list(l.words)) for l in self._lines
        ]
        self._undo_stack.append((snapshot, self._cursor_idx))

    def _apply_undo(self) -> None:
        if not self._undo_stack:
            return
        lines, cursor = self._undo_stack.pop()
        self._lines = lines
        self._refresh_list()
        self._set_cursor(cursor)
        self._mark_dirty()

    def _set_cursor(self, idx: int) -> None:
        """Move ListView cursor to idx and update internal tracking.

        Deferred via lv.call_after_refresh (not self.call_after_refresh) so
        it runs after the ListView has processed all pending remove/mount
        operations from lv.clear() + lv.append().  At that point lv._nodes
        contains only the new items, so lv.index = idx triggers watch_index
        on the correct item.  Direct item.highlighted is set too as a
        belt-and-suspenders backup.  Leaving lv.index = None would cause
        the ListView to auto-select index 0 when rendering is active.
        """
        self._cursor_idx = idx
        items = self._list_items  # snapshot — same objects appended in _refresh_list
        lv = self.query_one("#lrc-list", ListView)

        def _apply() -> None:
            for i, item in enumerate(items):
                item.highlighted = i == idx
            lv.index = idx

        lv.call_after_refresh(_apply)

    def _log_lrc_operation(self, operation: str, **params) -> None:
        """Log an LRC operation with the full resulting line snapshot."""

        log_lrc_operation(
            operation,
            after=snapshot_lrc_lines(self._lines),
            params=params,
        )

    # ------------------------------------------------------------------
    # Keyboard handling (LRC mode)
    # ------------------------------------------------------------------

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        if event.item is None or event.control.index is None:
            return
        self._cursor_idx = event.control.index

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        """Track dirty state for plain text mode. Ignored during initial load."""
        if self._mode == "plain" and not self._loading:
            self._mark_dirty()

    def on_key(self, event) -> None:
        if self._mode != "lrc":
            return

        key = event.key

        # Playback controls — mirror waveform pane so you don't have to switch panes
        if key == keybinds.KB_PLAY_PAUSE:
            event.stop()
            self.post_message(self.PlayPauseRequested())
            return
        elif key == keybinds.KB_SEEK_FWD:
            event.stop()
            self._seek(keybinds.SEEK_SMALL)
            return
        elif key == keybinds.KB_SEEK_BACK:
            event.stop()
            self._seek(-keybinds.SEEK_SMALL)
            return
        elif key == keybinds.KB_SEEK_FWD_LARGE:
            event.stop()
            self._seek(keybinds.SEEK_LARGE)
            return
        elif key == keybinds.KB_SEEK_BACK_LARGE:
            event.stop()
            self._seek(-keybinds.SEEK_LARGE)
            return

        if key == keybinds.KB_SEEK_TO_LINE:
            event.stop()
            if 0 <= self._cursor_idx < len(self._lines):
                ts = self._lines[self._cursor_idx].timestamp
                self.post_message(self.SeekRequested(ts))

        elif key == keybinds.KB_STAMP_LINE:
            event.stop()
            if 0 <= self._cursor_idx < len(self._lines):
                idx_before = self._cursor_idx
                self._save_undo()
                line = self._lines[self._cursor_idx]
                _shift_line_timing(line, self._current_position - line.timestamp)
                self._lines.sort(key=lambda l: l.timestamp)
                self._cursor_idx = next(
                    (i for i, l in enumerate(self._lines) if l is line),
                    self._cursor_idx,
                )
                self._mark_dirty()
                self._refresh_all_labels()
                self._refresh_active_highlight()
                self._set_cursor(self._cursor_idx)
                self._log_lrc_operation(
                    "stamp",
                    idx=idx_before,
                    idx_after=self._cursor_idx,
                    position=self._current_position,
                )

        elif key == keybinds.KB_UNDO:
            event.stop()
            if not self._undo_stack:
                return
            self._apply_undo()
            self._log_lrc_operation("undo", idx=self._cursor_idx)

        elif key in _KEY_NUDGE:
            event.stop()
            self._nudge(self._cursor_idx, _KEY_NUDGE[key])

        elif key == keybinds.KB_DELETE_LINE:
            event.stop()
            self._delete(self._cursor_idx)

        elif key == keybinds.KB_MERGE_LINE:
            event.stop()
            self._merge(self._cursor_idx)

        elif key == keybinds.KB_INSERT_LINE:
            event.stop()
            self._insert_blank(self._cursor_idx)

        elif key == keybinds.KB_EDIT_LINE:
            event.stop()
            if self._is_playing:
                self.post_message(self.StopPlaybackRequested())
            self._start_edit(self._cursor_idx)

    def _nudge(self, idx: int, delta: float) -> None:
        if not (0 <= idx < len(self._lines)):
            return
        self._lines, self._cursor_idx = _op_nudge(self._lines, idx, delta)
        self._mark_dirty()
        self._refresh_all_labels()
        self._refresh_active_highlight()
        self._set_cursor(self._cursor_idx)
        self._log_lrc_operation("nudge", idx=idx, delta=delta)

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
        self._log_lrc_operation("delete", idx=idx)

    def _merge(self, idx: int) -> None:
        if not (0 <= idx < len(self._lines) - 1):
            return
        self._save_undo()
        self._lines, _ = _op_merge(self._lines, idx)
        self._mark_dirty()
        self._refresh_list()
        self._set_cursor(idx)
        self._log_lrc_operation("merge", idx=idx)

    def _insert_blank(self, idx: int) -> None:
        if not (0 <= idx < len(self._lines)):
            return
        self._save_undo()
        self._lines, new_cursor = _op_insert_blank(self._lines, idx)
        self._mark_dirty()
        self._refresh_list()
        self._set_cursor(new_cursor)
        self._log_lrc_operation("insert_blank", idx=idx)

    def _start_edit(self, idx: int) -> None:
        if not (0 <= idx < len(self._lines)):
            return
        self.post_message(self.EditLineRequested(idx, self._lines[idx].text))

    def apply_edit(self, idx: int, result: EditLineResult | None, lang: str = "") -> None:
        """Apply the result returned by EditLineModal for the line at *idx*.

        Called by the app layer after the modal is dismissed.  Handles the
        three possible outcomes: cancel (no-op), save, and split.

        *lang* is the ISO 639-2 language code used for syllable-based word
        timing interpolation (e.g. 'eng', 'pol'); pass the loaded file's
        detected language for best results.
        """
        if result is None or result.action == "cancel":
            return

        if result.action == "save":
            if result.text == self._lines[idx].text:
                return  # nothing changed — leave undo buffer intact
            self._save_undo()
            old_words = self._lines[idx].words
            self._lines[idx].text = result.text
            # Reconcile word timing: preserves timings through edits that
            # join, split, delete, or insert words rather than dropping
            # them whenever the word count changes.
            self._lines[idx].words = reconcile_word_timings(
                old_words,
                result.text,
                lang,
                line_start=self._lines[idx].timestamp,
            )
            self._mark_dirty()
            self._refresh_list()
            self._set_cursor(idx)
            self._log_lrc_operation("edit_save", idx=idx, text=result.text)

        elif result.action == "split":
            self._save_undo()
            # The original segment's end timestamp belongs to the second half.
            # The first half's end is derived from its last word when word
            # data is available; otherwise it is cleared.
            original_end = self._lines[idx].end
            original_words = self._lines[idx].words

            # Distribute word timing by counting tokens in the first-half
            # text. This is robust against duplicate words across the split
            # boundary (text-search would misfire on the first occurrence).
            # Clamp to the available word count so partial word lists are
            # handled gracefully.
            n_first = len(result.text.split())
            if original_words:
                split_word_idx = min(n_first, len(original_words))
                first_half_words = original_words[:split_word_idx]
                second_words = original_words[split_word_idx:]
                ts_from_words = second_words[0].start if second_words else None
            else:
                first_half_words = []
                second_words = []
                ts_from_words = None
            has_word_ts = ts_from_words is not None

            self._lines[idx].text = result.text
            self._lines[idx].words = first_half_words
            # End time: last word's end when word data is available, else None.
            self._lines[idx].end = first_half_words[-1].end if first_half_words else None

            # Timestamp for second half: word-precise if available, otherwise
            # fall back to current playback position or midpoint heuristic.
            first_ts = self._lines[idx].timestamp
            next_ts = (
                self._lines[idx + 1].timestamp if idx + 1 < len(self._lines) else first_ts + 2.0
            )
            new_ts = (
                ts_from_words
                if has_word_ts
                else (
                    self._current_position
                    if self._current_position > first_ts
                    else (first_ts + next_ts) / 2
                )
            )
            self._lines.insert(
                idx + 1,
                LRCLine(new_ts, result.second, end=original_end, words=second_words),
            )
            self._mark_dirty()
            self._refresh_list()
            self._set_cursor(idx)
            self._log_lrc_operation(
                "edit_split",
                idx=idx,
                first=result.text,
                second=result.second,
                split_col=len(result.text),
            )

    def _mark_dirty(self) -> None:
        if self._mode == "lrc":
            self._is_dirty = hash(serialize(self._meta, self._lines)) != self._saved_hash
            self.post_message(self.LinesChanged())
        else:
            self._is_dirty = True
