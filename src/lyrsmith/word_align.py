"""Best-effort word timing reconciliation for edited LRC lines.

Algorithm overview
------------------
1. Normalise old and new word lists (lowercase, strip spaces) and align
   them at the *word* level using difflib.SequenceMatcher.
2. Each opcode segment is handled separately:

   equal   – copy timing verbatim; update word text for case / typo fixes.
   delete  – old word removed; timing dropped.
   insert  – new word with no old match; timing is interpolated from
             adjacent anchors in a post-processing pass.
   replace – N old words → M new words:
               N→1:  join   (start = first old start, end = last old end).
               1→M:  split  (proportional to syllable counts via pyphen).
               N→M:  character-level alignment of the concatenated strings;
                     new word timing is derived from where its characters
                     fall in the old char timeline.

3. After the main loop, inserted words (those with sentinel timing) are
   filled by linear interpolation between their surrounding anchors.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

from .lrc import WordTiming

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _norm(word: str) -> str:
    """Normalise a word for comparison: lowercase, strip whitespace."""
    return word.strip().lower()


def _count_syllables(word: str, lang: str = "") -> int:
    """Count syllables using pyphen; fall back to vowel-group counting."""
    clean = re.sub(r"[^a-zA-ZÀ-ÿ]", "", word)
    if not clean:
        return 1
    try:
        import pyphen

        dic = pyphen.Pyphen(lang=lang or "en")
        return len(dic.positions(clean)) + 1
    except Exception:
        groups = re.findall(r"[aeiouąęóáéíúàèìùāēīūæœy]+", clean.lower())
        return max(1, len(groups))


def _split_by_syllables(
    start: float,
    end: float,
    words: list[str],
    lang: str,
) -> list[WordTiming]:
    """Divide the interval [start, end] across words proportional to syllable count."""
    if not words:
        return []
    if len(words) == 1:
        return [WordTiming(word=words[0], start=round(start, 3), end=round(end, 3))]

    counts = [max(1, _count_syllables(_norm(w), lang)) for w in words]
    total = sum(counts)
    duration = end - start

    result: list[WordTiming] = []
    t = start
    for i, (word, count) in enumerate(zip(words, counts)):
        word_end = end if i == len(words) - 1 else t + (count / total) * duration
        result.append(WordTiming(word=word, start=round(t, 3), end=round(word_end, 3)))
        t = word_end
    return result


def _char_align_chunk(
    old_words: list[WordTiming],
    new_words: list[str],
) -> list[WordTiming]:
    """Align N old words → M new words via character-level fractional mapping.

    Builds a fractional timeline across old_concat (0.0 = first old start,
    1.0 = last old end), then uses SequenceMatcher on the concatenated
    normalised strings to map each new word's character range to a fraction
    of that timeline.  Unmatched characters are linearly interpolated between
    the nearest matched anchors.

    Handles the join case (N→1) naturally: the single new word maps to the
    full old timeline.
    """
    old_norm = "".join(_norm(w.word) for w in old_words)
    new_norm = "".join(_norm(w) for w in new_words)

    chunk_start = old_words[0].start
    chunk_end = old_words[-1].end
    duration = chunk_end - chunk_start

    n_old = len(old_norm)
    n_new = len(new_norm)

    # Build per-character fractional positions in the old timeline
    # old_frac[i]   = fractional start of old char i
    # old_frac[n_old] = 1.0  (end sentinel)
    old_frac: list[float] = []
    for w in old_words:
        text = _norm(w.word)
        n = len(text)
        if n == 0:
            continue
        w_start = (w.start - chunk_start) / duration if duration > 0 else 0.0
        w_end = (w.end - chunk_start) / duration if duration > 0 else 1.0
        for i in range(n):
            old_frac.append(w_start + (i / n) * (w_end - w_start))
    old_frac.append(1.0)  # end sentinel

    if not old_frac or n_old == 0 or n_new == 0:
        return [
            WordTiming(word=w, start=round(chunk_start, 3), end=round(chunk_end, 3))
            for w in new_words
        ]

    # Build (new_pos, old_frac) anchor list from SequenceMatcher matching blocks
    matcher = SequenceMatcher(None, old_norm, new_norm, autojunk=False)
    anchors: list[tuple[float, float]] = [(0.0, old_frac[0]), (float(n_new), 1.0)]
    for block in matcher.get_matching_blocks():
        oi, ni, size = block.a, block.b, block.size
        if size == 0:
            continue
        for k in range(size):
            anchors.append((float(ni + k), old_frac[oi + k]))
        anchors.append((float(ni + size), old_frac[oi + size]))

    anchors.sort(key=lambda x: x[0])
    # Deduplicate: keep the first value for each new_pos
    deduped: list[tuple[float, float]] = [anchors[0]]
    for a in anchors[1:]:
        if a[0] != deduped[-1][0]:
            deduped.append(a)
    anchors = deduped

    def _frac_at(pos: float) -> float:
        """Linearly interpolate the old fractional position at new char pos."""
        lo, hi = 0, len(anchors) - 1
        while lo < hi - 1:
            mid = (lo + hi) // 2
            if anchors[mid][0] <= pos:
                lo = mid
            else:
                hi = mid
        a0, f0 = anchors[lo]
        a1, f1 = anchors[hi]
        if a1 == a0:
            return f0
        return f0 + (pos - a0) / (a1 - a0) * (f1 - f0)

    # Map each new word's character range to a time interval
    result: list[WordTiming] = []
    pos = 0
    for i, word in enumerate(new_words):
        word_norm = _norm(word)
        word_len = len(word_norm)
        j_start = pos
        j_end = pos + word_len

        frac_s = _frac_at(float(j_start))
        frac_e = _frac_at(float(j_end))

        t_start = chunk_start + max(0.0, min(1.0, frac_s)) * duration
        t_end = chunk_start + max(0.0, min(1.0, frac_e)) * duration
        t_end = max(t_start, t_end)

        # Last word must end exactly at chunk_end
        if i == len(new_words) - 1:
            t_end = chunk_end

        result.append(WordTiming(word=word, start=round(t_start, 3), end=round(t_end, 3)))
        pos = j_end

    return result


_SENTINEL = -999.0  # marks words inserted with no old timing


def _fill_inserted(words: list[WordTiming], line_start: float | None = None) -> None:
    """Interpolate timing for words marked with the _SENTINEL start value."""
    n = len(words)
    i = 0
    while i < n:
        if words[i].start != _SENTINEL:
            i += 1
            continue
        # Find extent of the sentinel run
        j = i
        while j < n and words[j].start == _SENTINEL:
            j += 1
        # Bounding times: end of previous word / start of next. For insertions
        # at the very start, never backfill from absolute 0.0 unless the line
        # itself starts there; otherwise an inserted leading word can end up
        # absurdly far before the line timestamp.
        if i > 0:
            t0 = words[i - 1].end
        elif line_start is not None:
            t0 = max(0.0, line_start)
        elif j < n:
            t0 = words[j].start
        else:
            t0 = 0.0
        t1 = words[j].start if j < n else t0
        if t1 < t0:
            t0 = t1
        count = j - i
        for k in range(count):
            seg_start = t0 + (k / count) * (t1 - t0)
            seg_end = t0 + ((k + 1) / count) * (t1 - t0)
            words[i + k] = WordTiming(
                word=words[i + k].word,
                start=round(seg_start, 3),
                end=round(seg_end, 3),
            )
        i = j


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def reconcile_word_timings(
    old_words: list[WordTiming],
    new_text: str,
    lang: str = "",
    line_start: float | None = None,
) -> list[WordTiming]:
    """Compute best-effort word timings for *new_text* based on *old_words*.

    Returns an empty list when *old_words* is empty or *new_text* is blank.
    The returned :class:`~lyrsmith.lrc.WordTiming` objects use the same
    word-prefix convention as *old_words* (usually a leading space).
    """
    if not old_words or not new_text.strip():
        return []

    raw_tokens = new_text.split()
    if not raw_tokens:
        return []

    # Reconstruct word text with space prefix matching old_words convention
    first_has_space = old_words[0].word.startswith(" ")
    if first_has_space:
        new_word_list = [f" {t}" for t in raw_tokens]
    else:
        new_word_list = [raw_tokens[0]] + [f" {t}" for t in raw_tokens[1:]]

    old_norm = [_norm(w.word) for w in old_words]
    new_norm = [_norm(w) for w in new_word_list]

    matcher = SequenceMatcher(None, old_norm, new_norm, autojunk=False)
    result: list[WordTiming] = []

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        old_chunk = old_words[i1:i2]
        new_chunk = new_word_list[j1:j2]

        if tag == "equal":
            # Same word (normalised) — copy timing, adopt new word text
            for old_w, new_w in zip(old_chunk, new_chunk):
                result.append(WordTiming(word=new_w, start=old_w.start, end=old_w.end))

        elif tag == "delete":
            # Old word removed — no output
            pass

        elif tag == "insert":
            # New word with no old counterpart — use sentinel; filled later
            for new_w in new_chunk:
                result.append(WordTiming(word=new_w, start=_SENTINEL, end=_SENTINEL))

        elif tag == "replace":
            n_old, n_new = len(old_chunk), len(new_chunk)

            if n_old == 0:
                for new_w in new_chunk:
                    result.append(WordTiming(word=new_w, start=_SENTINEL, end=_SENTINEL))
            elif n_new == 0:
                pass  # nothing to emit

            elif n_old == 1 and n_new > 1:
                # 1 old → M new: split proportionally by syllable count
                splits = _split_by_syllables(
                    old_chunk[0].start,
                    old_chunk[0].end,
                    new_chunk,
                    lang,
                )
                result.extend(splits)

            else:
                # N→1 (join) or N→M: character-level alignment handles both
                result.extend(_char_align_chunk(old_chunk, new_chunk))

    _fill_inserted(result, line_start=line_start)
    return result
