"""
Waveform rendering with halfblock vertical doubling.

Each terminal row represents two virtual time slices.
Four characters cover all fill combinations per column:
  ▀  top half filled (upper block)
  ▄  bottom half filled (lower block)
  █  both halves filled
     neither filled (space)

The playhead is a full terminal row rendered without halfblocking.
"""

from __future__ import annotations

import numpy as np
from rich.style import Style
from rich.text import Text

PLAYHEAD_THRESHOLD = 0.80
PLAYHEAD_RESET = 0.20

_UPPER = "▀"
_LOWER = "▄"
_FULL = "█"
_EMPTY = " "

_BAR_STYLE = Style(color="white")
_LRC_MARK_STYLE = Style(color="yellow3")
_PLAYHEAD_STYLE = Style(color="bright_cyan")


def compute_view_start(
    current_view_start: float,
    position: float,
    zoom: float,
) -> float:
    """Return updated view_start applying 80/20 paged scrolling."""
    if zoom <= 0:
        return current_view_start
    relative = (position - current_view_start) / zoom
    if relative >= PLAYHEAD_THRESHOLD or relative < 0:
        return position - PLAYHEAD_RESET * zoom
    return current_view_start


def render(
    pcm: np.ndarray,
    sample_rate: int,
    position: float,
    view_start: float,
    zoom: float,
    width: int,
    height: int,
    lrc_timestamps: list[float] | None = None,
) -> Text:
    """
    Render waveform as a Rich Text (newline-separated rows).
    Effective vertical resolution is height * 2 via halfblock chars.

    Rows whose time window contains an LRC line timestamp are rendered in
    _LRC_MARK_STYLE instead of _BAR_STYLE.
    """
    if pcm is None or len(pcm) == 0 or width <= 0 or height <= 0:
        return Text("\n".join([" " * width] * height))

    duration = len(pcm) / sample_rate
    vrows = height * 2  # virtual rows (halfblock doubling)
    secs_per_v = zoom / vrows

    # Playhead: which terminal row contains the current position
    ph_vrow = int((position - view_start) / zoom * vrows)
    ph_vrow = max(0, min(vrows - 1, ph_vrow))
    ph_trow = ph_vrow // 2

    # LRC marker rows: set of terminal rows that contain at least one timestamp
    marked_trows: set[int] = set()
    if lrc_timestamps:
        for ts in lrc_timestamps:
            vr = int((ts - view_start) / zoom * vrows)
            if 0 <= vr < vrows:
                marked_trows.add(vr // 2)

    # Per-virtual-row peak amplitude
    amps: list[float] = []
    for vr in range(vrows):
        t0 = view_start + vr * secs_per_v
        t1 = t0 + secs_per_v
        i0 = max(0, int(t0 * sample_rate))
        i1 = min(len(pcm), int(t1 * sample_rate))
        if i0 >= i1 or t0 > duration or t1 < 0:
            amps.append(0.0)
        else:
            chunk = pcm[i0:i1]
            amps.append(float(np.max(np.abs(chunk))) if len(chunk) else 0.0)

    peak = max(amps) or 1.0
    norm = [a / peak for a in amps]

    result = Text()
    for tr in range(height):
        if tr > 0:
            result.append("\n")

        if tr == ph_trow:
            # Full-row playhead — always spans the entire width
            bar = "▶" + "─" * (width - 1)
            result.append(bar, style=_PLAYHEAD_STYLE)
            continue

        bar_style = _LRC_MARK_STYLE if tr in marked_trows else _BAR_STYLE

        top_f = round(norm[tr * 2] * width) if tr * 2 < len(norm) else 0
        bot_f = round(norm[tr * 2 + 1] * width) if tr * 2 + 1 < len(norm) else 0

        for col in range(width):
            t = col < top_f
            b = col < bot_f
            if t and b:
                result.append(_FULL, style=bar_style)
            elif t:
                result.append(_UPPER, style=bar_style)
            elif b:
                result.append(_LOWER, style=bar_style)
            else:
                result.append(_EMPTY)

    return result
