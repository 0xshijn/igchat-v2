"""
Đường dẫn file:
  src/_messaging/_unsend.py

Mục đích:
  - Thu hồi (unsend) tin nhắn đã gửi.

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
from typing import Any

import httpx

from _core._utils import (
    formAll,
    mainRequests,
    parse_json_response,
    send_request_async,
)

_URL = "https://www.instagram.com/api/v1/direct_v2/threads/items/delete/"
_GRAPHQL_URL = "https://www.instagram.com/api/graphql/"
_IG_UNSEND_DOC_ID = "26948700068153789"


def _build_request(messageID: str, dataIGS: dict[str, Any]) -> dict[str, Any]:
    if not str(messageID).strip():
        raise ValueError("messageID không được để trống.")
    data_form = formAll(dataIGS, requireGraphql=False)
    data_form["message_id"] = str(messageID)
    return mainRequests(_URL, data_form, dataIGS["cookieIGS"])


def _build_ig_graphql_request(
    messageID: str, threadID: str | int, dataIGS: dict[str, Any]
) -> dict[str, Any]:
    if not str(messageID).strip():
        raise ValueError("messageID không được để trống.")
    if not str(threadID).strip():
        raise ValueError("threadID không được để trống.")
    data_form = formAll(
        dataIGS,
        IGSApiReqFriendlyName="IGDMessageUnsendDialogOffMsysMutation",
        docID=_IG_UNSEND_DOC_ID,
    )
    data_form["variables"] = json.dumps(
        {
            "message_id": str(messageID),
            "send_data": {"thread_id": str(threadID)},
        },
        separators=(",", ":"),
    )
    return mainRequests(_GRAPHQL_URL, data_form, dataIGS["cookieIGS"])


def _parse_response(text: str) -> dict[str, Any]:
    try:
        payload = parse_json_response(text, strip_for_loop_prefix=True)
    except (ValueError, TypeError) as error:
        return {"error": 1, "messages": f"Phản hồi thu hồi không hợp lệ: {error}"}
    if payload.get("error"):
        return {
            "error": 1,
            "messages": payload.get("errorDescription")
            or f"Instagram từ chối thu hồi tin nhắn: {payload['error']}",
        }
    errors = payload.get("errors")
    if isinstance(errors, list) and errors:
        first_err = errors[0] if isinstance(errors[0], dict) else {}
        return {
            "error": 1,
            "messages": first_err.get("message")
            or first_err.get("summary")
            or "Instagram từ chối thu hồi tin nhắn.",
        }
    return {"success": 1, "messages": "Thu hồi tin nhắn thành công."}


async def func(
    messageID: str,
    dataIGS: dict[str, Any],
    *,
    threadID: str | int | None = None,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    req = (
        _build_ig_graphql_request(messageID, threadID, dataIGS)
        if threadID is not None
        else _build_request(messageID, dataIGS)
    )
    response = await send_request_async(req, client=client)
    response.raise_for_status()
    return _parse_response(response.text)
