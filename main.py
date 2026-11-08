#!/usr/bin/env python3
"""Root launcher for igchat Instagram Direct reference bot."""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("PYTHONUTF8", "1")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

from igchat.bot import main_blocking

if __name__ == "__main__":
    cfg_file = Path(__file__).resolve().parent / "config.json"
    raise SystemExit(main_blocking(cfg_file if cfg_file.is_file() else None))
