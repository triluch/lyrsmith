"""Tests for metadata/disk_cache.py — SQLite-backed metadata cache."""

from pathlib import Path

import pytest

from lyrsmith.metadata.cache import FileInfo
from lyrsmith.metadata.disk_cache import DiskMetadataCache


def _info(path: Path, lyrics_type=None) -> FileInfo:
    return FileInfo(
        path=path,
        title="Test",
        artist="Artist",
        album="Album",
        has_lyrics=lyrics_type is not None,
        lyrics_type=lyrics_type,
    )


@pytest.fixture
def cache(tmp_path):
    return DiskMetadataCache(tmp_path / "test.db")


@pytest.fixture
def audio_file(tmp_path):
    p = tmp_path / "song.mp3"
    p.write_bytes(b"ID3\x03\x00\x00\x00\x00\x00\x00")
    return p


class TestDiskMetadataCacheBasics:
    def test_miss_returns_none(self, cache, audio_file):
        assert cache.get(audio_file) is None

    def test_put_then_get(self, cache, audio_file):
        info = _info(audio_file, "lrc")
        cache.put(info)
        result = cache.get(audio_file)
        assert result is not None
        assert result.lyrics_type == "lrc"
        assert result.title == "Test"
        assert result.artist == "Artist"

    def test_mtime_mismatch_returns_none(self, cache, audio_file):
        info = _info(audio_file)
        cache.put(info)
        # Touch the file to change its mtime
        audio_file.write_bytes(b"modified")
        assert cache.get(audio_file) is None

    def test_invalidate_removes_entry(self, cache, audio_file):
        cache.put(_info(audio_file))
        cache.invalidate(audio_file)
        assert cache.get(audio_file) is None

    def test_invalidate_nonexistent_does_not_raise(self, cache, tmp_path):
        cache.invalidate(tmp_path / "ghost.mp3")

    def test_put_replaces_existing(self, cache, audio_file):
        cache.put(_info(audio_file, "plain"))
        cache.put(_info(audio_file, "lrc"))
        assert cache.get(audio_file).lyrics_type == "lrc"

    def test_none_lyrics_type_stored_and_returned(self, cache, audio_file):
        cache.put(_info(audio_file, None))
        result = cache.get(audio_file)
        assert result is not None
        assert result.lyrics_type is None
        assert result.has_lyrics is False

    def test_missing_file_get_returns_none(self, cache, tmp_path):
        ghost = tmp_path / "missing.mp3"
        assert cache.get(ghost) is None

    def test_missing_file_put_is_noop(self, cache, tmp_path):
        ghost = tmp_path / "missing.mp3"
        cache.put(_info(ghost))  # should not raise


class TestDiskMetadataCachePersistence:
    def test_persists_across_instances(self, tmp_path, audio_file):
        """Data written by one instance is readable by another on the same db."""
        db = tmp_path / "shared.db"
        c1 = DiskMetadataCache(db)
        c1.put(_info(audio_file, "lrc"))
        c2 = DiskMetadataCache(db)
        result = c2.get(audio_file)
        assert result is not None
        assert result.lyrics_type == "lrc"
