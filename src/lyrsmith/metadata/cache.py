"""Shared data types for file metadata."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

LyricsType = Literal["lrc", "plain", None]


@dataclass
class FileInfo:
    path: Path
    title: str
    artist: str
    album: str
    has_lyrics: bool
    lyrics_type: LyricsType

    def display_title(self) -> str:
        if self.artist and self.title:
            return f"{self.artist} — {self.title}"
        return self.title or self.path.name

    def lyrics_label(self) -> str:
        if not self.has_lyrics:
            return "no lyrics"
        return "synced LRC" if self.lyrics_type == "lrc" else "plain text"
