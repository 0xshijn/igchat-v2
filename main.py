#!/usr/bin/env python3
"""Root launcher for igchat-v2 Instagram Direct reference bot."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

os.environ.setdefault("PYTHONUTF8", "1")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

from igchat_v2.bot import main_blocking  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main_blocking(SRC_DIR / "config.json"))
