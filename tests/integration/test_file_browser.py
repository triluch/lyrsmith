"""File browser: keyboard navigation, directory descent, file selection."""

from __future__ import annotations

import asyncio
from pathlib import Path

from textual.widgets import Label

from lyrsmith.metadata.cache import FileInfo
from lyrsmith.metadata.disk_cache import DiskMetadataCache
from lyrsmith.ui.file_browser import FileBrowser
from lyrsmith.ui.lyrics_editor import LyricsEditor

from ._helpers import _SAMPLE_LRC, _fake_info, _make_mp3


class TestFileBrowser:
    """Keyboard navigation, directory descent, and file selection."""

    def _setup_dir(self, tmp_path: Path, monkeypatch) -> Path:
        audio = _make_mp3(tmp_path / "song.mp3")
        monkeypatch.setattr("lyrsmith.app.read_info", _fake_info)
        monkeypatch.setattr("lyrsmith.app.read_lyrics", lambda _p, **_kw: None)
        return audio

    def _setup_multi(self, tmp_path: Path, monkeypatch) -> list[Path]:
        files = [
            _make_mp3(tmp_path / "rock.mp3"),
            _make_mp3(tmp_path / "jazz.mp3"),
            _make_mp3(tmp_path / "rock_ballad.mp3"),
        ]
        monkeypatch.setattr("lyrsmith.app.read_info", _fake_info)
        monkeypatch.setattr("lyrsmith.app.read_lyrics", lambda _p, **_kw: None)
        return files

    @staticmethod
    def _visible_names(fb: FileBrowser, lv) -> list[str]:
        from textual.widgets import ListItem

        return [
            entry.name
            for item, entry in zip(lv.children, fb._entries)
            if isinstance(item, ListItem) and item.display and entry is not None
        ]

    def test_enter_on_file_loads_it(self, make_app, monkeypatch):
        _factory, tmp_path = make_app
        audio = self._setup_dir(tmp_path, monkeypatch)

        async def _impl():
            async with _factory(path=tmp_path).run_test(headless=True) as pilot:
                await pilot.pause()
                # Entry order: ".." (0), song.mp3 (1).
                # lv.index starts None; first down → 0 (..); second → 1 (file).
                await pilot.press("down")
                await pilot.pause()
                await pilot.press("down")
                await pilot.pause()
                await pilot.press("enter")
                await pilot.pause()
                app = pilot.app
                assert app._loaded_path == audio
                assert app.query_one(LyricsEditor).mode == "plain"

        asyncio.run(_impl())

    def test_enter_on_directory_descends(self, make_app, monkeypatch):
        _factory, tmp_path = make_app
        self._setup_dir(tmp_path, monkeypatch)
        subdir = tmp_path / "subdir"
        subdir.mkdir()

        async def _impl():
            async with _factory(path=tmp_path).run_test(headless=True) as pilot:
                await pilot.pause()
                fb = pilot.app.query_one(FileBrowser)
                # Entry order: ".." (0), subdir/ (1), song.mp3 (2).
                # Navigate to subdir: down × 2 (None → 0, 0 → 1).
                await pilot.press("down")
                await pilot.pause()
                await pilot.press("down")
                await pilot.pause()
                await pilot.press("enter")
                await pilot.pause()
                assert fb.current_path == subdir.resolve()

        asyncio.run(_impl())

    def test_backspace_navigates_up(self, make_app, monkeypatch):
        _factory, tmp_path = make_app
        self._setup_dir(tmp_path, monkeypatch)
        subdir = tmp_path / "subdir"
        subdir.mkdir()

        async def _impl():
            async with _factory(path=subdir).run_test(headless=True) as pilot:
                await pilot.pause()
                fb = pilot.app.query_one(FileBrowser)
                assert fb.current_path == subdir.resolve()
                await pilot.press("backspace")
                await pilot.pause()
                assert fb.current_path == tmp_path.resolve()

        asyncio.run(_impl())

    def test_file_browser_marks_loaded_file(self, make_app, monkeypatch):
        _factory, tmp_path = make_app
        audio = self._setup_dir(tmp_path, monkeypatch)

        async def _impl():
            async with _factory(path=tmp_path).run_test(headless=True) as pilot:
                await pilot.pause()
                fb = pilot.app.query_one(FileBrowser)
                fb.set_loaded(audio)
                await pilot.pause()
                lv = pilot.app.query_one("#browser-list")
                loaded_items = [item for item in lv.children if item.has_class("is-loaded")]
                assert len(loaded_items) == 1

        asyncio.run(_impl())

    def test_typing_filters_list_to_matching_files(self, make_app, monkeypatch):
        _factory, tmp_path = make_app
        self._setup_multi(tmp_path, monkeypatch)

        async def _impl():
            async with _factory(path=tmp_path).run_test(headless=True) as pilot:
                await pilot.pause()
                fb = pilot.app.query_one(FileBrowser)
                lv = pilot.app.query_one("#browser-list")
                assert len(self._visible_names(fb, lv)) == 3
                await pilot.press("j")
                await pilot.pause()
                assert self._visible_names(fb, lv) == ["jazz.mp3"]

        asyncio.run(_impl())

    def test_filter_label_active_while_query_set(self, make_app, monkeypatch):
        _factory, tmp_path = make_app
        self._setup_multi(tmp_path, monkeypatch)

        async def _impl():
            async with _factory(path=tmp_path).run_test(headless=True) as pilot:
                await pilot.pause()
                fb = pilot.app.query_one(FileBrowser)
                await pilot.press("j")
                await pilot.pause()
                assert fb._filter == "j"
                fl = pilot.app.query_one("#filter-label", Label)
                assert fl.has_class("active")

        asyncio.run(_impl())

    def test_escape_clears_filter_and_restores_all_items(self, make_app, monkeypatch):
        _factory, tmp_path = make_app
        self._setup_multi(tmp_path, monkeypatch)

        async def _impl():
            async with _factory(path=tmp_path).run_test(headless=True) as pilot:
                await pilot.pause()
                fb = pilot.app.query_one(FileBrowser)
                lv = pilot.app.query_one("#browser-list")
                await pilot.press("x")
                await pilot.pause()
                assert len(self._visible_names(fb, lv)) == 0
                await pilot.press("escape")
                await pilot.pause()
                assert len(self._visible_names(fb, lv)) == 3
                fl = pilot.app.query_one("#filter-label", Label)
                assert not fl.has_class("active")

        asyncio.run(_impl())

    def test_backspace_trims_filter_one_char(self, make_app, monkeypatch):
        _factory, tmp_path = make_app
        self._setup_multi(tmp_path, monkeypatch)

        async def _impl():
            async with _factory(path=tmp_path).run_test(headless=True) as pilot:
                await pilot.pause()
                fb = pilot.app.query_one(FileBrowser)
                lv = pilot.app.query_one("#browser-list")
                await pilot.press("j")
                await pilot.pause()
                await pilot.press("a")
                await pilot.pause()
                await pilot.press("z")
                await pilot.pause()
                assert self._visible_names(fb, lv) == ["jazz.mp3"]
                await pilot.press("backspace")
                await pilot.pause()
                assert fb._filter == "ja"
                assert self._visible_names(fb, lv) == ["jazz.mp3"]

        asyncio.run(_impl())

    def test_backspace_with_empty_filter_navigates_up(self, make_app, monkeypatch):
        _factory, tmp_path = make_app
        self._setup_dir(tmp_path, monkeypatch)
        subdir = tmp_path / "subdir"
        subdir.mkdir()

        async def _impl():
            async with _factory(path=subdir).run_test(headless=True) as pilot:
                await pilot.pause()
                fb = pilot.app.query_one(FileBrowser)
                assert fb._filter == ""
                assert fb.current_path == subdir.resolve()
                await pilot.press("backspace")
                await pilot.pause()
                assert fb.current_path == tmp_path.resolve()

        asyncio.run(_impl())

    def test_loaded_file_stays_visible_when_filtered_out(self, make_app, monkeypatch):
        _factory, tmp_path = make_app
        files = self._setup_multi(tmp_path, monkeypatch)
        rock_file = files[0]

        async def _impl():
            async with _factory(path=tmp_path).run_test(headless=True) as pilot:
                await pilot.pause()
                fb = pilot.app.query_one(FileBrowser)
                lv = pilot.app.query_one("#browser-list")
                fb.set_loaded(rock_file)
                await pilot.pause()
                await pilot.press("j")
                await pilot.pause()
                visible = self._visible_names(fb, lv)
                assert "jazz.mp3" in visible
                assert "rock.mp3" in visible
                assert "rock_ballad.mp3" not in visible

        asyncio.run(_impl())

    def test_filter_cleared_on_directory_change(self, make_app, monkeypatch):
        _factory, tmp_path = make_app
        self._setup_dir(tmp_path, monkeypatch)
        subdir = tmp_path / "subdir"
        subdir.mkdir()

        async def _impl():
            async with _factory(path=tmp_path).run_test(headless=True) as pilot:
                await pilot.pause()
                fb = pilot.app.query_one(FileBrowser)
                await pilot.press("s")
                await pilot.pause()
                assert fb._filter == "s"
                # _apply_filter moves cursor to first non-dotdot match (subdir at idx 1).
                # After one pause the reactive has settled — Enter descends directly.
                await pilot.press("enter")
                await pilot.pause()
                assert fb._filter == ""
                fl = pilot.app.query_one("#filter-label", Label)
                assert not fl.has_class("active")

        asyncio.run(_impl())

    def test_down_with_filter_does_not_visit_hidden_items(self, make_app, monkeypatch):
        _factory, tmp_path = make_app
        self._setup_multi(tmp_path, monkeypatch)

        async def _impl():
            async with _factory(path=tmp_path).run_test(headless=True) as pilot:
                await pilot.pause()
                lv = pilot.app.query_one("#browser-list")
                await pilot.press("j")
                await pilot.pause()
                idx_before = lv.index
                await pilot.press("down")
                await pilot.pause()
                assert lv.index == idx_before
                assert lv.children[lv.index].display

        asyncio.run(_impl())

    def test_up_with_filter_skips_hidden_items(self, make_app, monkeypatch):
        _factory, tmp_path = make_app
        self._setup_multi(tmp_path, monkeypatch)

        async def _impl():
            async with _factory(path=tmp_path).run_test(headless=True) as pilot:
                await pilot.pause()
                lv = pilot.app.query_one("#browser-list")
                await pilot.press("r")
                await pilot.pause()
                await pilot.press("o")
                await pilot.pause()
                await pilot.press("c")
                await pilot.pause()
                await pilot.press("k")
                await pilot.pause()
                await pilot.press("up")
                await pilot.pause()
                assert lv.children[lv.index].display

        asyncio.run(_impl())

    def test_down_with_filter_navigates_between_visible_items(self, make_app, monkeypatch):
        _factory, tmp_path = make_app
        self._setup_multi(tmp_path, monkeypatch)

        async def _impl():
            async with _factory(path=tmp_path).run_test(headless=True) as pilot:
                await pilot.pause()
                fb = pilot.app.query_one(FileBrowser)
                lv = pilot.app.query_one("#browser-list")
                await pilot.press("r")
                await pilot.pause()
                await pilot.press("o")
                await pilot.pause()
                await pilot.press("c")
                await pilot.pause()
                await pilot.press("k")
                await pilot.pause()
                idx_rock = lv.index
                await pilot.press("down")
                await pilot.pause()
                idx_after = lv.index
                assert idx_after > idx_rock
                assert lv.children[idx_after].display
                assert fb._entries[idx_after] is not None
                assert "rock" in fb._entries[idx_after].name.lower()

        asyncio.run(_impl())


class TestLyricsFilter:
    """ctrl+w cycles the lyrics-type filter; affected items are hidden/shown."""

    def _setup_files(self, tmp_path: Path, db: DiskMetadataCache) -> dict[str, Path]:
        """Create three audio files with different lyrics types in cache."""
        files = {
            "lrc": _make_mp3(tmp_path / "synced.mp3"),
            "plain": _make_mp3(tmp_path / "plain.mp3"),
            "none": _make_mp3(tmp_path / "nolrc.mp3"),
        }
        db.put(FileInfo(files["lrc"], "", "", "", True, "lrc"))
        db.put(FileInfo(files["plain"], "", "", "", True, "plain"))
        db.put(FileInfo(files["none"], "", "", "", False, None))
        return files

    def _item_display(self, fb: FileBrowser, path: Path) -> bool:
        """Return the display state of the list item for path."""
        lv = fb.query_one("#browser-list")
        for item, entry in zip(lv.children, fb._entries):
            if entry == path:
                return item.display
        raise AssertionError(f"{path.name} not found in browser entries")

    def test_ctrl_f_cycles_through_filter_states(self, make_app, monkeypatch, tmp_path):
        """ctrl+w advances: None → lrc → plain → none → None."""
        _factory, _ = make_app
        test_cache = DiskMetadataCache(":memory:")
        monkeypatch.setattr("lyrsmith.ui.file_browser.disk_cache", test_cache)

        async def _impl():
            async with _factory(path=tmp_path).run_test(headless=True) as pilot:
                await pilot.pause()
                fb = pilot.app.query_one(FileBrowser)
                assert fb._lyrics_filter is None
                await pilot.press("ctrl+w")
                await pilot.pause()
                assert fb._lyrics_filter == "lrc"
                await pilot.press("ctrl+w")
                await pilot.pause()
                assert fb._lyrics_filter == "plain"
                await pilot.press("ctrl+w")
                await pilot.pause()
                assert fb._lyrics_filter == "none"
                await pilot.press("ctrl+w")
                await pilot.pause()
                assert fb._lyrics_filter is None

        asyncio.run(_impl())

    def test_lrc_filter_shows_only_lrc_files(self, make_app, monkeypatch, tmp_path):
        """ctrl+w once hides plain and no-lyrics files, keeps LRC files visible."""
        _factory, _ = make_app
        test_cache = DiskMetadataCache(":memory:")
        files = self._setup_files(tmp_path, test_cache)
        monkeypatch.setattr("lyrsmith.ui.file_browser.disk_cache", test_cache)

        async def _impl():
            async with _factory(path=tmp_path).run_test(headless=True) as pilot:
                await pilot.pause()
                fb = pilot.app.query_one(FileBrowser)
                await pilot.press("ctrl+w")  # → lrc
                await pilot.pause()
                assert self._item_display(fb, files["lrc"]) is True
                assert self._item_display(fb, files["plain"]) is False
                assert self._item_display(fb, files["none"]) is False

        asyncio.run(_impl())

    def test_escape_clears_lyrics_filter(self, make_app, monkeypatch, tmp_path):
        """escape removes the lyrics filter and shows all files again."""
        _factory, _ = make_app
        test_cache = DiskMetadataCache(":memory:")
        files = self._setup_files(tmp_path, test_cache)
        monkeypatch.setattr("lyrsmith.ui.file_browser.disk_cache", test_cache)

        async def _impl():
            async with _factory(path=tmp_path).run_test(headless=True) as pilot:
                await pilot.pause()
                fb = pilot.app.query_one(FileBrowser)
                await pilot.press("ctrl+w")  # → lrc
                await pilot.pause()
                assert fb._lyrics_filter == "lrc"
                await pilot.press("escape")
                await pilot.pause()
                assert fb._lyrics_filter is None
                assert all(self._item_display(fb, f) for f in files.values())

        asyncio.run(_impl())

    def test_filter_label_shows_active_filter(self, make_app, monkeypatch, tmp_path):
        """The filter label reflects the active lyrics filter type."""
        _factory, _ = make_app
        test_cache = DiskMetadataCache(":memory:")
        monkeypatch.setattr("lyrsmith.ui.file_browser.disk_cache", test_cache)

        async def _impl():
            async with _factory(path=tmp_path).run_test(headless=True) as pilot:
                await pilot.pause()
                fb = pilot.app.query_one(FileBrowser)
                fl = fb.query_one("#filter-label", Label)
                assert not fl.display
                await pilot.press("ctrl+w")  # → lrc
                await pilot.pause()
                assert fl.display
                assert "[LRC]" in fl.content.plain
                await pilot.press("ctrl+w")  # → plain
                await pilot.pause()
                assert "[plain]" in fl.content.plain
                await pilot.press("ctrl+w")  # → none
                await pilot.pause()
                assert "[—]" in fl.content.plain

        asyncio.run(_impl())

    def test_warming_indicator_shown_while_cache_is_building(
        self, make_app, monkeypatch, tmp_path
    ):
        """set_warming(True) appends … to the filter label when a filter is active."""
        _factory, _ = make_app
        test_cache = DiskMetadataCache(":memory:")
        monkeypatch.setattr("lyrsmith.ui.file_browser.disk_cache", test_cache)

        async def _impl():
            async with _factory(path=tmp_path).run_test(headless=True) as pilot:
                await pilot.pause()
                fb = pilot.app.query_one(FileBrowser)
                fl = fb.query_one("#filter-label", Label)

                # No filter → warming indicator has no effect on visibility
                fb.set_warming(True)
                await pilot.pause()
                assert not fl.display

                # Activate filter → label should show … suffix
                await pilot.press("ctrl+w")
                await pilot.pause()
                assert "…" in fl.content.plain

                # set_warming(False) → indicator removed
                fb.set_warming(False)
                await pilot.pause()
                assert "…" not in fl.content.plain
                assert "[LRC]" in fl.content.plain

        asyncio.run(_impl())

    def test_warming_indicator_absent_when_no_filter(self, make_app, monkeypatch, tmp_path):
        """set_warming(True) has no visible effect when no lyrics filter is active."""
        _factory, _ = make_app
        test_cache = DiskMetadataCache(":memory:")
        monkeypatch.setattr("lyrsmith.ui.file_browser.disk_cache", test_cache)

        async def _impl():
            async with _factory(path=tmp_path).run_test(headless=True) as pilot:
                await pilot.pause()
                fb = pilot.app.query_one(FileBrowser)
                fl = fb.query_one("#filter-label", Label)
                fb.set_warming(True)
                await pilot.pause()
                assert not fl.display  # label hidden when no filter is active

        asyncio.run(_impl())

    def test_none_filter_shows_only_unlabelled_files(self, make_app, monkeypatch, tmp_path):
        """ctrl+w ×3 (→ none) hides LRC and plain files."""
        _factory, _ = make_app
        test_cache = DiskMetadataCache(":memory:")
        files = self._setup_files(tmp_path, test_cache)
        monkeypatch.setattr("lyrsmith.ui.file_browser.disk_cache", test_cache)

        async def _impl():
            async with _factory(path=tmp_path).run_test(headless=True) as pilot:
                await pilot.pause()
                fb = pilot.app.query_one(FileBrowser)
                for _ in range(3):
                    await pilot.press("ctrl+w")
                    await pilot.pause()
                assert fb._lyrics_filter == "none"
                assert self._item_display(fb, files["none"]) is True
                assert self._item_display(fb, files["lrc"]) is False
                assert self._item_display(fb, files["plain"]) is False

        asyncio.run(_impl())

    def test_loaded_file_always_visible_under_filter(self, make_app, monkeypatch, tmp_path):
        """A loaded file is always shown even when the lyrics filter would hide it."""
        _factory, _ = make_app
        audio = _make_mp3(tmp_path / "nolrc.mp3")
        test_cache = DiskMetadataCache(":memory:")
        test_cache.put(FileInfo(audio, "", "", "", False, None))  # no lyrics
        monkeypatch.setattr("lyrsmith.ui.file_browser.disk_cache", test_cache)

        async def _impl():
            async with _factory(path=tmp_path).run_test(headless=True) as pilot:
                await pilot.pause()
                fb = pilot.app.query_one(FileBrowser)

                # [LRC] filter: audio has no lyrics → hidden
                await pilot.press("ctrl+w")
                await pilot.pause()
                assert fb._lyrics_filter == "lrc"
                assert self._item_display(fb, audio) is False

                # Mark file as loaded (public API) — must become visible
                fb.set_loaded(audio)
                await pilot.pause()
                assert self._item_display(fb, audio) is True

        asyncio.run(_impl())

    def test_save_lrc_lyrics_updates_filter(self, make_app, monkeypatch, tmp_path):
        """After saving LRC lyrics, the browser filter reflects the new lyrics type.

        Flow: open file with no lyrics → load LRC content → save → verify the
        lyrics-type filter correctly shows/hides the file based on its new type.
        """
        _factory, _ = make_app
        audio = _make_mp3(tmp_path / "song.mp3")
        test_cache = DiskMetadataCache(":memory:")
        # Both the file-browser and the tags module must share the same cache so
        # the post-save read_info() call in _do_save updates what the filter sees.
        monkeypatch.setattr("lyrsmith.ui.file_browser.disk_cache", test_cache)
        monkeypatch.setattr("lyrsmith.metadata.tags.disk_cache", test_cache)

        async def _impl():
            async with _factory(path=tmp_path).run_test(headless=True) as pilot:
                await pilot.pause()
                await pilot.app.workers.wait_for_complete()
                await pilot.pause()
                fb = pilot.app.query_one(FileBrowser)

                # Navigate to file and open it while no filter is active.
                # Browser entries: ".." (0), "song.mp3" (1); lv.index starts None
                await pilot.press("down")  # None → 0 ("..")
                await pilot.pause()
                await pilot.press("down")  # 0 → 1 ("song.mp3")
                await pilot.pause()
                await pilot.press("enter")  # load the file
                await pilot.pause()

                # Load LRC content into the editor and mark it dirty
                ed = pilot.app.query_one(LyricsEditor)
                ed.load_lrc(_SAMPLE_LRC)
                ed.mark_dirty()
                await pilot.pause()

                # Activate [none] filter — file is loaded so it stays visible
                for _ in range(3):
                    await pilot.press("ctrl+w")
                    await pilot.pause()
                assert fb._lyrics_filter == "none"
                assert self._item_display(fb, audio) is True  # visible: it's loaded

                # Save — writes LRC to disk, updates cache, re-evaluates filter
                await pilot.press("ctrl+s")
                await pilot.pause()

                # Cache should now record the file as having LRC lyrics
                cached = test_cache.get(audio)
                assert cached is not None
                assert cached.lyrics_type == "lrc"

                # Unload the file so the filter isn't bypassed by the loaded exception
                fb.set_loaded(None)
                await pilot.pause()

                # [none] filter active, file now has LRC → hidden
                assert self._item_display(fb, audio) is False

                # Cycle to [LRC] filter → file should be shown
                await pilot.press("ctrl+w")  # none → off
                await pilot.pause()
                await pilot.press("ctrl+w")  # off → lrc
                await pilot.pause()
                assert fb._lyrics_filter == "lrc"
                assert self._item_display(fb, audio) is True

        asyncio.run(_impl())
