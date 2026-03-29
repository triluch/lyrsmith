"""ListView subclass that skips the O(n) children walk on focus changes."""

from __future__ import annotations

from textual.widgets import ListView


class FastListView(ListView):
    """ListView optimised for large item counts.

    Two expensive O(n) operations are eliminated:

    1. update_node_styles() — Textual's default walks ALL children and
       re-evaluates CSS on every focus gain/loss.  We suppress the two
       things that actually change (background-tint and cursor state) via
       CSS, so the walk produces no visual effect.  Skipping it is safe.

    2. focus_chain traversal — Textual's Tab-order algorithm sorts and
       iterates every displayed child to find focusable widgets.  ListItems
       are never directly focusable; CAN_FOCUS_CHILDREN = False tells
       Textual not to enter our children at all (same flag WaveformPane uses).
       The FastListView itself remains in the focus chain normally.
    """

    CAN_FOCUS_CHILDREN = False

    def update_node_styles(self, animate: bool = True) -> None:
        try:
            self.app.stylesheet.update_nodes([self], animate=animate)
        except Exception:
            pass
