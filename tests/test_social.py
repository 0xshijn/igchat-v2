"""Unit tests for igchat.social features."""

from __future__ import annotations

import httpx
import pytest

from igchat.core.models import InstagramSession
from igchat.social.friendships import (
    block_user,
    follow_user,
    remove_follower,
    unblock_user,
    unfollow_user,
)
from igchat.social.notifications import fetch_notifications
from igchat.social.posts import (
    comment_media,
    delete_comment,
    like_media,
    media_id_to_shortcode,
    publish_photo,
    save_media,
    shortcode_to_media_id,
)
from igchat.social.profile import change_bio, get_user_profile
from igchat.social.search import search_users


def test_shortcode_conversions() -> None:
    shortcode = "CxYw123AB"
    media_id = shortcode_to_media_id(shortcode)
    assert media_id.isdigit()
    assert media_id_to_shortcode(media_id) == shortcode

    with pytest.raises(ValueError):
        shortcode_to_media_id("invalid!char")


@pytest.mark.asyncio
async def test_profile_and_bio(mock_session: InstagramSession) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        url_str = str(request.url)
        if "web_profile_info" in url_str:
            return httpx.Response(
                200,
                json={"data": {"user": {"username": "test_user", "id": "12345"}}},
                request=request,
            )
        if "web_form_data" in url_str:
            return httpx.Response(
                200, json={"form_data": {"first_name": "Test"}}, request=request
            )
        if "accounts/edit" in url_str:
            return httpx.Response(200, json={"status": "ok"}, request=request)
        return httpx.Response(200, json={}, request=request)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        profile = await get_user_profile(mock_session, "test_user", client=client)
        assert profile["username"] == "test_user"

        bio_res = await change_bio(mock_session, "New Bio 🚀", client=client)
        assert bio_res["success"] is True


@pytest.mark.asyncio
async def test_friendships_actions(mock_session: InstagramSession) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "ok"}, request=request)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        res_follow = await follow_user(mock_session, 12345, client=client)
        assert res_follow["success"] is True

        res_unfollow = await unfollow_user(mock_session, 12345, client=client)
        assert res_unfollow["success"] is True

        res_remove = await remove_follower(mock_session, 12345, client=client)
        assert res_remove["success"] is True

        res_block = await block_user(mock_session, 12345, client=client)
        assert res_block["success"] is True

        res_unblock = await unblock_user(mock_session, 12345, client=client)
        assert res_unblock["success"] is True


@pytest.mark.asyncio
async def test_posts_interactions(mock_session: InstagramSession) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        url_str = str(request.url)
        if "rupload_igphoto" in url_str:
            return httpx.Response(200, json={"upload_id": "up_123"}, request=request)
        return httpx.Response(200, json={"status": "ok"}, request=request)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        res_like = await like_media(mock_session, "12345678", client=client)
        assert res_like["success"] is True

        res_save = await save_media(mock_session, "12345678", client=client)
        assert res_save["success"] is True

        res_comment = await comment_media(
            mock_session, "12345678", "Cool post!", client=client
        )
        assert res_comment["success"] is True

        res_del_comment = await delete_comment(
            mock_session, "12345678", "999", client=client
        )
        assert res_del_comment["success"] is True

        res_pub = await publish_photo(
            mock_session, b"photo_bytes", caption="Caption", client=client
        )
        assert res_pub["success"] is True


@pytest.mark.asyncio
async def test_search_and_notifications(mock_session: InstagramSession) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        url_str = str(request.url)
        if "news/inbox" in url_str:
            return httpx.Response(
                200, json={"status": "ok", "new_stories": []}, request=request
            )
        return httpx.Response(
            200,
            json={
                "data": {
                    "results": [
                        {"username": "target_user", "pk": "888", "full_name": "Target"}
                    ]
                }
            },
            request=request,
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        users = await search_users(mock_session, "target", client=client)
        assert len(users) == 1
        assert users[0]["username"] == "target_user"

        notifs = await fetch_notifications(mock_session, client=client)
        assert notifs["success"] is True
