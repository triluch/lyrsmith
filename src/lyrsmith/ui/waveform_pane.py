"""Waveform pane: scrolling waveform visualisation + player controls."""

from __future__ import annotations

import numpy as np
from textual.app import ComposeResult
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Label, Static

from ..audio import waveform as wf
from ..audio.player import Player
from ..keybinds import (
    KB_PLAY_PAUSE,
    KB_SEEK_BACK,
    KB_SEEK_BACK_LARGE,
    KB_SEEK_FWD,
    KB_SEEK_FWD_LARGE,
    KB_ZOOM_IN,
    KB_ZOOM_OUT,
    SEEK_SMALL,
    SEEK_LARGE,
)

ZOOM_STEP = 5.0
ZOOM_MIN = 5.0
ZOOM_MAX = 120.0


def _fmt_ts(seconds: float) -> str:
    """Format seconds as LRC-style [mm:ss.xx]."""
    total_cs = round(seconds * 100)
    cs = total_cs % 100
    total_s = total_cs // 100
    s = total_s % 60
    m = total_s // 60
    return f"[{m:02d}:{s:02d}.{cs:02d}]"


class WaveformPane(Widget):
    DEFAULT_CSS = """
    WaveformPane {
        border: solid $panel-darken-2;
        layout: vertical;
    }
    WaveformPane:focus {
        border: solid $accent;
    }
    WaveformPane #wf-timestamp {
        width: 1fr;
        height: 1;
        text-align: center;
        color: $accent;
        background: transparent;
    }
    WaveformPane #wf-display {
        width: 1fr;
        height: 1fr;
        background: transparent;
    }
    """

    can_focus = True
    CAN_FOCUS_CHILDREN = False

    class SeekRequested(Message):
        def __init__(self, position: float) -> None:
            super().__init__()
            self.position = position

    class ZoomChanged(Message):
        def __init__(self, zoom: float) -> None:
            super().__init__()
            self.zoom = zoom

    def __init__(self, player: Player) -> None:
        super().__init__()
        self._player = player
        self._pcm: np.ndarray | None = None
        self._sample_rate: int = 44100
        self._position: float = 0.0
        self._view_start: float = 0.0
        self._zoom: float = 20.0

    def compose(self) -> ComposeResult:
        yield Label(_fmt_ts(0.0), id="wf-timestamp")
        yield Static("", id="wf-display")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_pcm(self, pcm: np.ndarray, sample_rate: int) -> None:
        self._pcm = pcm
        self._sample_rate = sample_rate
        self._position = 0.0
        self._view_start = 0.0
        self._redraw()

    def set_zoom(self, zoom: float) -> None:
        clamped = max(ZOOM_MIN, min(ZOOM_MAX, zoom))
        changed = clamped != self._zoom
        self._zoom = clamped
        self._redraw()
        if changed:
            self.post_message(self.ZoomChanged(self._zoom))

    def update_position(self, position: float) -> None:
        self._position = position
        self._view_start = wf.compute_view_start(self._view_start, position, self._zoom)
        self._redraw()

    @property
    def view_start(self) -> float:
        return self._view_start

    @property
    def zoom(self) -> float:
        return self._zoom

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def _redraw(self) -> None:
        self.query_one("#wf-timestamp", Label).update(_fmt_ts(self._position))

        display = self.query_one("#wf-display", Static)
        w = self.content_size.width
        # Subtract 1 for the timestamp row.
        h = max(0, self.content_size.height - 1)
        if w <= 0 or h <= 0:
            return

        if self._pcm is None or len(self._pcm) == 0:
            display.update("\n".join([" " * w] * h))
            return

        display.update(
            wf.render(
                pcm=self._pcm,
                sample_rate=self._sample_rate,
                position=self._position,
                view_start=self._view_start,
                zoom=self._zoom,
                width=w,
                height=h,
            )
        )

    def on_resize(self, event) -> None:
        self._redraw()

    # ------------------------------------------------------------------
    # Keys
    # ------------------------------------------------------------------

    def on_key(self, event) -> None:
        key = event.key
        if key == KB_PLAY_PAUSE:
            event.stop()
            self._player.toggle()
        elif key == KB_SEEK_FWD:
            event.stop()
            self._seek(SEEK_SMALL)
        elif key == KB_SEEK_BACK:
            event.stop()
            self._seek(-SEEK_SMALL)
        elif key == KB_SEEK_FWD_LARGE:
            event.stop()
            self._seek(SEEK_LARGE)
        elif key == KB_SEEK_BACK_LARGE:
            event.stop()
            self._seek(-SEEK_LARGE)
        elif key == KB_ZOOM_IN:
            event.stop()
            self.set_zoom(self._zoom - ZOOM_STEP)
        elif key == KB_ZOOM_OUT:
            event.stop()
            self.set_zoom(self._zoom + ZOOM_STEP)

    def _seek(self, delta: float) -> None:
        target = max(0.0, self._position + delta)
        self._player.seek(target)
        self.post_message(self.SeekRequested(target))
