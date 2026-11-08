# Changelog

Các thay đổi đáng chú ý của dự án `igchat-v2`, tuân theo định dạng [Keep a Changelog](https://keepachangelog.com/vi/1.1.0/) và [Semantic Versioning](https://semver.org/lang/vi/).

---

## [2.3.4] - 2026-11-08

### Added

- **Kiến trúc Async-first:** Toàn bộ API I/O được xây dựng trên `async`/`await` với HTTP connection pooling qua `httpx.AsyncClient`.
- **E2EE Bridge:** Tích hợp Go bridge (`igchat-bridge-e2ee`) hỗ trợ mã hóa đầu cuối (E2EE) qua giao thức Labyrinth / Signal.
- **Tự động Reconnect:** MQTT và E2EE tự động khôi phục kết nối khi mạng gián đoạn với cơ chế exponential backoff và jitter.
- **Tính năng Instagram Direct:**
  - Gửi, nhận và xử lý tin nhắn cá nhân / nhóm.
  - Hỗ trợ gửi ảnh, video, tin nhắn thoại (Voice Note), sticker và tệp đính kèm.
  - Thu hồi (unsend), chỉnh sửa (edit), và thả cảm xúc (reaction).
  - Quản lý hội thoại: đổi tên nhóm, cập nhật avatar nhóm, tag thành viên, ghim tin nhắn.
  - Tương tác bài viết / Reel: like, unlike, comment, save, lấy link tải trực tiếp.
  - Quản lý tài khoản: xem thông tin cá nhân, cập nhật Bio, chặn / bỏ chặn.
- **Bot mẫu hoàn chỉnh:** Cung cấp sẵn `src/main.py` với hơn 30 lệnh quản trị và tiện ích hoạt động trực tiếp trên Instagram Direct.
- **Tài liệu song ngữ:** Tài liệu hướng dẫn chi tiết tiếng Việt ([README.md](README.md), [DOCS.md](DOCS.md)) và tiếng Anh ([README_EN.md](README_EN.md)).
