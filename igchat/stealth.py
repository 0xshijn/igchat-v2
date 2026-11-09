"""Ghost Mode & Anti-Fingerprint Humanizer Engine for Instagram Direct.

Provides zero-presence stealth inspection and Gaussian human typing simulation
to keep accounts invisible and immune to Meta automated behavior radar.
"""

from __future__ import annotations

import asyncio
import random
from typing import Any


class GhostMode:
    """Manages ghost mode and zero-presence stealth operation."""

    def __init__(self, *, enabled: bool = True) -> None:
        self._enabled = enabled

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    def enable(self) -> None:
        self._enabled = True

    def disable(self) -> None:
        self._enabled = False

    def build_stealth_headers(self) -> dict[str, str]:
        """Return HTTP headers that suppress Instagram presence broadcast."""
        if not self._enabled:
            return {}
        return {
            "X-IG-Presence": "0",
            "X-IG-Disable-Read-Receipt": "1",
        }

    def should_suppress_receipt(self, thread_id: int | str) -> bool:
        """Return True if read receipts should be dropped for this thread."""
        return self._enabled


class Humanizer:
    """Simulates realistic human typing rhythms and reading latency."""

    def __init__(
        self,
        *,
        reading_wpm: float = 240.0,
        typing_wpm: float = 65.0,
        min_typing_sec: float = 0.8,
        max_typing_sec: float = 6.0,
    ) -> None:
        self.reading_wpm = max(50.0, float(reading_wpm))
        self.typing_wpm = max(20.0, float(typing_wpm))
        self.min_typing_sec = float(min_typing_sec)
        self.max_typing_sec = float(max_typing_sec)

    def calculate_reading_delay(self, text: str) -> float:
        """Estimate the seconds a human would take to read incoming text."""
        words = len(text.strip().split())
        if words <= 0:
            return 0.3
        base = (words / self.reading_wpm) * 60.0
        # Add random Gaussian reading hesitation
        jitter = random.gauss(0.2, 0.1)
        return max(0.2, min(5.0, base + jitter))

    def calculate_typing_delay(self, text: str) -> float:
        """Estimate the seconds a human would take to type outgoing text."""
        chars = len(text.strip())
        if chars <= 0:
            return self.min_typing_sec
        # Average English/Vietnamese word is ~5 chars
        words = max(1.0, chars / 5.0)
        base = (words / self.typing_wpm) * 60.0
        # Gaussian jitter with standard deviation ~15%
        jitter = random.gauss(0.0, base * 0.15)
        raw = base + jitter
        return max(self.min_typing_sec, min(self.max_typing_sec, raw))

    async def simulate_human_pacing(
        self,
        incoming_text: str | None = None,
        outgoing_text: str | None = None,
        *,
        actions: Any | None = None,
        thread_id: int | str | None = None,
    ) -> None:
        """Sleep realistic reading & typing delays and trigger typing indicators."""
        if incoming_text:
            read_delay = self.calculate_reading_delay(incoming_text)
            await asyncio.sleep(read_delay)

        if outgoing_text:
            type_delay = self.calculate_typing_delay(outgoing_text)
            if actions is not None and thread_id is not None:
                # Send typing ON
                try:
                    if hasattr(actions, "send_typing_indicator"):
                        await actions.send_typing_indicator(thread_id, is_typing=True)
                except Exception:
                    pass

            await asyncio.sleep(type_delay)

            if actions is not None and thread_id is not None:
                # Send typing OFF
                try:
                    if hasattr(actions, "send_typing_indicator"):
                        await actions.send_typing_indicator(thread_id, is_typing=False)
                except Exception:
                    pass


__all__ = [
    "GhostMode",
    "Humanizer",
]
