from __future__ import annotations

from unittest.mock import AsyncMock, patch
import pytest

from igchat import IGClient, filters
from igchat.core.models import InstagramSession


@pytest.mark.asyncio
async def test_client_context_and_send():
    session = InstagramSession(
        ig_user_id="12345",
        sessionid="dummy_sess",
        csrftoken="dummy_csrf",
        cookies="sessionid=dummy_sess; ds_user_id=12345;",
    )
    client = IGClient(session)

    with patch("igchat.client.send_text_message", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {"success": True, "message_id": "mid_123"}
        res = await client.send_message(
            thread_id=999,
            text="Hello from IGClient",
            silent=True,
        )
        assert res["message_id"] == "mid_123"
        mock_send.assert_called_once()
        # Verify @silent prepended
        assert mock_send.call_args[1]["text"] == "@silent Hello from IGClient"


@pytest.mark.asyncio
async def test_client_event_dispatch():
    session = InstagramSession(
        ig_user_id="12345",
        sessionid="dummy_sess",
        csrftoken="dummy_csrf",
        cookies="sessionid=dummy_sess; ds_user_id=12345;",
    )
    client = IGClient(session)
    received: list[dict] = []

    @client.on(filters.command("start"))
    async def on_start(event):
        received.append(event)

    # Event matching /start
    await client.dispatch_event({"data": {"text": "/start now"}})
    assert len(received) == 1

    # Event not matching
    await client.dispatch_event({"data": {"text": "/other"}})
    assert len(received) == 1
