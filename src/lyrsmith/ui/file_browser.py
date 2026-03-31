"""Left pane top: directory listing with navigation."""

from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Label, ListItem, ListView

from ..metadata.tags import is_audio_file
from ._fast_list_view import FastListView


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

    # ------------------------------------------------------------------
    # Filtering
    # ------------------------------------------------------------------

    def _apply_filter(self) -> None:
        """Show/hide list items by substring match; update the filter label."""
        lv = self.query_one("#browser-list", ListView)
        q = self._filter.lower()
        first_match: int | None = None
        for i, (item, entry) in enumerate(zip(lv.children, self._entries)):
            if not isinstance(item, ListItem):
                continue
            # ".." is always visible; loaded file stays visible regardless of filter
            visible = entry is None or not q or q in entry.name.lower() or entry == self._loaded
            item.display = visible
            if visible and first_match is None and entry is not None:
                first_match = i
        # Move cursor to first match when filter is active
        if q and first_match is not None:
            lv.index = first_match
        fl = self.query_one("#filter-label", Label)
        fl.update(f"/ {self._filter}" if self._filter else "")
        fl.set_class(bool(self._filter), "active")

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
        # Printable characters build the filter string
        if event.character and event.character.isprintable():
            self._filter += event.character
            self._apply_filter()
            event.stop()
            return

        if event.key == "escape":
            if self._filter:
                self._filter = ""
                self._apply_filter()
                event.stop()
            return

        if event.key == "backspace":
            event.stop()
            if self._filter:
                # Eat one character from the filter
                self._filter = self._filter[:-1]
                self._apply_filter()
            elif self._path.parent != self._path:
                self._populate(self._path.parent)

    @property
    def current_path(self) -> Path:
        return self._path
