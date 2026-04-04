"""
Thin wrapper around python-mpv for playback control.

The mpv time-pos observer fires on mpv's internal thread. Callers should
set on_position to a thread-safe callback (e.g. app.call_from_thread(fn)).
"""

from __future__ import annotations

import ctypes.util
import os
import threading
import time
from pathlib import Path
from typing import Callable


def _configure_mpv_library_lookup() -> None:
    appdir = os.getenv("APPDIR")
    if not appdir:
        return

    candidates = [
        Path(appdir) / "usr/lib/x86_64-linux-gnu/libmpv.so.2",
        Path(appdir) / "usr/lib/libmpv.so.2",
    ]
    libmpv = next((p for p in candidates if p.exists()), None)
    if libmpv is None:
        return

    lib_dirs = [str(libmpv.parent), str(Path(appdir) / "usr/lib")]
    existing = os.environ.get("LD_LIBRARY_PATH", "")
    os.environ["LD_LIBRARY_PATH"] = (
        ":".join([*lib_dirs, existing]) if existing else ":".join(lib_dirs)
    )

    original_find_library = ctypes.util.find_library

    def _find_library(name: str) -> str | None:
        if name == "mpv":
            return str(libmpv)
        return original_find_library(name)

    ctypes.util.find_library = _find_library


_configure_mpv_library_lookup()

import mpv  # noqa: E402

_SEEK_MIN = 0.05  # avoid exact position-0 edge cases in mpv
_SEEK_END = 1.0  # auto-pause this many seconds before EOF
_REVIVE_TIMEOUT = 5.0  # max seconds to wait for mpv to finish reloading


class Player:
    def __init__(self, on_position: Callable[[float], None] | None = None) -> None:
        self._mpv = mpv.MPV(
            video=False,
            terminal=False,
            quiet=True,
        )
        self._mpv.pause = True
        self.on_position = on_position
        self._loaded: Path | None = None

        # Revive state — replacing the old plain bool (_reviving).
        # _revive_lock is held for the duration of a revive thread.
        # _revive_stop is set by load() to abort an in-progress revive.
        self._revive_lock = threading.Lock()
        self._revive_stop = threading.Event()

        @self._mpv.property_observer("time-pos")
        def _time_obs(_name: str, value: float | None) -> None:
            if value is None:
                return
            # Preemptively pause before EOF so mpv never enters idle/eof state.
            # This covers the common case; the eof-reached observer is a fallback.
            try:
                dur = self._mpv.duration
                if dur and float(dur) > 0 and value >= float(dur) - _SEEK_END:
                    self._mpv.pause = True
            except Exception:
                pass
            if self.on_position is not None:
                self.on_position(value)

        @self._mpv.property_observer("eof-reached")
        def _eof_obs(_name: str, value: bool | None) -> None:
            # Fallback: preemptive pause didn't catch it in time.
            # acquire(blocking=False) is atomic — prevents double-spawn from
            # multiple rapid EOF events on the mpv callback thread.
            if value and self._loaded is not None:
                if self._revive_lock.acquire(blocking=False):
                    threading.Thread(
                        target=self._revive_from_eof,
                        daemon=True,
                    ).start()

    # ------------------------------------------------------------------
    # Playback control
    # ------------------------------------------------------------------

    def load(self, path: Path) -> None:
        """Load file without starting playback."""
        # Signal any in-progress revive thread to abort, then wait briefly
        # for it to release the lock before we issue the new play command.
        self._revive_stop.set()
        if self._revive_lock.acquire(timeout=0.5):
            # Lock acquired: revive thread has exited (or never ran).
            self._revive_lock.release()
        # Safe to clear — the revive thread checks the stop flag before
        # touching mpv, so a late-exiting thread is harmless at this point.
        self._revive_stop.clear()

        self._loaded = path
        self._mpv.play(str(path))
        self._mpv.pause = True

    def play(self) -> None:
        self._mpv.pause = False

    def pause(self) -> None:
        self._mpv.pause = True

    def stop(self) -> None:
        self._mpv.pause = True
        self.seek(0.0)

    def toggle(self) -> None:
        self._mpv.pause = not self._mpv.pause

    def seek(self, seconds: float) -> None:
        """Seek to an absolute position, clamped to a safe range."""
        if self._loaded is None or self._revive_lock.locked():
            return
        duration = self.duration
        # Apply the minimum only for non-zero seeks; seeking exactly to 0.0 is
        # legitimate (e.g. first LRC line at timestamp 0.0) and should not be
        # bumped forward by _SEEK_MIN.
        target = max(_SEEK_MIN, seconds) if seconds > 0.0 else 0.0
        if duration > _SEEK_END:
            target = min(target, duration - _SEEK_END)
        try:
            self._mpv.seek(target, "absolute")
        except Exception:
            pass

    # ------------------------------------------------------------------
    # EOF recovery (background thread)
    # ------------------------------------------------------------------

    def _revive_from_eof(self) -> None:
        """
        Reload the file after EOF so seeking works again.
        The lock was acquired by _eof_obs before this thread was started;
        release it in finally so load() can proceed if it's waiting.
        """
        try:
            if self._revive_stop.is_set():
                return
            self._mpv.play(str(self._loaded))
            # Wait until mpv reports a valid position (file is loaded)
            deadline = time.monotonic() + _REVIVE_TIMEOUT
            while time.monotonic() < deadline:
                if self._revive_stop.is_set():
                    return
                if self._mpv.time_pos is not None:
                    break
                time.sleep(0.05)
            if self._revive_stop.is_set():
                return
            # Restore pre-EOF pause state: if the user had paused near the end
            # and sought into it, stay paused; if they were playing, stay paused
            # too (rewinding to start automatically is rarely the right UX).
            self._mpv.pause = True
            # Let the position callback know we're back at the start
            if self.on_position is not None:
                self.on_position(float(self._mpv.time_pos or 0.0))
        except Exception:
            pass
        finally:
            self._revive_lock.release()

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------

    @property
    def volume(self) -> float:
        return float(self._mpv.volume or 100.0)

    @volume.setter
    def volume(self, value: float) -> None:
        self._mpv.volume = max(0.0, min(100.0, value))

    @property
    def is_playing(self) -> bool:
        return not bool(self._mpv.pause)

    @property
    def position(self) -> float:
        return float(self._mpv.time_pos or 0.0)

    @property
    def duration(self) -> float:
        return float(self._mpv.duration or 0.0)

    @property
    def loaded_path(self) -> Path | None:
        return self._loaded

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def terminate(self) -> None:
        try:
            self._mpv.terminate()
        except Exception:
            pass
