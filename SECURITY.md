# Chính sách Bảo mật (Security Policy)

Dự án **IGChat-v2** coi trọng bảo mật dữ liệu người dùng và tính toàn vẹn của hệ sinh thái giao tiếp Instagram Direct. Tài liệu này cung cấp hướng dẫn báo cáo lỗ hổng và tổng quan về kiến trúc an ninh của thư viện.

---

## 🛡️ Phiên bản được hỗ trợ

| Phiên bản | Tình trạng hỗ trợ | Ghi chú |
|---|---|---|
| **`v3.0.0`** (hiện tại) | ✅ **Được hỗ trợ tích cực** | Bản phát hành chính thức Pure Instagram Direct & Polaris GraphQL |
| `< v3.0.0` | ❌ **Ngừng hỗ trợ** | Các bản cũ chứa tàn dư giao thức Facebook/Messenger legacy |

---

## 🚨 Báo cáo lỗ hổng bảo mật (Reporting a Vulnerability)

Nếu bạn phát hiện vấn đề bảo mật trong mã nguồn hoặc kiến trúc của **IGChat-v2**, vui lòng **KHÔNG tạo public issue** trên GitHub.

Hãy báo cáo thông qua một trong hai kênh bảo mật bảo mật dưới đây:
1. **GitHub Security Advisory**: Tạo báo cáo tại tab [Security Advisories](https://github.com/0xshijn/igchat-v2/security/advisories/new).
2. **Email trực tiếp**: Gửi email có tiêu đề `[SECURITY] igchat-v2 vulnerability` tới:
   - **Tác giả**: Phước Toàn (Shiin / 0xshijn)
   - **Email**: `shiinnohacker@hotmail.com`
   - **Telegram**: [@ShiinNoHacker](https://t.me/ShiinNoHacker)

### Quy trình tiếp nhận & xử lý
- **Phản hồi xác nhận**: Trong vòng **24–48 giờ**.
- **Đánh giá mức độ ảnh hưởng**: Phân loại theo CVSS v3.1.
- **Bản vá & Thông cáo**: Bản vá sẽ được commit kín và phát hành cùng CVE/Advisory sau khi hoàn tất kiểm thử.

---

## 🔒 Kiến trúc An ninh (Security Architecture & Hardening)

### 1. Phòng chống SSRF (Server-Side Request Forgery)
- Mọi hàm tải media từ URL bên ngoài (`/image`, `/voice`, `/post`, `/upstory`) đều được bảo vệ bởi bộ lọc `validate_public_http_url()`.
- Tự động chặn:
  - Dải mạng Private IPv4: `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`.
  - Dải Loopback: `127.0.0.0/8`, `::1`.
  - Link-local & Cloud Metadata: `169.254.169.254`, `fe80::/10`.
  - Toàn bộ scheme nguy hiểm ngoài `http://` và `https://`.

### 2. Che giấu thông tin nhạy cảm (Sensitive Secret Redaction)
- Lớp `redact_sensitive_text()` tự động kiểm tra và làm mờ các token, session cookie (`sessionid`, `csrftoken`, `mid`, `authorization`, `password`) trước khi xuất ra console hoặc ghi nhật ký.
- Cấu hình `"log_message_content": false` mặc định giúp tránh lưu trữ nội dung tin nhắn của người dùng ra log file ngoài ý muốn.

### 3. Phân quyền tập tin lưu trữ (Private File Access)
- Hàm `write_private_text_file()` đảm bảo file cache phiên (`.session_cache.json`) và file cấu hình chỉ được cấp quyền đọc/ghi cho chủ sở hữu quy trình (`0600` trên Unix / ACL Restricted trên Windows).
- File `.gitignore` được cấu hình nghiêm ngặt loại trừ tất cả các tệp `config.json`, `*.session_cache.json`, `.env`, SQLite databases và thư mục logs.

### 4. Cách ly tiến trình Go Bridge (IPC Isolation)
- Giao tiếp giữa Python Async Client và Go Bridge Companion diễn ra hoàn toàn qua anonymous OS pipes (`stdin`/`stdout`) trên cùng một host, không mở bất kỳ TCP port lắng nghe công khai nào trên mạng.
- Cơ chế generation-fencing đảm bảo các gói tin từ phiên kết nối cũ bị loại bỏ ngay lập tức, ngăn ngừa race conditions hoặc chèn dữ liệu không hợp lệ.

