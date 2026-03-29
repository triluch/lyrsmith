# All keybindings in one place. Edit here to rebind.
# Values are Textual key strings.

# Pane navigation
KB_NEXT_PANE = "tab"
KB_PREV_PANE = "shift+tab"

# File browser
KB_UP = "up"
KB_DOWN = "down"
KB_SELECT = "enter"  # load file into workspace
KB_BACK = "backspace"  # navigate up one directory

# Player (waveform pane active)
KB_PLAY_PAUSE = "space"
KB_SEEK_FWD = "right"  # +5s
KB_SEEK_BACK = "left"  # -5s
KB_SEEK_FWD_LARGE = "shift+right"  # +30s
KB_SEEK_BACK_LARGE = "shift+left"  # -30s
KB_ZOOM_IN = "plus"
KB_ZOOM_OUT = "minus"

# Lyrics editor - LRC mode
KB_LINE_UP = "up"
KB_LINE_DOWN = "down"
KB_SEEK_TO_LINE = "enter"  # seek playback to selected line's timestamp
KB_STAMP_LINE = "t"  # set selected line's timestamp to current playback position
KB_DELETE_LINE = "ctrl+d"  # delete selected line (undoable)
KB_EDIT_LINE = "e"  # enter inline text-edit mode (Ctrl+K inside modal to split)
KB_MERGE_LINE = "m"  # merge selected line with next
KB_NUDGE_FINE_FWD = "period"  # +10ms   (.)
KB_NUDGE_FINE_BACK = "comma"  # -10ms   (,)
KB_NUDGE_MED_FWD = "apostrophe"  # +100ms  (')
KB_NUDGE_MED_BACK = "semicolon"  # -100ms  (;)
KB_NUDGE_ROUGH_FWD = "right_square_bracket"  # +1s
KB_NUDGE_ROUGH_BACK = "left_square_bracket"  # -1s

# Nudge amounts in seconds
NUDGE_FINE = 0.010
NUDGE_MED = 0.100
NUDGE_ROUGH = 1.000

# Seek step amounts in seconds (shared by waveform pane and lyrics editor)
SEEK_SMALL = 5.0
SEEK_LARGE = 30.0

# Global
KB_UNDO = "ctrl+z"
KB_SAVE = "ctrl+s"
KB_DISCARD_RELOAD = "ctrl+r"  # discard work copy, reload from tags
KB_TRANSCRIBE = "ctrl+t"  # trigger whisper transcription
KB_NEXT_MODEL = "ctrl+n"  # cycle whisper model  (ctrl+m = CR = Enter in terminals)
KB_NEXT_LANG = "ctrl+l"  # cycle whisper language
KB_QUIT = "ctrl+q"
KB_HELP = "f1"  # open keybind reference
KB_CONFIG = "f2"  # open config editor
