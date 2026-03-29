"""Sanity checks for keybinds.py — types, ordering, no duplicates, no conflicts."""

import lyrsmith.keybinds as kb

# Keys registered in LyrsmithApp.BINDINGS (app-level, always active).
_APP_GLOBALS: frozenset[str] = frozenset(
    {
        kb.KB_QUIT,
        kb.KB_SAVE,
        kb.KB_DISCARD_RELOAD,
        kb.KB_TRANSCRIBE,
        kb.KB_NEXT_MODEL,
        kb.KB_NEXT_LANG,
    }
)

# Keys handled inside LyricsEditor.on_key (active only in LRC mode).
_LRC_LOCAL: frozenset[str] = frozenset(
    {
        kb.KB_PLAY_PAUSE,
        kb.KB_SEEK_FWD,
        kb.KB_SEEK_BACK,
        kb.KB_SEEK_FWD_LARGE,
        kb.KB_SEEK_BACK_LARGE,
        kb.KB_SEEK_TO_LINE,
        kb.KB_STAMP_LINE,
        kb.KB_UNDO,
        kb.KB_NUDGE_FINE_FWD,
        kb.KB_NUDGE_FINE_BACK,
        kb.KB_NUDGE_MED_FWD,
        kb.KB_NUDGE_MED_BACK,
        kb.KB_NUDGE_ROUGH_FWD,
        kb.KB_NUDGE_ROUGH_BACK,
        kb.KB_DELETE_LINE,
        kb.KB_EDIT_LINE,
        kb.KB_MERGE_LINE,
    }
)

# Keys handled inside WaveformPane.on_key.
_WAVEFORM_LOCAL: frozenset[str] = frozenset(
    {
        kb.KB_PLAY_PAUSE,
        kb.KB_SEEK_FWD,
        kb.KB_SEEK_BACK,
        kb.KB_SEEK_FWD_LARGE,
        kb.KB_SEEK_BACK_LARGE,
        kb.KB_ZOOM_IN,
        kb.KB_ZOOM_OUT,
    }
)


class TestAmounts:
    def test_nudge_positive(self):
        assert kb.NUDGE_FINE > 0
        assert kb.NUDGE_MED > 0
        assert kb.NUDGE_ROUGH > 0

    def test_nudge_ordering(self):
        assert kb.NUDGE_FINE < kb.NUDGE_MED < kb.NUDGE_ROUGH

    def test_seek_positive(self):
        assert kb.SEEK_SMALL > 0
        assert kb.SEEK_LARGE > 0

    def test_seek_ordering(self):
        assert kb.SEEK_SMALL < kb.SEEK_LARGE


class TestKeyTypes:
    def test_all_KB_constants_are_strings(self):
        bad = [
            name
            for name in dir(kb)
            if name.startswith("KB_") and not isinstance(getattr(kb, name), str)
        ]
        assert bad == [], f"Non-string KB_ constants: {bad}"

    def test_no_empty_keybind(self):
        empty = [
            name
            for name in dir(kb)
            if name.startswith("KB_") and getattr(kb, name) == ""
        ]
        assert empty == []


class TestNoDuplicates:
    def _global_binds(self):
        # Exactly the keys registered in LyrsmithApp.BINDINGS.
        # KB_UNDO is handled in LyricsEditor.on_key (context-local), not here.
        return [
            kb.KB_SAVE,
            kb.KB_DISCARD_RELOAD,
            kb.KB_TRANSCRIBE,
            kb.KB_NEXT_MODEL,
            kb.KB_NEXT_LANG,
            kb.KB_QUIT,
        ]

    def test_global_binds_unique(self):
        binds = self._global_binds()
        assert len(binds) == len(set(binds)), "Duplicate global keybinds detected"

    def test_nudge_fwd_back_differ(self):
        assert kb.KB_NUDGE_FINE_FWD != kb.KB_NUDGE_FINE_BACK
        assert kb.KB_NUDGE_MED_FWD != kb.KB_NUDGE_MED_BACK
        assert kb.KB_NUDGE_ROUGH_FWD != kb.KB_NUDGE_ROUGH_BACK


class TestConflicts:
    """Global app bindings must not shadow any context-local widget bindings."""

    def test_no_global_vs_lrc_local_conflict(self):
        overlap = _APP_GLOBALS & _LRC_LOCAL
        assert overlap == set(), (
            f"App-global keybind(s) shadow LRC-editor local binds: {overlap}"
        )

    def test_no_global_vs_waveform_local_conflict(self):
        overlap = _APP_GLOBALS & _WAVEFORM_LOCAL
        assert overlap == set(), (
            f"App-global keybind(s) shadow waveform-pane local binds: {overlap}"
        )
