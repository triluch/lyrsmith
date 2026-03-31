"""Shared pytest fixtures for integration tests.

Fixtures defined here are automatically available to all tests under
tests/integration/ without explicit imports.
"""

from __future__ import annotations

import numpy as np
import pytest

import lyrsmith.config as config_module
from lyrsmith.app import LyrsmithApp
from lyrsmith.config import Config

from ._helpers import FakePlayer


@pytest.fixture
def make_app(monkeypatch, tmp_path):
    """Redirect config I/O, replace Player with FakePlayer, stub PCM decode.

    Returns (app_factory, tmp_path).  Call app_factory() inside
    ``async with app.run_test(headless=True) as pilot`` in each test.
    """
    monkeypatch.setattr(config_module, "_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(config_module, "_CONFIG_FILE", tmp_path / "config.yaml")
    monkeypatch.setattr("lyrsmith.app.Player", FakePlayer)
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
