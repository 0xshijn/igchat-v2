# Tài liệu ngôn ngữ

Tài liệu tổng quan và tài liệu kỹ thuật có bản tiếng Việt và tiếng Anh:

| Phạm vi | Tiếng Việt | English |
|---|---|---|
| Tổng quan | [`../README.md`](../README.md) | [`../README_EN.md`](../README_EN.md) |
| Tài liệu API & Module | [`../DOCS.md`](../DOCS.md) | [`../DOCS.md`](../DOCS.md) |
| Go Bridge Architecture | [`../bridge/README.md`](../bridge/README.md) | [`../bridge/README.md`](../bridge/README.md) |
| Sơ đồ luồng xử lý | [`../FLOWCHART.md`](../FLOWCHART.md) | [`../FLOWCHART.md`](../FLOWCHART.md) |
| Sơ đồ tư duy kiến trúc | [`../mindmap-mermaid.md`](../mindmap-mermaid.md) | [`../mindmap-mermaid.md`](../mindmap-mermaid.md) |

[`../DOCS.md`](../DOCS.md) là tài liệu API chi tiết bằng tiếng Việt. [`../FLOWCHART.md`](../FLOWCHART.md) và [`../mindmap-mermaid.md`](../mindmap-mermaid.md) mô tả kiến trúc Instagram Direct bằng Mermaid.

## Quy tắc cập nhật

- Khi đổi public API, cập nhật tài liệu tương ứng trong cùng commit.
- Mọi tác vụ I/O mạng đều dùng `async`/`await` và `httpx.AsyncClient` hoặc Go Bridge JSON-RPC.
- Giữ nguyên tên package `igchat_v2`, tên hàm, class và tham số; không dịch identifier.
- Chuỗi tiếng Việt viết đủ dấu và lưu UTF-8 không BOM.
- Không dùng em dash; dùng dấu gạch ngang `-`.
- Kiểm tra liên kết nội bộ, code fence và cú pháp Mermaid trước khi push.
- Không đưa cookie, token, password, TOTP secret hoặc `sessionid` thật vào tài liệu hoặc ví dụ.

## Kiểm tra encoding

Đảm bảo mọi file markdown và source code lưu dưới định dạng UTF-8 tiêu chuẩn. Kiểm tra codepoint và encoding trước khi commit.
