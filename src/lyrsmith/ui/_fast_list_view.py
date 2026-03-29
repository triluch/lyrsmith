"""ListView subclass that skips the O(n) children walk on focus changes."""

from __future__ import annotations

from textual.binding import Binding
from textual.widgets import ListItem, ListView


class FastListView(ListView):
    """ListView optimised for large item counts.

    Four behaviours are customised:

    1. update_node_styles() — Textual's default walks ALL children and
       re-evaluates CSS on every focus gain/loss.  We suppress the two
       things that actually change (background-tint and cursor state) via
       CSS, so the walk produces no visual effect.  Skipping it is safe.

    2. focus_chain traversal — Textual's Tab-order algorithm sorts and
       iterates every displayed child to find focusable widgets.  ListItems
       are never directly focusable; CAN_FOCUS_CHILDREN = False tells
       Textual not to enter our children at all (same flag WaveformPane uses).
       The FastListView itself remains in the focus chain normally.

    3. action_cursor_up / action_cursor_down — skip items whose ``display``
       is False so that CSS-filtered lists (e.g. the file-browser filter)
       navigate only visible items.

    4. action_page_up / action_page_down — page through visible items only,
       jumping by the widget's current height in rows.
    """

    CAN_FOCUS_CHILDREN = False

    BINDINGS = [
        Binding("pagedown", "page_down", show=False),
        Binding("page_down", "page_down", show=False),
        Binding("pageup", "page_up", show=False),
        Binding("page_up", "page_up", show=False),
    ]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _visible_indices(self) -> list[int]:
        """Indices of currently visible (non-hidden) ListItems."""
        return [
            i
            for i, child in enumerate(self.children)
            if isinstance(child, ListItem) and child.display
        ]

    # ------------------------------------------------------------------
    # Action overrides — all respect display=False items
    # ------------------------------------------------------------------

    def action_cursor_up(self) -> None:
        """Move to the previous visible item, skipping hidden ones."""
        current = self.index or 0
        for i in range(current - 1, -1, -1):
            child = self.children[i]
            if isinstance(child, ListItem) and child.display:
                self.index = i
                return

    def action_cursor_down(self) -> None:
        """Move to the next visible item, skipping hidden ones."""
        current = self.index if self.index is not None else -1
        for i in range(current + 1, len(self.children)):
            child = self.children[i]
            if isinstance(child, ListItem) and child.display:
                self.index = i
                return

    def action_page_down(self) -> None:
        """Move forward by one page through visible items."""
        page = max(1, self.size.height)
        visible = self._visible_indices()
        if not visible:
            return
        current = self.index or 0
        pos = next(
            (j for j, v in enumerate(visible) if v >= current),
            len(visible) - 1,
        )
        self.index = visible[min(pos + page, len(visible) - 1)]

    def action_page_up(self) -> None:
        """Move backward by one page through visible items."""
        page = max(1, self.size.height)
        visible = self._visible_indices()
        if not visible:
            return
        current = self.index or 0
        pos = next(
            (j for j in range(len(visible) - 1, -1, -1) if visible[j] <= current),
            0,
        )
        self.index = visible[max(pos - page, 0)]

    # ------------------------------------------------------------------

    def update_node_styles(self, animate: bool = True) -> None:
        try:
            self.app.stylesheet.update_nodes([self], animate=animate)
        except Exception:
            pass
