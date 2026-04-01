"""Shared non-fixture helpers for integration tests.

Fixtures live in conftest.py; helpers that test files must import explicitly
live here so they are not auto-injected by pytest.
"""

from __future__ import annotations

from pathlib import Path

from lyrsmith.metadata.cache import FileInfo

# ---------------------------------------------------------------------------
# Sample LRC content reused across many tests
# ---------------------------------------------------------------------------

_SAMPLE_LRC = (
    "[00:01.00]First line\n"
    "[00:03.00]Second line\n"
    "[00:05.00]Third line\n"
    "[00:07.00]Fourth line\n"
    "[00:09.00]Fifth line\n"
)


# ---------------------------------------------------------------------------
# Minimal audio file stub
# ---------------------------------------------------------------------------


def _make_mp3(path: Path) -> Path:
    """Write a minimal ID3v2.3 header — sufficient for FileBrowser to list
    the file as an audio entry. Does NOT contain audio frames."""
    path.write_bytes(b"ID3\x03\x00\x00\x00\x00\x00\x00")
    return path


# ---------------------------------------------------------------------------
# FileInfo stub
# ---------------------------------------------------------------------------


def _fake_info(path: Path) -> FileInfo:
    return FileInfo(
        path=path,
        title=path.stem,
        artist="",
        album="",
        has_lyrics=False,
        lyrics_type=None,
    )


# ---------------------------------------------------------------------------
# Async setup helper — load LRC and navigate to lrc-list via tab
# ---------------------------------------------------------------------------


async def _load_and_focus(pilot, lrc: str = _SAMPLE_LRC):
    """Load LRC content into the editor and navigate to the lrc-list.

    Presses tab twice from the file browser (browser → waveform → lrc-list),
    matching real user navigation. Returns the LyricsEditor instance.
    """
    from lyrsmith.ui.lyrics_editor import LyricsEditor

    ed = pilot.app.query_one(LyricsEditor)
    ed.load_lrc(lrc)
    await pilot.pause()
    await pilot.press("tab")  # browser → waveform
    await pilot.pause()
    await pilot.press("tab")  # waveform → lrc-list
    await pilot.pause()
    return ed


# ---------------------------------------------------------------------------
# FakePlayer — no libmpv dependency
# ---------------------------------------------------------------------------


class FakePlayer:
    """Drop-in replacement for Player; stores state in plain Python attrs."""

    def __init__(self, on_position=None):
        self._position = 0.0
        self._playing = False
        self._duration = 120.0
        self._volume = 100.0
        self.loaded_path: Path | None = None

    def load(self, path: Path) -> None:
        self.loaded_path = path
        self._position = 0.0
        self._playing = False

    def play(self) -> None:
        self._playing = True

    def pause(self) -> None:
        self._playing = False

    def stop(self) -> None:
        self._playing = False

    def toggle(self) -> None:
        self._playing = not self._playing

    def terminate(self) -> None:
        pass

    def seek(self, s: float) -> None:
        self._position = max(0.0, min(s, self._duration))

    @property
    def is_playing(self) -> bool:
        return self._playing

    @property
    def position(self) -> float:
        return self._position

    @property
    def duration(self) -> float:
        return self._duration

    @property
    def volume(self) -> float:
        return self._volume

    @volume.setter
    def volume(self, value: float) -> None:
        self._volume = max(0.0, min(100.0, value))
