"""Safe UTF-8 console output helpers for Windows and POSIX terminals."""

from __future__ import annotations

import sys


def configure_utf8_console() -> None:
    """Ensure stdout/stderr never fail on Unicode output in Windows terminals."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def safe_print(*args: object, sep: str = " ", end: str = "\n") -> None:
    """Print text safely even if the terminal encoding cannot render every codepoint."""
    text = sep.join(str(arg) for arg in args)
    try:
        sys.stdout.write(text + end)
        sys.stdout.flush()
    except UnicodeEncodeError:
        encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
        encoded = (
            (text + end)
            .encode(encoding, errors="replace")
            .decode(encoding, errors="replace")
        )
        sys.stdout.write(encoded)
        sys.stdout.flush()
