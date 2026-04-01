"""Thin focus-indicator widget used in the indicator row."""

from __future__ import annotations

from textual.widget import Widget


class IndicatorSegment(Widget):
    """Renders ▀ half-blocks in $accent when .lit.

    Filling the full widget width with ▀ makes the accent appear only in the
    upper half of the character cell, giving a visually thin accent stripe.
    Unlit: foreground = $panel → solid panel row, invisible against the bar.
    """

    DEFAULT_CSS = """
    IndicatorSegment {
        height: 1;
        background: $background;
        color: $panel;
    }
    IndicatorSegment.lit {
        color: $accent;
    }
    """

    def render(self) -> str:
        return "\u2580" * self.content_size.width  # ▀
