"""Unit tests for igchat.direct features and DirectListener."""

from __future__ import annotations

import httpx
import pytest

from igchat.core.models import InstagramSession
from igchat.direct.listener import DirectListener
from igchat.direct.media import upload_photo_rupload
from igchat.direct.messages import (
    edit_text_message,
    react_to_message,
    send_text_message,
    unsend_text_message,
)
from igchat.direct.notes import (
    create_note,
    delete_note,
    fetch_notes,
    search_note_music,
)
from igchat.direct.threads import (
    accept_message_request,
    demote_admin,
    fetch_inbox_threads,
    mute_thread_rest,
    promote_admin,
    rename_thread,
)


@pytest.mark.asyncio
async def test_direct_listener_deduplication(mock_session: InstagramSession) -> None:
    listener = DirectListener(mock_session)
    msg_received = []

    listener.on_message(lambda evt: msg_received.append(evt))

    await listener._dispatch(
        {"type": "message", "data": {"id": "mid_1", "text": "hello"}}
    )
    await listener._dispatch(
        {"type": "message", "data": {"id": "mid_1", "text": "hello"}}
    )
    await listener._dispatch(
        {"type": "message", "data": {"id": "mid_2", "text": "world"}}
    )

    assert len(msg_received) == 2
    assert msg_received[0]["data"]["id"] == "mid_1"
    assert msg_received[1]["data"]["id"] == "mid_2"


@pytest.mark.asyncio
async def test_send_and_edit_message(mock_session: InstagramSession) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"data": {"xig_send_text_message": {"item_id": "sent_item_123"}}},
            request=request,
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        res = await send_text_message(
            mock_session, 123456789, "Hello Polaris", client=client
        )
        assert res["success"] is True
        assert res["message_id"] == "sent_item_123"

        edit_res = await edit_text_message(
            mock_session, 123456789, "sent_item_123", "Edited text", client=client
        )
        assert edit_res["success"] is True

        unsend_res = await unsend_text_message(
            mock_session, 123456789, "sent_item_123", client=client
        )
        assert unsend_res["success"] is True

        react_res = await react_to_message(
            mock_session, 123456789, "sent_item_123", "❤️", client=client
        )
        assert react_res["success"] is True


@pytest.mark.asyncio
async def test_threads_and_admin_management(mock_session: InstagramSession) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        url_str = str(request.url)
        if "direct_v2/threads" in url_str:
            return httpx.Response(200, json={"status": "ok"}, request=request)
        return httpx.Response(
            200,
            json={"data": {"status": "success"}},
            request=request,
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        inbox = await fetch_inbox_threads(mock_session, limit=10, client=client)
        assert "data" in inbox

        rename = await rename_thread(mock_session, 123, "New Group Name", client=client)
        assert rename["success"] is True

        accept = await accept_message_request(mock_session, 123, client=client)
        assert accept["success"] is True

        promote = await promote_admin(mock_session, 123, 456, client=client)
        assert promote["success"] is True

        demote = await demote_admin(mock_session, 123, 456, client=client)
        assert demote["success"] is True

        mute = await mute_thread_rest(mock_session, 123, mute=True, client=client)
        assert mute["success"] is True


@pytest.mark.asyncio
async def test_notes_and_music(mock_session: InstagramSession) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": {
                    "get_inbox_tray_items": {
                        "inbox_tray_items": [{"id": "note_1", "text": "Testing Note"}]
                    },
                    "music_search": {
                        "items": [{"audio_cluster_id": "111", "title": "Song"}]
                    },
                }
            },
            request=request,
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        notes = await fetch_notes(mock_session, client=client)
        assert notes["success"] is True
        assert len(notes["notes"]) == 1

        music = await search_note_music(mock_session, "lofi", client=client)
        assert len(music) == 1
        assert music[0]["title"] == "Song"

        created = await create_note(mock_session, "My 24h Note", client=client)
        assert created["success"] is True

        deleted = await delete_note(mock_session, "note_1", client=client)
        assert deleted["success"] is True


@pytest.mark.asyncio
async def test_rupload_photo(mock_session: InstagramSession) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"upload_id": "12345678", "status": "ok"},
            request=request,
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        res = await upload_photo_rupload(
            mock_session, b"fake_jpeg_bytes", client=client
        )
        assert res["status"] == "ok"
        assert res["upload_id"] == "12345678"
