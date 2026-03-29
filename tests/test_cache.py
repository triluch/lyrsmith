"""Tests for metadata/cache.py — LRU cache behaviour."""

from pathlib import Path

from lyrsmith.metadata.cache import FileInfo, MetadataCache


def _info(name: str) -> FileInfo:
    return FileInfo(
        path=Path(f"/music/{name}.mp3"),
        title=name.title(),
        artist="Test Artist",
        album="Test Album",
        has_lyrics=False,
        lyrics_type=None,
    )


class TestMetadataCache:
    def test_get_miss_returns_none(self):
        cache = MetadataCache(maxsize=5)
        assert cache.get(Path("/music/x.mp3")) is None

    def test_put_then_get(self):
        cache = MetadataCache(maxsize=5)
        info = _info("song")
        cache.put(info)
        assert cache.get(info.path) is info

    def test_get_updates_recency(self):
        cache = MetadataCache(maxsize=2)
        a, b = _info("a"), _info("b")
        cache.put(a)
        cache.put(b)
        # Access a — now b is least recently used
        cache.get(a.path)
        c = _info("c")
        cache.put(c)
        assert cache.get(b.path) is None  # b evicted
        assert cache.get(a.path) is not None

    def test_lru_evicts_oldest(self):
        cache = MetadataCache(maxsize=3)
        a, b, c, d = [_info(n) for n in "abcd"]
        cache.put(a)
        cache.put(b)
        cache.put(c)
        cache.put(d)  # should evict a
        assert cache.get(a.path) is None
        assert cache.get(b.path) is not None
        assert cache.get(d.path) is not None

    def test_re_put_updates_recency(self):
        cache = MetadataCache(maxsize=2)
        a, b = _info("a"), _info("b")
        cache.put(a)
        cache.put(b)
        cache.put(a)  # re-put a → a is most recent, b is now LRU
        c = _info("c")
        cache.put(c)  # should evict b
        assert cache.get(b.path) is None
        assert cache.get(a.path) is not None

    def test_invalidate_removes_entry(self):
        cache = MetadataCache(maxsize=5)
        info = _info("song")
        cache.put(info)
        cache.invalidate(info.path)
        assert cache.get(info.path) is None

    def test_invalidate_nonexistent_does_not_raise(self):
        cache = MetadataCache(maxsize=5)
        cache.invalidate(Path("/music/ghost.mp3"))  # no exception

    def test_maxsize_one(self):
        cache = MetadataCache(maxsize=1)
        a, b = _info("a"), _info("b")
        cache.put(a)
        cache.put(b)
        assert cache.get(a.path) is None
        assert cache.get(b.path) is not None

    def test_does_not_exceed_maxsize(self):
        cache = MetadataCache(maxsize=5)
        for i in range(20):
            cache.put(_info(str(i)))
        assert len(cache._cache) <= 5

    def test_concurrent_writes_do_not_corrupt(self):
        """Multiple threads writing simultaneously must not raise or exceed maxsize."""
        import threading

        cache = MetadataCache(maxsize=20)
        errors: list[Exception] = []

        def writer(offset: int) -> None:
            try:
                for i in range(50):
                    cache.put(_info(f"{offset}-{i}"))
                    cache.get(Path(f"/music/{offset}-{i}.mp3"))
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=writer, args=(t,)) for t in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Concurrent access raised: {errors}"
        assert len(cache._cache) <= 20


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
