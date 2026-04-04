from __future__ import annotations

from pathlib import Path

import lyrsmith.__main__ as main_module
from lyrsmith.config import Config


def test_debug_flag_enables_file_logging(monkeypatch, tmp_path: Path) -> None:
    """--debug forwards to configure_debug_logging before app run."""

    cfg = Config(last_directory="")
    calls: dict[str, object] = {}

    monkeypatch.setattr(main_module, "load_config", lambda: cfg)

    def _fake_configure(enabled: bool) -> None:
        calls["debug"] = enabled

    monkeypatch.setattr(main_module, "configure_debug_logging", _fake_configure)

    class _FakeApp:
        def __init__(self, initial_dir: Path, config: Config) -> None:
            calls["initial_dir"] = initial_dir
            calls["config"] = config

        def run(self) -> None:
            calls["ran"] = True

    monkeypatch.setattr(main_module, "LyrsmithApp", _FakeApp)
    monkeypatch.setattr(
        "sys.argv",
        ["lyrsmith", "--debug", str(tmp_path)],
    )

    main_module.main()

    assert calls["debug"] is True
    assert calls["initial_dir"] == tmp_path.resolve()
    assert calls["config"] is cfg
    assert calls["ran"] is True
