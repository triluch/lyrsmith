#!/usr/bin/env python3
"""
Build conjunction word lists from Universal Dependencies treebanks.

Downloads UD train files from GitHub, extracts all CCONJ-tagged tokens,
and writes one human-reviewable .txt file per language to
src/lyrsmith/data/conjunctions/.

Usage (run from repo root with dev dependencies installed):
    uv run scripts/build_conjunctions.py            # all languages
    uv run scripts/build_conjunctions.py en de pl   # specific
    uv run scripts/build_conjunctions.py --check    # verify URLs only

After generation, review each file:
  - Lines starting with # are comments — ignored by the runtime loader.
  - Pre-commented words (below the threshold marker) are excluded by default;
    uncomment a line to include it.
  - Delete a line to permanently exclude a word.
  - Add plain lines to include words not found in the source treebank.

Re-run to regenerate; existing files are NOT overwritten unless --force is given.
"""

from __future__ import annotations

import argparse
import sys
import urllib.request
from collections import Counter
from datetime import date
from pathlib import Path

import conllu

# ---------------------------------------------------------------------------
# Treebank registry
# (lang_iso_639_1, ud_repo, file_prefix, split)
# split is usually "train"; a few small treebanks only have "test"
# ---------------------------------------------------------------------------
TREEBANKS: dict[str, tuple[str, str, str]] = {
    "af": ("UD_Afrikaans-AfriBooms", "af_afribooms", "train"),
    "be": ("UD_Belarusian-HSE", "be_hse", "train"),
    "bg": ("UD_Bulgarian-BTB", "bg_btb", "train"),
    "ca": ("UD_Catalan-AnCora", "ca_ancora", "train"),
    "cs": ("UD_Czech-FicTree", "cs_fictree", "train"),
    "da": ("UD_Danish-DDT", "da_ddt", "train"),
    "de": ("UD_German-GSD", "de_gsd", "train"),
    "el": ("UD_Greek-GDT", "el_gdt", "train"),
    "en": ("UD_English-EWT", "en_ewt", "train"),
    "eo": ("UD_Esperanto-Prago", "eo_prago", "test"),  # no train split
    "et": ("UD_Estonian-EDT", "et_edt", "train"),
    "fr": ("UD_French-GSD", "fr_gsd", "train"),
    "ga": ("UD_Irish-IDT", "ga_idt", "train"),
    "gl": ("UD_Galician-CTG", "gl_ctg", "train"),
    "hr": ("UD_Croatian-SET", "hr_set", "train"),
    "hu": ("UD_Hungarian-Szeged", "hu_szeged", "train"),
    "id": ("UD_Indonesian-GSD", "id_gsd", "train"),
    "is": ("UD_Icelandic-Modern", "is_modern", "train"),
    "it": ("UD_Italian-ISDT", "it_isdt", "train"),
    "lt": ("UD_Lithuanian-ALKSNIS", "lt_alksnis", "train"),
    "lv": ("UD_Latvian-LVTB", "lv_lvtb", "train"),
    "nb": ("UD_Norwegian-Bokmaal", "no_bokmaal", "train"),
    "nl": ("UD_Dutch-Alpino", "nl_alpino", "train"),
    "nn": ("UD_Norwegian-Nynorsk", "no_nynorsk", "train"),
    "pl": ("UD_Polish-PDB", "pl_pdb", "train"),
    "pt": ("UD_Portuguese-GSD", "pt_gsd", "train"),
    "ro": ("UD_Romanian-RRT", "ro_rrt", "train"),
    "ru": ("UD_Russian-GSD", "ru_gsd", "train"),
    "sk": ("UD_Slovak-SNK", "sk_snk", "train"),
    "sl": ("UD_Slovenian-SSJ", "sl_ssj", "train"),
    "sr": ("UD_Serbian-SET", "sr_set", "train"),
    "es": ("UD_Spanish-GSD", "es_gsd", "train"),
    "sv": ("UD_Swedish-Talbanken", "sv_talbanken", "train"),
    "uk": ("UD_Ukrainian-IU", "uk_iu", "train"),
}

BASE_URL = "https://raw.githubusercontent.com/UniversalDependencies/{repo}/master/{prefix}-ud-{split}.conllu"
OUT_DIR = Path(__file__).parent.parent / "src" / "lyrsmith" / "data" / "conjunctions"


# ---------------------------------------------------------------------------
# Fetch + extract
# ---------------------------------------------------------------------------


def treebank_url(lang: str) -> str:
    repo, prefix, split = TREEBANKS[lang]
    return BASE_URL.format(repo=repo, prefix=prefix, split=split)


def fetch_cconj(lang: str) -> tuple[Counter[str], int, int]:
    """
    Download the treebank file and return:
      (cconj_counter, total_cconj_tokens, total_tokens)
    """
    url = treebank_url(lang)
    print(f"  Fetching {url.split('/')[-1]} … ", end="", flush=True)
    req = urllib.request.Request(url, headers={"User-Agent": "lyrsmith-build/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        raw = r.read()
    print(f"{len(raw) // 1024} KB")

    data = raw.decode("utf-8", errors="replace")
    cconj: Counter[str] = Counter()
    total_tokens = 0

    for sent in conllu.parse(data):
        for tok in sent:
            if not isinstance(tok["id"], int):
                continue
            total_tokens += 1
            if tok["upos"] == "CCONJ":
                cconj[tok["form"].lower()] += 1

    return cconj, sum(cconj.values()), total_tokens


# ---------------------------------------------------------------------------
# Write output
# ---------------------------------------------------------------------------


def review_threshold(total_cconj: int) -> int:
    """
    Frequency below which entries are pre-commented for manual review.
    Scales with corpus size; minimum of 2 to filter true singletons.
    """
    return max(2, total_cconj // 200)


def write_txt(lang: str, cconj: Counter[str], total_cconj: int, total_tokens: int) -> Path:
    repo, prefix, split = TREEBANKS[lang]
    threshold = review_threshold(total_cconj)
    unique = len(cconj)
    out = OUT_DIR / f"{lang}.txt"

    included = [(w, f) for w, f in cconj.most_common() if f >= threshold]
    review = [(w, f) for w, f in cconj.most_common() if f < threshold]

    max_wlen = max((len(w) for w, _ in cconj.most_common()), default=1)
    col = max(max_wlen + 2, 12)

    lines: list[str] = []

    lines += [
        f"# lang:     {lang}",
        f"# treebank: {repo}  ({prefix}-ud-{split}.conllu)",
        f"# fetched:  {date.today().isoformat()}",
        f"# tokens:   {total_tokens:,}  total  |  {total_cconj:,}  CCONJ  |  {unique}  unique",
        f"# threshold: freq >= {threshold}  (= max(2, {total_cconj} // 200))",
        "#",
        "# HOW TO REVIEW:",
        "#   - Lines starting with # are ignored by the loader.",
        "#   - Delete a line to exclude a word.",
        "#   - Uncomment a pre-commented line to include it.",
        "#   - Add a plain line to include a word not found in the source.",
        "#   - Frequency counts are shown for context only.",
        "",
    ]

    if included:
        for word, freq in included:
            lines.append(f"{word:{col}}# {freq}")
    else:
        lines.append("# (no entries above threshold)")

    if review:
        lines += [
            "",
            f"# --- below threshold (freq < {threshold}) — review before including ---",
        ]
        for word, freq in review:
            lines.append(f"#{word:{col}}# {freq}")

    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


# ---------------------------------------------------------------------------
# Check mode
# ---------------------------------------------------------------------------


def check_all() -> None:
    print("Checking URLs for all languages …\n")
    ok, fail = [], []
    for lang in sorted(TREEBANKS):
        url = treebank_url(lang)
        fname = url.split("/")[-1]
        try:
            req = urllib.request.Request(
                url, method="HEAD", headers={"User-Agent": "lyrsmith/1.0"}
            )
            with urllib.request.urlopen(req, timeout=10) as r:
                kb = int(r.headers.get("Content-Length", 0)) // 1024
            print(f"  OK  {lang}  {kb:>7,} KB  {fname}")
            ok.append(lang)
        except Exception as e:
            print(f"  FAIL {lang}  {e}")
            fail.append(lang)
    print(f"\n{len(ok)} OK  {len(fail)} FAIL")
    if fail:
        sys.exit(1)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "langs", nargs="*", metavar="LANG", help="ISO 639-1 language codes (default: all)"
    )
    parser.add_argument("--check", action="store_true", help="Verify URLs only, do not download")
    parser.add_argument("--force", action="store_true", help="Overwrite existing output files")
    args = parser.parse_args()

    if args.check:
        check_all()
        return

    langs = args.langs or sorted(TREEBANKS)
    unknown = [l for l in langs if l not in TREEBANKS]
    if unknown:
        print(f"Unknown language codes: {unknown}", file=sys.stderr)
        print(f"Available: {sorted(TREEBANKS.keys())}", file=sys.stderr)
        sys.exit(1)

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    results: list[tuple[str, Path, int, int]] = []  # lang, path, included, review
    errors: list[str] = []

    for lang in langs:
        out = OUT_DIR / f"{lang}.txt"
        if out.exists() and not args.force:
            print(f"[{lang}] {out.name} exists — skipping (use --force to overwrite)")
            continue

        print(f"[{lang}]")
        try:
            cconj, total_cconj, total_tokens = fetch_cconj(lang)
        except Exception as e:
            print(f"  ERROR: {e}")
            errors.append(lang)
            continue

        threshold = review_threshold(total_cconj)
        n_included = sum(1 for f in cconj.values() if f >= threshold)
        n_review = sum(1 for f in cconj.values() if f < threshold)

        path = write_txt(lang, cconj, total_cconj, total_tokens)
        results.append((lang, path, n_included, n_review))
        print(f"  → {path}  ({n_included} included, {n_review} flagged for review)")

    print()
    if results:
        print(f"Written {len(results)} file(s) to {OUT_DIR}")
    if errors:
        print(f"Failed: {errors}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
