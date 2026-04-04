"""Entry point: lyrsmith [directory]"""

from __future__ import annotations

import argparse
import warnings
from pathlib import Path

from .app import LyrsmithApp
from .config import load as load_config
from .debug import configure_debug_logging


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="lyrsmith",
        description="TUI for transcribing and editing synced song lyrics (LRC).",
    )
    parser.add_argument(
        "directory",
        nargs="?",
        type=Path,
        metavar="DIRECTORY",
        help="music directory to browse (default: last used, or current directory)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="enable file-based debug logging",
    )
    args = parser.parse_args()

    config = load_config()

    if args.directory is not None:
        initial_dir = args.directory.expanduser().resolve()
        if not initial_dir.is_dir():
            parser.error(f"'{initial_dir}' is not a directory")
    elif config.last_directory:
        initial_dir = Path(config.last_directory)
        if not initial_dir.is_dir():
            initial_dir = Path.cwd()
    else:
        initial_dir = Path.cwd()

    # Suppress Python-level warnings (HuggingFace, PyTorch, urllib3, etc.)
    # before the TUI starts — they'd corrupt the display if printed to stderr.
    warnings.filterwarnings("ignore")
    configure_debug_logging(args.debug)

    app = LyrsmithApp(initial_dir=initial_dir, config=config)
    app.run()


if __name__ == "__main__":
    main()
