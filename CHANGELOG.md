# Changelog

Các thay đổi đáng chú ý của dự án `igchat-v2`, tuân theo định dạng [Keep a Changelog](https://keepachangelog.com/vi/1.1.0/) và [Semantic Versioning](https://semver.org/lang/vi/).

---

## [3.0.0] - 2026-11-08

### Changed / Rebuilt (Architecture Overhaul)

- **Pure Instagram Direct & Polaris GraphQL Engine:**
  - Tái cấu trúc toàn diện thành package chuẩn duy nhất `src/igchat_v2/` (`version = "3.0.0"`).
  - Loại bỏ hoàn toàn mọi tàn dư E2EE (`whatsmeow`, `libsignal`, `DeviceStore`, `e2eeMessage`, `sendE2EE*`, `bridge-e2ee/`).
  - Loại bỏ toàn bộ Comet mutations, Facebook/Messenger queries (`CometUFIFeedbackReactMutation`, `FriendingCometUnfriendMutation`, `ProfileCometSetBioMutation`, `edge-chat.*`, `paho-mqtt`, `c_user`/`xs`/`datr` cookie expectations) và mã rác không liên quan.
- **Go Bridge v3.0.0 (`bridge/` & `build/igchat-bridge.exe`):**
  - Tái cấu trúc bridge Go dựa thuần túy trên `go.mau.fi/mautrix-meta/pkg/instameow`.
  - Kết nối thời gian thực qua Instagram Direct DGW WebSocket, Slide GraphQL và MQTT bypass.
  - Tích hợp SSRF guard chặn loopback/private IP khi tải media, che giấu credential tự động trong log stderr, và kiểm tra quyền file riêng tư (POSIX `0600` / Windows ACL).
  - Hỗ trợ đầy đủ 34 RPC method cho Direct messaging, thread management, reaction, unsend, edit, typing indicator.
- **Python Client Architecture:**
  - `igchat_v2.core`: Module nền tảng với kiểu dữ liệu strongly-typed (`InstagramSession`, `UserSummary`, `ThreadSummary`, `MessageEvent`), quản lý HTTP pooling qua `httpx.AsyncClient`, SSRF validation.
  - `igchat_v2.auth`: Xác thực Instagram Web AJAX, trích xuất cookie chuẩn Instagram (`sessionid`, `ds_user_id`, `csrftoken`, `mid`, `ig_did`), hỗ trợ 2FA TOTP qua `pyotp`.
  - `igchat_v2.bridge`: Quản lý tiến trình bridge Go qua stdin/stdout line JSON-RPC, generation-fenced, tự động reconnect với exponential backoff.
  - `igchat_v2.direct`: Direct messaging (`send`, `edit`, `unsend`, `react`), quản lý thread (inbox pagination, admin, rename, mute), Notes 24h và rupload media.
  - `igchat_v2.social`: Polaris Web REST/GraphQL cho Profile, Quan hệ bạn bè (follow/unfollow/block), Bài viết (like/save/comment/publish), Tìm kiếm người dùng, và Thông báo.
  - `igchat_v2.bot`: Khung bot tích hợp `InstagramBot` với router lệnh, rate limiter theo user, LRU message deduplication, và quản trị an toàn.
- **Testing & Packaging:**
  - Test suite hoàn chỉnh 38/38 bài test passing.
  - Chuẩn hóa cấu hình `pyproject.toml` (Hatchling backend, Python >= 3.10) và `requirements.txt`.
