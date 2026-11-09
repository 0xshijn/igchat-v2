from __future__ import annotations

import pytest

from igchat.stealth import GhostMode, Humanizer


def test_ghost_mode_toggle():
    ghost = GhostMode(enabled=False)
    assert not ghost.is_enabled
    assert ghost.build_stealth_headers() == {}

    ghost.enable()
    assert ghost.is_enabled
    headers = ghost.build_stealth_headers()
    assert headers.get("X-IG-Presence") == "0"
    assert headers.get("X-IG-Disable-Read-Receipt") == "1"
    assert ghost.should_suppress_receipt("12345")


def test_humanizer_delays():
    human = Humanizer(reading_wpm=200, typing_wpm=60)
    read_delay = human.calculate_reading_delay(
        "Một hai ba bốn năm sáu bảy tám chín mười"
    )
    assert 0.2 <= read_delay <= 5.0

    type_delay = human.calculate_typing_delay("Nội dung tin nhắn test")
    assert 0.8 <= type_delay <= 6.0


@pytest.mark.asyncio
async def test_humanizer_pacing():
    human = Humanizer(min_typing_sec=0.01, max_typing_sec=0.05)
    await human.simulate_human_pacing(
        incoming_text="Test",
        outgoing_text="Ok",
    )
