"""Tests for metadata/cache.py — FileInfo data type."""

from pathlib import Path

from lyrsmith.metadata.cache import FileInfo


class TestFileInfoHelpers:
    def test_display_title_with_both(self):
        info = FileInfo(Path("/x.mp3"), "Song", "Band", "Album", False, None)
        assert info.display_title() == "Band — Song"

    def test_display_title_fallback_to_filename(self):
        info = FileInfo(Path("/x.mp3"), "", "", "", False, None)
        assert info.display_title() == "x.mp3"

    def test_lyrics_label_none(self):
        info = FileInfo(Path("/x.mp3"), "", "", "", False, None)
        assert info.lyrics_label() == "no lyrics"

    def test_lyrics_label_lrc(self):
        info = FileInfo(Path("/x.mp3"), "", "", "", True, "lrc")
        assert info.lyrics_label() == "synced LRC"

    def test_lyrics_label_plain(self):
        info = FileInfo(Path("/x.mp3"), "", "", "", True, "plain")
        assert info.lyrics_label() == "plain text"
