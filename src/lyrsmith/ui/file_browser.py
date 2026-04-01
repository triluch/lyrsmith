"""Left pane top: directory listing with navigation."""

from __future__ import annotations

from pathlib import Path

from rich.text import Text
from textual.app import ComposeResult
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Label, ListItem, ListView

from .. import keybinds
from ..metadata.cache import LyricsType
from ..metadata.disk_cache import disk_cache
from ..metadata.tags import is_audio_file
from ._fast_list_view import FastListView

# Cycle order: no filter → LRC only → plain only → no-lyrics only → …
_FILTER_CYCLE: list[LyricsType | str] = ["lrc", "plain", "none"]
_FILTER_LABELS: dict[str, str] = {
    "lrc": "[LRC]",
    "plain": "[plain]",
    "none": "[—]",
}


class FileBrowser(Widget):
    """
    Directory listing. Fires FileHighlighted on cursor move, FileSelected on Enter.
    '..' appears at top; dirs show with trailing slash; audio files shown directly.
    """

    DEFAULT_CSS = """
    FileBrowser {
        height: 1fr;
    }
    FileBrowser ListView {
        height: 1fr;
        background: transparent;
    }
    FileBrowser ListView:focus {
        /* Suppress the default 5% foreground tint on focus.
           Without this Textual repaints every ListItem on every Tab press,
           which is O(n) and causes visible lag with large directories. */
        background-tint: $foreground 0%;
    }
    /* Always-focused cursor: specificity 0,2,3 beats ListView:focus rule 0,2,2
       so this wins in both focused and blurred states — interior never changes. */
    FileBrowser ListView.always-focused-cursor ListItem.-highlight {
        color: $block-cursor-foreground;
        background: $block-cursor-background;
        text-style: $block-cursor-text-style;
    }
    FileBrowser ListItem {
        padding: 0 1;
    }
    FileBrowser ListItem.is-dir Label {
        color: $secondary;
    }
    FileBrowser ListItem.is-loaded Label {
        color: $accent;
        text-style: bold;
    }
    FileBrowser ListItem.is-dotdot Label {
        color: $text-muted;
    }
    FileBrowser #filter-label {
        display: none;
        height: 1;
        padding: 0 1;
        color: $accent;
        background: $surface;
    }
    FileBrowser #filter-label.active {
        display: block;
    }
    """

    # ------------------------------------------------------------------
    # Messages
    # ------------------------------------------------------------------

    class FileHighlighted(Message):
        def __init__(self, path: Path) -> None:
            super().__init__()
            self.path = path

    class FileSelected(Message):
        def __init__(self, path: Path) -> None:
            super().__init__()
            self.path = path

    class DirChanged(Message):
        def __init__(self, path: Path, audio_files: list[Path]) -> None:
            super().__init__()
            self.path = path
            self.audio_files = audio_files

    # ------------------------------------------------------------------

    def __init__(self, initial_path: Path) -> None:
        super().__init__()
        self._path = initial_path.resolve()
        # _entries[i] corresponds to ListView item i
        # None = ".." (go up)
        self._entries: list[Path | None] = []
        self._loaded: Path | None = None
        self._filter: str = ""
        self._lyrics_filter: str | None = None  # None | "lrc" | "plain" | "none"
        self._warming: bool = False  # True while background cache warm-up is running

    def compose(self) -> ComposeResult:
        yield FastListView(id="browser-list")
        yield Label("", id="filter-label")

    def on_mount(self) -> None:
        # Add class while ListView is still empty → update_node_styles walks 0 items.
        self.query_one("#browser-list", ListView).add_class("always-focused-cursor")
        self._populate(self._path)

    def _populate(self, path: Path) -> None:
        self._path = path
        self._filter = ""
        self._lyrics_filter = None
        self._warming = False
        lv = self.query_one("#browser-list", ListView)
        lv.clear()
        self._entries = []

        all_items: list[ListItem] = []

        # ".." entry
        if path.parent != path:
            all_items.append(ListItem(Label(".."), classes="is-dotdot"))
            self._entries.append(None)

        dirs: list[Path] = []
        files: list[Path] = []
        try:
            for p in sorted(path.iterdir()):
                if p.name.startswith("."):
                    continue
                if p.is_dir():
                    dirs.append(p)
                elif p.is_file() and is_audio_file(p):
                    files.append(p)
        except OSError:
            pass

        for d in dirs:
            all_items.append(ListItem(Label(f"{d.name}/"), classes="is-dir"))
            self._entries.append(d)

        for f in files:
            classes = "is-loaded" if (self._loaded and f == self._loaded) else ""
            all_items.append(ListItem(Label(f.name), classes=classes))
            self._entries.append(f)

        # Mount all items in one batch — one layout pass instead of N.
        if all_items:
            lv.mount(*all_items)

        self.post_message(self.DirChanged(path, list(files)))
        self._apply_filter()

    def set_loaded(self, path: Path | None) -> None:
        """Mark which file is currently loaded. Updates styles in-place, preserving cursor."""
        old_loaded = self._loaded
        self._loaded = path
        lv = self.query_one("#browser-list", ListView)
        for i, (entry, item) in enumerate(zip(self._entries, lv.children)):
            if not isinstance(item, ListItem):
                continue
            if entry == path:
                item.add_class("is-loaded")
            elif entry == old_loaded:
                item.remove_class("is-loaded")
        # Re-apply visibility so the newly loaded file is always shown and
        # any previous loaded file is re-evaluated against the active filter.
        self._apply_filter(move_cursor=False)

    # ------------------------------------------------------------------
    # Filtering
    # ------------------------------------------------------------------

    def _apply_filter(self, *, move_cursor: bool = True) -> None:
        """Show/hide list items; update the filter label.

        *move_cursor*: when True and a filter is active, jump the cursor to the
        first visible item (correct when the user just changed the filter via a
        key press).  Pass False when re-applying filter as a side-effect of
        another action (set_loaded, post-save refresh) so the cursor stays put.
        """
        lv = self.query_one("#browser-list", ListView)
        q = self._filter.lower()
        lf = self._lyrics_filter
        first_match: int | None = None
        for i, (item, entry) in enumerate(zip(lv.children, self._entries)):
            if not isinstance(item, ListItem):
                continue
            # ".." is always visible; loaded file stays visible regardless of filter
            if entry is None or entry == self._loaded:
                item.display = True
                continue
            visible = not q or q in entry.name.lower()
            if visible and lf and entry.is_file():
                info = disk_cache.get(entry)
                if info is not None:
                    if lf == "none":
                        visible = info.lyrics_type is None
                    else:
                        visible = info.lyrics_type == lf
                # cache miss → show the item conservatively;
                # refresh_filter() is called again after warm-up
            item.display = visible
            if visible and first_match is None:
                first_match = i
        if move_cursor and (q or lf) and first_match is not None:
            lv.index = first_match
        fl = self.query_one("#filter-label", Label)
        parts: list[str] = []
        if self._filter:
            parts.append(f"/ {self._filter}")
        if lf:
            label = _FILTER_LABELS[lf]
            if self._warming:
                label += " …"
            parts.append(label)
        fl.update(Text("  ".join(parts)))
        fl.set_class(bool(parts), "active")

    def cycle_lyrics_filter(self) -> None:
        """Advance the lyrics-type filter one step through the cycle."""
        if self._lyrics_filter is None:
            self._lyrics_filter = _FILTER_CYCLE[0]
        else:
            idx = _FILTER_CYCLE.index(self._lyrics_filter)
            next_idx = (idx + 1) % (len(_FILTER_CYCLE) + 1)
            self._lyrics_filter = (
                None if next_idx == len(_FILTER_CYCLE) else _FILTER_CYCLE[next_idx]
            )
        self._apply_filter()

    def refresh_filter(self) -> None:
        """Re-apply the current filter without moving the cursor.

        Called after warm-up completes or after a save so visibility updates
        without disrupting the user's current cursor position.
        """
        self._apply_filter(move_cursor=False)

    def set_warming(self, warming: bool) -> None:
        """Set the cache warm-up state and re-render the filter label.

        Pass True when a warm-up worker starts (so an in-progress indicator
        appears on the filter label) and False when it finishes (indicator
        removed and filter re-evaluated with fresh cache data).
        """
        self._warming = warming
        self._apply_filter(move_cursor=False)

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        event.stop()
        if event.item is None or event.control.index is None:
            return
        entry = self._entries[event.control.index]
        if entry is not None:
            self.post_message(self.FileHighlighted(entry))

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        event.stop()
        if event.item is None or event.control.index is None:
            return
        entry = self._entries[event.control.index]
        if entry is None:
            # ".." — go up
            self._populate(self._path.parent)
        elif entry.is_dir():
            self._populate(entry)
        else:
            self.post_message(self.FileSelected(entry))

    def on_key(self, event) -> None:
        if event.key == keybinds.KB_LYRICS_FILTER:
            self.cycle_lyrics_filter()
            event.stop()
            return

        # Printable characters build the text filter string
        if event.character and event.character.isprintable():
            self._filter += event.character
            self._apply_filter()
            event.stop()
            return

        if event.key == "escape":
            if self._filter or self._lyrics_filter:
                self._filter = ""
                self._lyrics_filter = None
                self._apply_filter()
                event.stop()
            return

        if event.key == "backspace":
            event.stop()
            if self._filter:
                self._filter = self._filter[:-1]
                self._apply_filter()
            elif self._path.parent != self._path:
                self._populate(self._path.parent)

    @property
    def current_path(self) -> Path:
        return self._path
