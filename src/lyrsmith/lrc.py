"""LRC format parser and serializer. Pure data, no I/O."""

from __future__ import annotations

import re
from dataclasses import dataclass

_TIMESTAMP_RE = re.compile(r"\[(\d{1,2}):(\d{2})\.(\d{2,3})\]")
_META_RE = re.compile(r"^\[(\w+):(.*?)\]\s*$")


def _fmt_ts(seconds: float) -> str:
    """Format seconds as [MM:SS.cc]."""
    total_cs = round(seconds * 100)
    cs = total_cs % 100
    total_s = total_cs // 100
    s = total_s % 60
    m = total_s // 60
    return f"[{m:02d}:{s:02d}.{cs:02d}]"


@dataclass
class LRCLine:
    timestamp: float  # seconds (segment start)
    text: str
    end: float | None = None  # optional segment end time (populated by transcriber)

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

    Does a full linear scan — does NOT assume sorted input.  Mutations such as
    nudge or stamp can leave _lines out of order between re-sorts, so an
    early-exit optimisation would return the wrong line.
    """
    result = -1
    for i, line in enumerate(lines):
        if line.timestamp <= position:
            result = i
    return result
