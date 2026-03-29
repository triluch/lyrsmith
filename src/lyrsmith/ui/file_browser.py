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

    def compose(self) -> ComposeResult:
        yield FastListView(id="browser-list")

    def on_mount(self) -> None:
        # Add class while ListView is still empty → update_node_styles walks 0 items.
        self.query_one("#browser-list", ListView).add_class("always-focused-cursor")
        self._populate(self._path)

    def _populate(self, path: Path) -> None:
        self._path = path
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
    # Events
    # ------------------------------------------------------------------

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        event.stop()
        if event.item is None:
            return
        idx = self._index_of(event.item)
        if idx is None:
            return
        entry = self._entries[idx]
        if entry is not None:
            self.post_message(self.FileHighlighted(entry))

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        event.stop()
        if event.item is None:
            return
        idx = self._index_of(event.item)
        if idx is None:
            return
        entry = self._entries[idx]
        if entry is None:
            # ".." — go up
            self._populate(self._path.parent)
        elif entry.is_dir():
            self._populate(entry)
        else:
            self.post_message(self.FileSelected(entry))

    def on_key(self, event) -> None:
        if event.key == "backspace":
            event.stop()
            if self._path.parent != self._path:
                self._populate(self._path.parent)

        elif event.key in ("pagedown", "page_down"):
            event.stop()
            lv = self.query_one("#browser-list", ListView)
            page = max(1, lv.size.height)
            lv.index = min((lv.index or 0) + page, len(self._entries) - 1)

        elif event.key in ("pageup", "page_up"):
            event.stop()
            lv = self.query_one("#browser-list", ListView)
            page = max(1, lv.size.height)
            lv.index = max(0, (lv.index or 0) - page)

    def _index_of(self, item: ListItem) -> int | None:
        lv = self.query_one("#browser-list", ListView)
        for i, child in enumerate(lv.children):
            if child is item:
                return i
        return None

    @property
    def current_path(self) -> Path:
        return self._path
