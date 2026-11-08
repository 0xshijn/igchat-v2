#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Root Launcher Shim (`main.py`) -> Chuyển hướng tương đối vào `buff_farm/main.py`.
Cho phép gõ `python main.py` từ cả thư mục gốc `igchat-v2-main/` lẫn `igchat-v2-main/buff_farm/`.
"""

from __future__ import annotations

import os
import runpy
import sys
from pathlib import Path

os.environ["PYTHONUTF8"] = "1"
os.environ["PYTHONIOENCODING"] = "utf-8"

if sys.platform == "win32":
    try:
        import ctypes
        ctypes.windll.kernel32.SetConsoleOutputCP(65001)
        ctypes.windll.kernel32.SetConsoleCP(65001)
    except Exception:
        pass

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT_DIR = Path(__file__).resolve().parent
FARM_DIR = ROOT_DIR / "buff_farm"

for _p in (str(ROOT_DIR), str(FARM_DIR), str(FARM_DIR / "captcha_solver")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

if __name__ == "__main__":
    runpy.run_path(str(FARM_DIR / "main.py"), run_name="__main__")
