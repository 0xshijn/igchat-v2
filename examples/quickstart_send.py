#!/usr/bin/env python3
"""Ví dụ gửi tin nhắn Instagram Direct nhanh qua Polaris GraphQL mà không cần Go Bridge."""

import asyncio
import os
import sys

from igchat.auth import bootstrap_session
from igchat.direct import send_text_message


async def main() -> None:
    # Lấy cookie từ biến môi trường hoặc nhập trực tiếp
    raw_cookie = os.getenv("IG_COOKIES")
    if not raw_cookie:
        print("Vui lòng đặt biến môi trường IG_COOKIES hoặc cấu hình trong code:")
        print("  export IG_COOKIES='sessionid=...; ds_user_id=...; csrftoken=...;'")
        raw_cookie = input("Nhập cookie Instagram của bạn: ").strip()

    if not raw_cookie:
        print("Lỗi: Cookie không được để trống.")
        sys.exit(1)

    print("Đang khởi tạo session Instagram...")
    session = await bootstrap_session(raw_cookie)
    print(f"Đăng nhập thành công! User ID: {session.ig_user_id}")

    thread_id = input("Nhập Thread ID cần gửi tin nhắn: ").strip()
    if not thread_id:
        print("Lỗi: Thread ID không được để trống.")
        sys.exit(1)

    message_text = "Xin chào từ igchat-v2 v3.0.0!"
    print(f"Đang gửi tin nhắn tới thread #{thread_id}...")

    result = await send_text_message(session, thread_id=thread_id, text=message_text)
    print(f"Gửi thành công! Message ID: {result.get('message_id')}")


if __name__ == "__main__":
    asyncio.run(main())
