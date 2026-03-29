"""Full Pilot UI integration tests — drives LyrsmithApp via Textual's Pilot.

Coverage:
  - Pane navigation (Tab/Shift+Tab, bottom-bar context updates)
  - File browser (arrow navigation, directory descent, backspace to go up,
    file selection triggers load)
  - LRC editor interactions (stamp, nudge, delete, merge, edit modal)
  - Undo chain (stamp→delete, ctrl+z restores state)
  - Save flow (dirty flag, ctrl+s, UnsavedModal back/discard branches)
  - Config modal (F2 opens, cancel is safe, save updates config)
  - Waveform pane (space toggles play, seek keys, zoom keys, volume keys)
  - Transcription worker (no-file guard, successful run populates LRC editor)
  - E2E pilot transcription (real tiny model, real fixture, marked slow)

Most transcription tests use a stub for determinism.  The E2E class at the
bottom uses the real model and is marked @pytest.mark.slow.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import numpy as np
import pytest

from textual.widgets import Label

import lyrsmith.config as config_module
from lyrsmith.app import LyrsmithApp
from lyrsmith.config import Config
from lyrsmith.lrc import LRCLine, WordTiming
from lyrsmith.metadata.cache import FileInfo
from lyrsmith.metadata.tags import read_word_data, write_word_data
from lyrsmith.ui.bottom_bar import BottomBar
from lyrsmith.ui.config_modal import ConfigModal
from lyrsmith.ui.edit_line_modal import EditLineModal
from lyrsmith.ui.file_browser import FileBrowser
from lyrsmith.ui.lyrics_editor import LyricsEditor
from lyrsmith.ui.unsaved_modal import UnsavedModal
from lyrsmith.ui.waveform_pane import VOL_MAX, ZOOM_MIN, WaveformPane


# ---------------------------------------------------------------------------
# Minimal audio file helper
# ---------------------------------------------------------------------------


def _make_mp3(path: Path) -> Path:
    """Write a minimal ID3v2.3 header — sufficient for FileBrowser to list the
    file as an audio entry. Does NOT contain audio frames; read_info must be
    mocked when testing the full load path."""
    path.write_bytes(b"ID3\x03\x00\x00\x00\x00\x00\x00")
    return path


# ---------------------------------------------------------------------------
# FakePlayer — no libmpv dependency
# ---------------------------------------------------------------------------


class FakePlayer:
    """Drop-in replacement for Player; stores state in plain Python attrs."""

    def __init__(self, on_position=None):
        self._position = 0.0
        self._playing = False
        self._duration = 120.0
        self.loaded_path: Path | None = None

    def load(self, path: Path) -> None:
        self.loaded_path = path
        self._position = 0.0
        self._playing = False

    def play(self) -> None:
        self._playing = True

    def pause(self) -> None:
        self._playing = False

    def stop(self) -> None:
        self._playing = False

    def toggle(self) -> None:
        self._playing = not self._playing

    def terminate(self) -> None:
        pass

    def seek(self, s: float) -> None:
        self._position = max(0.0, min(s, self._duration))

    @property
    def is_playing(self) -> bool:
        return self._playing

    @property
    def position(self) -> float:
        return self._position

    @property
    def duration(self) -> float:
        return self._duration


# ---------------------------------------------------------------------------
# Shared fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def make_app(monkeypatch, tmp_path):
    """Redirect config I/O, replace Player with FakePlayer, stub PCM decode.

    Returns (app_factory, tmp_path).  Call app_factory() inside
    ``async with app.run_test(headless=True) as pilot`` in each test.
    """
    monkeypatch.setattr(config_module, "_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(config_module, "_CONFIG_FILE", tmp_path / "config.yaml")
    monkeypatch.setattr("lyrsmith.app.Player", FakePlayer)
    # Stub PCM decode so waveform load never touches real audio I/O.
    monkeypatch.setattr(
        "lyrsmith.app.decode_to_pcm",
        lambda _path: (np.array([], dtype=np.float32), 22050),
    )

    def _factory(path=None, config=None):
        return LyrsmithApp(
            initial_dir=path or tmp_path,
            config=config or Config(),
        )

    return _factory, tmp_path


@pytest.fixture
def make_app_real_decode(monkeypatch, tmp_path):
    """Like make_app but decode_to_pcm is NOT stubbed — waveform decodes for real.

    Use for e2e tests that also verify waveform data is populated.
    """
    monkeypatch.setattr(config_module, "_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(config_module, "_CONFIG_FILE", tmp_path / "config.yaml")
    monkeypatch.setattr("lyrsmith.app.Player", FakePlayer)

    def _factory(path=None, config=None):
        return LyrsmithApp(
            initial_dir=path or tmp_path,
            config=config or Config(),
        )

    return _factory, tmp_path


# ---------------------------------------------------------------------------
# Sample LRC content used by multiple test classes
# ---------------------------------------------------------------------------

_SAMPLE_LRC = (
    "[00:01.00]First line\n"
    "[00:03.00]Second line\n"
    "[00:05.00]Third line\n"
    "[00:07.00]Fourth line\n"
    "[00:09.00]Fifth line\n"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fake_info(path: Path) -> FileInfo:
    return FileInfo(
        path=path,
        title=path.stem,
        artist="",
        album="",
        has_lyrics=False,
        lyrics_type=None,
        lyrics_text=None,
    )


# ---------------------------------------------------------------------------
# TestPaneNavigation
# ---------------------------------------------------------------------------


class TestPaneNavigation:
    """Tab/Shift+Tab cycle focus; bottom bar context tracks the active pane."""

    def test_initial_context_is_browser(self, make_app):
        _factory, _ = make_app

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                await pilot.pause()
                pilot.app._poll_focus()
                assert pilot.app.query_one(BottomBar).context == "browser"

        asyncio.run(_impl())

    def test_tab_moves_focus_to_waveform(self, make_app):
        _factory, _ = make_app

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                await pilot.pause()
                await pilot.press("tab")
                await pilot.pause()
                pilot.app._poll_focus()
                assert pilot.app.query_one(BottomBar).context == "waveform"

        asyncio.run(_impl())

    def test_two_tabs_reach_lrc_editor(self, make_app):
        """Tab twice: browser → waveform → lrc-list (LRC mode required so the
        list widget is visible and in the focus chain)."""
        _factory, _ = make_app

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                await pilot.pause()
                # Pre-load LRC so #lrc-list is display:block and focusable.
                pilot.app.query_one(LyricsEditor).load_lrc(_SAMPLE_LRC)
                await pilot.pause()
                await pilot.press("tab")  # → WaveformPane
                await pilot.pause()
                await pilot.press("tab")  # → #lrc-list
                await pilot.pause()
                pilot.app._poll_focus()
                assert pilot.app.query_one(BottomBar).context == "lyrics-lrc"

        asyncio.run(_impl())

    def test_shift_tab_reverses_direction(self, make_app):
        _factory, _ = make_app

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                await pilot.pause()
                await pilot.press("tab")  # browser → waveform
                await pilot.pause()
                await pilot.press("shift+tab")  # waveform → browser
                await pilot.pause()
                pilot.app._poll_focus()
                assert pilot.app.query_one(BottomBar).context == "browser"

        asyncio.run(_impl())

    def test_tab_wraps_back_to_browser_in_empty_mode(self, make_app):
        """In empty mode #lrc-list is hidden, so Tab wraps after waveform."""
        _factory, _ = make_app

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                await pilot.pause()
                assert pilot.app.query_one(LyricsEditor).mode == "empty"
                await pilot.press("tab")  # → waveform
                await pilot.pause()
                await pilot.press("tab")  # wraps back to browser
                await pilot.pause()
                pilot.app._poll_focus()
                assert pilot.app.query_one(BottomBar).context == "browser"

        asyncio.run(_impl())


# ---------------------------------------------------------------------------
# TestFileBrowser
# ---------------------------------------------------------------------------


class TestFileBrowser:
    """Keyboard navigation, directory descent, and file selection."""

    def _setup_dir(self, tmp_path: Path, monkeypatch) -> Path:
        """Create song.mp3 and stub out read_info / read_lyrics."""
        audio = _make_mp3(tmp_path / "song.mp3")
        monkeypatch.setattr("lyrsmith.app.read_info", _fake_info)
        monkeypatch.setattr("lyrsmith.app.read_lyrics", lambda _p: None)
        return audio

    def _setup_multi(self, tmp_path: Path, monkeypatch) -> list[Path]:
        """Create three distinctly-named files for filter tests."""
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
        """Return names of visible non-'..' list items."""
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
                fb = pilot.app.query_one(FileBrowser)
                lv = pilot.app.query_one("#browser-list")
                # Jump cursor to song.mp3 (last entry)
                lv.index = len(fb._entries) - 1
                await pilot.pause()
                await pilot.press("enter")
                await pilot.pause()
                app = pilot.app
                assert app._loaded_path == audio
                # No embedded lyrics → plain mode with empty string
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
                lv = pilot.app.query_one("#browser-list")
                # Find the subdir entry
                idx = next(
                    i for i, e in enumerate(fb._entries) if e is not None and e.is_dir()
                )
                lv.index = idx
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
        """set_loaded() adds is-loaded CSS class to the correct list item."""
        _factory, tmp_path = make_app
        audio = self._setup_dir(tmp_path, monkeypatch)

        async def _impl():
            async with _factory(path=tmp_path).run_test(headless=True) as pilot:
                await pilot.pause()
                fb = pilot.app.query_one(FileBrowser)
                fb.set_loaded(audio)
                await pilot.pause()
                lv = pilot.app.query_one("#browser-list")
                loaded_items = [
                    item for item in lv.children if item.has_class("is-loaded")
                ]
                assert len(loaded_items) == 1

        asyncio.run(_impl())

    # ------------------------------------------------------------------
    # Filtering tests
    # ------------------------------------------------------------------

    def test_typing_filters_list_to_matching_files(self, make_app, monkeypatch):
        """Pressing printable keys narrows the visible file list by substring."""
        _factory, tmp_path = make_app
        self._setup_multi(tmp_path, monkeypatch)

        async def _impl():
            async with _factory(path=tmp_path).run_test(headless=True) as pilot:
                await pilot.pause()
                fb = pilot.app.query_one(FileBrowser)
                lv = pilot.app.query_one("#browser-list")
                # All three files visible before typing
                assert len(self._visible_names(fb, lv)) == 3
                # "j" only appears in jazz.mp3
                await pilot.press("j")
                await pilot.pause()
                visible = self._visible_names(fb, lv)
                assert visible == ["jazz.mp3"]

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
                await pilot.press(
                    "x"
                )  # no match — all hidden (x absent in rock/jazz/rock_ballad)
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
                # "jaz" → only jazz.mp3; backspace → "ja" → still only jazz.mp3
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
        """When no filter is active, backspace still navigates to parent dir."""
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
        """The currently loaded file is always shown regardless of the filter."""
        _factory, tmp_path = make_app
        files = self._setup_multi(tmp_path, monkeypatch)
        rock_file = files[0]  # rock.mp3

        async def _impl():
            async with _factory(path=tmp_path).run_test(headless=True) as pilot:
                await pilot.pause()
                fb = pilot.app.query_one(FileBrowser)
                lv = pilot.app.query_one("#browser-list")
                fb.set_loaded(rock_file)
                await pilot.pause()
                # "j" matches only jazz.mp3 — rock.mp3 would normally be hidden
                await pilot.press("j")
                await pilot.pause()
                visible = self._visible_names(fb, lv)
                assert "jazz.mp3" in visible
                assert "rock.mp3" in visible  # pinned: currently loaded
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
                lv = pilot.app.query_one("#browser-list")
                # Activate filter
                await pilot.press("s")
                await pilot.pause()
                assert fb._filter == "s"
                # Navigate into subdir — filter must reset
                idx = next(
                    i for i, e in enumerate(fb._entries) if e is not None and e.is_dir()
                )
                lv.index = idx
                await pilot.pause()
                await pilot.press("enter")
                await pilot.pause()
                assert fb._filter == ""
                fl = pilot.app.query_one("#filter-label", Label)
                assert not fl.has_class("active")

        asyncio.run(_impl())

    def test_down_with_filter_does_not_visit_hidden_items(self, make_app, monkeypatch):
        """Arrow-down must stop at the last visible item, not fall into hidden ones."""
        _factory, tmp_path = make_app
        self._setup_multi(tmp_path, monkeypatch)  # jazz, rock, rock_ballad

        async def _impl():
            async with _factory(path=tmp_path).run_test(headless=True) as pilot:
                await pilot.pause()
                lv = pilot.app.query_one("#browser-list")
                # "j" matches only jazz.mp3; rock* are hidden
                await pilot.press("j")
                await pilot.pause()
                idx_before = lv.index
                # Press down — no visible items after jazz.mp3, cursor must not move
                await pilot.press("down")
                await pilot.pause()
                assert lv.index == idx_before
                # Confirm we're not on a hidden item
                from textual.widgets import ListItem as _LI

                assert lv.children[lv.index].display

        asyncio.run(_impl())

    def test_up_with_filter_skips_hidden_items(self, make_app, monkeypatch):
        """Arrow-up must skip hidden items and land on the nearest visible one."""
        _factory, tmp_path = make_app
        self._setup_multi(
            tmp_path, monkeypatch
        )  # jazz(hidden), rock(vis), rock_ballad(vis)

        async def _impl():
            async with _factory(path=tmp_path).run_test(headless=True) as pilot:
                await pilot.pause()
                lv = pilot.app.query_one("#browser-list")
                # "rock" → rock.mp3 and rock_ballad visible; jazz hidden
                await pilot.press("r")
                await pilot.pause()
                await pilot.press("o")
                await pilot.pause()
                await pilot.press("c")
                await pilot.pause()
                await pilot.press("k")
                await pilot.pause()
                # Cursor is on rock.mp3 (first match).  Press up — jazz is hidden,
                # so we should skip it and land on ".." (always visible).
                await pilot.press("up")
                await pilot.pause()
                from textual.widgets import ListItem as _LI

                assert lv.children[lv.index].display  # must not land on a hidden item

        asyncio.run(_impl())

    def test_down_with_filter_navigates_between_visible_items(
        self, make_app, monkeypatch
    ):
        """Arrow-down with filter navigates correctly between visible items."""
        _factory, tmp_path = make_app
        self._setup_multi(tmp_path, monkeypatch)

        async def _impl():
            async with _factory(path=tmp_path).run_test(headless=True) as pilot:
                await pilot.pause()
                fb = pilot.app.query_one(FileBrowser)
                lv = pilot.app.query_one("#browser-list")
                # "rock" → rock.mp3 and rock_ballad both visible; jazz hidden between them
                await pilot.press("r")
                await pilot.pause()
                await pilot.press("o")
                await pilot.pause()
                await pilot.press("c")
                await pilot.pause()
                await pilot.press("k")
                await pilot.pause()
                idx_rock = lv.index  # first match: rock.mp3
                await pilot.press("down")
                await pilot.pause()
                idx_after = lv.index
                assert idx_after > idx_rock  # moved forward
                from textual.widgets import ListItem as _LI

                assert lv.children[idx_after].display  # landed on a visible item
                assert fb._entries[idx_after] is not None
                assert "rock" in fb._entries[idx_after].name.lower()

        asyncio.run(_impl())


# ---------------------------------------------------------------------------
# TestLrcEditorInteractions
# ---------------------------------------------------------------------------


class TestLrcEditorInteractions:
    """Key-driven LRC editing: stamp, nudge, delete, merge, edit modal."""

    async def _setup(self, pilot):
        """Load _SAMPLE_LRC and focus the lrc-list. Returns the editor."""
        ed = pilot.app.query_one(LyricsEditor)
        ed.load_lrc(_SAMPLE_LRC)
        await pilot.pause()
        # Focus the lrc-list so key events reach LyricsEditor.on_key
        pilot.app.query_one("#lrc-list").focus()
        await pilot.pause()
        return ed

    def test_stamp_updates_timestamp_to_playback_position(self, make_app):
        _factory, _ = make_app

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                ed = await self._setup(pilot)
                original_ts = ed._lines[ed._cursor_idx].timestamp  # 1.0
                # Stamp reads ed._current_position; the player callback is not
                # active in tests so we set the editor's tracking field directly.
                ed._current_position = 4.5
                await pilot.press("t")  # KB_STAMP_LINE
                await pilot.pause()
                stamped_ts = ed._lines[ed._cursor_idx].timestamp
                assert stamped_ts == pytest.approx(4.5)
                assert stamped_ts != pytest.approx(original_ts)
                assert ed.is_dirty
                ed.clear_dirty()
                await pilot.press("ctrl+q")

        asyncio.run(_impl())

    def test_nudge_fine_forward_shifts_timestamp(self, make_app):
        _factory, _ = make_app

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                ed = await self._setup(pilot)
                original_ts = ed._lines[ed._cursor_idx].timestamp  # 1.0
                await pilot.press("period")  # KB_NUDGE_FINE_FWD (+0.01 s)
                await pilot.pause()
                assert ed._lines[ed._cursor_idx].timestamp == pytest.approx(
                    original_ts + 0.010, abs=1e-4
                )
                assert ed.is_dirty

        asyncio.run(_impl())

    def test_nudge_med_backward_shifts_timestamp(self, make_app):
        _factory, _ = make_app

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                ed = await self._setup(pilot)
                # Move cursor to line 1 (ts=3.0) so backward nudge stays > 0
                ed._set_cursor(1)
                await pilot.pause()
                original_ts = ed._lines[1].timestamp  # 3.0
                await pilot.press("semicolon")  # KB_NUDGE_MED_BACK (-0.1 s)
                await pilot.pause()
                assert ed._lines[ed._cursor_idx].timestamp == pytest.approx(
                    original_ts - 0.100, abs=1e-4
                )

        asyncio.run(_impl())

    def test_delete_removes_line_and_marks_dirty(self, make_app):
        _factory, _ = make_app

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                ed = await self._setup(pilot)
                assert len(ed._lines) == 5
                assert not ed.is_dirty
                await pilot.press("ctrl+d")  # KB_DELETE_LINE
                await pilot.pause()
                assert len(ed._lines) == 4
                assert ed.is_dirty

        asyncio.run(_impl())

    def test_merge_joins_adjacent_lines(self, make_app):
        _factory, _ = make_app

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                ed = await self._setup(pilot)
                assert len(ed._lines) == 5
                await pilot.press("m")  # KB_MERGE_LINE
                await pilot.pause()
                assert len(ed._lines) == 4
                # _join_lines lowercases sentence-start of the second fragment
                assert ed._lines[0].text == "First line second line"
                assert ed.is_dirty

        asyncio.run(_impl())

    def test_edit_modal_opens_on_e_and_escape_cancels(self, make_app):
        _factory, _ = make_app

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                ed = await self._setup(pilot)
                original_text = ed._lines[0].text
                await pilot.press("e")  # KB_EDIT_LINE
                await pilot.pause()
                assert isinstance(pilot.app.screen, EditLineModal)
                await pilot.press("escape")
                await pilot.pause()
                assert not isinstance(pilot.app.screen, EditLineModal)
                # Text unchanged after cancel
                assert ed._lines[0].text == original_text

        asyncio.run(_impl())

    def test_edit_modal_enter_saves_modified_text(self, make_app):
        _factory, _ = make_app

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                from textual.widgets import TextArea as _TA

                ed = await self._setup(pilot)
                ed._set_cursor(0)
                await pilot.pause()
                await pilot.press("e")
                await pilot.pause()
                assert isinstance(pilot.app.screen, EditLineModal)
                # Replace the TextArea content directly, then confirm with Enter
                ta = pilot.app.screen.query_one("#edit-area", _TA)
                ta.load_text("Edited text")
                await pilot.pause()
                await pilot.press("enter")  # priority binding: action_save
                await pilot.pause()
                assert not isinstance(pilot.app.screen, EditLineModal)
                assert ed._lines[0].text == "Edited text"
                assert ed.is_dirty
                ed.clear_dirty()
                await pilot.press("ctrl+q")

        asyncio.run(_impl())

    def test_edit_modal_ctrl_k_splits_line(self, make_app):
        """Ctrl+K in the edit modal splits the current line into two."""
        _factory, _ = make_app

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                from textual.widgets import TextArea as _TA

                ed = await self._setup(pilot)
                ed._set_cursor(0)
                await pilot.pause()
                original_count = len(ed._lines)
                await pilot.press("e")
                await pilot.pause()
                assert isinstance(pilot.app.screen, EditLineModal)
                # Load multi-word text and split after the first word
                ta = pilot.app.screen.query_one("#edit-area", _TA)
                ta.load_text("Hello World")
                await pilot.pause()
                # Move cursor to position 5 (after "Hello")
                ta.move_cursor((0, 5))
                await pilot.pause()
                await pilot.press("ctrl+k")  # action_split
                await pilot.pause()
                assert not isinstance(pilot.app.screen, EditLineModal)
                assert len(ed._lines) == original_count + 1
                ed.clear_dirty()
                await pilot.press("ctrl+q")

        asyncio.run(_impl())

    def test_split_with_words_updates_first_half_end(self, make_app):
        """After a word-matched split, first half end = last first-half word end."""
        _factory, _ = make_app

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                from textual.widgets import TextArea as _TA

                ed = await self._setup(pilot)
                # Give line 0 word timing: "Hello" ends at 1.4, "World" ends at 2.0
                w_hello = WordTiming(word=" Hello", start=1.0, end=1.4)
                w_world = WordTiming(word=" World", start=1.6, end=2.0)
                ed._lines[0].words = [w_hello, w_world]
                ed._lines[0].end = 2.0  # original segment end

                ed._set_cursor(0)
                await pilot.pause()
                await pilot.press("e")
                await pilot.pause()
                assert isinstance(pilot.app.screen, EditLineModal)
                ta = pilot.app.screen.query_one("#edit-area", _TA)
                ta.load_text("Hello World")
                await pilot.pause()
                ta.move_cursor((0, 5))  # cursor after "Hello"
                await pilot.pause()
                await pilot.press("ctrl+k")
                await pilot.pause()

                # First half: "Hello" — end must be updated to w_hello.end
                assert ed._lines[0].end == pytest.approx(1.4)
                assert ed._lines[0].words == [w_hello]
                # Second half: "World" — keeps original segment end; ts from word
                assert ed._lines[1].end == pytest.approx(2.0)
                assert ed._lines[1].timestamp == pytest.approx(1.6)
                assert ed._lines[1].words == [w_world]

                ed.clear_dirty()
                await pilot.press("ctrl+q")

        asyncio.run(_impl())

    def test_edit_save_clears_word_data(self, make_app):
        """Changing line text via the edit modal must invalidate word timing."""
        _factory, _ = make_app

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                from textual.widgets import TextArea as _TA

                ed = await self._setup(pilot)
                ed._lines[0].words = [
                    WordTiming(" Hello", 1.0, 1.4),
                    WordTiming(" World", 1.6, 2.0),
                ]
                ed._set_cursor(0)
                await pilot.pause()
                await pilot.press("e")
                await pilot.pause()
                assert isinstance(pilot.app.screen, EditLineModal)
                ta = pilot.app.screen.query_one("#edit-area", _TA)
                # Modify the text — word alignment is now stale
                ta.load_text("Hello beautiful world")
                await pilot.pause()
                await pilot.press("enter")
                await pilot.pause()
                assert not isinstance(pilot.app.screen, EditLineModal)
                assert ed._lines[0].text == "Hello beautiful world"
                assert ed._lines[0].words == []
                ed.clear_dirty()
                await pilot.press("ctrl+q")

        asyncio.run(_impl())

    def test_edit_noop_preserves_word_data(self, make_app):
        """Saving without changing text must leave word timing untouched."""
        _factory, _ = make_app

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                from textual.widgets import TextArea as _TA

                ed = await self._setup(pilot)
                words = [
                    WordTiming(" First", 1.0, 1.3),
                    WordTiming(" line", 1.4, 1.7),
                ]
                ed._lines[0].words = words
                ed._set_cursor(0)
                await pilot.pause()
                await pilot.press("e")
                await pilot.pause()
                assert isinstance(pilot.app.screen, EditLineModal)
                # Press Enter immediately — text unchanged, early return expected
                await pilot.press("enter")
                await pilot.pause()
                assert not isinstance(pilot.app.screen, EditLineModal)
                # Words must be intact: no undo was saved, nothing was cleared
                assert ed._lines[0].words == words
                await pilot.press("ctrl+q")

        asyncio.run(_impl())

    def test_split_after_edit_uses_heuristic_timestamp(self, make_app):
        """After text is edited (words cleared), split falls back to playback position."""
        _factory, _ = make_app

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                from textual.widgets import TextArea as _TA

                ed = await self._setup(pilot)
                # words=[] simulates the state after a manual text edit
                ed._lines[0].words = []
                ed._lines[0].timestamp = 1.0
                # Playback position is past line 0 — heuristic should pick it up
                ed._current_position = 3.5
                ed._set_cursor(0)
                await pilot.pause()
                await pilot.press("e")
                await pilot.pause()
                assert isinstance(pilot.app.screen, EditLineModal)
                ta = pilot.app.screen.query_one("#edit-area", _TA)
                ta.load_text("Hello World")
                await pilot.pause()
                ta.move_cursor((0, 5))
                await pilot.pause()
                await pilot.press("ctrl+k")
                await pilot.pause()
                # New line timestamp must come from current_position (3.5),
                # NOT from any word start (there are none).
                assert ed._lines[1].timestamp == pytest.approx(3.5)
                assert ed._lines[1].words == []
                ed.clear_dirty()
                await pilot.press("ctrl+q")

        asyncio.run(_impl())


# ---------------------------------------------------------------------------
# TestUndoChain
# ---------------------------------------------------------------------------


class TestUndoChain:
    """Single-level undo: Ctrl+Z restores the most recent snapshot."""

    def test_stamp_then_undo_restores_timestamp(self, make_app):
        _factory, _ = make_app

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                ed = pilot.app.query_one(LyricsEditor)
                ed.load_lrc(_SAMPLE_LRC)
                await pilot.pause()
                pilot.app.query_one("#lrc-list").focus()
                await pilot.pause()

                original_ts = ed._lines[0].timestamp  # 1.0
                ed._current_position = 8.0  # stamp reads this, not player._position
                await pilot.press("t")  # stamp → saves undo snapshot
                await pilot.pause()
                assert ed._lines[ed._cursor_idx].timestamp == pytest.approx(8.0)

                await pilot.press("ctrl+z")  # undo
                await pilot.pause()
                # Cursor may have moved after undo; find "First line" by text
                ts = next(l.timestamp for l in ed._lines if l.text == "First line")
                assert ts == pytest.approx(original_ts)
                ed.clear_dirty()
                await pilot.press("ctrl+q")

        asyncio.run(_impl())

    def test_delete_then_undo_restores_line(self, make_app):
        _factory, _ = make_app

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                ed = pilot.app.query_one(LyricsEditor)
                ed.load_lrc(_SAMPLE_LRC)
                await pilot.pause()
                pilot.app.query_one("#lrc-list").focus()
                await pilot.pause()

                assert len(ed._lines) == 5
                deleted_text = ed._lines[0].text
                await pilot.press("ctrl+d")  # delete → saves undo
                await pilot.pause()
                assert len(ed._lines) == 4

                await pilot.press("ctrl+z")  # undo
                await pilot.pause()
                assert len(ed._lines) == 5
                assert any(l.text == deleted_text for l in ed._lines)
                ed.clear_dirty()
                await pilot.press("ctrl+q")

        asyncio.run(_impl())

    def test_stamp_nudge_delete_undo_chain(self, make_app):
        """Stamp then delete; only delete snapshot is available after ctrl+z
        (single-level undo — stamp's snapshot is overwritten by delete)."""
        _factory, _ = make_app

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                ed = pilot.app.query_one(LyricsEditor)
                ed.load_lrc(_SAMPLE_LRC)
                await pilot.pause()
                pilot.app.query_one("#lrc-list").focus()
                await pilot.pause()

                # Step 1: stamp (saves snapshot A)
                ed._current_position = (
                    6.0  # stamp reads this; player callback inactive in tests
                )
                await pilot.press("t")
                await pilot.pause()

                # Step 2: nudge (no new snapshot)
                await pilot.press("period")
                await pilot.pause()

                # Step 3: delete (saves snapshot B, overwriting A)
                count_before_delete = len(ed._lines)
                await pilot.press("ctrl+d")
                await pilot.pause()
                assert len(ed._lines) == count_before_delete - 1

                # ctrl+z → restores snapshot B (before delete)
                await pilot.press("ctrl+z")
                await pilot.pause()
                assert len(ed._lines) == count_before_delete

                # Second ctrl+z is a no-op (snapshot consumed)
                await pilot.press("ctrl+z")
                await pilot.pause()
                assert len(ed._lines) == count_before_delete
                ed.clear_dirty()

        asyncio.run(_impl())


# ---------------------------------------------------------------------------
# TestSaveFlow
# ---------------------------------------------------------------------------


class TestSaveFlow:
    """Dirty-flag tracking, ctrl+s save, and UnsavedModal interactions."""

    def test_dirty_flag_set_after_delete(self, make_app):
        _factory, _ = make_app

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                ed = pilot.app.query_one(LyricsEditor)
                ed.load_lrc(_SAMPLE_LRC)
                await pilot.pause()
                assert not ed.is_dirty
                pilot.app.query_one("#lrc-list").focus()
                await pilot.pause()
                await pilot.press("ctrl+d")
                await pilot.pause()
                assert ed.is_dirty
                ed.clear_dirty()
                await pilot.press("ctrl+q")

        asyncio.run(_impl())

    def test_ctrl_s_calls_write_lyrics(self, make_app, monkeypatch, tmp_path):
        _factory, _ = make_app
        audio = _make_mp3(tmp_path / "track.mp3")
        saved_calls: list[tuple[Path, str]] = []

        monkeypatch.setattr(
            "lyrsmith.app.write_lyrics",
            lambda path, text: saved_calls.append((path, text)),
        )
        monkeypatch.setattr("lyrsmith.app.read_info", _fake_info)
        monkeypatch.setattr("lyrsmith.app.read_lyrics", lambda _p: _SAMPLE_LRC)

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                app = pilot.app
                app._loaded_path = audio
                ed = app.query_one(LyricsEditor)
                ed.load_lrc(_SAMPLE_LRC)
                ed.mark_dirty()
                await pilot.pause()
                await pilot.press("ctrl+s")
                await pilot.pause()
                assert len(saved_calls) == 1
                assert saved_calls[0][0] == audio
                assert not ed.is_dirty
                await pilot.press("ctrl+q")

        asyncio.run(_impl())

    def test_ctrl_s_noop_when_no_file_loaded(self, make_app):
        """ctrl+s with no loaded file should silently do nothing (no crash)."""
        _factory, _ = make_app

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                assert pilot.app._loaded_path is None
                await pilot.press("ctrl+s")
                await pilot.pause()
                # No crash and editor remains in empty mode
                await pilot.press("ctrl+q")

        asyncio.run(_impl())

    def test_unsaved_modal_appears_when_loading_over_dirty(
        self, make_app, monkeypatch, tmp_path
    ):
        _factory, _ = make_app
        audio1 = _make_mp3(tmp_path / "a.mp3")
        audio2 = _make_mp3(tmp_path / "b.mp3")
        monkeypatch.setattr("lyrsmith.app.read_info", _fake_info)
        monkeypatch.setattr("lyrsmith.app.read_lyrics", lambda _p: None)
        monkeypatch.setattr("lyrsmith.app.write_lyrics", lambda *_: None)

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                app = pilot.app
                app._loaded_path = audio1
                ed = app.query_one(LyricsEditor)
                ed.load_lrc(_SAMPLE_LRC)
                ed.mark_dirty()
                await pilot.pause()

                # Simulate selecting a second file while dirty
                app.on_file_browser_file_selected(FileBrowser.FileSelected(audio2))
                await pilot.pause()
                assert isinstance(app.screen, UnsavedModal)

                # "Back" — dismiss without loading
                await pilot.press("escape")
                await pilot.pause()
                assert not isinstance(app.screen, UnsavedModal)
                assert app._loaded_path == audio1  # unchanged
                ed.clear_dirty()

        asyncio.run(_impl())

    def test_unsaved_modal_discard_proceeds_with_load(
        self, make_app, monkeypatch, tmp_path
    ):
        _factory, _ = make_app
        audio1 = _make_mp3(tmp_path / "a.mp3")
        audio2 = _make_mp3(tmp_path / "b.mp3")
        monkeypatch.setattr("lyrsmith.app.read_info", _fake_info)
        monkeypatch.setattr("lyrsmith.app.read_lyrics", lambda _p: None)
        monkeypatch.setattr("lyrsmith.app.write_lyrics", lambda *_: None)

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                app = pilot.app
                app._loaded_path = audio1
                ed = app.query_one(LyricsEditor)
                ed.load_lrc(_SAMPLE_LRC)
                ed.mark_dirty()
                await pilot.pause()

                app.on_file_browser_file_selected(FileBrowser.FileSelected(audio2))
                await pilot.pause()
                assert isinstance(app.screen, UnsavedModal)

                await pilot.press("2")  # discard
                await pilot.pause()
                assert not isinstance(app.screen, UnsavedModal)
                assert app._loaded_path == audio2

        asyncio.run(_impl())

    def test_unsaved_modal_save_writes_then_loads(
        self, make_app, monkeypatch, tmp_path
    ):
        _factory, _ = make_app
        audio1 = _make_mp3(tmp_path / "a.mp3")
        audio2 = _make_mp3(tmp_path / "b.mp3")
        saved_calls: list = []
        monkeypatch.setattr(
            "lyrsmith.app.write_lyrics",
            lambda path, text: saved_calls.append((path, text)),
        )
        monkeypatch.setattr("lyrsmith.app.read_info", _fake_info)
        monkeypatch.setattr("lyrsmith.app.read_lyrics", lambda _p: None)

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                app = pilot.app
                app._loaded_path = audio1
                ed = app.query_one(LyricsEditor)
                ed.load_lrc(_SAMPLE_LRC)
                ed.mark_dirty()
                await pilot.pause()

                app.on_file_browser_file_selected(FileBrowser.FileSelected(audio2))
                await pilot.pause()
                assert isinstance(app.screen, UnsavedModal)

                await pilot.press("3")  # save and proceed
                await pilot.pause()
                assert not isinstance(app.screen, UnsavedModal)
                # write_lyrics was called for the original file
                assert any(c[0] == audio1 for c in saved_calls)
                # And the new file is now loaded
                assert app._loaded_path == audio2
                await pilot.press("ctrl+q")

        asyncio.run(_impl())

    def test_ctrl_s_also_calls_write_word_data(self, make_app, monkeypatch, tmp_path):
        """ctrl+s must invoke write_word_data after write_lyrics."""
        _factory, _ = make_app
        audio = _make_mp3(tmp_path / "track.mp3")
        word_write_calls: list = []
        monkeypatch.setattr("lyrsmith.app.write_lyrics", lambda *_: None)
        monkeypatch.setattr(
            "lyrsmith.app.write_word_data",
            lambda path, lines: word_write_calls.append((path, lines)),
        )
        monkeypatch.setattr("lyrsmith.app.read_info", _fake_info)
        monkeypatch.setattr("lyrsmith.app.read_lyrics", lambda _p: _SAMPLE_LRC)

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                app = pilot.app
                app._loaded_path = audio
                ed = app.query_one(LyricsEditor)
                ed.load_lrc(_SAMPLE_LRC)
                ed._lines[0].words = [WordTiming(" First", 1.0, 1.3)]
                ed.mark_dirty()
                await pilot.pause()
                await pilot.press("ctrl+s")
                await pilot.pause()
                assert len(word_write_calls) == 1
                assert word_write_calls[0][0] == audio
                # Lines passed to write_word_data must include the word data
                assert any(l.words for l in word_write_calls[0][1])
                await pilot.press("ctrl+q")

        asyncio.run(_impl())

    def test_save_plain_mode_removes_word_data_tag(
        self, make_app, monkeypatch, tmp_path
    ):
        """Saving in plain-text mode must delete the LYRSMITH_WORDS tag from the file."""
        _factory, _ = make_app
        audio = _make_mp3(tmp_path / "track.mp3")
        # Pre-populate word data so there is something to delete
        write_word_data(
            audio, [LRCLine(1.0, "Hello", words=[WordTiming(" Hello", 1.0, 1.3)])]
        )
        assert read_word_data(audio) != {}

        monkeypatch.setattr("lyrsmith.app.read_info", _fake_info)
        # Return plain (non-LRC) text → editor enters plain mode
        monkeypatch.setattr("lyrsmith.app.read_lyrics", lambda _p: "Just plain lyrics")

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                app = pilot.app
                app._do_load(audio)
                await pilot.pause()
                ed = app.query_one(LyricsEditor)
                assert ed.mode == "plain"
                ed.mark_dirty()
                await pilot.press("ctrl+s")
                await pilot.pause()
                assert read_word_data(audio) == {}
                await pilot.press("ctrl+q")

        asyncio.run(_impl())


# ---------------------------------------------------------------------------
# TestWordDataPersistence
# ---------------------------------------------------------------------------


class TestWordDataPersistence:
    """Load→save→reload round-trips for word timing data."""

    def _prep_file(self, tmp_path, monkeypatch, *, word_lines):
        """Write word data to a fresh mp3 and mock read_info."""
        audio = _make_mp3(tmp_path / "track.mp3")
        write_word_data(audio, word_lines)
        monkeypatch.setattr("lyrsmith.app.read_info", _fake_info)
        return audio

    def test_word_data_attached_on_load(self, make_app, monkeypatch, tmp_path):
        """Words and end timestamps written to the tag must be attached to lines on load."""
        _factory, _ = make_app
        w = WordTiming(" First", 1.0, 1.3)
        audio = self._prep_file(
            tmp_path,
            monkeypatch,
            word_lines=[LRCLine(1.0, "First line", end=3.0, words=[w])],
        )
        monkeypatch.setattr("lyrsmith.app.read_lyrics", lambda _p: _SAMPLE_LRC)

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                app = pilot.app
                app._do_load(audio)
                await pilot.pause()
                ed = app.query_one(LyricsEditor)
                assert ed.mode == "lrc"
                line_1 = next(l for l in ed._lines if abs(l.timestamp - 1.0) < 0.01)
                assert len(line_1.words) == 1
                assert line_1.words[0].word == " First"
                assert line_1.end == pytest.approx(3.0)
                ed.clear_dirty()
                await pilot.press("ctrl+q")

        asyncio.run(_impl())

    def test_word_data_survives_save_then_reload(self, make_app, monkeypatch, tmp_path):
        """Word data must round-trip through ctrl+s → action_discard_reload."""
        _factory, _ = make_app
        w = WordTiming(" First", 1.0, 1.3)
        audio = self._prep_file(
            tmp_path,
            monkeypatch,
            word_lines=[LRCLine(1.0, "First line", end=3.0, words=[w])],
        )
        monkeypatch.setattr("lyrsmith.app.read_lyrics", lambda _p: _SAMPLE_LRC)

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                app = pilot.app
                app._do_load(audio)
                await pilot.pause()
                ed = app.query_one(LyricsEditor)
                assert ed._lines[0].words  # sanity: attached on load

                ed.mark_dirty()
                await pilot.press("ctrl+s")  # writes word data to tag
                await pilot.pause()

                app.action_discard_reload()  # reads word data from tag
                await pilot.pause()

                line_1 = next(l for l in ed._lines if abs(l.timestamp - 1.0) < 0.01)
                assert line_1.words[0].word == " First"
                assert line_1.end == pytest.approx(3.0)
                await pilot.press("ctrl+q")

        asyncio.run(_impl())

    def test_discard_reload_reattaches_word_data(self, make_app, monkeypatch, tmp_path):
        """action_discard_reload must re-read word data even after in-memory edits cleared it."""
        _factory, _ = make_app
        w = WordTiming(" Second", 3.0, 3.4)
        audio = self._prep_file(
            tmp_path,
            monkeypatch,
            word_lines=[LRCLine(3.0, "Second line", end=5.0, words=[w])],
        )
        monkeypatch.setattr("lyrsmith.app.read_lyrics", lambda _p: _SAMPLE_LRC)

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                app = pilot.app
                app._do_load(audio)
                await pilot.pause()
                ed = app.query_one(LyricsEditor)

                line_3 = next(l for l in ed._lines if abs(l.timestamp - 3.0) < 0.01)
                assert line_3.words[0].word == " Second"  # sanity

                # Simulate in-memory edits clearing word data
                for l in ed._lines:
                    l.words = []
                    l.end = None

                app.action_discard_reload()
                await pilot.pause()

                line_3_after = next(
                    l for l in ed._lines if abs(l.timestamp - 3.0) < 0.01
                )
                assert line_3_after.words[0].word == " Second"
                assert line_3_after.end == pytest.approx(5.0)
                await pilot.press("ctrl+q")

        asyncio.run(_impl())


# ---------------------------------------------------------------------------
# TestConfigModal
# ---------------------------------------------------------------------------


class TestConfigModal:
    """F2 config editor: open, cancel, and save with validation."""

    def test_f2_key_press_opens_modal(self, make_app):
        _factory, _ = make_app

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                await pilot.pause()
                await pilot.press("f2")
                await pilot.pause()
                assert isinstance(pilot.app.screen, ConfigModal)
                await pilot.press("f2")  # f2 also cancels
                await pilot.pause()
                assert not isinstance(pilot.app.screen, ConfigModal)

        asyncio.run(_impl())

    def test_cancel_leaves_config_unchanged(self, make_app):
        _factory, _ = make_app

        async def _impl():
            async with _factory(config=Config(whisper_model="base")).run_test(
                headless=True
            ) as pilot:
                app = pilot.app
                await pilot.pause()
                app.action_show_config()
                await pilot.pause()
                await pilot.press("escape")
                await pilot.pause()
                assert app._config.whisper_model == "base"

        asyncio.run(_impl())

    def test_save_updates_whisper_model(self, make_app):
        _factory, _ = make_app

        async def _impl():
            async with _factory(config=Config(whisper_model="base")).run_test(
                headless=True
            ) as pilot:
                from textual.widgets import Input as _Input

                app = pilot.app
                await pilot.pause()
                app.action_show_config()
                await pilot.pause()
                assert isinstance(app.screen, ConfigModal)

                inp = app.screen.query_one("#f-whisper-model", _Input)
                inp.value = "tiny"
                await pilot.pause()
                await pilot.press("ctrl+s")  # priority binding → action_save_config
                await pilot.pause()
                assert not isinstance(app.screen, ConfigModal)
                assert app._config.whisper_model == "tiny"
                await pilot.press("ctrl+q")

        asyncio.run(_impl())

    def test_save_with_invalid_threads_shows_error(self, make_app):
        """Non-integer intra_threads value triggers error label instead of dismissing."""
        _factory, _ = make_app

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                from textual.widgets import Input as _Input

                app = pilot.app
                await pilot.pause()
                app.action_show_config()
                await pilot.pause()
                assert isinstance(app.screen, ConfigModal)

                app.screen.query_one("#f-intra-threads", _Input).value = "not_a_number"
                await pilot.pause()
                await pilot.press("ctrl+s")
                await pilot.pause()
                # Modal stays open (validation failed — no dismiss)
                assert isinstance(app.screen, ConfigModal)
                await pilot.press("escape")
                await pilot.pause()
                assert not isinstance(app.screen, ConfigModal)
                await pilot.press("ctrl+q")

        asyncio.run(_impl())


# ---------------------------------------------------------------------------
# TestWaveformPane
# ---------------------------------------------------------------------------


class TestWaveformPane:
    """Key handling on the waveform pane: play/pause, seek, zoom."""

    async def _focus_waveform(self, pilot):
        await pilot.press("tab")  # browser → waveform
        await pilot.pause()

    def test_space_toggles_play_pause(self, make_app):
        _factory, _ = make_app

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                await self._focus_waveform(pilot)
                player = pilot.app._player
                assert not player.is_playing
                await pilot.press("space")
                await pilot.pause()
                assert player.is_playing
                await pilot.press("space")
                await pilot.pause()
                assert not player.is_playing
                await pilot.press("ctrl+q")

        asyncio.run(_impl())

    def test_right_arrow_seeks_forward(self, make_app):
        _factory, _ = make_app

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                await self._focus_waveform(pilot)
                player = pilot.app._player
                assert player.position == pytest.approx(0.0)
                await pilot.press("right")  # +5 s
                await pilot.pause()
                assert player.position == pytest.approx(5.0)

        asyncio.run(_impl())

    def test_left_arrow_seeks_backward(self, make_app):
        _factory, _ = make_app

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                await self._focus_waveform(pilot)
                # Set waveform's internal position directly so the delta is meaningful
                wf = pilot.app.query_one(WaveformPane)
                wf._position = 20.0
                await pilot.press("left")  # −5 s → 15.0
                await pilot.pause()
                assert pilot.app._player.position == pytest.approx(15.0)

        asyncio.run(_impl())

    def test_shift_right_seeks_large_forward(self, make_app):
        _factory, _ = make_app

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                await self._focus_waveform(pilot)
                await pilot.press("shift+right")  # +30 s
                await pilot.pause()
                assert pilot.app._player.position == pytest.approx(30.0)

        asyncio.run(_impl())

    def test_plus_zooms_in(self, make_app):
        _factory, _ = make_app

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                await self._focus_waveform(pilot)
                wf = pilot.app.query_one(WaveformPane)
                initial_zoom = wf.zoom
                await pilot.press("plus")  # zoom in → smaller value
                await pilot.pause()
                assert wf.zoom < initial_zoom
                await pilot.press("ctrl+q")

        asyncio.run(_impl())

    def test_minus_zooms_out(self, make_app):
        _factory, _ = make_app

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                await self._focus_waveform(pilot)
                wf = pilot.app.query_one(WaveformPane)
                initial_zoom = wf.zoom
                await pilot.press("minus")  # zoom out → larger value
                await pilot.pause()
                assert wf.zoom > initial_zoom

        asyncio.run(_impl())

    def test_zoom_clamped_at_minimum(self, make_app):
        _factory, _ = make_app

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                await self._focus_waveform(pilot)
                wf = pilot.app.query_one(WaveformPane)
                # Drive zoom to minimum
                for _ in range(50):
                    await pilot.press("plus")
                await pilot.pause()
                assert wf.zoom == pytest.approx(ZOOM_MIN)

        asyncio.run(_impl())

    def test_up_increases_volume(self, make_app):
        _factory, _ = make_app

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                await self._focus_waveform(pilot)
                wf = pilot.app.query_one(WaveformPane)
                wf.set_volume(50.0)
                await pilot.press("up")
                await pilot.pause()
                assert wf.volume > 50.0

        asyncio.run(_impl())

    def test_down_decreases_volume(self, make_app):
        _factory, _ = make_app

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                await self._focus_waveform(pilot)
                wf = pilot.app.query_one(WaveformPane)
                wf.set_volume(50.0)
                await pilot.press("down")
                await pilot.pause()
                assert wf.volume < 50.0

        asyncio.run(_impl())

    def test_volume_clamped_at_zero(self, make_app):
        _factory, _ = make_app

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                await self._focus_waveform(pilot)
                wf = pilot.app.query_one(WaveformPane)
                for _ in range(30):
                    await pilot.press("down")
                await pilot.pause()
                assert wf.volume == pytest.approx(0.0)

        asyncio.run(_impl())

    def test_volume_clamped_at_max(self, make_app):
        _factory, _ = make_app

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                await self._focus_waveform(pilot)
                wf = pilot.app.query_one(WaveformPane)
                for _ in range(30):
                    await pilot.press("up")
                await pilot.pause()
                assert wf.volume == pytest.approx(VOL_MAX)

        asyncio.run(_impl())

    def test_volume_change_saved_to_config(self, make_app):
        _factory, cfg = make_app

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                await self._focus_waveform(pilot)
                wf = pilot.app.query_one(WaveformPane)
                wf.set_volume(40.0)
                await pilot.press("up")  # → 45%
                await pilot.pause()
                assert pilot.app._config.volume == pytest.approx(45.0)

        asyncio.run(_impl())


# ---------------------------------------------------------------------------
# TestTranscription
# ---------------------------------------------------------------------------


class TestTranscription:
    """Ctrl+T triggers transcription worker; result populates the LRC editor.

    Transcription output in production is non-deterministic.  All tests here
    use a deterministic stub so assertions are stable across runs.
    """

    def test_transcribe_with_no_file_loaded_is_noop(self, make_app):
        _factory, _ = make_app

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                app = pilot.app
                assert app._loaded_path is None
                ed = app.query_one(LyricsEditor)
                assert ed.mode == "empty"
                app.action_transcribe()  # action, not key press (avoids focus dep)
                await pilot.pause()
                assert ed.mode == "empty"

        asyncio.run(_impl())

    def test_transcribe_populates_lrc_editor(self, make_app, monkeypatch, tmp_path):
        """Stub transcriber returns fixed lines; verifies mode, line count, dirty
        flag, and that current_text() round-trips back through LRC parse correctly."""
        from lyrsmith.lrc import parse
        from lyrsmith.transcribe.whisper import transcriber as _tr

        _factory, _ = make_app
        audio = _make_mp3(tmp_path / "vocal.mp3")

        stub_lines = [
            LRCLine(1.0, "Hello world"),
            LRCLine(3.5, "Goodbye world"),
            LRCLine(6.0, "See you later"),
        ]
        monkeypatch.setattr(_tr, "transcribe", lambda *a, **kw: stub_lines)
        monkeypatch.setattr(_tr, "load_model", lambda *a, **kw: None)

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                app = pilot.app
                app._loaded_path = audio
                ed = app.query_one(LyricsEditor)
                await pilot.pause()
                app.action_transcribe()
                await pilot.app.workers.wait_for_complete()
                await pilot.pause()
                assert ed.mode == "lrc"
                assert len(ed._lines) == 3
                assert ed.is_dirty
                _, parsed = parse(ed.current_text())
                assert [l.text for l in parsed] == [
                    "Hello world",
                    "Goodbye world",
                    "See you later",
                ]
                ed.clear_dirty()
                await pilot.press("ctrl+q")

        asyncio.run(_impl())


# ---------------------------------------------------------------------------
# TestE2EPilotTranscription
# ---------------------------------------------------------------------------

_E2E_FIXTURE = Path(__file__).parent / "fixtures" / "tts_sample.flac"


@pytest.mark.slow
class TestE2EPilotTranscription:
    """Full load → waveform → transcription path through Pilot with real I/O.

    FakePlayer keeps libmpv out of the test; decode_to_pcm and WhisperModel
    both run for real so we can assert on waveform data and LRC editor state.
    """

    def test_load_generates_waveform_and_transcription_populates_lrc(
        self, make_app_real_decode
    ):
        _factory, _ = make_app_real_decode

        async def _impl():
            async with _factory().run_test(headless=True) as pilot:
                app = pilot.app
                wf = app.query_one(WaveformPane)
                ed = app.query_one(LyricsEditor)

                # Full load — triggers real PCM decode worker.
                app._do_load(_E2E_FIXTURE)
                await pilot.app.workers.wait_for_complete()
                await pilot.pause()

                # Waveform was decoded from the actual audio file.
                assert wf._pcm is not None, "PCM not populated after load"
                assert len(wf._pcm) > 0, "PCM array is empty after load"
                assert wf._sample_rate > 0, "Sample rate not set after load"

                # Transcribe using the real tiny model.
                app.action_transcribe()
                await pilot.app.workers.wait_for_complete()
                await pilot.pause()

                assert ed.mode == "lrc", f"Expected lrc mode, got {ed.mode!r}"
                # Segment count is non-deterministic — Whisper may merge the
                # whole clip into one line depending on model state and audio.
                assert len(ed._lines) >= 1, (
                    f"Expected at least 1 line, got {len(ed._lines)}"
                )
                assert ed.is_dirty

                total_words = sum(len(line.words) for line in ed._lines)
                assert total_words > 0, "No word-level timing data in editor"

                ts = [line.timestamp for line in ed._lines]
                assert ts == sorted(ts), f"Line timestamps not sorted: {ts}"

                assert all(line.end is not None for line in ed._lines), (
                    "Some transcribed lines are missing end timestamps"
                )

                await pilot.press("ctrl+q")

        asyncio.run(_impl())
