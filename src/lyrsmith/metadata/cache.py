"""LRU in-memory cache for file tag info."""

from __future__ import annotations

import threading
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

# Large enough to hold a full directory of ~500 tracks after warm-up.
CACHE_SIZE = 512
LyricsType = Literal["lrc", "plain", None]


@dataclass
class FileInfo:
    path: Path
    title: str
    artist: str
    album: str
    has_lyrics: bool
    lyrics_type: LyricsType  # 'lrc', 'plain', or None
    lyrics_text: str | None = None  # cached raw lyrics string (avoids re-parse)

    def display_title(self) -> str:
        if self.artist and self.title:
            return f"{self.artist} — {self.title}"
        return self.title or self.path.name

    def lyrics_label(self) -> str:
        if not self.has_lyrics:
            return "no lyrics"
        return "synced LRC" if self.lyrics_type == "lrc" else "plain text"


class MetadataCache:
    def __init__(self, maxsize: int = CACHE_SIZE) -> None:
        self._cache: OrderedDict[Path, FileInfo] = OrderedDict()
        self._maxsize = maxsize
        self._lock = threading.Lock()

    def get(self, path: Path) -> FileInfo | None:
        with self._lock:
            if path in self._cache:
                self._cache.move_to_end(path)
                return self._cache[path]
        return None

    def put(self, info: FileInfo) -> None:
        with self._lock:
            if info.path in self._cache:
                self._cache.move_to_end(info.path)
            else:
                if len(self._cache) >= self._maxsize:
                    self._cache.popitem(last=False)
            self._cache[info.path] = info

    def invalidate(self, path: Path) -> None:
        with self._lock:
            self._cache.pop(path, None)


# Module-level shared cache
cache = MetadataCache()
