"""SQLite-backed persistent metadata cache.

Replaces the old in-memory LRU.  SQLite's own page cache and the OS
filesystem cache make a separate in-memory layer unnecessary.

Schema: one row per audio file — path (PK), mtime for invalidation,
and the four metadata fields needed by the file browser.  Lyrics text
is not stored here; read_lyrics() always hits the audio file directly.
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from platformdirs import user_cache_dir

from .cache import FileInfo

_DB_DIR = Path(user_cache_dir("lyrsmith"))
_DB_FILE = _DB_DIR / "metadata.db"

_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS meta (
    path        TEXT PRIMARY KEY,
    mtime       REAL NOT NULL,
    title       TEXT NOT NULL DEFAULT '',
    artist      TEXT NOT NULL DEFAULT '',
    album       TEXT NOT NULL DEFAULT '',
    lyrics_type TEXT          -- 'lrc' | 'plain' | NULL
);
"""


class DiskMetadataCache:
    """Thread-safe SQLite metadata cache with mtime-based invalidation."""

    def __init__(self, db_path: Path | str = _DB_FILE) -> None:
        self._db_path = str(db_path)
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None
        self._open()

    def _open(self) -> None:
        try:
            if self._db_path != ":memory:":
                Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self._db_path, check_same_thread=False)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(_CREATE_SQL)
            conn.commit()
            self._conn = conn
        except Exception:
            self._conn = None  # non-fatal; all methods fall back gracefully

    def _conn_or_none(self) -> sqlite3.Connection | None:
        return self._conn

    def get(self, path: Path) -> FileInfo | None:
        """Return cached FileInfo if the file's mtime matches, else None."""
        try:
            mtime = path.stat().st_mtime
        except OSError:
            return None
        try:
            with self._lock:
                conn = self._conn_or_none()
                if conn is None:
                    return None
                row = conn.execute(
                    "SELECT mtime, title, artist, album, lyrics_type FROM meta WHERE path = ?",
                    (str(path),),
                ).fetchone()
            if row is None or row[0] != mtime:
                return None
            _, title, artist, album, lt = row
            return FileInfo(
                path=path,
                title=title or "",
                artist=artist or "",
                album=album or "",
                has_lyrics=lt is not None,
                lyrics_type=lt,  # type: ignore[arg-type]
            )
        except Exception:
            return None

    def put(self, info: FileInfo) -> None:
        """Store or replace the cache entry for info.path."""
        try:
            mtime = info.path.stat().st_mtime
        except OSError:
            return
        try:
            with self._lock:
                conn = self._conn_or_none()
                if conn is None:
                    return
                conn.execute(
                    "INSERT OR REPLACE INTO meta"
                    " (path, mtime, title, artist, album, lyrics_type)"
                    " VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        str(info.path),
                        mtime,
                        info.title,
                        info.artist,
                        info.album,
                        info.lyrics_type,
                    ),
                )
                conn.commit()
        except Exception:
            pass

    def invalidate(self, path: Path) -> None:
        """Remove the cache entry for path (e.g. after writing new lyrics)."""
        try:
            with self._lock:
                conn = self._conn_or_none()
                if conn is None:
                    return
                conn.execute("DELETE FROM meta WHERE path = ?", (str(path),))
                conn.commit()
        except Exception:
            pass


# Module-level shared instance — can be monkeypatched in tests.
disk_cache = DiskMetadataCache()
