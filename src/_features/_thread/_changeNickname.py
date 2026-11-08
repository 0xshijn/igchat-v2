"""
Đường dẫn file:
  src/_features/_thread/_changeNickname.py

Mục đích:
  - Cập nhật biệt danh (nickname) cho thành viên trong nhóm chat.

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

from typing import Any

import httpx

from _core._utils import formatResults, formAll, post_form_json_async

_URL = "https://www.instagram.com/api/v1/direct_v2/threads/save_thread_nickname/?source=thread_settings&dpr=1"


def _build_form(
    dataIGS: dict[str, Any],
    threadID: str | int,
    idUser: str | int,
    newNickname: str,
) -> dict[str, Any]:
    data_form = formAll(dataIGS, requireGraphql=False)
    data_form.update(
        {
            "nickname": newNickname,
            "participant_id": str(idUser),
            "thread_or_other_fbid": str(threadID),
        }
    )
    return data_form


def _parse_result(payload: dict[str, Any]) -> dict[str, str]:
    error = payload.get("error")
    if error == 1545014:
        return formatResults("error", "Người dùng không tồn tại trong cuộc trò chuyện.")
    if error == 1357031:
        return formatResults("error", "Cuộc trò chuyện không tồn tại.")
    if error:
        return formatResults("error", f"Instagram từ chối đổi biệt danh: {error}.")
    return formatResults("success", "Thay đổi biệt danh thành công.")


async def func(
    dataIGS: dict[str, Any],
    threadID: str | int,
    idUser: str | int,
    NewNickname: str,
    *,
    client: httpx.AsyncClient | None = None,
) -> dict[str, str]:
    payload = await post_form_json_async(
        _URL,
        _build_form(dataIGS, threadID, idUser, NewNickname),
        dataIGS["cookieIGS"],
        strip_for_loop_prefix=True,
        client=client,
    )
    return _parse_result(payload)


async def set_instagram_nickname_graphql(
    dataIGS: dict[str, Any],
    threadID: str | int,
    idUser: str | int,
    newNickname: str,
    *,
    client: httpx.AsyncClient | None = None,
) -> dict[str, str]:
    """Cập nhật biệt danh thành viên trong cuộc trò chuyện Instagram Direct."""
    return await func(dataIGS, threadID, idUser, newNickname, client=client)

