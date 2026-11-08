"""Unit tests for igchat.bot module."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from igchat.bot.bot import (
    InstagramBot,
    PerUserRateLimiter,
    _BoundedLRU,
    load_bot_config,
)
from igchat.core.models import InstagramSession
from igchat.direct.listener import DirectListener


def test_bounded_lru() -> None:
    cache: _BoundedLRU[str, int] = _BoundedLRU(maxsize=16)
    for i in range(20):
        cache.set(f"k{i}", i)
    assert len(cache) == 16
    assert "k0" not in cache
    assert "k19" in cache
    assert cache.get("k19") == 19
    assert cache.pop("k19") == 19
    assert "k19" not in cache


def test_per_user_rate_limiter() -> None:
    limiter = PerUserRateLimiter(max_calls=3, window_seconds=1.0)
    user = "user_1"
    assert limiter.allow(user, now=10.0)
    assert limiter.allow(user, now=10.1)
    assert limiter.allow(user, now=10.2)
    assert not limiter.allow(user, now=10.3)
    assert limiter.allow(user, now=11.1)


def test_load_bot_config(tmp_path: Path) -> None:
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(
        json.dumps(
            {
                "prefix": "!",
                "admins": ["123", "456"],
                "cookies": "sessionid=token",
                "auto_download_links": True,
            }
        ),
        encoding="utf-8",
    )
    conf = load_bot_config(cfg_file)
    assert conf["prefix"] == "!"
    assert conf["admins"] == {"123", "456"}
    assert conf["cookies"] == "sessionid=token"
    assert conf["auto_download_links"] is True


@pytest.mark.asyncio
async def test_bot_dispatch(mock_session: InstagramSession) -> None:
    mock_listener = AsyncMock(spec=DirectListener)
    mock_actions = AsyncMock()
    mock_listener.actions = mock_actions

    bot = InstagramBot(
        mock_session,
        mock_listener,
        prefix="/",
        admins=["17841400000000001"],
    )

    # Test /ping
    mock_actions.send_message.return_value = {"messageId": "bot_mid_1"}
    await bot.handle_event(
        {
            "type": "message",
            "data": {
                "id": "msg_ping",
                "threadId": 12345,
                "senderId": "99999",
                "text": "/ping",
            },
        }
    )
    mock_actions.send_message.assert_called_once()
    assert "pong" in mock_actions.send_message.call_args[0][1].lower()

    # Test anti-unsend toggle
    mock_actions.send_message.reset_mock()
    await bot.handle_event(
        {
            "type": "message",
            "data": {
                "id": "msg_toggle",
                "threadId": 12345,
                "senderId": "17841400000000001",
                "text": "/antiunsend on",
            },
        }
    )
    assert 12345 in bot.anti_unsend_threads

    # Simulate message cache & unsend event
    bot._msg_cache.set("victim_msg", {"senderId": "99999", "text": "secret info"})
    mock_actions.send_message.reset_mock()
    await bot.handle_event(
        {
            "type": "messageUnsend",
            "data": {"threadId": 12345, "messageId": "victim_msg"},
        }
    )
    mock_actions.send_message.assert_called_once()
    assert "secret info" in mock_actions.send_message.call_args[0][1]
