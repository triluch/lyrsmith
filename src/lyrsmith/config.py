"""XDG config load/save. YAML format."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path

import yaml
from platformdirs import user_config_dir

APP_NAME = "lyrsmith"
_CONFIG_DIR = Path(user_config_dir(APP_NAME))
_CONFIG_FILE = _CONFIG_DIR / "config.yaml"


@dataclass
class Config:
    whisper_model: str = "base"
    whisper_language: str = "auto"
    # Languages cycled by Ctrl+L. Edit this list in the config file to taste.
    whisper_languages: list[str] = field(
        default_factory=lambda: ["auto", "en", "pl", "de", "fr", "es", "ja", "zh"]
    )
    waveform_zoom: float = 20.0  # seconds visible in waveform pane
    # Transcription acceleration
    transcription_device: str = "cpu"  # cpu / cuda / hip
    intra_threads: int = 0  # 0 = let ctranslate2 decide
    inter_threads: int = 1
    compute_type: str = "default"  # default / int8 / float16 / float32
    last_directory: str = ""


def load() -> Config:
    if not _CONFIG_FILE.exists():
        return Config()
    try:
        with open(_CONFIG_FILE) as f:
            data = yaml.safe_load(f) or {}
        known = {k: v for k, v in data.items() if k in Config.__dataclass_fields__}
        cfg = Config(**known)
        # Guard against a bare YAML string instead of a list, which would
        # cause action_next_lang to cycle through individual characters.
        if not isinstance(cfg.whisper_languages, list):
            cfg.whisper_languages = Config.__dataclass_fields__[
                "whisper_languages"
            ].default_factory()
        return cfg
    except Exception:
        return Config()


def save(cfg: Config) -> None:
    try:
        _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with open(_CONFIG_FILE, "w") as f:
            yaml.dump(asdict(cfg), f, default_flow_style=False, allow_unicode=True)
    except Exception:
        pass  # non-fatal: stale config is preferable to a crash on exit
