"""Waveform pane: scrolling waveform visualisation + player controls."""

from __future__ import annotations

import numpy as np
from textual.app import ComposeResult
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Label, Static

from .. import keybinds
from ..audio import waveform as wf
from ..audio.player import Player

ZOOM_STEP = 5.0
ZOOM_MIN = 5.0
ZOOM_MAX = 120.0

VOL_MIN = 0.0
VOL_MAX = 100.0


def _fmt_single(seconds: float) -> str:
    """Format seconds as mm:ss.xx (no brackets)."""
    total_cs = round(seconds * 100)
    cs = total_cs % 100
    total_s = total_cs // 100
    s = total_s % 60
    m = total_s // 60
    return f"{m:02d}:{s:02d}.{cs:02d}"


def _fmt_ts_pair(position: float, duration: float) -> str:
    """Format position/duration as [mm:ss.xx/mm:ss.xx]."""
    return f"[{_fmt_single(position)}/{_fmt_single(duration)}]"


def _fmt_vol(volume: float) -> str:
    """Format volume as 'vol: NN%'."""
    return f"vol: {int(round(volume))}%"


class WaveformPane(Widget):
    DEFAULT_CSS = """
    WaveformPane {
        border: solid $panel-darken-2;
        layout: vertical;
    }
    WaveformPane #wf-timestamp {
        width: 1fr;
        height: 1;
        text-align: center;
        color: $accent;
        background: transparent;
    }
    WaveformPane #wf-volume {
        width: 1fr;
        height: 1;
        text-align: center;
        color: $text-muted;
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

    class VolumeChanged(Message):
        def __init__(self, volume: float) -> None:
            super().__init__()
            self.volume = volume

    def __init__(self, player: Player) -> None:
        super().__init__()
        self._player = player
        self._pcm: np.ndarray | None = None
        self._sample_rate: int = 44100
        self._position: float = 0.0
        self._duration: float = 0.0
        self._view_start: float = 0.0
        self._zoom: float = 20.0
        self._volume: float = 100.0
        self._lrc_timestamps: list[float] = []

    def compose(self) -> ComposeResult:
        yield Label(_fmt_ts_pair(0.0, 0.0), id="wf-timestamp")
        yield Label(_fmt_vol(self._volume), id="wf-volume")
        yield Static("", id="wf-display")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_pcm(self, pcm: np.ndarray, sample_rate: int) -> None:
        self._pcm = pcm
        self._sample_rate = sample_rate
        self._position = 0.0
        self._duration = len(pcm) / sample_rate if len(pcm) > 0 else 0.0
        self._view_start = 0.0
        self._redraw()

    def set_zoom(self, zoom: float) -> None:
        clamped = max(ZOOM_MIN, min(ZOOM_MAX, zoom))
        changed = clamped != self._zoom
        self._zoom = clamped
        self._redraw()
        if changed:
            self.post_message(self.ZoomChanged(self._zoom))

    def set_volume(self, volume: float) -> None:
        clamped = max(VOL_MIN, min(VOL_MAX, volume))
        changed = clamped != self._volume
        self._volume = clamped
        self._player.volume = clamped
        self._redraw_volume()
        if changed:
            self.post_message(self.VolumeChanged(self._volume))

    def set_lrc_timestamps(self, timestamps: list[float]) -> None:
        self._lrc_timestamps = timestamps
        self._redraw()

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

    @property
    def volume(self) -> float:
        return self._volume

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def _redraw_volume(self) -> None:
        self.query_one("#wf-volume", Label).update(_fmt_vol(self._volume))

    def _redraw(self) -> None:
        self.query_one("#wf-timestamp", Label).update(_fmt_ts_pair(self._position, self._duration))

        display = self.query_one("#wf-display", Static)
        w = self.content_size.width
        # Subtract 2 for the timestamp and volume rows.
        h = max(0, self.content_size.height - 2)
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
                lrc_timestamps=self._lrc_timestamps or None,
            )
        )

    def on_resize(self, event) -> None:
        self._redraw()

    # ------------------------------------------------------------------
    # Keys
    # ------------------------------------------------------------------

    def on_key(self, event) -> None:
        key = event.key
        if key == keybinds.KB_PLAY_PAUSE:
            event.stop()
            self._player.toggle()
        elif key == keybinds.KB_SEEK_FWD:
            event.stop()
            self._seek(keybinds.SEEK_SMALL)
        elif key == keybinds.KB_SEEK_BACK:
            event.stop()
            self._seek(-keybinds.SEEK_SMALL)
        elif key == keybinds.KB_SEEK_FWD_LARGE:
            event.stop()
            self._seek(keybinds.SEEK_LARGE)
        elif key == keybinds.KB_SEEK_BACK_LARGE:
            event.stop()
            self._seek(-keybinds.SEEK_LARGE)
        elif key == keybinds.KB_ZOOM_IN:
            event.stop()
            self.set_zoom(self._zoom - ZOOM_STEP)
        elif key == keybinds.KB_ZOOM_OUT:
            event.stop()
            self.set_zoom(self._zoom + ZOOM_STEP)
        elif key == keybinds.KB_VOL_UP:
            event.stop()
            self.set_volume(self._volume + keybinds.VOL_STEP)
        elif key == keybinds.KB_VOL_DOWN:
            event.stop()
            self.set_volume(self._volume - keybinds.VOL_STEP)

    def _seek(self, delta: float) -> None:
        target = max(0.0, self._position + delta)
        self._player.seek(target)
        self.post_message(self.SeekRequested(target))
