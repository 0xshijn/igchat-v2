"""
Đường dẫn file:
  src/_messaging/_reactions.py

Mục đích:
  - Thả cảm xúc (reaction) vào tin nhắn cụ thể.

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

import httpx
import json
from typing import Any
from _core._utils import (
    Headers,
    parse_cookie_string,
    formAll,
    send_request_async,
)


def _build_request(
    dataIGS: dict[str, Any], typeAdded: str, messageID: str | int, emojiChoice: str
) -> dict[str, Any]:
    normalized_action = str(typeAdded).strip().casefold()
    action_map = {
        "add": "ADD_REACTION",
        "add_reaction": "ADD_REACTION",
        "remove": "REMOVE_REACTION",
        "remove_reaction": "REMOVE_REACTION",
    }
    if normalized_action not in action_map:
        raise ValueError(
            "typeAdded chỉ nhận add/ADD_REACTION hoặc remove/REMOVE_REACTION."
        )
    if not str(messageID).strip():
        raise ValueError("messageID không được để trống.")
    if not emojiChoice:
        raise ValueError("emojiChoice không được để trống.")
    dataForm: dict[str, Any] = formAll(dataIGS, docID=1491398900900362)
    dataForm["variables"] = json.dumps(
        {
            "data": {
                "action": action_map[normalized_action],
                "client_mutation_id": "1",
                "actor_id": dataIGS["IGSID"],
                "message_id": str(messageID),
                "reaction": emojiChoice,
            }
        }
    )
    dataForm["dpr"] = 1

    return {
        "headers": Headers(dataForm),
        "timeout": 30,
        "url": "https://www.instagram.com/api/graphql/",
        "data": dataForm,
        "cookies": parse_cookie_string(dataIGS["cookieIGS"]),
        "verify": True,
    }


def _build_ig_graphql_request(
    dataIGS: dict[str, Any],
    typeAdded: str,
    messageID: str | int,
    emojiChoice: str,
    threadID: str | int,
) -> dict[str, Any]:
    normalized_action = str(typeAdded).strip().casefold()
    status_map = {
        "add": "created",
        "add_reaction": "created",
        "remove": "deleted",
        "remove_reaction": "deleted",
    }
    if normalized_action not in status_map:
        raise ValueError(
            "typeAdded chỉ nhận add/ADD_REACTION hoặc remove/REMOVE_REACTION."
        )
    if not str(messageID).strip():
        raise ValueError("messageID không được để trống.")
    if not str(threadID).strip():
        raise ValueError("threadID không được để trống.")
    dataForm: dict[str, Any] = formAll(
        dataIGS,
        IGSApiReqFriendlyName="IGDirectReactionSendMutation",
        docID=24374451552236906,
    )
    dataForm["variables"] = json.dumps(
        {
            "input": {
                "emoji": (
                    emojiChoice if status_map[normalized_action] == "created" else ""
                ),
                "item_id": "",
                "message_id": str(messageID),
                "reaction_status": status_map[normalized_action],
                "thread_id": str(threadID),
            }
        },
        separators=(",", ":"),
    )
    return {
        "headers": Headers(dataForm),
        "timeout": 30,
        "url": "https://www.instagram.com/api/graphql/",
        "data": dataForm,
        "cookies": parse_cookie_string(dataIGS["cookieIGS"]),
        "verify": True,
    }


async def func(
    dataIGS: dict[str, Any],
    typeAdded: str,
    messageID: str | int,
    emojiChoice: str,
    *,
    threadID: str | int | None = None,
    client: httpx.AsyncClient | None = None,
) -> httpx.Response:
    req = (
        _build_ig_graphql_request(dataIGS, typeAdded, messageID, emojiChoice, threadID)
        if threadID is not None
        else _build_request(dataIGS, typeAdded, messageID, emojiChoice)
    )
    response = await send_request_async(req, client=client)
    response.raise_for_status()
    return response


""" Hướng dẫn sử dụng (Tutorial)

 * Dữ liệu yêu cầu (args):

     - dataIGS: lấy từ _core._session.dataGetHome(setCookies)
     - typeAdded: "add" thêm reaction vào tin nhắn đó. "remove" để xoá reaction tại tin nhắn đó
     - messageID: messageID của tin nhắn
     - emojiChoice: emoji cần reaction vào tin nhắn (VD: 👍, 😭, 😎,....)(All emoji)

* Kết quả trả về:

     - Không có dữ liệu
     - Ghi chú: tùy thuộc vào nhiều trường hợp mà error có thể báo code lỗi và chi tiết khác nhau!

* Thông tin tác giả:
     Author: Shiin (Phước Toàn)

✓ Remake by Shiin (Phước Toàn)
✓ Tôn trọng tác giả ❤️
"""
