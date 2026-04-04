"""Optional file-based debug logging for LRC state transitions."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from platformdirs import user_log_dir

from .lrc import LRCLine

APP_NAME = "lyrsmith"

_LOGGER = logging.getLogger("lyrsmith.debug")
_LOGGER.propagate = False
_ENABLED = False
_LOG_PATH: Path | None = None


def configure_debug_logging(enabled: bool) -> Path | None:
    """Enable/disable debug logging to a file and return the log path.

    When enabled, logs are written to ``<user_log_dir>/debug.log``.
    No console handler is ever attached.
    """

    global _ENABLED, _LOG_PATH

    # Reset old handlers so repeated calls (tests) don't duplicate output.
    for handler in list(_LOGGER.handlers):
        _LOGGER.removeHandler(handler)
        handler.close()

    _ENABLED = False
    _LOG_PATH = None

    if not enabled:
        return None

    log_dir = Path(user_log_dir(APP_NAME))
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / "debug.log"

    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(message)s"))
    _LOGGER.addHandler(handler)
    _LOGGER.setLevel(logging.DEBUG)

    _ENABLED = True
    _LOG_PATH = path
    log_event("session_start", pid=os.getpid(), log_path=str(path))
    return path


def is_debug_enabled() -> bool:
    return _ENABLED


def debug_log_path() -> Path | None:
    return _LOG_PATH


def snapshot_lrc_lines(lines: list[LRCLine]) -> list[dict[str, Any]]:
    """Return a JSON-serializable deep snapshot of LRC lines."""

    payload: list[dict[str, Any]] = []
    for line in lines:
        item = {
            "timestamp": line.timestamp,
            "text": line.text,
            "end": line.end,
            "words": [asdict(word) for word in line.words],
        }
        payload.append(item)
    return payload


def log_event(event: str, **fields: Any) -> None:
    """Write a structured debug event when debug mode is enabled."""

    if not _ENABLED:
        return
    payload = {
        "ts": datetime.now(UTC).isoformat(),
        "event": event,
        **fields,
    }
    _LOGGER.debug(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def log_lrc_operation(
    operation: str,
    *,
    after: list[dict[str, Any]],
    params: dict[str, Any] | None = None,
) -> None:
    """Log one LRC operation with full resulting line structures."""

    log_event(
        "lrc_operation",
        operation=operation,
        params=params or {},
        after=after,
    )
