"""Read/write audio tags via mutagen.

Supported formats and their lyrics storage:
  MP3  — ID3 USLT frame
  FLAC — Vorbis comment LYRICS field
  OGG  — Vorbis comment LYRICS field
  OPUS — Vorbis comment LYRICS field

All other formats are not shown in the file browser (see AUDIO_EXTENSIONS).
"""

from __future__ import annotations

from pathlib import Path

from mutagen import File as MutagenFile
from mutagen.id3 import ID3, ID3NoHeaderError, USLT

from ..lrc import is_lrc
from .cache import FileInfo, LyricsType, cache

# Only formats with reliable lyrics read/write support.
# Files not matching this set are hidden in the file browser.
AUDIO_EXTENSIONS = frozenset({".mp3", ".flac", ".ogg", ".opus"})

_VORBIS_EXTS = frozenset({".flac", ".ogg", ".opus"})


def is_audio_file(path: Path) -> bool:
    return path.suffix.lower() in AUDIO_EXTENSIONS


# ------------------------------------------------------------------
# Public API
# ------------------------------------------------------------------


def read_info(path: Path) -> FileInfo:
    """Return FileInfo for path, using cache when possible."""
    cached = cache.get(path)
    if cached is not None:
        return cached

    title = artist = album = ""
    has_lyrics = False
    lyrics_type: LyricsType = None
    lyrics_text: str | None = None

    try:
        f = MutagenFile(path, easy=True)
        if f is not None and f.tags:
            title = str(f.tags.get("title", [""])[0])
            artist = str(f.tags.get("artist", [""])[0])
            album = str(f.tags.get("album", [""])[0])
    except Exception:
        pass

    try:
        raw = _read_lyrics_raw(path)
        lyrics_text = raw if raw else None  # treat empty tag as absent
        if lyrics_text is not None:
            has_lyrics = True
            lyrics_type = "lrc" if is_lrc(lyrics_text) else "plain"
    except Exception:
        pass

    info = FileInfo(
        path=path,
        title=title,
        artist=artist,
        album=album,
        has_lyrics=has_lyrics,
        lyrics_type=lyrics_type,
        lyrics_text=lyrics_text,
    )
    cache.put(info)
    return info


def read_lyrics(path: Path) -> str | None:
    """Return raw lyrics string, served from warm cache where possible."""
    return read_info(path).lyrics_text


def write_lyrics(path: Path, lyrics: str) -> None:
    """Write lyrics tag. Format is inferred from the file extension."""
    ext = path.suffix.lower()
    try:
        if ext == ".mp3":
            _write_id3_uslt(path, lyrics)
        elif ext in _VORBIS_EXTS:
            _write_vorbis_lyrics(path, lyrics)
        else:
            raise RuntimeError(f"Lyrics saving not supported for {ext} files")
        cache.invalidate(path)
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"Failed to write lyrics to {path}: {e}") from e


# ------------------------------------------------------------------
# Format-specific helpers
# ------------------------------------------------------------------


def _read_lyrics_raw(path: Path) -> str | None:
    """Read lyrics from any supported format, returning None if absent."""
    ext = path.suffix.lower()
    if ext == ".mp3":
        return _read_id3_uslt(path)
    elif ext in _VORBIS_EXTS:
        return _read_vorbis_lyrics(path)
    return None


def _read_id3_uslt(path: Path) -> str | None:
    try:
        tags = ID3(path)
        for key in tags.keys():
            if key.startswith("USLT"):
                return tags[key].text
    except Exception:
        pass
    return None


def _write_id3_uslt(path: Path, lyrics: str) -> None:
    try:
        tags = ID3(path)
    except ID3NoHeaderError:
        tags = ID3()
    tags.delall("USLT")
    tags.add(USLT(encoding=3, lang="eng", desc="", text=lyrics))
    tags.save(path)


def _read_vorbis_lyrics(path: Path) -> str | None:
    """Read LYRICS Vorbis comment from FLAC/OGG/OPUS."""
    try:
        f = MutagenFile(path)
        if f is None or f.tags is None:
            return None
        # VorbisComment normalises keys to lowercase internally
        val = f.tags.get("lyrics")
        if val:
            return str(val[0]) if isinstance(val, list) else str(val)
    except Exception:
        pass
    return None


def _write_vorbis_lyrics(path: Path, lyrics: str) -> None:
    """Write LYRICS Vorbis comment to FLAC/OGG/OPUS."""
    f = MutagenFile(path)
    if f is None:
        raise RuntimeError(f"Cannot open {path}")
    if f.tags is None:
        f.add_tags()
    f.tags["LYRICS"] = [lyrics]  # type: ignore[index]
    f.save()
