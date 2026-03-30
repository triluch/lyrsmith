"""
Segment splitting: find the natural phrase boundary within a long segment.

Algorithm (validated experimentally against real music and TTS data):

  1. Candidates — word boundaries that are either:
       a. Followed by a Whisper inter-word gap >= GAP_THRESHOLD_MS  (language-agnostic),
          OR
       b. Before a coordinating conjunction whose split-time falls within
          CONJ_TOLERANCE_S of the syllable-balanced midpoint (language-specific).

  2. Score each candidate by syllable imbalance |left_syllables - right_syllables|;
     pick the minimum (most balanced split). Scoring by time-proximity to the
     midpoint is intentionally NOT used — when multiple gap candidates exist it
     picks the most-central gap rather than the most-balanced one.

  3. Fallback: if no candidates qualify, use pure syllable balance (the word
     boundary closest to half the total syllable count).

Syllable counting uses pyphen (LibreOffice hyphenation dictionaries).
Languages without a pyphen dictionary (CJK, Arabic, …) fall back to character
count as a syllabic proxy — pyphen.language_fallback() returns None for these.

Conjunction data lives in the bundled per-language .txt files under
src/lyrsmith/data/conjunctions/. Generate or refresh them with
scripts/build_conjunctions.py.
"""

from __future__ import annotations

import re
from functools import lru_cache
from importlib.resources import files as _pkg_files
from typing import Protocol, runtime_checkable

import pyphen

# ---------------------------------------------------------------------------
# Configuration (not exposed to the user; validated by experiment)
# ---------------------------------------------------------------------------

GAP_THRESHOLD_MS: float = 50.0  # inter-word gap that qualifies as a split candidate
CONJ_TOLERANCE_S: float = 1.0  # conjunction must be within this of the syllable midpoint

# ---------------------------------------------------------------------------
# Word protocol — accept faster-whisper Word objects or anything duck-typed
# ---------------------------------------------------------------------------


@runtime_checkable
class _Word(Protocol):
    word: str
    start: float
    end: float


# ---------------------------------------------------------------------------
# Conjunction data
# ---------------------------------------------------------------------------


@lru_cache(maxsize=64)
def conjunction_set(lang: str) -> frozenset[str]:
    """
    Load the conjunction set for *lang* from bundled data files.
    Returns an empty frozenset when no data file exists for that language.
    Cached so the file is read at most once per language per process.
    """
    try:
        ref = _pkg_files("lyrsmith") / "data" / "conjunctions" / f"{lang}.txt"
        text = ref.read_text(encoding="utf-8")
    except (FileNotFoundError, TypeError, OSError):
        return frozenset()

    words: set[str] = set()
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        # "word   # freq comment" → take part before inline #
        word = stripped.split("#")[0].strip()
        if word:
            words.add(word)
    return frozenset(words)


# ---------------------------------------------------------------------------
# Syllable counting
# ---------------------------------------------------------------------------


@lru_cache(maxsize=64)
def _pyphen_dic(lang: str) -> pyphen.Pyphen | None:
    fb = pyphen.language_fallback(lang)
    return None if fb is None else pyphen.Pyphen(lang=fb)


_STRIP_PUNCT = re.compile(r"[^\w]", re.UNICODE)


def _syllable_count(word_str: str, dic: pyphen.Pyphen | None) -> int:
    w = _STRIP_PUNCT.sub("", word_str).lower()
    if not w:
        return 1
    if dic is None:
        # character count as proxy (CJK, Arabic, …)
        return max(1, len(w) // 3)
    return len(dic.positions(w)) + 1


def _syllable_counts(words: list, lang: str) -> list[int]:
    dic = _pyphen_dic(lang)
    return [_syllable_count(w.word, dic) for w in words]


# ---------------------------------------------------------------------------
# Core split logic
# ---------------------------------------------------------------------------


def _split_time(words: list, idx: int) -> float:
    """Midpoint of the gap between words[idx] and words[idx+1]."""
    return (words[idx].end + words[idx + 1].start) / 2.0


def _syllable_midpoint(counts: list[int]) -> int:
    """Index i that minimises |sum(counts[:i+1]) - sum(counts[i+1:])|."""
    total = sum(counts)
    half = total / 2.0
    best_i, best_diff = 0, float("inf")
    running = 0
    for i, c in enumerate(counts[:-1]):
        running += c
        d = abs(running - half)
        if d < best_diff:
            best_diff = d
            best_i = i
    return best_i


def _imbalance(counts: list[int], split_after: int) -> int:
    left = sum(counts[: split_after + 1])
    right = sum(counts[split_after + 1 :])
    return abs(left - right)


def best_split_index(words: list, lang: str) -> int:
    """
    Return the index *i* after which to split *words* for the most natural result,
    based on gap candidates, conjunction candidates, and syllable balance.

    *words* must have at least 2 elements.
    *lang*  is the ISO 639-1 language code returned by Whisper's detection.
    """
    n = len(words)
    assert n >= 2, "need at least 2 words to split"

    counts = _syllable_counts(words, lang)
    syl_mid_i = _syllable_midpoint(counts)
    syl_mid_t = _split_time(words, syl_mid_i)

    candidates: set[int] = set()

    # (a) gap candidates
    for i in range(n - 1):
        gap_ms = (words[i + 1].start - words[i].end) * 1000.0
        if gap_ms >= GAP_THRESHOLD_MS:
            candidates.add(i)

    # (b) conjunction candidates (language-specific; skip if no data loaded)
    conj = conjunction_set(lang)
    if conj:
        for i in range(n - 1):
            next_w = _STRIP_PUNCT.sub("", words[i + 1].word).lower()
            if next_w in conj:
                if abs(_split_time(words, i) - syl_mid_t) <= CONJ_TOLERANCE_S:
                    candidates.add(i)

    if not candidates:
        return syl_mid_i

    # score by syllable imbalance; min() is stable so ties go to lower index
    return min(candidates, key=lambda i: _imbalance(counts, i))
