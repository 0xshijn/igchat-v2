"""
Đường dẫn file:
  src/_features/_instagram/_search.py

Mục đích:
  - Tìm kiếm người dùng, nhóm, trang trên Instagram.

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
    post_form_json_async,
)

GRAPHQL_URL = "https://www.instagram.com/api/graphql/"


def _build_request(dataIGS: dict[str, Any], keywordSearch: str) -> dict[str, Any]:
    keyword = str(keywordSearch).strip()
    if not keyword:
        raise ValueError("Từ khoá tìm kiếm không được để trống.")
    data_form = formAll(
        dataIGS, "IGDOmniPickerSearchResultsListQuery", 27248216181454285
    )
    data_form["variables"] = json.dumps(
        {
            "search_text": keyword,
        },
        separators=(",", ":"),
    )
    return data_form


def _parse_response(payload: dict[str, Any], keyword: str) -> dict[str, Any]:
    data = payload.get("data") if isinstance(payload, dict) else None
    results: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    if isinstance(data, dict) and "xfb_combinedIGSearchQuery" in data:
        combined = data.get("xfb_combinedIGSearchQuery") or {}
        contacts = (
            combined.get("search_messenger_contact_v2")
            if isinstance(combined, dict)
            else None
        )
        for item in contacts if isinstance(contacts, list) else []:
            if not isinstance(item, dict):
                continue
            user_id = str(
                item.get("interop_messaging_user_fbid") or item.get("pk") or ""
            ).strip()
            if not user_id or user_id in seen_ids:
                continue
            seen_ids.add(user_id)
            username = str(item.get("username") or "").strip()
            name = str(item.get("full_name") or username or user_id).strip()
            url = (
                f"https://www.instagram.com/{username}/"
                if username
                else f"https://www.instagram.com/{user_id}/"
            )
            results.append({"name": name, "id": user_id, "url": url})
            if len(results) == 5:
                break
    else:
        try:
            edges = payload["data"]["serpResponse"]["results"]["edges"]
        except (KeyError, TypeError):
            message = ((payload.get("errors") or [{}])[0]).get("message")
            return {
                "error": 1,
                "messages": message or "Response tìm kiếm không hợp lệ.",
            }

        for edge in edges if isinstance(edges, list) else []:
            strategies = (
                (
                    (edge.get("relay_rendering_strategy") or {}).get(
                        "result_rendering_strategies"
                    )
                    or []
                )
                if isinstance(edge, dict)
                else []
            )
            for strategy in strategies:
                profile = (
                    ((strategy.get("view_model") or {}).get("profile") or {})
                    if isinstance(strategy, dict)
                    else {}
                )
                user_id = str(profile.get("id") or "")
                if not user_id or user_id in seen_ids:
                    continue
                seen_ids.add(user_id)
                results.append(
                    {
                        "name": profile.get("name"),
                        "id": user_id,
                        "url": profile.get("url"),
                    }
                )
                if len(results) == 5:
                    break
            if len(results) == 5:
                break

    lines = [
        f"{index}. {item.get('name')} — {item.get('id')} — {item.get('url')}"
        for index, item in enumerate(results, 1)
    ]
    return {
        "success": 1,
        "searchResults": f"Tìm kiếm Instagram: {keyword}\n"
        + "\n".join(lines)
        + f"\nSố lượng kết quả: {len(results)}",
        "searchResultsDict": results,
    }


async def func(
    dataIGS: dict[str, Any],
    keywordSearch: str,
    *,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    try:
        keyword = str(keywordSearch).strip()
        payload = await post_form_json_async(
            GRAPHQL_URL,
            _build_request(dataIGS, keyword),
            dataIGS["cookieIGS"],
            client=client,
        )
        return _parse_response(payload, keyword)
    except (httpx.HTTPError, ValueError, TypeError, KeyError) as exc:
        return {"error": 1, "messages": str(exc)}
