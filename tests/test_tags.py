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

from lyrsmith.metadata.cache import cache
from lyrsmith.metadata.tags import (
    is_audio_file,
    read_info,
    read_lyrics,
    write_lyrics,
)


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
