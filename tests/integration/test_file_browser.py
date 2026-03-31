"""File browser: keyboard navigation, directory descent, file selection."""

from __future__ import annotations

import asyncio
from pathlib import Path

from textual.widgets import Label

from lyrsmith.ui.file_browser import FileBrowser
from lyrsmith.ui.lyrics_editor import LyricsEditor

from ._helpers import _fake_info, _make_mp3


class TestFileBrowser:
    """Keyboard navigation, directory descent, and file selection."""

    def _setup_dir(self, tmp_path: Path, monkeypatch) -> Path:
        audio = _make_mp3(tmp_path / "song.mp3")
        monkeypatch.setattr("lyrsmith.app.read_info", _fake_info)
        monkeypatch.setattr("lyrsmith.app.read_lyrics", lambda _p: None)
        return audio

    def _setup_multi(self, tmp_path: Path, monkeypatch) -> list[Path]:
        files = [
            _make_mp3(tmp_path / "rock.mp3"),
            _make_mp3(tmp_path / "jazz.mp3"),
            _make_mp3(tmp_path / "rock_ballad.mp3"),
        ]
        monkeypatch.setattr("lyrsmith.app.read_info", _fake_info)
        monkeypatch.setattr("lyrsmith.app.read_lyrics", lambda _p: None)
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
