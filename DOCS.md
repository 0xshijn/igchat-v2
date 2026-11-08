# igchat-v2 - Tài liệu API v3.0.0

Tài liệu tham chiếu toàn diện cho thư viện `igchat-v2` phiên bản `3.0.0`. Thư viện được xây dựng hoàn toàn trên nền tảng async/await (`asyncio`), `httpx.AsyncClient` pooling, và tiến trình Go companion (`igchat-bridge.exe`) kết nối thời gian thực qua Instagram Direct DGW WebSocket và Slide GraphQL.

> [!NOTE]
> Đây là thư viện tương tác trực tiếp với giao thức Instagram Direct và Polaris Web REST/GraphQL. Thư viện độc lập hoàn toàn, không phụ thuộc vào Facebook Comet mutations hay các giao thức Messenger legacy.

> [!WARNING]
> Không bao giờ commit hoặc công khai file cấu hình `src/config.json`, giá trị `sessionid`, mật khẩu hoặc 2FA TOTP secret lên kho mã nguồn công cộng.

---

## 📋 Mục lục

1. [Cài đặt và Khởi tạo](#1-cài-đặt-và-khởi-tạo)
2. [Mô hình Dữ liệu (Data Models)](#2-mô-hình-dữ-liệu-data-models)
3. [Xác thực và Phiên (Authentication & Session)](#3-xác-thực-và-phiên-authentication--session)
4. [Kết nối Go Bridge (Bridge & Reconnect)](#4-kết-nối-go-bridge-bridge--reconnect)
5. [Tin nhắn Direct (Direct Messaging)](#5-tin-nhắn-direct-direct-messaging)
6. [Quản lý Hộp thư & Nhóm (Threads & Inbox)](#6-quản-lý-hộp-thư--nhóm-threads--inbox)
7. [Instagram Notes & Media Upload](#7-instagram-notes--media-upload)
8. [Tính năng Mạng Xã hội (Social Features)](#8-tính-năng-mạng-xã-hội-social-features)
9. [Xây dựng Bot (InstagramBot Framework)](#9-xây-dựng-bot-instagrambot-framework)
10. [Bảo mật & Xử lý Ngoại lệ](#10-bảo-mật--xử-lý-ngoại-lệ)

---

## 1. Cài đặt và Khởi tạo

### Cài đặt thư viện

```bash
# Cài đặt các gói phụ thuộc Python
pip install -r requirements.txt

# Cài đặt ở chế độ development
pip install -e .
```

### Biên dịch Go Bridge

```bash
cd bridge
go build -trimpath -ldflags="-s -w -X main.bridgeVersion=3.0.0" -o ../build/igchat-bridge.exe .
cd ..
```

### Import chuẩn

```python
import asyncio
from igchat_v2 import (
    InstagramBot,
    InstagramSession,
    DirectListener,
    BridgeActions,
    bootstrap_session,
    send_text_message,
)
```

---

## 2. Mô hình Dữ liệu (Data Models)

Các model chính trong `igchat_v2.core.models`:

### `InstagramSession`
Đại diện cho phiên làm việc Instagram đã xác thực:
- `user_id: str`: ID định danh người dùng trên Instagram (tương ứng `ds_user_id`).
- `sessionid: str`: Cookie xác thực phiên làm việc.
- `csrftoken: str`: Token chống giả mạo request (CSRF).
- `mid: str | None`: Machine identifier cookie.
- `ig_did: str | None`: Device identifier cookie.
- `username: str | None`: Tên tài khoản Instagram.
- `full_name: str | None`: Tên hiển thị đầy đủ.
- `raw_cookies: str`: Chuỗi cookie header đầy đủ.

### `MessageEvent`
Dữ liệu sự kiện tin nhắn thời gian thực:
- `thread_id: str`: ID cuộc trò chuyện / nhóm chat.
- `message_id: str`: ID duy nhất của tin nhắn.
- `sender_id: str`: ID tài khoản người gửi.
- `timestamp_ms: int`: Thời gian gửi (mili-giây epoch).
- `text: str`: Nội dung tin nhắn dạng văn bản.
- `reply_to_id: str | None`: ID tin nhắn được trả lời (nếu có).
- `is_outgoing: bool`: `True` nếu tin nhắn do chính tài khoản bot gửi.
- `attachments: list[dict[str, Any]]`: Danh sách tệp đính kèm.

### `SendResult`
Kết quả thực hiện thao tác gửi / chỉnh sửa tin nhắn:
- `success: bool`: Trạng thái thành công.
- `message_id: str | None`: ID tin nhắn vừa gửi.
- `thread_id: str | None`: ID hội thoại.
- `timestamp_ms: int | None`: Dấu thời gian từ máy chủ.
- `error: str | None`: Chi tiết lỗi nếu thao tác thất bại.

---

## 3. Xác thực và Phiên (Authentication & Session)

### Khởi tạo session từ Cookie

```python
import httpx
from igchat_v2.auth import bootstrap_session, FileSessionStorage

cookie_str = "sessionid=...; ds_user_id=123456789; csrftoken=...;"

async with httpx.AsyncClient() as client:
    session = await bootstrap_session(cookie_str, client=client)
    print(f"Đã đăng nhập thành công tài khoản: @{session.username} ({session.user_id})")

    # Lưu session vào file với quyền an toàn (0600)
    storage = FileSessionStorage("storage/session.json")
    await storage.save_session(session)
```

### Đăng nhập trực tiếp bằng Username / Mật khẩu / 2FA

```python
from igchat_v2.auth import login_with_credentials, generate_totp_code

async with httpx.AsyncClient() as client:
    # Nếu tài khoản bật 2FA TOTP:
    totp_secret = "JBSWY3DPEHPK3PXP"
    two_factor_code = generate_totp_code(totp_secret) if totp_secret else None

    session = await login_with_credentials(
        username="my_instagram_username",
        password="my_secret_password",
        two_factor_code=two_factor_code,
        client=client,
    )
    print(f"Đăng nhập thành công: {session.user_id}")
```

---

## 4. Kết nối Go Bridge (Bridge & Reconnect)

Tiến trình `igchat-bridge.exe` điều phối kết nối WebSocket DGW thời gian thực.

```python
from igchat_v2.bridge import BridgeProcess, BridgeActions, ReconnectPolicy

# Khởi chạy subprocess bridge
process = BridgeProcess()
await process.start()

# Tạo wrapper hành động RPC
actions = BridgeActions(process)

# Kết nối tài khoản Instagram
connect_result = await actions.connect(session.raw_cookies)
print(f"Bridge connected: {connect_result}")

# Kiểm tra trạng thái sức khỏe
health = await actions.health()
print(f"Bridge health: {health}")
```

---

## 5. Tin nhắn Direct (Direct Messaging)

Toàn bộ thao tác gửi, chỉnh sửa, thu hồi và thả cảm xúc được đóng gói trong `igchat_v2.direct.messages`:

### Gửi tin nhắn

```python
from igchat_v2.direct import send_text_message

# Gửi tin nhắn văn bản thông thường
result = await send_text_message(
    actions,
    thread_id="340282366841710300949128134123456789012",
    text="Xin chào từ igchat-v2 v3.0.0!",
)

# Gửi phản hồi trích dẫn (quote reply)
reply_result = await send_text_message(
    actions,
    thread_id="340282366841710300949128134123456789012",
    text="Nội dung phản hồi",
    reply_to=result.message_id,
)
```

### Chỉnh sửa tin nhắn

```python
from igchat_v2.direct import edit_text_message

await edit_text_message(
    actions,
    thread_id="340282366841710300949128134123456789012",
    message_id="3049128301293810293",
    new_text="Tin nhắn đã được cập nhật!",
)
```

### Thu hồi (Unsend) tin nhắn

```python
from igchat_v2.direct import unsend_text_message

await unsend_text_message(
    actions,
    thread_id="340282366841710300949128134123456789012",
    message_id="3049128301293810293",
)
```

### Thả cảm xúc (Reaction)

```python
from igchat_v2.direct import react_to_message

# Thả reaction trái tim ❤️
await react_to_message(
    actions,
    thread_id="340282366841710300949128134123456789012",
    message_id="3049128301293810293",
    emoji="❤️",
)

# Hủy reaction (gửi emoji rỗng)
await react_to_message(
    actions,
    thread_id="340282366841710300949128134123456789012",
    message_id="3049128301293810293",
    emoji="",
)
```

---

## 6. Quản lý Hộp thư & Nhóm (Threads & Inbox)

Module `igchat_v2.direct.threads` hỗ trợ đầy đủ quản trị hộp thư:

### Lấy danh sách hộp thư và chi tiết hội thoại

```python
from igchat_v2.direct import fetch_inbox, fetch_thread_detail

# Phân trang hộp thư đến (Inbox)
inbox_data = await fetch_inbox(actions, limit=20)
for thread in inbox_data.get("threads", []):
    print(f"Hội thoại: {thread.get('title')} - ID: {thread.get('thread_id')}")

# Lấy tin nhắn chi tiết trong nhóm
detail = await fetch_thread_detail(actions, thread_id="340282366841710300949128134123456789012")
```

### Quản trị nhóm chat

```python
from igchat_v2.direct import (
    change_thread_title,
    add_thread_participants,
    remove_thread_participant,
    mute_thread,
)

# Đổi tên nhóm chat
await change_thread_title(actions, thread_id="...", new_title="Nhóm Nghiên Cứu Hệ Thống")

# Thêm thành viên mới
await add_thread_participants(actions, thread_id="...", user_ids=["987654321"])

# Xóa thành viên khỏi nhóm
await remove_thread_participant(actions, thread_id="...", user_id="987654321")

# Tắt thông báo hội thoại (Mute)
await mute_thread(session, thread_id="...", mute=True)
```

---

## 7. Instagram Notes & Media Upload

### Đăng và Quản lý Instagram Notes 24h

```python
from igchat_v2.direct import fetch_notes, create_text_note, delete_note, search_notes_music

# Lấy danh sách Notes của bạn bè
notes = await fetch_notes(session)

# Tìm bài hát để gắn vào Note
music_results = await search_notes_music(session, query="Die With A Smile")

# Đăng Note 24h mới
created_note = await create_text_note(
    session,
    text="Building system automation with Python & Go...",
)

# Xóa Note
await delete_note(session, note_id=created_note["id"])
```

### Tải lên Media bảo vệ SSRF

```python
from igchat_v2.direct import upload_photo_rupload

# Đọc file ảnh cục bộ và tải lên qua rupload an toàn
with open("photo.jpg", "rb") as f:
    photo_bytes = f.read()

upload_res = await upload_photo_rupload(session, image_bytes=photo_bytes)
print(f"Upload ID: {upload_res['upload_id']}")
```

---

## 8. Tính năng Mạng Xã hội (Social Features)

Module `igchat_v2.social` tương tác với các API Polaris Web REST/GraphQL:

### Thông tin cá nhân & Bio

```python
from igchat_v2.social import get_user_profile, change_bio

# Xem trang cá nhân
profile = await get_user_profile(session, username="instagram")
print(f"Followers: {profile.follower_count}, Bio: {profile.biography}")

# Cập nhật tiểu sử Bio
await change_bio(session, new_bio="Pwn & Systems Research // 0xshijn")
```

### Quan hệ bạn bè (Friendships)

```python
from igchat_v2.social import follow_user, unfollow_user, block_user, unblock_user

target_user_id = "123456789"

await follow_user(session, user_id=target_user_id)
await unfollow_user(session, user_id=target_user_id)
await block_user(session, user_id=target_user_id)
await unblock_user(session, user_id=target_user_id)
```

### Tương tác Bài viết & Reel

```python
from igchat_v2.social import (
    like_media,
    save_media,
    comment_media,
    delete_comment,
    shortcode_to_media_id,
)

# Chuyển đổi URL shortcode thành media_id
media_id = shortcode_to_media_id("C_XYZ123")

# Thả tim bài viết
await like_media(session, media_id=media_id)

# Lưu bài viết vào bộ sưu tập
await save_media(session, media_id=media_id)

# Bình luận
comment = await comment_media(session, media_id=media_id, text="Great post!")

# Xóa bình luận
await delete_comment(session, media_id=media_id, comment_id=comment["id"])
```

---

## 9. Xây dựng Bot (InstagramBot Framework)

Khung bot `InstagramBot` cung cấp giải pháp hoàn chỉnh với định tuyến lệnh, LRU message deduplication, rate limit, và cơ chế bảo vệ admin.

```python
import asyncio
from igchat_v2.bot import InstagramBot, load_bot_config
from igchat_v2.core.models import MessageEvent


async def main() -> None:
    config = load_bot_config("src/config.json")
    bot = InstagramBot(config=config)

    # Đăng ký lệnh bot tùy chỉnh
    @bot.command("ping", description="Kiểm tra độ trễ của bot")
    async def cmd_ping(event: MessageEvent, args: list[str]) -> None:
        await bot.reply(event, "🏓 Pong! Bot igchat-v2 v3.0.0 đang hoạt động ổn định.")

    @bot.command("echo", description="Lặp lại nội dung")
    async def cmd_echo(event: MessageEvent, args: list[str]) -> None:
        text = " ".join(args) if args else "Bạn chưa nhập nội dung!"
        await bot.reply(event, f"📢 {text}")

    # Chạy bot với signal handling an toàn
    await bot.start()


if __name__ == "__main__":
    asyncio.run(main())
```

---

## 10. Bảo mật & Xử lý Ngoại lệ

Thư viện tuân thủ các nguyên tắc bảo mật phần mềm:
1. **SSRF Guard**: Hàm `validate_public_http_url` xác minh địa chỉ IP đích trước khi thực hiện request, ngăn chặn triệt để tấn công SSRF vào mạng nội bộ hoặc cloud metadata.
2. **Quyền File Riêng Tư**: File lưu trữ session được thiết lập quyền POSIX `0600` hoặc Windows Access Control List tương đương (`IGCHAT_PRIVATE_FILE`).
3. **Che Giấu Thông Tin Nhạy Cảm**: Các hàm `redact_sensitive_text` tự động lọc sạch cookie, session ID, và auth tokens trước khi in ra stdout hoặc log file.
4. **Phân cấp Ngoại lệ Rõ ràng**: Mọi lỗi kế thừa từ `IGChatError` (`AuthError`, `BridgeFatalError`, `RateLimitError`, `SSRFError`), giúp ứng dụng bắt và xử lý ngoại lệ chính xác.
