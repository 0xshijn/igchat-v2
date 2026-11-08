#!/usr/bin/env python3
"""Ví dụ quản trị nhóm chat Instagram Direct: đổi tên nhóm qua Polaris Web GraphQL."""

import asyncio
import os
import sys

from igchat.auth import bootstrap_session
from igchat.direct import rename_thread


async def main() -> None:
    raw_cookie = os.getenv("IG_COOKIES")
    if not raw_cookie:
        print("Vui lòng đặt biến môi trường IG_COOKIES:")
        print("  export IG_COOKIES='sessionid=...; ds_user_id=...; csrftoken=...;'")
        raw_cookie = input("Nhập cookie Instagram của bạn: ").strip()

    if not raw_cookie:
        print("Lỗi: Cookie không được để trống.")
        sys.exit(1)

    print("Đang kết nối session...")
    session = await bootstrap_session(raw_cookie)
    print(f"Đã đăng nhập! User ID: {session.ig_user_id}")

    thread_id = input("\nNhập Thread ID nhóm chat: ").strip()
    if not thread_id:
        print("Lỗi: Thread ID không được để trống.")
        return

    new_name = input(f"Nhập tên mới cho nhóm #{thread_id}: ").strip()
    if not new_name:
        print("Lỗi: Tên mới không được để trống.")
        return

    print(f"Đang đổi tên nhóm #{thread_id} thành: '{new_name}'...")
    res = await rename_thread(session, thread_id=thread_id, new_title=new_name)
    if res.get("errors"):
        print(f"Đổi tên thất bại: {res.get('errors')}")
    else:
        print("Đổi tên nhóm thành công!")


if __name__ == "__main__":
    asyncio.run(main())
