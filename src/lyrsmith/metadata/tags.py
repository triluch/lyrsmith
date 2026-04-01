"""Read/write audio tags via mutagen.

Supported formats and their lyrics storage:
  MP3  — ID3 USLT frame
  FLAC — Vorbis comment LYRICS field
  OGG  — Vorbis comment LYRICS field
  OPUS — Vorbis comment LYRICS field

All other formats are not shown in the file browser (see AUDIO_EXTENSIONS).
"""

from __future__ import annotations

import json
from pathlib import Path

import langcodes
from mutagen import File as MutagenFile
from mutagen.id3 import ID3, TXXX, USLT, ID3NoHeaderError

from ..lrc import LineEnrichment, LRCLine, WordTiming, is_lrc
from .cache import FileInfo, LyricsType
from .disk_cache import disk_cache


def _lang_to_id3(lang: str) -> str:
    """Convert a BCP-47 code (or 'auto') to an ISO 639-2 alpha-3 code for USLT.

    'auto' (Whisper auto-detect) and anything unrecognised map to 'und'.
    A caller passing an already-valid 3-char code (e.g. 'eng') passes through.
    """
    if lang.lower() == "auto":
        return "und"
    try:
        return langcodes.Language.get(lang).to_alpha3()
    except Exception:
        return "und"


# Only formats with reliable lyrics read/write support.
# Files not matching this set are hidden in the file browser.
AUDIO_EXTENSIONS = frozenset({".mp3", ".flac", ".ogg", ".opus"})

_VORBIS_EXTS = frozenset({".flac", ".ogg", ".opus"})

# Custom tag name used to persist word-level timing data.
# MP3: stored as a TXXX frame (user-defined text) with this description.
# FLAC/OGG/OPUS: stored as a Vorbis comment key.
WORD_DATA_TAG = "LYRSMITH_WORDS"


def is_audio_file(path: Path) -> bool:
    return path.suffix.lower() in AUDIO_EXTENSIONS


# ------------------------------------------------------------------
# Public API
# ------------------------------------------------------------------


def read_info(path: Path) -> FileInfo:
    """Return FileInfo for path, using the SQLite disk cache when possible."""
    cached = disk_cache.get(path)
    if cached is not None:
        return cached

    title = artist = album = ""
    has_lyrics = False
    lyrics_type: LyricsType = None

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
        if raw:
            has_lyrics = True
            lyrics_type = "lrc" if is_lrc(raw) else "plain"
    except Exception:
        pass

    info = FileInfo(
        path=path,
        title=title,
        artist=artist,
        album=album,
        has_lyrics=has_lyrics,
        lyrics_type=lyrics_type,
    )
    disk_cache.put(info)
    return info


def read_lyrics(path: Path, lang_prefs: list[str] | None = None) -> str | None:
    """Return raw lyrics string, always reading from the audio file directly."""
    ext = path.suffix.lower()
    if ext == ".mp3":
        return _read_id3_uslt(path, lang_prefs=lang_prefs)
    elif ext in _VORBIS_EXTS:
        return _read_vorbis_lyrics(path)
    return None


def write_lyrics(path: Path, lyrics: str, lang: str = "und") -> None:
    """Write lyrics tag. Format is inferred from the file extension.

    *lang* accepts BCP-47 alpha-2 (e.g. 'en', 'pl'), ISO 639-2 alpha-3
    (e.g. 'eng', 'pol'), 'auto', or 'und'.  Converted to ISO 639-2
    internally for ID3 USLT frames; ignored for Vorbis formats.
    """
    ext = path.suffix.lower()
    try:
        if ext == ".mp3":
            _write_id3_uslt(path, lyrics, _lang_to_id3(lang))
        elif ext in _VORBIS_EXTS:
            _write_vorbis_lyrics(path, lyrics)
        else:
            raise RuntimeError(f"Lyrics saving not supported for {ext} files")
        disk_cache.invalidate(path)
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


def _select_uslt_frame(path: Path, lang_prefs: list[str] | None = None) -> tuple[str, str] | None:
    """Return ``(text, iso639_2_lang)`` of the best USLT frame, or ``None``.

    Selection priority:
    1. Synced (LRC) frames before plain-text frames.
    2. Among LRC frames, prefer the one whose lang matches the earliest entry
       in *lang_prefs* (BCP-47 alpha-2 codes; "auto" is ignored).
    3. If no lang matches, return the first LRC frame found.
    4. If no LRC frames exist, apply the same preference order to plain frames.
    """
    try:
        tags = ID3(path)
        frames = [tags[k] for k in tags.keys() if k.startswith("USLT")]
    except Exception:
        return None
    if not frames:
        return None

    lrc_frames = [f for f in frames if is_lrc(f.text)]
    plain_frames = [f for f in frames if not is_lrc(f.text)]

    def _pick(candidates: list) -> tuple[str, str] | None:
        if not candidates:
            return None
        if lang_prefs:
            id3_prefs = [_lang_to_id3(lp) for lp in lang_prefs if lp != "auto"]
            for id3_lang in id3_prefs:
                for f in candidates:
                    if f.lang == id3_lang:
                        return f.text, f.lang
        return candidates[0].text, candidates[0].lang

    return _pick(lrc_frames) or _pick(plain_frames)


def _read_id3_uslt(path: Path, lang_prefs: list[str] | None = None) -> str | None:
    """Return lyrics text from the best matching USLT frame, or ``None``."""
    result = _select_uslt_frame(path, lang_prefs)
    return result[0] if result else None


def read_uslt_lang(path: Path, lang_prefs: list[str] | None = None) -> str:
    """Return the ISO 639-2 lang of the selected USLT frame, or 'und' if none."""
    result = _select_uslt_frame(path, lang_prefs)
    return result[1] if result else "und"


def _write_id3_uslt(path: Path, lyrics: str, lang: str = "und") -> None:
    """Write lyrics to a single USLT frame, replacing any existing frames.

    *lang* should be an ISO 639-2 alpha-3 code (e.g. 'eng', 'pol').
    Always produces exactly one USLT frame regardless of how many existed.
    """
    try:
        tags = ID3(path)
    except ID3NoHeaderError:
        tags = ID3()
    tags.delall("USLT")
    tags.add(USLT(encoding=3, lang=lang, desc="", text=lyrics))
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


# ------------------------------------------------------------------
# Word timing data — encode / decode
# ------------------------------------------------------------------


def _ts_key(ts: float) -> str:
    """Timestamp → dict key, formatted to millisecond precision."""
    return f"{ts:.3f}"


def encode_word_data(lines: list[LRCLine]) -> str | None:
    """Serialise per-line enrichment data from *lines* to a compact JSON string.

    A line is included when it has words **or** a segment end timestamp.
    Returns ``None`` when no lines have enrichment data so callers can
    delete the tag rather than writing an empty payload.

    Schema::

        {
          "<ts>": {
            "end": <float>,          # optional — segment end seconds
            "words": [               # optional — word-level alignment
              {"w": str, "s": float, "e": float},
              ...
            ]
          },
          ...
        }

    where ``<ts>`` is ``f"{line.timestamp:.3f}"``.
    """
    data: dict[str, dict] = {}
    for line in lines:
        if not line.words and line.end is None:
            continue
        entry: dict = {}
        if line.end is not None:
            entry["end"] = round(line.end, 3)
        if line.words:
            entry["words"] = [
                {"w": w.word, "s": round(w.start, 3), "e": round(w.end, 3)} for w in line.words
            ]
        data[_ts_key(line.timestamp)] = entry
    return json.dumps(data, separators=(",", ":")) if data else None


def decode_word_data(text: str | None) -> dict[str, LineEnrichment]:
    """Deserialise a JSON string produced by *encode_word_data*.

    Returns a ``{timestamp_key: LineEnrichment}`` dict.  Returns ``{}``
    on a completely unparseable payload; partially corrupt data is handled
    gracefully — malformed word entries are skipped, malformed line entries
    are skipped, and all valid entries are still returned.
    """
    if not text:
        return {}
    try:
        raw = json.loads(text)
    except Exception:
        return {}
    result: dict[str, LineEnrichment] = {}
    for ts_key, entry in raw.items():
        if not isinstance(entry, dict):
            continue  # non-dict line entry skipped entirely
        # Parse end — fall back to None on a bad value, but keep the line.
        try:
            end = float(entry["end"]) if "end" in entry else None
        except Exception:
            end = None
        # Parse words — skip individual bad word entries.
        words: list[WordTiming] = []
        for w in entry.get("words", []):
            try:
                words.append(WordTiming(word=w["w"], start=float(w["s"]), end=float(w["e"])))
            except Exception:
                pass  # skip this word; keep the rest of the line
        result[ts_key] = LineEnrichment(end=end, words=words)
    return result


# ------------------------------------------------------------------
# Word timing data — tag I/O (public)
# ------------------------------------------------------------------


def read_word_data(path: Path) -> dict[str, LineEnrichment]:
    """Read enrichment data from *path*'s custom tag.

    Returns a ``{timestamp_key: LineEnrichment}`` dict on success, or
    ``{}`` when the tag is absent, the file format is unsupported, or any
    error occurs.  Pass the result to ``lrc.attach_word_data`` to hydrate
    a list of ``LRCLine`` objects.
    """
    try:
        ext = path.suffix.lower()
        if ext == ".mp3":
            raw = _read_id3_word_data(path)
        elif ext in _VORBIS_EXTS:
            raw = _read_vorbis_word_data(path)
        else:
            return {}
        return decode_word_data(raw)
    except Exception:
        return {}


def write_word_data(path: Path, lines: list[LRCLine]) -> None:
    """Write (or delete) word timing tag for *path*.

    Encodes word data from *lines* and writes the result.  When no lines
    carry word data the existing tag is deleted so files stay clean.
    Errors are silently swallowed — word data is enrichment and must never
    interfere with the main lyrics save.
    """
    data = encode_word_data(lines)
    ext = path.suffix.lower()
    try:
        if ext == ".mp3":
            _write_id3_word_data(path, data)
        elif ext in _VORBIS_EXTS:
            _write_vorbis_word_data(path, data)
    except Exception:
        pass


# ------------------------------------------------------------------
# Word timing data — format-specific helpers (private)
# ------------------------------------------------------------------


def _read_id3_word_data(path: Path) -> str | None:
    try:
        tags = ID3(path)
        frame = tags.get(f"TXXX:{WORD_DATA_TAG}")
        if frame is not None:
            return frame.text[0]
    except Exception:
        pass
    return None


def _write_id3_word_data(path: Path, data: str | None) -> None:
    try:
        tags = ID3(path)
    except ID3NoHeaderError:
        if data is None:
            return  # nothing to delete, no header to create
        tags = ID3()
    tags.delall(f"TXXX:{WORD_DATA_TAG}")
    if data is not None:
        tags.add(TXXX(encoding=3, desc=WORD_DATA_TAG, text=[data]))
    tags.save(path)


def _read_vorbis_word_data(path: Path) -> str | None:
    try:
        f = MutagenFile(path)
        if f is None or f.tags is None:
            return None
        val = f.tags.get(WORD_DATA_TAG.lower())
        if val:
            return str(val[0]) if isinstance(val, list) else str(val)
    except Exception:
        pass
    return None


def _write_vorbis_word_data(path: Path, data: str | None) -> None:
    f = MutagenFile(path)
    if f is None:
        return
    if f.tags is None:
        if data is None:
            return
        f.add_tags()
    # VorbisComment is case-insensitive; mutagen normalises keys to lowercase
    # internally.  Use the lowercase form consistently for both write and
    # delete so the two paths always address the same key.
    tag_key = WORD_DATA_TAG.lower()
    if data is None:
        if tag_key in f.tags:
            del f.tags[tag_key]  # type: ignore[attr-defined]
    else:
        f.tags[tag_key] = [data]  # type: ignore[index]
    f.save()
