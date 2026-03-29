"""Tests for metadata/tags.py — extension filtering and lyrics I/O.

write_lyrics / read_lyrics require real audio files. MP3 tests use a minimal
ID3 header (no audio frames). Vorbis-family tests (FLAC/OGG/OPUS) are created
via PyAV encoding a short silent WAV in memory.
"""

import io
import struct
import wave as wave_mod
from pathlib import Path

import pytest

from unittest.mock import MagicMock

from lyrsmith.metadata.cache import cache
from lyrsmith.lrc import LRCLine, LineEnrichment, WordTiming
from lyrsmith.metadata.tags import (
    WORD_DATA_TAG,
    _read_id3_uslt,
    _read_lyrics_raw,
    _read_vorbis_lyrics,
    decode_word_data,
    encode_word_data,
    is_audio_file,
    read_info,
    read_lyrics,
    read_word_data,
    write_lyrics,
    write_word_data,
)
import lyrsmith.metadata.tags as _tags_mod


# ---------------------------------------------------------------------------
# File creation helpers
# ---------------------------------------------------------------------------


def _make_mp3(path: Path) -> Path:
    """Write a file with a valid ID3v2 header and no audio so mutagen accepts it."""
    # ID3v2.3 header: 'ID3' + version(2.3) + flags(0) + syncsafe size(0)
    header = b"ID3\x03\x00\x00\x00\x00\x00\x00"
    path.write_bytes(header)
    return path


def _make_audio_via_pyav(path: Path, fmt: str, codec: str, sr: int = 22050) -> Path:
    """Encode 100 ms of silence to path using PyAV."""
    import av

    buf = io.BytesIO()
    with wave_mod.open(buf, "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(b"\x00" * (sr // 10 * 2))
    buf.seek(0)
    with av.open(buf, format="wav") as src:
        with av.open(str(path), mode="w", format=fmt) as dst:
            in_st = src.streams.audio[0]
            out_st = dst.add_stream(codec, rate=sr, layout="mono")
            for frame in src.decode(in_st):
                frame.pts = None
                for pkt in out_st.encode(frame):
                    dst.mux(pkt)
            for pkt in out_st.encode(None):
                dst.mux(pkt)
    return path


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mp3_file(tmp_path) -> Path:
    return _make_mp3(tmp_path / "test.mp3")


@pytest.fixture
def flac_file(tmp_path) -> Path:
    return _make_audio_via_pyav(tmp_path / "test.flac", "flac", "flac")


@pytest.fixture
def ogg_file(tmp_path) -> Path:
    return _make_audio_via_pyav(tmp_path / "test.ogg", "ogg", "libvorbis")


@pytest.fixture
def opus_file(tmp_path) -> Path:
    # libopus requires a standard sample rate; 48000 Hz is the native Opus rate.
    return _make_audio_via_pyav(tmp_path / "test.opus", "ogg", "libopus", sr=48000)


# ---------------------------------------------------------------------------
# is_audio_file
# ---------------------------------------------------------------------------


class TestIsAudioFile:
    @pytest.mark.parametrize(
        "ext",
        [".mp3", ".flac", ".ogg", ".opus"],
    )
    def test_known_audio_extensions(self, ext, tmp_path):
        p = tmp_path / f"file{ext}"
        assert is_audio_file(p) is True

    @pytest.mark.parametrize(
        "ext",
        [
            # never-supported formats
            ".txt",
            ".lrc",
            ".srt",
            ".py",
            ".jpg",
            ".pdf",
            "",
            ".mp",
            # dropped formats (no reliable cross-format lyrics R/W)
            ".m4a",
            ".wav",
            ".aac",
            ".wma",
            ".ape",
            ".aiff",
            ".aif",
        ],
    )
    def test_non_audio_extensions(self, ext, tmp_path):
        p = tmp_path / f"file{ext}"
        assert is_audio_file(p) is False

    def test_case_insensitive(self, tmp_path):
        assert is_audio_file(tmp_path / "FILE.MP3") is True
        assert is_audio_file(tmp_path / "file.FLAC") is True


# ---------------------------------------------------------------------------
# MP3 (ID3/USLT) lyrics I/O
# ---------------------------------------------------------------------------


class TestLyricsIO:
    def test_read_returns_none_for_no_lyrics(self, mp3_file):
        assert read_lyrics(mp3_file) is None

    def test_write_then_read_plain(self, mp3_file):
        write_lyrics(mp3_file, "Verse one\nVerse two")
        result = read_lyrics(mp3_file)
        assert result == "Verse one\nVerse two"

    def test_write_then_read_lrc(self, mp3_file):
        lrc = "[00:01.00]Hello\n[00:02.00]World"
        write_lyrics(mp3_file, lrc)
        result = read_lyrics(mp3_file)
        assert result == lrc

    def test_overwrite_replaces_existing(self, mp3_file):
        write_lyrics(mp3_file, "First version")
        write_lyrics(mp3_file, "Second version")
        assert read_lyrics(mp3_file) == "Second version"

    def test_write_to_nonexistent_path_raises(self, tmp_path):
        bad = tmp_path / "ghost.mp3"
        with pytest.raises(Exception):
            write_lyrics(bad, "some lyrics")

    def test_unicode_lyrics(self, mp3_file):
        lyrics = "Żółw\nСупер\n日本語"
        write_lyrics(mp3_file, lyrics)
        assert read_lyrics(mp3_file) == lyrics

    def test_write_to_unsupported_extension_raises_runtime_error(self, tmp_path):
        """write_lyrics must reject extensions outside the supported set."""
        wav = tmp_path / "audio.wav"
        wav.write_bytes(b"")
        with pytest.raises(RuntimeError, match="not supported"):
            write_lyrics(wav, "some lyrics")

    def test_write_to_mp3_without_id3_header_creates_new_tag(self, tmp_path):
        """A bare .mp3 with no ID3 header triggers the ID3NoHeaderError → ID3() fallback."""
        bare = tmp_path / "bare.mp3"
        bare.write_bytes(b"")  # no ID3 header at all
        write_lyrics(bare, "Fresh lyrics")
        assert _read_id3_uslt(bare) == "Fresh lyrics"

    def test_read_on_unsupported_extension_returns_none(self, tmp_path):
        """_read_lyrics_raw returns None for any extension not in the supported set."""
        unsupported = tmp_path / "audio.wav"
        assert _read_lyrics_raw(unsupported) is None


# ---------------------------------------------------------------------------
# Vorbis (FLAC / OGG / OPUS) lyrics I/O
# ---------------------------------------------------------------------------


class TestVorbisLyricsIO:
    def test_flac_no_lyrics_returns_none(self, flac_file):
        assert read_lyrics(flac_file) is None

    def test_flac_write_then_read_plain(self, flac_file):
        write_lyrics(flac_file, "Some lyrics\nLine two")
        assert read_lyrics(flac_file) == "Some lyrics\nLine two"

    def test_flac_write_then_read_lrc(self, flac_file):
        lrc = "[00:01.00]Hello\n[00:02.00]World"
        write_lyrics(flac_file, lrc)
        assert read_lyrics(flac_file) == lrc

    def test_flac_overwrite_replaces_existing(self, flac_file):
        write_lyrics(flac_file, "First")
        write_lyrics(flac_file, "Second")
        assert read_lyrics(flac_file) == "Second"

    def test_flac_unicode(self, flac_file):
        lyrics = "Żółw\nСупер\n日本語"
        write_lyrics(flac_file, lyrics)
        assert read_lyrics(flac_file) == lyrics

    def test_ogg_write_then_read(self, ogg_file):
        write_lyrics(ogg_file, "OGG lyrics")
        assert read_lyrics(ogg_file) == "OGG lyrics"

    def test_opus_write_then_read(self, opus_file):
        write_lyrics(opus_file, "OPUS lyrics")
        assert read_lyrics(opus_file) == "OPUS lyrics"

    def test_read_vorbis_non_list_lyrics_value(self, tmp_path, monkeypatch):
        """VorbisComment can occasionally return a bare string instead of a list;
        _read_vorbis_lyrics must handle both via the isinstance(val, list) guard."""
        mock_f = MagicMock()
        mock_f.tags.get.return_value = "plain string lyrics"
        monkeypatch.setattr(_tags_mod, "MutagenFile", lambda *a, **kw: mock_f)
        result = _read_vorbis_lyrics(tmp_path / "test.flac")
        assert result == "plain string lyrics"


# ---------------------------------------------------------------------------
# read_info — metadata extraction and cache
# ---------------------------------------------------------------------------


class TestReadInfo:
    def test_extracts_title_artist_album(self, flac_file):
        # The minimal MP3 fixture has no audio frames so MutagenFile(easy=True)
        # raises HeaderNotFoundError before it can read tags. Use a real FLAC
        # (which doesn't need audio frames to be identified) instead.
        from mutagen import File as MF

        f = MF(str(flac_file), easy=True)
        f.tags["title"] = ["My Song"]
        f.tags["artist"] = ["Artist Name"]
        f.tags["album"] = ["Album Name"]
        f.save()
        cache.invalidate(flac_file)

        info = read_info(flac_file)
        assert info.title == "My Song"
        assert info.artist == "Artist Name"
        assert info.album == "Album Name"

    def test_has_lyrics_set_when_lyrics_present(self, mp3_file):
        cache.invalidate(mp3_file)
        write_lyrics(mp3_file, "Hello world")
        info = read_info(mp3_file)
        assert info.has_lyrics is True
        assert info.lyrics_type == "plain"
        assert info.lyrics_text == "Hello world"

    def test_has_lyrics_false_when_absent(self, mp3_file):
        cache.invalidate(mp3_file)
        info = read_info(mp3_file)
        assert info.has_lyrics is False
        assert info.lyrics_text is None

    def test_lrc_type_detected(self, mp3_file):
        cache.invalidate(mp3_file)
        write_lyrics(mp3_file, "[00:01.00]Hello\n[00:02.00]World")
        info = read_info(mp3_file)
        assert info.lyrics_type == "lrc"

    def test_cache_hit_returns_same_object(self, mp3_file):
        # Ensure a fresh read then verify the second call hits the cache
        cache.invalidate(mp3_file)
        info1 = read_info(mp3_file)
        info2 = read_info(mp3_file)
        assert info1 is info2  # identical object from LRU cache


# ---------------------------------------------------------------------------
# encode_word_data / decode_word_data — pure serialisation
# ---------------------------------------------------------------------------


def _wt(word, start, end):
    return WordTiming(word=word, start=start, end=end)


def _line_with_words(ts, text, *word_specs, end=None):
    return LRCLine(ts, text, end=end, words=[_wt(*s) for s in word_specs])


class TestEncodeDecodeWordData:
    def test_empty_lines_returns_none(self):
        assert encode_word_data([]) is None

    def test_lines_without_enrichment_return_none(self):
        # Neither words nor end — nothing to store.
        lines = [LRCLine(1.0, "A"), LRCLine(2.0, "B")]
        assert encode_word_data(lines) is None

    def test_line_with_only_end_is_encoded(self):
        # A line may have end set but no words (e.g. after a text edit).
        line = LRCLine(1.0, "Edited", end=2.5)
        encoded = encode_word_data([line])
        assert encoded is not None
        decoded = decode_word_data(encoded)
        assert "1.000" in decoded
        assert decoded["1.000"].end == pytest.approx(2.5)
        assert decoded["1.000"].words == []

    def test_single_line_words_roundtrip(self):
        line = _line_with_words(
            1.0, "Hello world", (" Hello", 1.0, 1.3), (" world", 1.4, 1.8)
        )
        encoded = encode_word_data([line])
        assert encoded is not None
        decoded = decode_word_data(encoded)
        assert "1.000" in decoded
        enrich = decoded["1.000"]
        assert len(enrich.words) == 2
        assert enrich.words[0].word == " Hello"
        assert enrich.words[0].start == pytest.approx(1.0)
        assert enrich.words[0].end == pytest.approx(1.3)
        assert enrich.words[1].word == " world"
        assert enrich.words[1].start == pytest.approx(1.4)

    def test_single_line_end_and_words_roundtrip(self):
        line = _line_with_words(
            1.0, "Hello world", (" Hello", 1.0, 1.3), (" world", 1.4, 1.8), end=2.0
        )
        decoded = decode_word_data(encode_word_data([line]))
        enrich = decoded["1.000"]
        assert enrich.end == pytest.approx(2.0)
        assert len(enrich.words) == 2

    def test_only_enriched_lines_are_encoded(self):
        lines = [
            LRCLine(1.0, "No enrichment"),
            _line_with_words(2.0, "Has words", (" Has", 2.0, 2.3)),
            LRCLine(3.0, "Has end", end=4.0),
        ]
        decoded = decode_word_data(encode_word_data(lines))
        assert "1.000" not in decoded
        assert "2.000" in decoded
        assert "3.000" in decoded

    def test_timestamp_key_format_three_decimal_places(self):
        line = _line_with_words(1.5, "Mid", (" Mid", 1.5, 1.8))
        decoded = decode_word_data(encode_word_data([line]))
        assert "1.500" in decoded

    def test_unicode_word_text_preserved(self):
        line = _line_with_words(1.0, "Żółw", ("Żółw", 1.0, 1.5))
        decoded = decode_word_data(encode_word_data([line]))
        assert decoded["1.000"].words[0].word == "Żółw"

    def test_decode_invalid_json_returns_empty(self):
        assert decode_word_data("not json at all") == {}

    def test_decode_empty_string_returns_empty(self):
        assert decode_word_data("") == {}

    def test_decode_none_returns_empty(self):
        assert decode_word_data(None) == {}

    def test_multiple_lines_all_encoded(self):
        lines = [
            _line_with_words(1.0, "A", (" A", 1.0, 1.2)),
            _line_with_words(3.0, "B", (" B", 3.0, 3.2)),
        ]
        decoded = decode_word_data(encode_word_data(lines))
        assert set(decoded.keys()) == {"1.000", "3.000"}

    # -- G9: end=0.0 round-trip --

    def test_end_zero_is_not_confused_with_none(self):
        """end=0.0 is falsy but must be stored and retrieved correctly."""
        line = LRCLine(0.0, "Intro", end=0.0)
        encoded = encode_word_data([line])
        assert encoded is not None  # 0.0 is not None — line must be included
        decoded = decode_word_data(encoded)
        assert "0.000" in decoded
        assert decoded["0.000"].end == pytest.approx(0.0)

    # -- G1: partial corruption resilience --

    def test_decode_bad_word_entry_skipped_others_survive(self):
        """A word with a missing key must be skipped; other words in the line survive."""
        import json as _json

        payload = _json.dumps(
            {
                "1.000": {
                    "words": [
                        {"w": " Hello", "s": 1.0, "e": 1.3},
                        {"w": " World"},  # missing "s" and "e" — malformed
                        {"w": " there", "s": 1.5, "e": 1.8},
                    ]
                }
            }
        )
        decoded = decode_word_data(payload)
        assert "1.000" in decoded
        ws = decoded["1.000"].words
        assert len(ws) == 2  # bad entry skipped
        assert ws[0].word == " Hello"
        assert ws[1].word == " there"

    def test_decode_bad_end_value_falls_back_to_none(self):
        """Non-numeric end value must be silently dropped; words still loaded."""
        import json as _json

        payload = _json.dumps(
            {
                "2.000": {
                    "end": "not-a-number",
                    "words": [{"w": " Hi", "s": 2.0, "e": 2.3}],
                }
            }
        )
        decoded = decode_word_data(payload)
        assert "2.000" in decoded
        assert decoded["2.000"].end is None  # bad end dropped
        assert decoded["2.000"].words[0].word == " Hi"  # words still present

    def test_decode_corrupt_line_skipped_valid_lines_survive(self):
        """A line whose entire entry is invalid is skipped; other lines are returned."""
        import json as _json

        # The inner for-loop catches per-line errors; a non-dict entry will raise
        # AttributeError when .get() is called on it.
        payload = _json.dumps(
            {
                "1.000": "this-is-not-a-dict",  # completely malformed line
                "2.000": {"words": [{"w": " Hi", "s": 2.0, "e": 2.3}]},
            }
        )
        decoded = decode_word_data(payload)
        assert "1.000" not in decoded  # corrupt line skipped
        assert "2.000" in decoded  # valid line preserved
        assert decoded["2.000"].words[0].word == " Hi"


# ---------------------------------------------------------------------------
# read_word_data / write_word_data — MP3
# ---------------------------------------------------------------------------


class TestReadWriteWordDataMP3:
    def _sample_lines(self):
        return [
            _line_with_words(
                1.0, "Hello world", (" Hello", 1.0, 1.3), (" world", 1.4, 1.8), end=2.0
            )
        ]

    def test_read_absent_tag_returns_empty(self, mp3_file):
        assert read_word_data(mp3_file) == {}

    def test_write_then_read_words_roundtrip(self, mp3_file):
        lines = self._sample_lines()
        write_word_data(mp3_file, lines)
        result = read_word_data(mp3_file)
        assert "1.000" in result
        enrich = result["1.000"]
        assert enrich.words[0].word == " Hello"
        assert enrich.words[0].start == pytest.approx(1.0)
        assert enrich.words[1].word == " world"

    def test_write_then_read_end_roundtrip(self, mp3_file):
        lines = self._sample_lines()
        write_word_data(mp3_file, lines)
        result = read_word_data(mp3_file)
        assert result["1.000"].end == pytest.approx(2.0)

    def test_end_only_line_roundtrip(self, mp3_file):
        """Lines with only end set (no words) must also be persisted."""
        line = LRCLine(1.0, "Edited text", end=3.5)
        write_word_data(mp3_file, [line])
        result = read_word_data(mp3_file)
        assert "1.000" in result
        assert result["1.000"].end == pytest.approx(3.5)
        assert result["1.000"].words == []

    def test_overwrite_replaces_existing(self, mp3_file):
        lines_v1 = [_line_with_words(1.0, "Old", (" Old", 1.0, 1.3))]
        lines_v2 = [_line_with_words(2.0, "New", (" New", 2.0, 2.4))]
        write_word_data(mp3_file, lines_v1)
        write_word_data(mp3_file, lines_v2)
        result = read_word_data(mp3_file)
        assert "1.000" not in result
        assert "2.000" in result

    def test_write_empty_lines_deletes_tag(self, mp3_file):
        write_word_data(mp3_file, self._sample_lines())
        assert read_word_data(mp3_file) != {}
        write_word_data(mp3_file, [])
        assert read_word_data(mp3_file) == {}

    def test_write_lines_without_enrichment_deletes_tag(self, mp3_file):
        write_word_data(mp3_file, self._sample_lines())
        write_word_data(mp3_file, [LRCLine(1.0, "No enrichment")])
        assert read_word_data(mp3_file) == {}

    def test_tag_name_constant_used(self, mp3_file):
        """WORD_DATA_TAG must be the description of the TXXX frame."""
        write_word_data(mp3_file, self._sample_lines())
        from mutagen.id3 import ID3

        tags = ID3(mp3_file)
        assert f"TXXX:{WORD_DATA_TAG}" in tags

    def test_lyrics_tag_unaffected_by_word_data_write(self, mp3_file):
        """Writing word data must not corrupt an existing USLT lyrics tag."""
        write_lyrics(mp3_file, "[00:01.00]Hello")
        write_word_data(mp3_file, self._sample_lines())
        assert read_lyrics(mp3_file) == "[00:01.00]Hello"


# ---------------------------------------------------------------------------
# read_word_data / write_word_data — Vorbis (FLAC / OGG / OPUS)
# ---------------------------------------------------------------------------


class TestReadWriteWordDataVorbis:
    def _sample_lines(self):
        return [
            _line_with_words(
                1.0, "Hello world", (" Hello", 1.0, 1.3), (" world", 1.4, 1.8), end=2.0
            )
        ]

    @pytest.mark.parametrize("fixture_name", ["flac_file", "ogg_file", "opus_file"])
    def test_read_absent_tag_returns_empty(self, fixture_name, request):
        f = request.getfixturevalue(fixture_name)
        assert read_word_data(f) == {}

    @pytest.mark.parametrize("fixture_name", ["flac_file", "ogg_file", "opus_file"])
    def test_write_then_read_roundtrip(self, fixture_name, request):
        f = request.getfixturevalue(fixture_name)
        write_word_data(f, self._sample_lines())
        result = read_word_data(f)
        assert "1.000" in result
        enrich = result["1.000"]
        assert enrich.words[0].word == " Hello"
        assert enrich.words[0].start == pytest.approx(1.0)
        assert enrich.words[1].word == " world"
        assert enrich.end == pytest.approx(2.0)

    @pytest.mark.parametrize("fixture_name", ["flac_file", "ogg_file", "opus_file"])
    def test_write_empty_deletes_tag(self, fixture_name, request):
        f = request.getfixturevalue(fixture_name)
        write_word_data(f, self._sample_lines())
        assert read_word_data(f) != {}
        write_word_data(f, [])
        assert read_word_data(f) == {}

    @pytest.mark.parametrize("fixture_name", ["flac_file", "ogg_file", "opus_file"])
    def test_end_only_roundtrip(self, fixture_name, request):
        """Lines with only end set (no words) must round-trip correctly."""
        f = request.getfixturevalue(fixture_name)
        line = LRCLine(2.0, "Edited", end=3.5)
        write_word_data(f, [line])
        result = read_word_data(f)
        assert result["2.000"].end == pytest.approx(3.5)
        assert result["2.000"].words == []

    @pytest.mark.parametrize("fixture_name", ["flac_file", "ogg_file", "opus_file"])
    def test_lyrics_tag_unaffected(self, fixture_name, request):
        """Writing word data must not corrupt an existing LYRICS Vorbis tag."""
        f = request.getfixturevalue(fixture_name)
        write_lyrics(f, "[00:01.00]Hello")
        write_word_data(f, self._sample_lines())
        assert read_lyrics(f) == "[00:01.00]Hello"

    def test_flac_tag_key_name(self, flac_file):
        """Vorbis comment key must be WORD_DATA_TAG (case-insensitive match)."""
        write_word_data(flac_file, self._sample_lines())
        from mutagen import File as MF

        f = MF(str(flac_file))
        keys_lower = {k.lower() for k in f.tags.keys()}
        assert WORD_DATA_TAG.lower() in keys_lower
