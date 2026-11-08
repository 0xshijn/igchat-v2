# igchat-v2 - Sơ đồ luồng xử lý v3.0.0

[README](README.md) | [README (EN)](README_EN.md) | [Tài liệu API](DOCS.md) | [Mindmap](mindmap-mermaid.md) | [Bridge Docs](bridge/README.md)

Các sơ đồ dưới đây mô tả chi tiết đường đi của dữ liệu và luồng thực thi trong kiến trúc `igchat-v2` v3.0.0. Toàn bộ tác vụ I/O được xây dựng trên `async`/`await` với connection pooling (`httpx.AsyncClient`) và tiến trình Go companion (`igchat-bridge.exe`) thông qua giao thức line-delimited JSON-RPC 2.0.

---

## 1. 🛤️ Luồng kiến trúc và quan hệ phụ thuộc

```mermaid
flowchart TD
    App[src/main.py / root main.py] --> Bot[igchat_v2.bot]
    Bot --> Direct[igchat_v2.direct]
    Bot --> Social[igchat_v2.social]
    Bot --> Auth[igchat_v2.auth]
    Bot --> Bridge[igchat_v2.bridge]

    Direct --> Bridge
    Direct --> Core[igchat_v2.core]
    Social --> Core
    Auth --> Core
    Bridge --> Core

    Core --> HTTP[httpx.AsyncClient]
    Bridge <--> GoBridge[igchat-bridge.exe Go Subprocess]
    GoBridge --> Instameow[go.mau.fi/mautrix-meta/pkg/instameow]
    Instameow --> IGDirect[Instagram Direct DGW / WebSocket / Slide GraphQL]

    Tests[tests/] --> Bot
    Tests --> Direct
    Tests --> Social
    Tests --> Auth
    Tests --> Bridge
    Tests --> Core
```

Phụ thuộc một chiều nghiêm ngặt: các module tính năng (`direct`, `social`, `bot`) phụ thuộc vào `core`, `auth` và `bridge`. Module `core` hoàn toàn độc lập và không bao giờ import ngược các tầng phía trên.

---

## 2. 💾 Khởi tạo phiên làm việc (Session Bootstrap)

```mermaid
flowchart TD
    A[Cookie string / SessionStorage] --> B{Có cookie hợp lệ?}
    B -- Không --> C[Raise ValueError / Ghi log cảnh báo]
    B -- Có --> D[parse_cookie_string]
    D --> E{Có ds_user_id & sessionid?}
    E -- Không --> F[Raise ValueError: thiếu sessionid/ds_user_id]
    E -- Có --> G[Tạo đối tượng InstagramSession]
    G --> H[GET /api/v1/direct_v2/inbox/ via httpx]
    H --> I{HTTP Status == 200?}
    I -- Không --> J[Cảnh báo session chưa verify / Checkpoint]
    I -- Có --> K[Trích xuất user info & CSRF token]
    K --> L[Lưu phiên an toàn qua FileSessionStorage]
    L --> M[Sẵn sàng cho Direct & Social pipelines]
```

`InstagramSession` được bảo vệ nghiêm ngặt: thông tin nhạy cảm (`sessionid`, token) luôn bị ẩn hoặc thay thế bằng `[REDACTED]` khi xuất ra log hoặc console.

---

## 3. 💬 Gửi tin nhắn Direct (Slide GraphQL / DGW)

```mermaid
sequenceDiagram
    participant App as Bot / User Application
    participant Direct as igchat_v2.direct.messages
    participant Actions as igchat_v2.bridge.actions.BridgeActions
    participant Process as igchat_v2.bridge.process.BridgeProcess
    participant Bridge as igchat-bridge.exe (Go)
    participant IG as Instagram Direct Infrastructure

    App->>Direct: await send_text_message(actions, thread_id, text, reply_to)
    Direct->>Direct: Validate thread_id và text non-empty
    Direct->>Actions: await actions.send_message(thread_id, text, reply_to)
    Actions->>Process: await process.call("send_message", params)
    Process->>Bridge: Gửi JSON-RPC qua stdin (line-delimited)
    Bridge->>Bridge: Parse request & validate params
    Bridge->>IG: Dispatch Direct Message qua instameow DGW
    IG-->>Bridge: Direct Send ACK (message_id, timestamp)
    Bridge-->>Process: JSON-RPC response {"result": {"message_id": ...}} qua stdout
    Process-->>Actions: Dict payload
    Actions-->>Direct: SendResult(success=True, message_id=...)
    Direct-->>App: SendResult
```

Mọi hành động nhắn tin Direct (gửi, chỉnh sửa, thu hồi, thả reaction) đều đi qua pipeline JSON-RPC được kiểm soát chặt chẽ với timeout và generation fencing.

---

## 4. 📡 Luồng sự kiện thời gian thực (DirectListener Event Loop)

```mermaid
sequenceDiagram
    participant IG as Instagram Direct (Meta)
    participant Bridge as igchat-bridge.exe (Go)
    participant Reader as Stdin/Stdout Reader Thread
    participant Listener as igchat_v2.direct.listener.DirectListener
    participant Loop as asyncio Event Loop
    participant Bot as igchat_v2.bot.InstagramBot

    IG-->>Bridge: DGW WebSocket Push Event (New message, reaction, typing)
    Bridge->>Bridge: Sanitize payload & format JSON-RPC event
    Bridge-->>Reader: Line JSON string qua stdout
    Reader->>Reader: Parse JSON envelope
    Reader->>Loop: loop.call_soon_threadsafe(dispatch_event)
    Loop->>Listener: _handle_bridge_event(event)
    Listener->>Bot: on_message(MessageEvent)
    Bot->>Bot: Deduplicate qua Bounded LRU cache
    Bot->>Bot: Rate limit check (PerUserRateLimiter)
    Bot->>Bot: Match command & dispatch async handler
```

`DirectListener` nhận sự kiện thời gian thực từ Go bridge mà không tạo blocking thread trong Python event loop. Mọi message được chuẩn hóa thành `MessageEvent` strongly-typed.

---

## 5. 📎 Quy trình tải lên và gửi Media (SSRF Guard & rupload)

```mermaid
flowchart TD
    A[Đường dẫn file cục bộ hoặc URL công khai] --> B{Nguồn media?}
    B -- URL từ xa --> C[validate_public_http_url: chặn loopback, private IP, SSRF]
    C --> D[download_public_bytes: bounded size & content-type check]
    B -- File cục bộ --> E[Kiểm tra file tồn tại & định dạng media]
    D --> F[Đọc bytes media & xác định MIME]
    E --> F
    F --> G[Gửi qua Bridge upload_media RPC hoặc Instagram rupload API]
    G --> H[POST rupload.instagram.com với X-Instagram-Rupload-Params]
    H --> I{Upload thành công?}
    I -- Không --> J[Raise MediaUploadError với chẩn đoán an toàn]
    I -- Có --> K[Nhận upload_id / media_id]
    K --> L[Dispatch tin nhắn Direct kèm media attachment]
```

Bảo vệ SSRF toàn diện: không cho phép tải media từ `127.0.0.1`, `10.0.0.0/8`, `192.168.0.0/16`, `169.254.0.0/16` hoặc domain nội bộ.

---

## 6. 🌉 Cơ chế tự phục hồi và Reconnect Bridge

```mermaid
flowchart TD
    A[Mất kết nối WebSocket hoặc tiến trình Bridge thoát] --> B{Trạng thái dừng chủ động?}
    B -- Có --> C[Dọn dẹp tài nguyên và kết thúc]
    B -- Không --> D{Số lần thử lại <= max_retries?}
    D -- Không --> E[Kích hoạt BridgeFatalError và thông báo admin]
    D -- Có --> F[Tính thời gian chờ exponential backoff + jitter]
    F --> G[Tạm dừng (asyncio.sleep)]
    G --> H[Khởi động lại subprocess igchat-bridge.exe]
    H --> I[Gửi handshake connect kèm session cookies]
    I --> J{Kết nối thành công?}
    J -- Có --> K[Reset bộ đếm retry về 0 & tiếp tục lắng nghe]
    J -- Không --> L[Tăng số lần retry]
    L --> D
```

Bộ điều phối `ReconnectPolicy` tự động tính toán thời gian chờ lũy thừa kèm jitter ngẫu nhiên để tránh hiện tượng thundering herd khi máy chủ Instagram gặp sự cố mạng tạm thời.

---

## 7. 🤖 Bộ định tuyến lệnh Bot và Kiểm soát tốc độ

```mermaid
flowchart TD
    A[Nhận MessageEvent mới] --> B{Đã từng xử lý? (LRU Cache)}
    B -- Đã xử lý --> C[Bỏ qua - chống lặp lệnh]
    B -- Chưa xử lý --> D[Đánh dấu message_id vào LRU]
    D --> E{Tin nhắn từ chính Bot hoặc rỗng?}
    E -- Có --> F[Bỏ qua]
    E -- Không --> G{Nội dung bắt đầu bằng command prefix?}
    G -- Không --> H[Bỏ qua]
    G -- Có --> I[Tách tên lệnh và tham số]
    I --> J{Người dùng bị rate-limit? (PerUserRateLimiter)}
    J -- Bị hạn chế --> K[Gửi thông báo chờ hoặc bỏ qua]
    J -- Hợp lệ --> L{Lệnh yêu cầu quyền Admin?}
    L -- Có & Không phải Admin --> M[Từ chối thực thi: Unauthorized]
    L -- Không hoặc Là Admin --> N[Thực thi async command handler]
```

Bộ nhớ đệm LRU giới hạn dung lượng lưu trữ các message ID gần nhất để loại bỏ trùng lặp khi mạng chập chờn. Rate limiter theo từng người dùng ngăn chặn spam và bảo vệ tài khoản Instagram khỏi bị hạn chế tác vụ.

---

## 8. 🛑 Trình tự tắt ứng dụng an toàn (Graceful Shutdown)

```mermaid
sequenceDiagram
    participant OS as Hệ điều hành (SIGINT / SIGTERM / Ctrl+C)
    participant App as Application Runner (main.py)
    participant Bot as InstagramBot
    participant Listener as DirectListener
    participant Bridge as BridgeProcess
    participant Client as httpx.AsyncClient

    OS->>App: Gửi tín hiệu dừng (Signal)
    App->>Bot: await bot.stop()
    Bot->>Listener: await listener.stop()
    Listener->>Bridge: await bridge.disconnect()
    Bridge->>Bridge: Gửi RPC disconnect & terminate subprocess
    Listener-->>Bot: Listener dừng hoàn tất
    Bot->>Client: await client.aclose()
    Client-->>Bot: Đóng toàn bộ connection pool
    Bot-->>App: Bot dừng an toàn
    App->>OS: Thoát tiến trình với mã 0
```

Mọi kết nối mạng và tiến trình Go được dọn dẹp sạch sẽ, không để lại tiến trình mồ côi (zombie processes) hay rò rỉ socket khi người dùng dừng chương trình.
