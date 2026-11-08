#!/usr/bin/env python3
"""Ví dụ bot Echo tự động phản hồi tin nhắn trong thời gian thực sử dụng DirectListener."""

import asyncio
import os
import sys
from typing import Any

from igchat.auth import bootstrap_session
from igchat.direct import DirectListener


async def main() -> None:
    raw_cookie = os.getenv("IG_COOKIES")
    if not raw_cookie:
        print("Vui lòng đặt biến môi trường IG_COOKIES:")
        print("  export IG_COOKIES='sessionid=...; ds_user_id=...; csrftoken=...;'")
        raw_cookie = input("Nhập cookie Instagram của bạn: ").strip()

    if not raw_cookie:
        print("Lỗi: Cookie không được để trống.")
        sys.exit(1)

    print("Đang khởi tạo session...")
    session = await bootstrap_session(raw_cookie)
    print(f"Đã đăng nhập! User ID: {session.ig_user_id}")

    listener = DirectListener(session=session)

    async def on_message_received(event: dict[str, Any]) -> None:
        data = event.get("data", {})
        thread_id = data.get("threadId") or data.get("thread_id")
        sender_id = str(data.get("senderId") or data.get("sender_id") or "")
        text = str(data.get("text") or "").strip()

        # Bỏ qua tin nhắn do chính bot gửi
        if sender_id == str(session.ig_user_id):
            return

        print(f"[{thread_id}] Nhận từ @{sender_id}: {text}")

        # Tự động phản hồi nếu tin nhắn bắt đầu bằng !echo
        if text.startswith("!echo ") and thread_id:
            reply_text = text[6:].strip()
            print(f"[{thread_id}] Đang phản hồi: {reply_text}")
            await listener.actions.send_message(
                thread_id=thread_id, text=f"Echo: {reply_text}"
            )

    listener.on_message(on_message_received)

    print("DirectListener đang lắng nghe sự kiện Instagram Direct...")
    print("Gửi '!echo nội dung' vào bất kỳ cuộc trò chuyện nào để thử nghiệm.")
    try:
        await listener.start()
    except (KeyboardInterrupt, asyncio.CancelledError):
        print("\nĐang dừng listener...")
        await listener.aclose()


if __name__ == "__main__":
    asyncio.run(main())
