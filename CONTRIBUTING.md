# Hướng dẫn Đóng góp (Contributing Guide)

Cảm ơn bạn đã quan tâm đến việc phát triển và hoàn thiện **IGChat-v2**! Chúng tôi hoan nghênh mọi đóng góp từ cộng đồng: từ việc sửa lỗi, cải tiến hiệu năng, viết tài liệu đến việc bổ sung các endpoint mới của Instagram Direct.

---

## 🛠️ Thiết lập Môi trường Phát triển (Local Setup)

### 1. Yêu cầu hệ thống
- **Python 3.10+** (khuyên dùng Python 3.11 hoặc 3.12/3.13)
- **Go 1.23+** (dành cho Go Bridge companion)
- **Git**

### 2. Fork & Clone repository
```bash
git clone --recurse-submodules https://github.com/<your-username>/igchat-v2.git
cd igchat-v2
```

### 3. Tạo môi trường ảo & cài đặt phụ thuộc
```bash
# Tạo môi trường ảo
python -m venv .venv

# Kích hoạt môi trường ảo:
# Windows (PowerShell):
.venv\Scripts\Activate.ps1
# Linux / macOS:
source .venv/bin/activate

# Cài đặt package ở chế độ development kèm các công cụ kiểm thử:
python -m pip install --upgrade pip
python -m pip install -e .[dev]
```

### 4. Biên dịch Go Bridge
```bash
cd bridge
go test -v ./...
go build -trimpath -ldflags="-s -w -X main.bridgeVersion=3.0.0" -o ../build/igchat-bridge.exe .
cd ..
```

---

## 🧪 Tiêu chuẩn Kiểm thử & Quality Gate

Mọi Pull Request đều phải vượt qua 100% các tiêu chuẩn kiểm tra trước khi được merge:

```bash
# 1. Chạy linter
ruff check .

# 2. Kiểm tra định dạng code
black --check .

# 3. Phân tích kiểu dữ liệu tĩnh nghiêm ngặt
mypy igchat main.py scripts tests

# 4. Chạy unit tests Python
pytest tests/ -v

# 5. Chạy kiểm thử toàn bộ 54 lệnh bot
python tests/test_all_commands.py

# 6. Kiểm tra Go Bridge
cd bridge && go test -v ./... && go vet ./... && cd ..
```

---

## 🔀 Quy ước Đặt tên Commit (Conventional Commits)

Chúng tôi sử dụng chuẩn [Conventional Commits](https://www.conventionalcommits.org/) để tạo nhật ký thay đổi tự động:

- `feat:` Tính năng hoặc endpoint mới (ví dụ: `feat(direct): add voice note sending support`)
- `fix:` Sửa lỗi (ví dụ: `fix(bridge): resolve race condition during DGW reconnect`)
- `docs:` Cập nhật tài liệu (ví dụ: `docs: update API examples in README`)
- `refactor:` Tái cấu trúc mã nguồn không làm thay đổi tính năng
- `test:` Bổ sung hoặc cập nhật bài kiểm thử
- `ci:` Thay đổi cấu hình GitHub Actions hoặc công cụ CI/CD
- `perf:` Tối ưu hóa hiệu năng

---

## 🚀 Quy trình Gửi Pull Request

1. **Tạo nhánh mới**:
   ```bash
   git checkout -b feat/ten-tinh-nang-moi
   ```
2. **Viết code & bài test tương ứng** trong thư mục `tests/`.
3. **Chạy toàn bộ Quality Gate** ở trên để đảm bảo không phát sinh lỗi hoặc cảnh báo kiểu.
4. **Cam kết không commit thông tin nhạy cảm** (`config.json`, `.session_cache.json`, cookie cá nhân).
5. **Tạo Pull Request** trên GitHub, mô tả rõ vấn đề và cách giải quyết theo template có sẵn.

