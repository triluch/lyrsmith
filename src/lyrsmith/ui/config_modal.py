"""Config editor modal — edit all user-facing settings in one place."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Input, Label

from ..config import Config
from ..keybinds import KB_CONFIG, KB_HELP
from .bottom_bar import fmt_key


class ConfigModal(ModalScreen[Config | None]):
    """Edit config. Ctrl+S to save, Esc / F1 / F2 to cancel."""

    DEFAULT_CSS = """
    ConfigModal {
        align: center middle;
    }
    ConfigModal #outer {
        width: 72;
        max-height: 90%;
        border: solid $accent;
        background: $surface;
    }
    ConfigModal #title-bar {
        width: 1fr;
        height: 1;
        background: $accent;
        color: $background;
        content-align: center middle;
        text-style: bold;
        padding: 0 1;
    }
    ConfigModal #hint {
        height: 1;
        width: 1fr;
        text-align: right;
        color: #606060;
        padding: 0 1;
    }
    ConfigModal #error-label {
        height: 1;
        width: 1fr;
        padding: 0 1;
        color: $error;
    }
    ConfigModal VerticalScroll {
        padding: 0 2 1 2;
    }
    ConfigModal .section-header {
        color: #87ceeb;
        text-style: bold;
        margin-top: 1;
    }
    ConfigModal .field-row {
        height: 3;
    }
    ConfigModal .field-label {
        width: 26;
        content-align: left middle;
        color: #909090;
    }
    ConfigModal .field-input {
        width: 1fr;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", priority=True),
        Binding(KB_CONFIG, "cancel", "", priority=True, show=False),
        Binding(KB_HELP, "cancel", "", priority=True, show=False),
        Binding("ctrl+s", "save_config", "Save", priority=True, show=False),
    ]

    def __init__(self, config: Config) -> None:
        super().__init__()
        self._cfg = config

    def compose(self) -> ComposeResult:
        cfg = self._cfg
        langs_str = ", ".join(cfg.whisper_languages)

        with Vertical(id="outer"):
            yield Label("Config", id="title-bar")
            yield Label(
                f"[#606060]Ctrl+S to save  "
                f"{fmt_key(KB_HELP)}/{fmt_key(KB_CONFIG)}/Esc to cancel[/]",
                id="hint",
            )
            yield Label("", id="error-label")
            with VerticalScroll():
                # ── Whisper ──────────────────────────────────────────────
                yield Label("Whisper", classes="section-header")
                with Horizontal(classes="field-row"):
                    yield Label("Model", classes="field-label")
                    yield Input(
                        value=cfg.whisper_model,
                        placeholder="base / small / medium / large-v2 / large-v3",
                        id="f-whisper-model",
                        classes="field-input",
                    )
                with Horizontal(classes="field-row"):
                    yield Label("Compute type", classes="field-label")
                    yield Input(
                        value=cfg.compute_type,
                        placeholder="default / int8 / float16 / float32",
                        id="f-compute-type",
                        classes="field-input",
                    )
                with Horizontal(classes="field-row"):
                    yield Label("Language default", classes="field-label")
                    yield Input(
                        value=cfg.whisper_language,
                        placeholder="auto / en / pl / ...",
                        id="f-whisper-language",
                        classes="field-input",
                    )
                with Horizontal(classes="field-row"):
                    yield Label("Language cycle (csv)", classes="field-label")
                    yield Input(
                        value=langs_str,
                        placeholder="auto, en, pl, de, ...",
                        id="f-whisper-languages",
                        classes="field-input",
                    )

                # ── Transcription ─────────────────────────────────────────
                yield Label("Transcription", classes="section-header")
                with Horizontal(classes="field-row"):
                    yield Label("Device", classes="field-label")
                    yield Input(
                        value=cfg.transcription_device,
                        placeholder="cpu / cuda / hip",
                        id="f-device",
                        classes="field-input",
                    )
                with Horizontal(classes="field-row"):
                    yield Label("Intra threads (0=auto)", classes="field-label")
                    yield Input(
                        value=str(cfg.intra_threads),
                        placeholder="0",
                        id="f-intra-threads",
                        classes="field-input",
                    )
                with Horizontal(classes="field-row"):
                    yield Label("Inter threads", classes="field-label")
                    yield Input(
                        value=str(cfg.inter_threads),
                        placeholder="1",
                        id="f-inter-threads",
                        classes="field-input",
                    )
                with Horizontal(classes="field-row"):
                    yield Label("Max words/line [WIP] (0=off)", classes="field-label")
                    yield Input(
                        value=str(cfg.whisper_max_words_per_line),
                        placeholder="0  (e.g. 10 to split long segments)",
                        id="f-max-words-per-line",
                        classes="field-input",
                    )

                # ── Display ───────────────────────────────────────────────
                yield Label("Display", classes="section-header")
                with Horizontal(classes="field-row"):
                    yield Label("Waveform zoom (s)", classes="field-label")
                    yield Input(
                        value=str(cfg.waveform_zoom),
                        placeholder="20.0",
                        id="f-waveform-zoom",
                        classes="field-input",
                    )

    def on_mount(self) -> None:
        self.query_one("#f-whisper-model", Input).focus()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get(self, id_: str) -> str:
        return self.query_one(f"#{id_}", Input).value.strip()

    def _set_error(self, msg: str) -> None:
        self.query_one("#error-label", Label).update(f"[red]{msg}[/]")

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_save_config(self) -> None:
        try:
            whisper_model = self._get("f-whisper-model") or self._cfg.whisper_model
            compute_type = self._get("f-compute-type") or "default"
            whisper_language = (
                self._get("f-whisper-language") or self._cfg.whisper_language
            )

            langs_raw = self._get("f-whisper-languages")
            whisper_languages = (
                [l.strip() for l in langs_raw.split(",") if l.strip()]
                if langs_raw
                else list(self._cfg.whisper_languages)
            )
            if not whisper_languages:
                whisper_languages = ["auto"]

            transcription_device = self._get("f-device") or "cpu"

            intra_threads = int(self._get("f-intra-threads") or "0")
            inter_threads = int(self._get("f-inter-threads") or "1")
            max_words_per_line = int(self._get("f-max-words-per-line") or "0")
            if intra_threads < 0:
                raise ValueError("intra threads must be >= 0")
            if inter_threads < 1:
                raise ValueError("inter threads must be >= 1")
            if max_words_per_line < 0:
                raise ValueError("max words/line must be >= 0")

            waveform_zoom = float(self._get("f-waveform-zoom") or "20.0")
            if waveform_zoom <= 0:
                raise ValueError("waveform zoom must be > 0")

        except ValueError as exc:
            self._set_error(str(exc))
            return

        self.dismiss(
            Config(
                whisper_model=whisper_model,
                whisper_language=whisper_language,
                whisper_languages=whisper_languages,
                waveform_zoom=waveform_zoom,
                transcription_device=transcription_device,
                intra_threads=intra_threads,
                inter_threads=inter_threads,
                compute_type=compute_type,
                whisper_max_words_per_line=max_words_per_line,
                last_directory=self._cfg.last_directory,
            )
        )
