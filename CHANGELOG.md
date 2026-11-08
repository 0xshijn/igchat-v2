# Changelog

Các thay đổi đáng chú ý của dự án `igchat-v2`, tuân theo định dạng [Keep a Changelog](https://keepachangelog.com/vi/1.1.0/) và [Semantic Versioning](https://semver.org/lang/vi/).

---

## [3.0.0] - 2026-11-08

### Added (Tính năng mới)

- **Pure Instagram Direct & Polaris GraphQL Engine:**
  - Tái cấu trúc thành package tinh gọn duy nhất `igchat/` đặt tại thư mục gốc repository.
  - Hỗ trợ đầy đủ các endpoint Polaris GraphQL: gửi, sửa, thu hồi tin nhắn Direct, thả cảm xúc, đổi tên nhóm, duyệt tin nhắn chờ, tạo/xóa Instagram Note 24h.
  - Bổ sung module `igchat.social`: quản lý Profile, cập nhật Bio, Follow/Unfollow/Block, Like/Save/Comment bài viết/Reel, và tìm kiếm người dùng.
- **Go Bridge Companion v3.0.0 (`bridge/` & `build/igchat-bridge.exe`):**
  - Tích hợp `instameow` (Go 1.23) kết nối thời gian thực qua chuẩn Instagram Direct DGW WebSocket và Slide GraphQL.
  - Giao tiếp hai chiều với Python qua JSON-RPC 2.0 dòng trên anonymous OS pipes (stdin/stdout).
  - Cơ chế generation-fencing và ReconnectPolicy với exponential backoff tự động phục hồi kết nối.
- **Khung Bot Instagram Toàn diện (`igchat.bot` & `main.py`):**
  - 54/54 lệnh chức năng hoàn chỉnh: kiểm tra hệ thống, xử lý tin nhắn, quản trị nhóm, Notes 24h, tải/bóc tách media, và tương tác mạng xã hội.
  - Tích hợp bộ đệm LRU chống trùng lặp tin nhắn, giới hạn tần suất lệnh độc lập theo từng người dùng (per-user rate limit), và hỗ trợ quyền Admin an toàn.
  - Tính năng chống thu hồi (`/antiunsend`) và phát hiện chỉnh sửa tin nhắn (`/antiedit`) trong thời gian thực.
- **Hệ thống Kiểm thử & Tự động hóa CI/CD:**
  - 34 unit tests với `pytest` và kịch bản test toàn diện 54/54 lệnh bot (`tests/test_all_commands.py`).
  - Kiểm tra kiểu tĩnh nghiêm ngặt 100% bằng `mypy` và chuẩn phong cách mã nguồn bằng `ruff` / `black`.
  - Cấu hình GitHub Actions CI (`.github/workflows/ci.yml`) tự động chạy trên Ubuntu và Windows với Python 3.10–3.13 và Go 1.23.
  - Cấu hình quy trình phát hành (`.github/workflows/release.yml`) tự động biên dịch bridge đa nền tảng và đóng gói PyPI wheel/sdist.
- **Thư mục Mẫu & Tài liệu Cộng đồng:**
  - Thư mục `examples/`: các script mẫu sẵn sàng chạy (`quickstart_send.py`, `echo_bot.py`, `group_manager.py`).
  - Chính sách bảo mật chi tiết (`SECURITY.md`), Hướng dẫn đóng góp (`CONTRIBUTING.md`), và mẫu Issue/PR (`.github/`).

### Security & Hardening (Bảo mật & Tăng cường An toàn)

- **SSRF Guard:** Bộ lọc `validate_public_http_url()` chặn truy cập vào private IPv4 (RFC 1918), loopback, link-local, cloud metadata (`169.254.169.254`) khi tải media từ URL.
- **Secret Redaction:** Tự động che giấu `sessionid`, `csrftoken`, `mid`, `authorization`, `password` trên mọi luồng xuất stderr và log chẩn đoán.
- **Atomic File Permissions:** Cưỡng chế phân quyền tập tin lưu trữ phiên (`0600` trên Unix / ACL Restricted trên Windows).
