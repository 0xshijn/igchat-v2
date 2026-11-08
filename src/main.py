#!/usr/bin/env python3
"""Entrypoint for running the igchat-v2 Instagram Direct reference bot."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT_SRC = Path(__file__).resolve().parent
if str(ROOT_SRC) not in sys.path:
    sys.path.insert(0, str(ROOT_SRC))

os.environ.setdefault("PYTHONUTF8", "1")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

from igchat_v2.bot import main_blocking  # noqa: E402


def main(config_path: str | Path | None = None) -> int:
    """Run the Instagram Direct bot using env cookies or src/config.json."""
    target = config_path if config_path is not None else (ROOT_SRC / "config.json")
    return main_blocking(target)


if __name__ == "__main__":
    raise SystemExit(main())
