"""
Đường dẫn file:
  src/_messaging/_message_requests.py

Mục đích:
  - Đọc và duyệt các tin nhắn chờ (message requests).

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

from _core._utils import formAll, mainRequests, send_request_async

_URL = "https://www.instagram.com/api/graphqlbatch/"
_IG_GRAPHQL_URL = "https://www.instagram.com/api/graphql/"
_IG_INBOX_PAGINATION_DOC_ID = "27712934271665380"


def _build_request(dataIGS: dict[str, Any]) -> dict[str, Any]:
    data_form = formAll(dataIGS, requireGraphql=False)
    data_form["queries"] = json.dumps(
        {
            "o0": {
                "doc_id": "3336396659757871",
                "query_params": {
                    "limit": 100,
                    "before": None,
                    "tags": ["PENDING"],
                    "includeDeliveryReceipts": False,
                    "includeSeqID": True,
                },
            }
        },
        separators=(",", ":"),
    )
    return mainRequests(_URL, data_form, dataIGS["cookieIGS"])


def _build_ig_graphql_request(dataIGS: dict[str, Any]) -> dict[str, Any]:
    data_form = formAll(
        dataIGS,
        IGSApiReqFriendlyName="IGDThreadListOffMsysPaginationQuery",
        docID=_IG_INBOX_PAGINATION_DOC_ID,
    )
    data_form["variables"] = json.dumps(
        {
            "cursor": "",
            "folder": "PENDING",
            "id": str(dataIGS.get("IGSID") or ""),
            "selected_pill_type": None,
        },
        separators=(",", ":"),
    )
    return mainRequests(_IG_GRAPHQL_URL, data_form, dataIGS["cookieIGS"])


def _find_batch_root(text: str) -> dict[str, Any] | None:
    payload = text.strip()
    if payload.startswith("for (;;);"):
        payload = payload[len("for (;;);") :].lstrip()
    decoder = json.JSONDecoder()
    index = 0
    while index < len(payload):
        while index < len(payload) and payload[index].isspace():
            index += 1
        if index >= len(payload):
            break
        try:
            item, index = decoder.raw_decode(payload, index)
        except json.JSONDecodeError:
            return None
        if isinstance(item, dict) and (
            "o0" in item
            or (
                isinstance(item.get("data"), dict)
                and "xig_direct_inbox_v2" in item["data"]
            )
        ):
            return item
    return None


def _parse_response(text: str) -> dict[str, Any]:
    root = _find_batch_root(text)
    if root is None:
        return {"error": 1, "messages": "Không thể đọc phản hồi message requests."}

    errors = (root.get("o0") or {}).get("errors") or []
    if errors:
        message = errors[0].get("summary") if isinstance(errors[0], dict) else None
        return {"error": 1, "messages": message or "Instagram trả lỗi message requests."}

    pending = (
        (root.get("o0") or {})
        .get("data", {})
        .get("viewer", {})
        .get("message_threads", {})
        .get("nodes", [])
    )
    ig_edges = (
        ((root.get("data") or {}).get("xig_direct_inbox_v2") or {})
        .get("threads_by_folder", {})
        .get("edges", [])
    )
    exported: dict[str | int, Any] = {"data": {}}
    total = 0
    for thread in pending:
        messages = (thread.get("last_message") or {}).get("nodes") or []
        if not messages or not isinstance(messages[0], dict):
            continue
        message = messages[0]
        actor = (message.get("message_sender") or {}).get("messaging_actor") or {}
        exported[total] = {
            "senderID": actor.get("id"),
            "snippet": message.get("snippet"),
            "timestamp_precise": message.get("timestamp_precise"),
        }
        total += 1
    for edge in ig_edges:
        node = edge.get("node") if isinstance(edge, dict) else {}
        if not isinstance(node, dict):
            continue
        msg_edges = ((node.get("slide_messages") or {}).get("edges")) or []
        last_msg = (
            msg_edges[0].get("node")
            if msg_edges and isinstance(msg_edges[0], dict)
            else {}
        )
        if not isinstance(last_msg, dict):
            last_msg = {}
        exported[total] = {
            "threadID": node.get("id") or node.get("thread_fbid"),
            "senderID": str(last_msg.get("sender_fbid") or ""),
            "snippet": last_msg.get("text_body") or node.get("thread_title") or "",
            "timestamp_precise": str(
                last_msg.get("timestamp_ms")
                or node.get("last_activity_timestamp_ms")
                or ""
            ),
        }
        total += 1
    exported["total_count"] = total
    return {
        "success": 1,
        "messages": "Lấy danh sách message requests thành công.",
        "data": exported,
    }


async def func(
    dataIGS: dict[str, Any], *, client: httpx.AsyncClient | None = None
) -> dict[str, Any]:
    response = await send_request_async(_build_request(dataIGS), client=client)
    response.raise_for_status()
    return _parse_response(response.text)


async def accept_instagram_request_graphql(
    dataIGS: dict[str, Any],
    threadID: str | int,
    *,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """Duyệt tin nhắn chờ Instagram qua IGDMessageRequestAcceptMutation (doc_id 10051610291581092)."""
    if not str(threadID).strip():
        raise ValueError("threadID không được để trống.")
    data_form = formAll(
        dataIGS,
        IGSApiReqFriendlyName="IGDMessageRequestAcceptMutation",
        docID="10051610291581092",
    )
    data_form["variables"] = json.dumps(
        {"thread_fbid": str(threadID)},
        separators=(",", ":"),
    )
    response = await send_request_async(
        mainRequests(_IG_GRAPHQL_URL, data_form, dataIGS["cookieIGS"]),
        client=client,
    )
    response.raise_for_status()
    payload = json.loads(response.text.removeprefix("for (;;);").strip())
    if payload.get("errors"):
        return {"error": 1, "messages": "Instagram từ chối duyệt tin nhắn chờ."}
    return {"success": 1, "messages": "Duyệt tin nhắn chờ thành công."}

