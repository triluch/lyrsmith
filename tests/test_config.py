"""Tests for config.py — load/save/defaults."""

import pytest

import lyrsmith.config as config_module
from lyrsmith.config import Config, load, save


def _patch(monkeypatch, tmp_path):
    cfg_file = tmp_path / "config.yaml"
    monkeypatch.setattr(config_module, "_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(config_module, "_CONFIG_FILE", cfg_file)
    return cfg_file


class TestDefaults:
    def test_default_model(self):
        assert Config().whisper_model == "base"

    def test_default_language(self):
        assert Config().whisper_language == "auto"

    def test_default_zoom(self):
        assert Config().waveform_zoom == 20.0

    def test_default_volume(self):
        assert Config().volume == 100.0

    def test_default_last_directory(self):
        assert Config().last_directory == ""

    def test_default_languages_list_contains_auto(self):
        assert "auto" in Config().whisper_languages

    def test_default_languages_list_nonempty(self):
        assert len(Config().whisper_languages) > 1


class TestSaveAndLoad:
    def test_roundtrip(self, tmp_path, monkeypatch):
        _patch(monkeypatch, tmp_path)
        cfg = Config(
            whisper_model="small",
            whisper_language="pl",
            waveform_zoom=15.0,
            last_directory="/music",
        )
        save(cfg)
        loaded = load()
        assert loaded.whisper_model == "small"
        assert loaded.whisper_language == "pl"
        assert loaded.waveform_zoom == pytest.approx(15.0)
        assert loaded.last_directory == "/music"

    def test_creates_dir_if_missing(self, tmp_path, monkeypatch):
        nested = tmp_path / "a" / "b" / "c"
        monkeypatch.setattr(config_module, "_CONFIG_DIR", nested)
        monkeypatch.setattr(config_module, "_CONFIG_FILE", nested / "config.yaml")
        save(Config())
        assert (nested / "config.yaml").exists()

    def test_languages_list_roundtrip(self, tmp_path, monkeypatch):
        _patch(monkeypatch, tmp_path)
        cfg = Config(whisper_languages=["auto", "en", "fr"])
        save(cfg)
        loaded = load()
        assert loaded.whisper_languages == ["auto", "en", "fr"]

    def test_save_is_silent_on_write_failure(self, tmp_path, monkeypatch):
        """save() swallows I/O errors — stale config is preferable to a crash on exit."""
        import yaml

        _patch(monkeypatch, tmp_path)

        def _raise(*a, **kw):
            raise OSError("disk full")

        monkeypatch.setattr(yaml, "dump", _raise)
        save(Config())  # must not raise


class TestLoadEdgeCases:
    def test_missing_file_returns_defaults(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config_module, "_CONFIG_FILE", tmp_path / "nonexistent.yaml")
        cfg = load()
        assert cfg.whisper_model == "base"

    def test_malformed_yaml_returns_defaults(self, tmp_path, monkeypatch):
        cfg_file = _patch(monkeypatch, tmp_path)
        cfg_file.write_text("this: is: invalid: yaml: :::: }{")
        cfg = load()  # must not raise
        assert cfg.whisper_model == "base"

    def test_unknown_keys_ignored(self, tmp_path, monkeypatch):
        cfg_file = _patch(monkeypatch, tmp_path)
        cfg_file.write_text("whisper_model: tiny\nunknown_key: surprise\n")
        cfg = load()
        assert cfg.whisper_model == "tiny"

    def test_partial_yaml_uses_defaults_for_rest(self, tmp_path, monkeypatch):
        cfg_file = _patch(monkeypatch, tmp_path)
        cfg_file.write_text("whisper_model: large-v3\n")
        cfg = load()
        assert cfg.whisper_model == "large-v3"
        assert cfg.waveform_zoom == pytest.approx(20.0)  # default

    def test_load_preserves_list_without_auto(self, tmp_path, monkeypatch):
        # load() must NOT inject "auto" — that would cause it to be written back
        # on the next save. The "auto" guarantee lives in action_next_lang only.
        cfg_file = _patch(monkeypatch, tmp_path)
        cfg_file.write_text("whisper_languages:\n- en\n- pl\n")
        cfg = load()
        assert cfg.whisper_languages == ["en", "pl"]

    def test_bare_string_languages_resets_to_default(self, tmp_path, monkeypatch):
        # User wrote `whisper_languages: en` (scalar) instead of a list.
        # Without validation this would cause action_next_lang to cycle through
        # individual characters ("e", "n", "e", ...).
        cfg_file = _patch(monkeypatch, tmp_path)
        cfg_file.write_text("whisper_languages: en\n")
        cfg = load()
        assert isinstance(cfg.whisper_languages, list)
        assert len(cfg.whisper_languages) > 1  # reset to default list
