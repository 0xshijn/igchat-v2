"""
Đường dẫn file:
  src/_features/_instagram/_changeBio.py

Mục đích:
  - Cập nhật tiểu sử (bio) cá nhân trên trang cá nhân.

Cách hoạt động:
  - Nạp dependency/guard cần thiết, thực hiện các async HTTP requests tới API nội bộ hoặc GraphQL của Instagram.
  - Các thao tác request đều phải thông qua httpx.AsyncClient và module _core._utils để bảo đảm an toàn kết nối.
  - Payload gửi đi/nhận về được xử lý JSON cẩn thận, bắt lỗi try-except đầy đủ để tránh crash hệ thống.

File liên quan:
  - src/main.py và các entrypoint khác.
  - Phụ thuộc vào _core._session, _core._utils để khởi tạo và thao tác HTTP.

Author: Shiin (Phước Toàn)
"""

from __future__ import annotations

import json
import random
from typing import Any

import httpx

from _core._utils import formAll, post_form_json_async

GRAPHQL_URL = "https://www.instagram.com/api/graphql/"


def _build_request(
    dataIGS: dict[str, Any], newContents: str, uploadPost: bool
) -> dict[str, Any]:
    data_form = formAll(dataIGS, "ProfileCometSetBioMutation", 6293552847364844)
    data_form["variables"] = json.dumps(
        {
            "input": {
                "bio": str(newContents),
                "publish_bio_feed_story": bool(uploadPost),
                "actor_id": dataIGS["IGSID"],
                "client_mutation_id": str(random.randrange(1025)),
            },
            "hasProfileTileViewID": False,
            "profileTileViewID": None,
            "scale": 1,
        },
        separators=(",", ":"),
    )
    return data_form


def _parse_response(payload: dict[str, Any], new_contents: str) -> dict[str, Any]:
    bio = (
        ((payload.get("data") or {}).get("profile_intro_card_set") or {}).get(
            "profile_intro_card"
        )
        or {}
    ).get("bio") or {}
    if bio.get("text") == str(new_contents):
        return {"success": 1, "messages": "Thay đổi bio thành công!"}
    form_data = payload.get("form_data")
    if isinstance(form_data, dict) and form_data.get("biography") == str(new_contents):
        return {"success": 1, "messages": "Thay đổi bio thành công!"}
    if payload.get("status") == "ok" and not payload.get("errors"):
        return {"success": 1, "messages": "Thay đổi bio thành công!"}
    message = ((payload.get("errors") or [{}])[0]).get("message")
    return {
        "error": 1,
        "messages": message or "Instagram không xác nhận nội dung bio mới.",
    }


async def func(
    dataIGS: dict[str, Any],
    newContents: str,
    uploadPost: bool = False,
    *,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    try:
        payload = await post_form_json_async(
            GRAPHQL_URL,
            _build_request(dataIGS, newContents, uploadPost),
            dataIGS["cookieIGS"],
            client=client,
        )
        return _parse_response(payload, newContents)
    except (httpx.HTTPError, ValueError, TypeError, KeyError) as exc:
        return {"error": 1, "messages": str(exc)}


async def change_instagram_bio(
    dataIGS: dict[str, Any],
    new_bio: str,
    *,
    first_name: str | None = None,
    username: str | None = None,
    email: str | None = None,
    external_url: str | None = None,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """Cập nhật tiểu sử (biography) tài khoản Instagram qua Web Accounts API."""
    import contextlib
    from _core._utils import USER_AGENTS, extract_csrftoken_from_cookie

    form_payload: dict[str, Any] = {"biography": str(new_bio)}
    cookie_str = str(dataIGS.get("cookieIGS") or "")
    if username is None and cookie_str:
        with contextlib.suppress(Exception):
            headers = {
                "Referer": "https://www.instagram.com/accounts/edit/",
                "User-Agent": random.choice(USER_AGENTS),
                "Cookie": cookie_str,
                "X-CSRFToken": extract_csrftoken_from_cookie(cookie_str),
                "X-IG-App-ID": "936619743392459",
                "X-Requested-With": "XMLHttpRequest",
            }
            get_url = "https://www.instagram.com/api/v1/accounts/edit/web_form_data/"
            if client is not None and hasattr(client, "get"):
                pre_resp = await client.get(get_url, headers=headers, timeout=15.0)
            else:
                async with httpx.AsyncClient(
                    timeout=15.0, follow_redirects=True
                ) as temp_client:
                    pre_resp = await temp_client.get(get_url, headers=headers)
            if pre_resp.status_code == 200:
                pre_json = json.loads(
                    pre_resp.text.removeprefix("for (;;);").strip()
                )
                fd = (
                    pre_json.get("form_data")
                    if isinstance(pre_json, dict)
                    else None
                )
                if isinstance(fd, dict):
                    for key in (
                        "first_name",
                        "username",
                        "email",
                        "phone_number",
                        "external_url",
                    ):
                        if fd.get(key) is not None:
                            form_payload[key] = str(fd.get(key) or "")
                    if "chaining_enabled" in fd:
                        form_payload["chaining_enabled"] = (
                            "on" if fd.get("chaining_enabled") else ""
                        )
    if first_name is not None:
        form_payload["first_name"] = first_name
    if username is not None:
        form_payload["username"] = username
    if email is not None:
        form_payload["email"] = email
    if external_url is not None:
        form_payload["external_url"] = external_url
    form_payload["biography"] = str(new_bio)
    try:
        payload = await post_form_json_async(
            "https://www.instagram.com/api/v1/web/accounts/edit/",
            form_payload,
            dataIGS["cookieIGS"],
            client=client,
        )
        if payload.get("status") == "ok" and not payload.get("errors"):
            return {
                "success": 1,
                "biography": str(new_bio),
                "messages": "Thay đổi tiểu sử Instagram thành công!",
            }
        errors = payload.get("errors")
        if isinstance(errors, dict):
            first_msgs = next(iter(errors.values()), None)
            if isinstance(first_msgs, list) and first_msgs:
                return {"error": 1, "messages": str(first_msgs[0])}
        return _parse_response(payload, new_bio)
    except (httpx.HTTPError, ValueError, TypeError, KeyError) as exc:
        return {"error": 1, "messages": str(exc)}

