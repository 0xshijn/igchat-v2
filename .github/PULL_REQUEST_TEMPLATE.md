## 📝 Tóm tắt thay đổi

Mô tả ngắn gọn về những thay đổi trong Pull Request này.

## 🎯 Mục đích & Liên kết Issue
- Khắc phục issue: Closes #...
- Tính năng liên quan: ...

## 🧪 Các bước kiểm tra đã thực hiện
Đánh dấu chọn các bước kiểm tra bạn đã chạy thành công cục bộ:

- [ ] Chạy linter: `ruff check .`
- [ ] Chạy type check: `mypy igchat main.py scripts tests`
- [ ] Chạy unit test suite: `pytest tests/ -v`
- [ ] Chạy 54/54 bot commands test: `python tests/test_all_commands.py`
- [ ] Chạy test Go Bridge: `cd bridge && go test -v ./... && go vet ./...`
- [ ] Đã kiểm tra không có cookie, access token hoặc thông tin nhạy cảm trong commit.

## 📌 Ghi chú thêm cho người review
Bất kỳ điểm kỹ thuật nào cần lưu ý khi review PR.
