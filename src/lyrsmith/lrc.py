"""LRC format parser and serializer. Pure data, no I/O."""

from __future__ import annotations

import bisect
import re
from dataclasses import dataclass, field

_TIMESTAMP_RE = re.compile(r"\[(\d{1,2}):(\d{2})\.(\d{2,3})\]")
_META_RE = re.compile(r"^\[(\w+):(.*?)\]\s*$")
_NONWORD_RE = re.compile(r"[^\w]+")


def _fmt_ts(seconds: float) -> str:
    """Format seconds as [MM:SS.cc]."""
    total_cs = round(seconds * 100)
    cs = total_cs % 100
    total_s = total_cs // 100
    s = total_s % 60
    m = total_s // 60
    return f"[{m:02d}:{s:02d}.{cs:02d}]"


@dataclass
class WordTiming:
    """Single word with its start/end times from Whisper word-level alignment.

    ``word`` is the raw string returned by faster-whisper and may contain
    leading whitespace or punctuation.  Consumers that need plain text should
    strip/normalise it themselves.
    """

    word: str  # raw word text (may include leading space / punctuation)
    start: float  # seconds
    end: float  # seconds


@dataclass
class LineEnrichment:
    """Persisted per-line enrichment data loaded from the ``LYRSMITH_WORDS`` tag.

    Both fields are optional so the tag can store any subset of enrichment:
    a line may have only an end timestamp, only word timing, or both.
    """

    end: float | None = None
    words: list[WordTiming] = field(default_factory=list)


@dataclass
class LRCLine:
    timestamp: float  # seconds (segment start)
    text: str
    end: float | None = None  # optional segment end time (populated by transcriber)
    words: list[WordTiming] = field(default_factory=list)  # word-level timing (in-memory only)

    def timestamp_str(self) -> str:
        return _fmt_ts(self.timestamp)

    def end_timestamp_str(self) -> str | None:
        """Return end time formatted as [MM:SS.cc], or None if not set."""
        return _fmt_ts(self.end) if self.end is not None else None

    def __str__(self) -> str:
        """Serialisation format — no padding, written to tags as-is."""
        return f"{self.timestamp_str()}{self.text}"

    def display_str(self) -> str:
        """Display format — adds a space after the timestamp for readability."""
        return f"{self.timestamp_str()} {self.text}"


def parse(text: str) -> tuple[dict[str, str], list[LRCLine]]:
    """Parse LRC text. Returns (metadata_dict, sorted list of LRCLines)."""
    meta: dict[str, str] = {}
    lines: list[LRCLine] = []

    for raw in text.splitlines():
        raw = raw.strip()
        if not raw:
            continue

        timestamps = _TIMESTAMP_RE.findall(raw)
        if timestamps:
            text_part = _TIMESTAMP_RE.sub("", raw).strip()
            for mins, secs, cs_str in timestamps:
                # Normalise centiseconds/milliseconds to 2-digit cs
                cs_str = cs_str.ljust(3, "0")[:3]
                ts = int(mins) * 60 + int(secs) + int(cs_str) / 1000
                lines.append(LRCLine(timestamp=ts, text=text_part))
            continue

        m = _META_RE.match(raw)
        if m:
            meta[m.group(1)] = m.group(2).strip()

    lines.sort(key=lambda l: l.timestamp)
    return meta, lines


def serialize(meta: dict[str, str], lines: list[LRCLine]) -> str:
    """Serialize metadata and lines back to LRC text."""
    parts: list[str] = []
    for key, value in meta.items():
        parts.append(f"[{key}:{value}]")
    if meta:
        parts.append("")
    for line in sorted(lines, key=lambda l: l.timestamp):
        parts.append(str(line))
    return "\n".join(parts)


def is_lrc(text: str) -> bool:
    """Return True if text has at least one line that *starts* with a timestamp.

    Anchoring to line-start avoids false positives on plain text that happens
    to contain bracket patterns (e.g. timestamped notes or setlists).
    """
    return bool(re.search(r"^\[(\d{1,2}):(\d{2})\.(\d{2,3})\]", text, re.MULTILINE))


def active_line_index(lines: list[LRCLine], position: float) -> int:
    """Return index of the last line whose timestamp <= position. -1 if none.

    Assumes *lines* is sorted by timestamp — all mutation paths (stamp, nudge,
    insert, split, undo) maintain this invariant.  Uses binary search: O(log n).
    """
    return bisect.bisect_right(lines, position, key=lambda l: l.timestamp) - 1


def attach_word_data(lines: list[LRCLine], enrichment: dict[str, LineEnrichment]) -> None:
    """Attach persisted enrichment data to matching lines.

    *enrichment* is keyed by timestamp formatted to 3 decimal places
    (``f"{ts:.3f}"``), which is the format produced by
    ``metadata.tags.decode_word_data``.  Lines whose timestamp has no
    matching entry are left unchanged; partial coverage is fine.

    Sets both ``line.words`` and ``line.end`` (when the enrichment entry
    carries an end timestamp).
    """
    for line in lines:
        key = f"{line.timestamp:.3f}"
        if key in enrichment:
            e = enrichment[key]
            line.words = e.words
            if e.end is not None:
                line.end = e.end


def word_ts_for_split(words: list[WordTiming], second_half: str) -> tuple[float | None, int]:
    """Find the start time and list index of the word that begins *second_half*.

    The first token of *second_half* (stripped of non-word characters,
    lowercased) is compared against each ``WordTiming.word`` in order.  The
    first match wins.

    Returns ``(start_seconds, word_index)`` on success, ``(None, 0)`` when
    *words* is empty, *second_half* is blank, or no word matches.

    Callers should fall back to their existing heuristic timestamp when
    ``start_seconds is None``.  The returned ``word_index`` can be used as
    the boundary to split a words list into first-half and second-half
    portions — it is only meaningful when ``start_seconds is not None``.
    """
    if not words:
        return None, 0
    tokens = second_half.split()
    if not tokens:
        return None, 0
    target = _NONWORD_RE.sub("", tokens[0]).lower()
    if not target:
        return None, 0
    for i, w in enumerate(words):
        if _NONWORD_RE.sub("", w.word).lower() == target:
            return w.start, i
    return None, 0
