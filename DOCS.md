# igchat-v2 - Tài liệu API async

Tài liệu dành cho `igchat-v2==2.3.4`. Các ví dụ I/O mới dùng `async`/`await`. API blocking được giữ lại để giải thích cách tích hợp hoặc hỗ trợ code cũ.

> [!NOTE]
> Đây là API Instagram không chính thức. Endpoint, token HTML, GraphQL `doc_id`, MQTT payload và E2EE protocol có thể thay đổi mà không báo trước.

> [!WARNING]
> Cookie, mật khẩu, access token, TOTP secret và toàn bộ `dataIGS` là thông tin nhạy cảm. Không đưa chúng vào issue, log, dữ liệu test hoặc commit Git.

## 📋 Mục lục

1. [Mô hình thực thi async](#1-mô-hình-thực-thi-async)
2. [Cài đặt và import](#2-cài-đặt-và-import)
3. [Tạo session và `dataIGS`](#3-tạo-session-và-dataigs)
4. [Session storage](#4-session-storage)
5. [HTTP transport và connection pool](#5-http-transport-và-connection-pool)
6. [Login credential và 2FA](#6-login-credential-và-2fa)
7. [Gửi tin nhắn thường](#7-gửi-tin-nhắn-thường)
8. [Upload và gửi attachment](#8-upload-và-gửi-attachment)
9. [Listener MQTT thường](#9-listener-mqtt-thường)
10. [Listener E2EE](#10-listener-e2ee)
11. [Gửi và thao tác qua bridge](#11-gửi-và-thao-tác-qua-bridge)
12. [Sửa, reaction và thu hồi tin thường](#12-sửa-reaction-và-thu-hồi-tin-thường)
13. [Theme và Instagram Notes](#13-theme-và-instagram-notes)
14. [Tính năng Instagram](#14-tính-năng-instagram)
15. [Quản lý thread](#15-quản-lý-thread)
16. [Bot mẫu `src/main.py`](#16-bot-mẫu-srcmainpy)
17. [Timeout, lỗi và cancellation](#17-timeout-lỗi-và-cancellation)
18. [Hợp đồng kết quả](#18-hợp-đồng-kết-quả)
19. [Chuyển từ sync sang async](#19-chuyển-từ-sync-sang-async)
20. [Kiểm tra chất lượng](#20-kiểm-tra-chất-lượng)
21. [FAQ và troubleshooting](#21-faq-và-troubleshooting)

---

## 1. <a id="1-mô-hình-thực-thi-async"></a>⚡ Mô hình thực thi async

Ứng dụng CLI nên có đúng một `asyncio.run()` tại entry point:

```python
import asyncio


async def main() -> None:
    ...


if __name__ == "__main__":
    asyncio.run(main())
```

FastAPI, Quart, Jupyter, Discord bot và nhiều framework khác đã có event loop. Trong môi trường đó, gọi trực tiếp:

```python
data_igs = await dataGetHome(cookie)
result = await _search.func(data_igs, "Minh")
```

Không gọi `asyncio.run()` bên trong coroutine. Python sẽ báo `RuntimeError: asyncio.run() cannot be called from a running event loop`, đồng thời coroutine chưa await có thể sinh warning.

### Boundary blocking hợp lệ

Không phải thư viện nào cũng cung cấp API asyncio:

- `paho-mqtt` dùng vòng lặp blocking.
- Bridge E2EE dùng hàng đợi response và subprocess pipe blocking.
- Credential login cũ dùng `requests`.

Wrapper chạy các phần blocking này qua `asyncio.to_thread()` để không chặn event loop. API HTTP mới dùng `httpx.AsyncClient`; thread adapter chỉ dành cho những phần blocking còn cần giữ lại.

---

## 2. <a id="2-cài-đặt-và-import"></a>⚙️ Cài đặt và import

```bash
git clone --recurse-submodules https://github.com/0xshijn/igchat-v2.git
cd igchat-v2
python -m venv .venv

# Windows PowerShell
.venv\Scripts\Activate.ps1

# macOS / Linux
source .venv/bin/activate

python -m pip install -e ".[dev]"
python scripts/verify_distribution.py
```

Sau khi cài ở chế độ editable, các script trong virtual environment có thể import `igchat_v2`.
Không cần đặt `PYTHONPATH=src` hoặc thêm prefix `src.` vào import.

```python
from igchat_v2._core._session import dataGetHome
from igchat_v2._features._instagram import _search
from igchat_v2._messaging._send import api as SendAPI
```

Ứng dụng không nên import các helper riêng như `_build_`, `_parse_` hoặc `_BridgeProcess`. Chúng phục vụ nội bộ và có thể thay đổi giữa các phiên bản.

---

## 3. <a id="3-tạo-session-và-dataigs"></a>💾 Tạo session và `dataIGS`

API:

```python
async def dataGetHome(
    setCookies: str | None = None,
    storage: SessionStorage | None = None,
) -> dict[str, Any] | None:
    ...
```

### Từ chuỗi cookie

```python
from igchat_v2._core._session import dataGetHome

data_igs = await dataGetHome("sessionid=...; ds_user_id=...; csrftoken=...;")
if data_igs is None:
    raise RuntimeError("Không tạo được session Instagram.")
```

`dataGetHome()` tải trang chủ qua HTTPS, đọc token từ HTML và trả dict khi đủ các trường bắt buộc:

```python
{
    "fb_dtsg": "...",
    "fb_dtsg_ag": "...",       # Có thể không xuất hiện ở mọi response
    "jazoest": "...",
    "hash": "...",             # Có thể không xuất hiện ở mọi response
    "sessionID": "...",
    "IGSID": "1000...",
    "clientRevision": "...",
    "cookieIGS": "sessionid=...; ds_user_id=...; ...",
}
```

Các trường bắt buộc là `fb_dtsg`, `jazoest`, `sessionID`, `IGSID` và `clientRevision`. `IGSID` phải là chuỗi số. Nếu thiếu cookie, request HTTP lỗi hoặc HTML không còn token cần thiết, hàm trả `None` và in chẩn đoán ngắn, không chứa cookie.

### Không log `dataIGS`

Sai:

```python
print(data_igs)
logger.debug("session=%r", data_igs)
```

Đúng hơn:

```python
logger.info("Instagram session ready for uid=%s", data_igs["IGSID"])
```

---

## 4. <a id="4-session-storage"></a>💾 Session storage

Ba class public:

| Class | Mục đích |
|---|---|
| `SessionStorage` | Interface `load`, `save`, `clear` |
| `FileSessionStorage` | Lưu cookie trong một key của file JSON |
| `EnvSessionStorage` | Đọc và ghi biến môi trường của tiến trình |

### File JSON local

```python
from igchat_v2._core._session import dataGetHome
from igchat_v2._core._storage import FileSessionStorage

storage = FileSessionStorage("src/config.json", key="cookies")
data_igs = await dataGetHome(storage=storage)
```

`FileSessionStorage.save()` ghi vào file tạm, flush, `fsync` rồi thay file bằng `os.replace()`. Cách này giảm nguy cơ file JSON bị ghi dở khi tiến trình dừng đột ngột. Cookie không được mã hóa; ứng dụng vẫn cần bảo vệ quyền truy cập file và quản lý thông tin nhạy cảm.

### Biến môi trường

```python
from igchat_v2._core._session import dataGetHome
from igchat_v2._core._storage import EnvSessionStorage

data_igs = await dataGetHome(storage=EnvSessionStorage("IGS_COOKIES"))
```

Windows PowerShell:

```powershell
$env:IGS_COOKIES = "sessionid=...; ds_user_id=...; csrftoken=...;"
```

Biến môi trường giúp giữ thông tin nhạy cảm ngoài mã nguồn, nhưng tiến trình cùng quyền vẫn có thể đọc chúng. Khi triển khai, nên dùng công cụ quản lý secret của nền tảng đang chạy.

---

## 5. <a id="5-http-transport-và-connection-pool"></a>🌍 HTTP transport và connection pool

`_core._http` cung cấp các hàm HTTP dùng chung:

```python
await post_async(request_kwargs, client=client)
await get_async(request_kwargs, client=client)
```

`_core._utils` bổ sung các hàm gửi request theo định dạng Instagram:

```python
await send_request_async(request_kwargs, client=client)
await send_get_request_async(request_kwargs, client=client)
await post_form_json_async(
    url,
    data_form,
    cookie,
    strip_for_loop_prefix=True,
    client=client,
)
```

### Tái sử dụng một client

```python
import asyncio
import httpx

from igchat_v2._features._instagram import _notification, _search

async with httpx.AsyncClient(
    timeout=httpx.Timeout(30.0, connect=10.0),
    follow_redirects=True,
) as client:
    notifications, users = await asyncio.gather(
        _notification.func(data_igs, client=client),
        _search.func(data_igs, "0xshijn", client=client),
    )
```

Lợi ích:

- Tái sử dụng kết nối TCP/TLS.
- Đặt timeout và proxy ở một chỗ.
- Có thể truyền `httpx.MockTransport` khi test.
- Đóng tài nguyên cùng vòng đời ứng dụng.

### Quyền sở hữu client

- Nếu bạn truyền `client=`, bạn chịu trách nhiệm đóng client.
- Nếu không truyền `client=`, helper tự tạo và đóng client cho lần gọi đó.
- Không dùng client sau khi thoát `async with`.
- Không chia sẻ một client giữa nhiều event loop ở các thread khác nhau.

Transport sao chép request kwargs trước khi bỏ `url`, `verify`, `timeout`, nên không sửa dict mà ứng dụng truyền vào.

---

## 6. <a id="6-login-credential-và-2fa"></a>🔑 Login credential và 2FA

Nên dùng cookie phiên có sẵn. Đăng nhập bằng thông tin tài khoản dễ gặp checkpoint, giới hạn tần suất hoặc thay đổi mã lỗi từ Instagram.

```python
from igchat_v2._core._instagramLogin import loginIGS

login = loginIGS(
    "username",
    "password",
    AuthenticationGoogleCode="JBSWY3DPEHPK3PXP",
)
result = await login.main()
```

`AuthenticationGoogleCode` nhận một trong hai dạng:

- OTP hiện hành gồm 6 đến 8 chữ số.
- TOTP shared secret để module tạo OTP cục bộ bằng `pyotp`.

`login.main()` chạy phần đăng nhập cũ dùng `requests` trên worker thread để không chặn event loop. Phần này vẫn là xử lý blocking, không phải HTTP async.

### IG4A defaults và override

Module có API key và app access token mặc định cho luồng IG4A cũ. Chỉ ghi đè khi Instagram hoặc môi trường test yêu cầu:

```powershell
$env:IGCHAT_API_KEY = "<optional-override>"
$env:IGCHAT_APP_ACCESS_TOKEN = "<optional-override>"
```

Không ghi giá trị bí mật thật vào mã nguồn hoặc `.env.example`.

### Kết quả login

Kết quả thành công thường chứa cookie đã xuất và trạng thái đăng nhập. Khi có lỗi, đọc message, code và subcode Instagram trả về. Code hiện xử lý các continuation subcode `1348162` và `1348023`; chúng có thể thay đổi.

TOTP secret không được gửi tới `2fa.live` hoặc dịch vụ bên thứ ba.

---

## 7. <a id="7-gửi-tin-nhắn-thường"></a>💬 Gửi tin nhắn thường

API:

```python
await SendAPI().send(
    dataIGS,
    contentSend,
    threadID,
    typeAttachment=None,
    attachmentID=None,
    typeChat=None,
    replyMessage=None,
    messageID=None,
    client=None,
)
```

### Gửi tới một user

```python
from igchat_v2._messaging._send import api as SendAPI

result = await SendAPI().send(
    data_igs,
    "Xin chào",
    threadID="100012345678",
    typeChat="user",
)
```

### Gửi tới group thread

```python
result = await SendAPI().send(
    data_igs,
    "Thông báo nhóm",
    threadID="987654321",
    typeChat=None,
)
```

### Gửi tới nhiều user

```python
result = await SendAPI().send(
    data_igs,
    "Thông báo riêng",
    threadID=["10001", "10002"],
    typeChat="user",
)
```

Chỉ truyền danh sách người nhận khi dùng `typeChat="user"`.

### Reply message

```python
result = await SendAPI().send(
    data_igs,
    "Nội dung trả lời",
    threadID="100012345678",
    typeChat="user",
    replyMessage=True,
    messageID="mid.$original",
)
```

Nếu `replyMessage=True` mà thiếu `messageID`, API báo `ValueError` trước khi gửi request.

### Validation

`send()` không nhận các đầu vào sau:

- `threadID` rỗng.
- `typeChat` khác `None` hoặc `"user"`.
- `typeAttachment` ngoài `gif`, `image`, `video`, `file`, `audio`.
- Chỉ truyền một trong hai `typeAttachment` và `attachmentID`.
- Cả nội dung lẫn tệp đính kèm đều rỗng.
- Danh sách người nhận rỗng hoặc chứa ID rỗng.

Mỗi lần gọi tạo form riêng nên có thể chạy đồng thời. `sender.results` chỉ giữ kết quả của lần gọi hoàn tất gần nhất; hãy dùng dict được hàm trả về để xử lý kết quả của từng lần gửi.

---

## 8. <a id="8-upload-và-gửi-attachment"></a>📎 Upload và gửi attachment

API:

```python
await _attachments.func(
    filenames,
    dataIGS,
    client=None,
    include_error=False,
)
```

`filenames` nhận một đường dẫn hoặc danh sách đường dẫn. Module kiểm tra file tồn tại trước khi gửi request và luôn đóng file trong `finally`.

Parser hiện chỉ trả metadata của phần tử đầu tiên (`metadata[0]` hoặc `metadata["0"]`), không trả danh sách kết quả. Để gửi nhiều tệp và kiểm tra kết quả của từng tệp, hãy upload lần lượt, lấy từng `attachmentID` rồi truyền danh sách ID vào `_send`.

```python
from igchat_v2._messaging import _attachments

uploaded = await _attachments.func(
    "photo.jpg",
    data_igs,
    include_error=True,
)
```

Success:

```python
{
    "attachmentID": "123...",
    "attachmentUrl": "https://...",
    "videoDuration": None,
    "attachmentType": "image/jpeg",
    "typeAttachment": "image",
}
```

`attachmentType` có thể là MIME hoặc loại tệp do Instagram trả về. Khi gọi `_send`, dùng `typeAttachment` đã chuẩn hóa:

```python
from igchat_v2._messaging._send import api as SendAPI

if not uploaded or not uploaded.get("attachmentID"):
    raise RuntimeError(f"Upload không có attachment ID: {uploaded}")

result = await SendAPI().send(
    data_igs,
    "Ảnh của bạn đây",
    threadID="100012345678",
    typeChat="user",
    typeAttachment=uploaded["typeAttachment"],
    attachmentID=uploaded["attachmentID"],
)
```

Khi `include_error=False`, response không parse được trả `None`. Khi `include_error=True`, module trả error payload có `error-code`, `error-summary`, `error-description`, `metadata`, `file-rejected` và `raw-excerpt` đã giới hạn độ dài.

Nếu Instagram trả `metadata: {"0": null}` hoặc lỗi `1357054`, server đã từ chối upload hoặc endpoint/session không còn phù hợp. Không dùng kết quả đó làm attachment ID.

---

## 9. <a id="9-listener-mqtt-thường"></a>📡 Listener MQTT thường

Khởi tạo:

```python
from igchat_v2._messaging._listening import listeningEvent

listener = listeningEvent(data_igs, message_queue_maxsize=1000)
```

Public async methods:

| Method | Kết quả |
|---|---|
| `await get_last_seq_id()` | Lấy sequence ID ban đầu |
| `await connect_mqtt()` | Chạy MQTT loop đến khi disconnect |
| `await get_message(timeout=None)` | Lấy event tiếp theo hoặc `None` khi timeout |
| `await disconnect()` | Dừng client và worker loop |

Workflow:

```python
import asyncio

listener_task = asyncio.create_task(listener.connect_mqtt())
try:
    while True:
        if listener_task.done():
            listener_task.result()
        event = await listener.get_message(timeout=30)
        if event is None:
            continue
        print(event["body"], event["messageID"])
finally:
    await listener.disconnect()
    await listener_task
```

Event normalized:

```python
{
    "body": "...",
    "timestamp": 1710000000000,
    "userID": "1000...",
    "messageID": "mid.$...",
    "replyToID": "thread-id",
    "type": "thread",
    "attachments": {"id": 0, "url": None},
    "mentions": [],
}
```

Listener đọc toàn bộ delta trong payload và đưa event vào queue có giới hạn. Khi queue đầy, event cũ nhất bị bỏ và `droppedMessages` tăng. Theo dõi giá trị này để biết ứng dụng có xử lý tin chậm hơn tốc độ nhận hay không.

Bot mới nên đọc event từ queue, không kiểm tra lặp lại `bodyResults`. Thuộc tính này chỉ giữ kết quả gần nhất để tương thích code cũ; nhiều event đến liên tiếp có thể ghi đè nhau.

### Tự nối lại

API dưới đây có từ `2.3.4`. Với E2EE, dùng bridge cùng phiên bản để có
capability `structuredConnectionStatus`. Nếu tự build, lấy bridge từ cùng
checkout với package Python; binary 2.3.3 không có contract này.

MQTT và E2EE dùng chung `ReconnectPolicy` cho lỗi kết nối tạm thời, kể cả khi
khởi động lúc mất mạng. Mặc định không giới hạn số lượt phục hồi của wrapper;
delay tăng dần từ 1 giây, có jitter 20% và không vượt 60 giây. Sau 60 giây
kết nối ổn định, budget được reset. Muốn giới hạn, truyền `max_attempts=5`;
muốn tắt retry, truyền `enabled=False` hoặc `max_attempts=0`.

Với MQTT, mỗi lượt là một lần thử tạo kết nối mới sau lần đầu. Với E2EE,
policy điều khiển retry từng phase startup và respawn; khi socket Go tự nối lại, mỗi lượt
là một lần wrapper kiểm tra đã phục hồi hay chưa. `attempt` không phải bộ đếm
TCP connect của Go. Delay socket native do thư viện Go quản lý riêng; regular
transport hiện có backoff trần 5 phút, không bị `max_delay` ghi đè. Policy
giới hạn có thể dừng listener trước khi socket native thử lần tiếp theo.

```python
from igchat_v2 import ReconnectPolicy, listeningE2EEEvent

policy = ReconnectPolicy(
    initial_delay=1.0,
    max_delay=60.0,
    jitter=0.2,
    max_attempts=None,
)

listener = listeningE2EEEvent(
    data_igs,
    reconnect_policy=policy,
    on_connection_state=lambda status: print(status),
    e2ee_memory_only=False,
    device_path=".state/e2ee_device.json",
)
```

File device chứa key thiết bị và session; không commit hoặc chia sẻ file này.
Repo đã bỏ qua thư mục `.state/` trong Git.

Với MQTT thường, truyền hai tham số `reconnect_policy` và `on_connection_state`
cho `listeningEvent` theo cùng cách. Chỉ chạy listener phù hợp với ứng dụng;
không khởi chạy thêm một listener để xử lý việc mất kết nối của listener cũ.

Đọc `listener.connection_state` hoặc `listener.connection_status` để lấy snapshot.
Callback trạng thái nhận `state`, `reason`, `attempt`, `next_retry_in`; không có
cookie, ID hội thoại hoặc nội dung chat. Callback đồng bộ có thể chạy từ worker
hoặc caller gọi `stop()`: giữ nó ngắn và dùng `loop.call_soon_threadsafe()` nếu
cần cập nhật asyncio. Không giả định callback được gọi tuần tự giữa các thread;
`connection_status` luôn là snapshot hiện tại.
Có thể thay callback bằng `listener.set_connection_state_callback(fn)`.

- `starting`: đang khởi tạo transport.
- `connected`: transport yêu cầu đã sẵn sàng; không phải xác nhận một tin gửi đã tới peer.
- `reconnecting`: đang chờ hoặc thử nối lại.
- `auth_required`: cần cập nhật cookie hoặc xử lý checkpoint; không retry cùng credential.
- `fatal`: lỗi protocol/config, hết retry budget hoặc không thể phục hồi an toàn.
- `stopped`: đã yêu cầu dừng.

Lỗi chưa phân loại được dừng với `fatal/unknown`, không retry vô hạn. Ví dụ,
Paho không giữ HTTP status khi WebSocket upgrade bị từ chối; thư viện không
đoán đây là lỗi mạng hay cookie hết hạn chỉ từ một thông báo handshake chung.

Socket Go/whatsmeow giữ quyền tự nối lại khi bridge vẫn khỏe. Python chỉ thay
process khi bridge crash hoặc RPC không còn dùng được, không giết bridge chỉ
vì mạng đang mất. Với E2EE mặc định `e2ee_memory_only=True`, device chỉ nằm trong
RAM của bridge: process chết thì listener báo `device_state_lost`, không tự
pair device mới và không tự ghi key ra đĩa. Nếu cần phục hồi qua process mới,
chọn `e2ee_memory_only=False` cùng `device_path` riêng như ví dụ trên.

MQTT giữ sync token/sequence qua reconnect và có cache message ID giới hạn để
lọc replay. Cache và khả năng đồng bộ của server vẫn có giới hạn; reconnect
không phải cam kết nhận đủ mọi tin đã gửi trong thời gian offline. Theo dõi
queue drop và thông báo khoảng trống dữ liệu khi thay process. Tin gửi trả
`unknown` không được tự gửi lại chỉ vì transport vừa kết nối lại.

`disconnect()`/`stop()` ngắt thời gian chờ retry. Hủy coroutine `connect_mqtt()`
sẽ yêu cầu dừng và chờ worker thu dọn; lời gọi mạng đang chạy vẫn chịu timeout
riêng. Không chạy listener mới trước khi task cũ kết thúc.

---

## 10. <a id="10-listener-e2ee"></a>🔐 Listener E2EE

Khởi tạo:

```python
listener = listeningE2EEEvent(
    data_igs,
    log_level="none",
    device_path=None,
    e2ee_memory_only=True,
    enable_e2ee=True,
    binary_path=None,
)
```

| Tham số | Ý nghĩa |
|---|---|
| `log_level` | Mức log gửi cho bridge |
| `device_path` | Path state thiết bị khi muốn persist |
| `e2ee_memory_only` | Giữ device state trong RAM khi `True` |
| `enable_e2ee` | Có gọi handshake E2EE hay không |
| `binary_path` | Override binary cho instance này |

Cookie bridge bắt buộc có `c_user`, `xs`, `datr`, `fr`. Wrapper chỉ chuyển các cookie cần thiết sang bridge.

### Binary discovery

Thứ tự:

1. `binary_path=` trên constructor.
2. `IGCHAT_E2EE_BIN` (hoặc `FBCHAT_E2EE_BIN` legacy).
3. `build/igchat-bridge-e2ee.exe` trên Windows hoặc không đuôi trên Unix.
4. Auto-download GitHub Release nếu path mặc định chưa có.

Nếu bạn chỉ định đường dẫn nhưng file không tồn tại, wrapper báo `FileNotFoundError`, không tự tải binary khác.

### Callback và event loop

`on_message()` nhận callback đồng bộ, được gọi từ vòng lặp đọc event của bridge. Không dùng `await` trực tiếp trong callback; hãy chuyển event về event loop:

```python
import asyncio

listener = listeningE2EEEvent(data_igs)
loop = asyncio.get_running_loop()
events: asyncio.Queue[dict] = asyncio.Queue(maxsize=1000)


def enqueue(event: dict) -> None:
    if events.full():
        events.get_nowait()
    events.put_nowait(event)


listener.on_message(
    lambda event: loop.call_soon_threadsafe(enqueue, event)
)
task = asyncio.create_task(listener.connect_mqtt())
```

### Đợi bridge sẵn sàng

`wait_until_connected()` dùng `threading.Event`. Gọi qua worker thread để không chặn event loop:

```python
ready = await asyncio.to_thread(
    listener.wait_until_connected,
    listener.startup_timeout,
    require_e2ee=True,
)
if not ready:
    raise TimeoutError("E2EE listener chưa sẵn sàng.")
```

Đừng gửi tin ngay sau `create_task(connect_mqtt())`; tiến trình bridge có thể đã chạy nhưng chưa xong `newClient`, `connect` và `connectE2EE`. Wrapper đặt timeout riêng cho các bước `contract`, `new client`, `regular connect`, `regular ready`, `E2EE connect` và `E2EE ready`. `startup_timeout` là ngân sách cho một lượt khởi động, không phải deadline cho toàn bộ thời gian retry. `wait_until_connected()` trả `False` khi hết thời gian chờ của caller; nếu listener còn `reconnecting`, ứng dụng có thể tiếp tục chờ. Lỗi terminal vẫn được trả về, không bị đổi thành timeout chung.

### Schema event

Raw callback event:

```python
{
    "type": "e2eeMessage",
    "data": {
        "id": "...",
        "text": "ping",
        "timestampMs": 1710000000000,
        "senderId": "1000...",
        "threadId": "...",
        "chatJid": "1000...@msgr",
        "senderJid": "1000...@msgr",
        "attachments": [],
        "mentions": [],
    },
}
```

`listener.bodyResults` giữ dữ liệu đã chuẩn hóa giống listener thường. `listener.e2eeBodyResults` giữ `chatJid` và `senderJid`. Ứng dụng mới nên xử lý event nhận qua callback, tránh đọc kết quả bị ghi đè khi nhiều tin đến liên tiếp.

### Shutdown

```python
try:
    ...
finally:
    listener.stop()
    await task
```

`stop()` là hàm đồng bộ: nó báo dừng và đóng tiến trình con. Bạn vẫn cần `await` task để chờ listener kết thúc.

---

## 11. <a id="11-gửi-và-thao-tác-qua-bridge"></a>🌉 Gửi và thao tác qua bridge

### Gửi text E2EE

Sau khi listener ready:

```python
result = await listener.send_e2ee_message(
    "100012345678@msgr",
    "Xin chào",
    reply_to_id="",
    reply_to_sender_jid="",
)
```

Reply:

```python
data = event["data"]
result = await listener.send_e2ee_message(
    data["chatJid"],
    "pong",
    reply_to_id=data["id"],
    reply_to_sender_jid=data["senderJid"],
)
```

### Gửi tin thường qua cùng bridge

```python
result = await listener.send_message(
    int(thread_id),
    "Thông báo group",
    reply_to_id="mid.$original",
)
```

### `BridgeActions`

```python
from igchat_v2._messaging._bridge_actions import BridgeActions

if listener._bridge is None:
    raise RuntimeError("Bridge chưa sẵn sàng.")
actions = BridgeActions(listener._bridge)
```

Public async actions:

| Method | Mục đích |
|---|---|
| `edit_message(message_id, new_text)` | Sửa tin thường qua bridge |
| `unsend_message(message_id)` | Thu hồi tin thường |
| `edit_e2ee_message(chat_jid, message_id, new_text)` | Sửa tin E2EE |
| `unsend_e2ee_message(chat_jid, message_id)` | Thu hồi tin E2EE |
| `send_typing_indicator(thread_id, is_typing, ...)` | Typing thường |
| `mark_read(thread_id, watermark_ts)` | Đánh dấu đã đọc |
| `send_e2ee_typing(chat_jid, is_typing)` | Typing E2EE |
| `send_e2ee_audio(chat_jid, data, ...)` | Gửi audio bytes |
| `send_e2ee_image(chat_jid, data, ...)` | Gửi image bytes |
| `download_media(url)` | Download media thường thành bytes |
| `download_e2ee_media(...)` | Download và giải mã media E2EE |

Ví dụ gửi ảnh:

```python
image_bytes = await asyncio.to_thread(Path("photo.jpg").read_bytes)
result = await actions.send_e2ee_image(
    "100012345678@msgr",
    image_bytes,
    mime_type="image/jpeg",
    caption="Ảnh test",
)
```

Bytes được chuyển sang base64 khi gửi qua JSON-RPC. Không đọc file lớn trực tiếp trong event loop; dùng `asyncio.to_thread()` hoặc I/O async phù hợp.

### `_send_e2ee.api`

`_send_e2ee.api` là sender blocking được giữ để tương thích, có thể chạy riêng hoặc dùng lại bridge. Ứng dụng asyncio mới nên dùng `await listener.send_e2ee_message(...)` và `BridgeActions`. Nếu cần sender chạy riêng, tách lời gọi blocking khỏi event loop.

---

## 12. <a id="12-sửa-reaction-và-thu-hồi-tin-thường"></a>🔄 Sửa, reaction và thu hồi tin thường

```python
from igchat_v2._messaging import _editMessage, _reactions, _unsend

edited = await _editMessage.func(
    data_igs,
    "mid.$message",
    "Nội dung mới",
)

reacted = await _reactions.func(
    data_igs,
    "ADD_REACTION",
    "mid.$message",
    "🔥",
)

removed = await _unsend.func("mid.$message", data_igs)
```

`_reactions.func()` chấp nhận `add`, `ADD_REACTION`, `remove` hoặc `REMOVE_REACTION`, không phân biệt hoa thường. ID và emoji không được rỗng.

`_editMessage` gửi LS task qua MQTT. Kết quả thành công chỉ xác nhận task đã được gửi lên `/ls_req`, chưa xác nhận server đã áp dụng thay đổi. Instagram thường chỉ cho sửa tin của chính tài khoản và có thể giới hạn thời gian sửa.

---

## 13. <a id="13-theme-và-instagram-notes"></a>🎨 Theme và Instagram Notes

### Theme

```python
from igchat_v2._messaging import _changeTheme

themes = await _changeTheme.listThemes(data_igs)
match = await _changeTheme.findTheme(data_igs, "love")
changed = await _changeTheme.changeTheme(
    data_igs,
    "thread-id",
    "love",
)
```

Entry point thống nhất:

```python
await _changeTheme.func(data_igs, action="list")
await _changeTheme.func(data_igs, themeName="love", action="find")
await _changeTheme.func(
    data_igs,
    threadID="thread-id",
    themeName="love",
    action="set",
)
```

Theme được match theo ID, tên chính xác rồi keyword. `changeTheme()` publish nhiều LS task cần thiết cho thread theme.

### Instagram Notes

```python
from igchat_v2._messaging import _createNotes

current = await _createNotes.checkNote(data_igs)
created = await _createNotes.createNote(
    data_igs,
    "Đang viết bot",
    privacy="FRIENDS",
)
deleted = await _createNotes.deleteNote(data_igs, "note-id")
replaced = await _createNotes.recreateNote(
    data_igs,
    "old-note-id",
    "Nội dung mới",
)
```

Entry point:

```python
await _createNotes.func(data_igs, action="check")
await _createNotes.func(data_igs, action="create", text="Hello")
await _createNotes.func(data_igs, action="delete", noteID="note-id")
await _createNotes.func(
    data_igs,
    action="recreate",
    oldNoteID="old-id",
    newText="New note",
)
```

`recreateNote()` xóa note rồi tạo lại và dừng khi có lỗi. Hai bước này không phải một transaction phía server: nếu xóa thành công nhưng tạo lại thất bại, note cũ đã mất.

---

## 14. <a id="14-tính-năng-instagram"></a>✨ Tính năng Instagram

Mọi API trong bảng là coroutine và phần lớn nhận optional keyword-only `client: httpx.AsyncClient`.

| Module | Chữ ký rút gọn | Mục đích |
|---|---|---|
| `_changeBio` | `func(dataIGS, newContents, uploadPost=False)` | Đổi bio |
| `_createPost` | `func(dataIGS, newContents, attachmentID=None)` | Tạo bài timeline |
| `_archivePost` | `func(dataIGS, postID, typePost="my_post")` | Lưu trữ bài viết |
| `_deletePost` | `func(dataIGS, postID, typePost="my_post")` | Xóa bài viết (vào thùng rác) |
| `_professional` | `func(dataIGS, statusBusiness=None)` | Bật/tắt Professional mode |
| `_search` | `func(dataIGS, keywordSearch)` | Tìm user, tối đa 5 kết quả đã loại trùng |
| `_blocking` | `func(dataIGS, idUser, choiceInteract)` | `block` hoặc `unblock` |
| `_registerOnProfile` | `func(dataIGS, newName, newUsername)` | Tạo profile bổ sung |
| `_notification` | `func(dataIGS)` | Lấy notification |
| `_get_user_info` | `func(dataIGS, userID)` | Lấy thông tin user |
| `_marketplace` | `createItem(...)` | Đăng sản phẩm |
| `_marketplace` | `getInformationProductItemMarketPlace(...)` | Lấy chi tiết sản phẩm |

Ví dụ workflow có connection pool:

```python
import httpx

from igchat_v2._features._instagram import _blocking, _get_user_info, _search

async with httpx.AsyncClient(timeout=30) as client:
    search = await _search.func(data_igs, "0xshijn", client=client)
    info = await _get_user_info.func(
        data_igs,
        "100012345678",
        client=client,
    )
    blocked = await _blocking.func(
        data_igs,
        "100012345678",
        "block",
        client=client,
    )
```

`_createPost` chưa có schema Composer ổn định cho attachment. Truyền `attachmentID` sẽ raise `NotImplementedError`, tránh trường hợp caller tưởng ảnh đã được đăng trong khi module âm thầm bỏ qua.

`_archivePost` sử dụng `useCometArchivePostMutation` để chuyển bài viết vào kho lưu trữ (Archive). Cơ chế tham số tương tự `_deletePost`.

`_deletePost` dùng `useCometTrashPostMutation` để đưa bài viết vào thùng rác, không xóa vĩnh viễn. Tham số `typePost` (`"my_post"` hoặc `"others"`) quyết định định dạng ID Base64 mà Instagram yêu cầu.

Marketplace validate category, tên, giá không âm, danh sách ảnh và tọa độ seller trước request.

---

## 15. <a id="15-quản-lý-thread"></a>🧵 Quản lý thread

| Module | API |
|---|---|
| `_all_thread_data` | `await func(dataIGS, client=...)` |
| `_all_thread_data` | `await features(dataGet, threadID, commandUse)` |
| `_changeNameThread` | `await func(dataIGS, threadID, newNameThread, client=...)` |
| `_changeEmoji` | `await func(dataIGS, threadID, newEmoji, client=...)` |
| `_addAdmin` | `await func(dataIGS, threadID, idUser, statusChoice=True, client=...)` |
| `_changeNickname` | `await func(dataIGS, threadID, idUser, NewNickname, client=...)` |

```python
from igchat_v2._features._thread import (
    _addAdmin,
    _all_thread_data,
    _changeEmoji,
    _changeNameThread,
    _changeNickname,
)

threads = await _all_thread_data.func(data_igs)
if threads.get("error"):
    raise RuntimeError(threads)

info = await _all_thread_data.features(
    threads["dataGet"],
    "thread-id",
    "threadInfomation",
)

await _changeNameThread.func(data_igs, "thread-id", "Tên mới")
await _changeEmoji.func(data_igs, "thread-id", "🔥")
await _changeNickname.func(data_igs, "thread-id", "user-id", "Biệt danh")
await _addAdmin.func(data_igs, "thread-id", "user-id", statusChoice=True)
await _addAdmin.func(data_igs, "thread-id", "user-id", statusChoice=False)
```

`statusChoice=False` thực sự gỡ admin. `features()` parse dữ liệu đã tải trong RAM và giữ coroutine để hợp đồng gọi nhất quán.

---

## 16. <a id="16-bot-mẫu-srcmainpy"></a>🤖 Bot mẫu `src/main.py`

Bot mẫu minh họa cách khởi động, nhận tin và dừng listener. Đây không phải framework bot để dùng nguyên trạng khi triển khai.

Bot mẫu cần Go E2EE bridge và chỉ xử lý lệnh sau khi E2EE sẵn sàng. Nó kiểm tra readiness theo từng khoảng `startup_timeout` và tiếp tục chờ khi listener đang `reconnecting`; lỗi terminal khiến bot dừng. Bot không chuyển sang Python MQTT. Nếu chỉ cần listener MQTT thường, hãy khởi tạo `listeningEvent` riêng; đó không phải chế độ dự phòng của bot mẫu.

### Cấu hình

```json
{
  "prefix": "/",
  "cookies": "c_user=...; xs=...; fr=...; datr=...;",
  "admins": ["100012345678"],
  "log_message_content": false,
  "debug_errors": false
}
```

Cookie được giữ trong file riêng tư (`0600` trên POSIX hoặc ACL chỉ dành cho
user hiện tại/SYSTEM trên Windows). Nội dung chat và chi tiết exception bị che
mặc định; chỉ bật `log_message_content` hoặc `debug_errors` trong môi trường
debug được kiểm soát.

### Luồng runtime

1. `load_config()` siết quyền file và validate `prefix`, `admins` cùng hai cờ log.
2. `FileSessionStorage` đưa cookie vào `await dataGetHome(...)`.
3. `is_valid_dataigs()` kiểm tra token bắt buộc.
4. Một `httpx.AsyncClient` được dùng lại cho command HTTP.
5. E2EE listener start thành task.
6. Callback bridge chuyển event về queue bằng `call_soon_threadsafe`.
7. Bot bỏ self-message, dedupe message ID và dispatch handler async.
8. Reply qua bridge theo event nhận được; startup vẫn bắt buộc hoàn tất E2EE.
9. Shutdown stop bridge, await listener task và đóng HTTP client.

### Command có sẵn

| Lệnh | Mục đích |
|---|---|
| `/ping` | Đo latency dựa trên timestamp event |
| `/help` | Liệt kê lệnh |
| `/id` | In type, chatJid, threadID, userID, senderJid, messageID |
| `/echo <text>` | Reply lại text |
| `/search <query>` | Gọi `_search.func` bằng HTTP client dùng chung |
| `/unsend` | Admin thu hồi tin E2EE cuối của bot trong chat |

Để thêm lệnh, viết async handler rồi đăng ký trong `self._handlers`. Không chạy tác vụ tính toán nặng ngay trong handler; hãy đưa chúng sang process pool hoặc worker phù hợp.

---

## 17. <a id="17-timeout-lỗi-và-cancellation"></a>🩺 Timeout, lỗi và cancellation

### Timeout một feature

```python
import asyncio

try:
    result = await asyncio.wait_for(
        _search.func(data_igs, "query"),
        timeout=20,
    )
except asyncio.TimeoutError:
    result = {"error": 1, "messages": "Quá thời gian tìm kiếm."}
```

### Structured concurrency

Với Python 3.11+:

```python
async with asyncio.TaskGroup() as group:
    notification_task = group.create_task(_notification.func(data_igs))
    search_task = group.create_task(_search.func(data_igs, "Minh"))

notifications = notification_task.result()
users = search_task.result()
```

Nếu một task fail, `TaskGroup` cancel task còn lại và gom lỗi thành `ExceptionGroup`.

### Cleanup khi cancel

Luôn đặt cleanup listener và client trong `finally` hoặc context manager. Không bắt `asyncio.CancelledError` rồi nuốt, vì ứng dụng sẽ không shutdown đúng.

```python
try:
    await bot.run()
finally:
    listener.stop()
```

### Log an toàn

Log loại exception và tên thao tác, không log provider ID/JID, request form, cookie, access token, mật khẩu hoặc TOTP. Logger của bridge và bộ đọc stderr Python đều che metadata nhạy cảm trước khi in. Bật `debug_errors` cũng không nên làm lộ nội dung chat.

Go logger và Python stderr drain giới hạn dòng thô ở 64 KiB. Dòng vượt ngưỡng
bị bỏ toàn bộ đến newline, chỉ phát diagnostic cố định; không in prefix/tail
có thể chứa secret. Python vẫn drain khi tắt log và giữ đúng UTF-8 qua ranh giới
chunk. E2EE typing dùng deadline 10 giây, nhận cancellation từ lifecycle client.
Media giải mã được ghi vào temp file có quyền riêng ngay khi tạo, gồm DACL
protected trên Windows.

---

## 18. <a id="18-hợp-đồng-kết-quả"></a>📝 Hợp đồng kết quả

Các module lịch sử chưa có một dataclass chung, nhưng thường dùng hai schema:

Success:

```python
{
    "success": 1,
    "payload": {...},
}
```

Error:

```python
{
    "error": 1,
    "messages": "...",
    "payload": {...},
}
```

Một số feature trả key domain-specific như `NotificationResults`, `searchResultsDict`, `messageRequests` hoặc `urlPost`. Vì endpoint private không ổn định, caller nên:

```python
if not isinstance(result, dict):
    raise TypeError("API không trả dict.")
if result.get("error"):
    ...
```

Không chỉ kiểm tra HTTP status. Instagram thường trả HTTP 200 nhưng body chứa `error`, `errors` hoặc metadata null.

---

## 19. <a id="19-chuyển-từ-sync-sang-async"></a>⚡ Chuyển từ sync sang async

### Session

Trước:

```python
data_igs = dataGetHome(cookie)
```

Hiện tại:

```python
data_igs = await dataGetHome(cookie)
```

### Feature module

Trước:

```python
result = _search.func(data_igs, "Minh")
```

Hiện tại:

```python
result = await _search.func(data_igs, "Minh")
```

### Send

Trước:

```python
result = sender.send(data_igs, "hello", user_id, typeChat="user")
```

Hiện tại:

```python
result = await sender.send(data_igs, "hello", user_id, typeChat="user")
```

### Listener

Trước thường start `connect_mqtt` bằng `threading.Thread`. Hiện tại:

```python
listener_task = asyncio.create_task(listener.connect_mqtt())
event = await listener.get_message(timeout=30)
```

Không tìm `func_async`; alias đó đã được loại bỏ. Helper blocking còn tồn tại ở một số class với hậu tố `_blocking`, nhưng application async không gọi chúng trực tiếp.

---

## 20. <a id="20-kiểm-tra-chất-lượng"></a>🧪 Kiểm tra chất lượng

Pytest giống CI:

```bash
pytest tests/ -v --tb=short
```

Lint, format và compile:

```bash
ruff check src tests scripts
black --check src tests scripts
mypy
python -m compileall -q src tests scripts
python -m build --wheel
python scripts/verify_distribution.py dist/igchat_v2-2.3.4-py3-none-any.whl
git diff --check
```

CI còn cài riêng wheel và sdist vào virtual environment sạch để xác minh namespace
`igchat_v2`, module lồng sâu và các public export như `_unFriend`.

Bridge:

```bash
cd bridge-e2ee
go test ./...
go vet ./...
```

Trước push, quét mọi file text tracked để phát hiện UTF-8 invalid, U+FFFD, NUL và mojibake thật. PowerShell hiển thị sai encoding không tự động có nghĩa file đã hỏng.

### Canary E2EE và soak có kiểm soát

Chỉ dùng tài khoản clone và một peer đã đồng ý kiểm thử. Driver đọc cookie từ
`IGCHAT_COOKIE` (hoặc `FBCHAT_COOKIE`) hoặc `src/config.json` nội bộ, lưu device bền vững và evidence
không có ID/nội dung chat trong một thư mục mới. Không chạy cùng device với bot
khác và không đưa `device.json` vào Git hoặc gửi cho người khác.

```powershell
python scripts/soak_e2ee.py `
  --binary-path .tmp/igchat-bridge-e2ee-soak.exe `
  --output-dir .tmp/e2ee-soak-run `
  --duration 7200 --sample-interval 60 --fault-after 300
```

Driver đăng nhập, dừng hẳn listener, tạo listener mới từ cùng device rồi so
sánh identity trước khi báo `READY`. Khi đó peer gửi đúng challenge có nonce
được in trên console qua cuộc trò chuyện E2EE; chỉ peer này được kích hoạt
một reply text, một ảnh và một file tối đa 2 MiB. Driver download/giải mã,
đối chiếu SHA-256 của attachment rồi echo lại, không lưu plaintext ra evidence.

Sau khi thật sự nhìn thấy reply, peer gửi mã `text-ok-...` nằm trong reply;
sau khi nhận đủ ảnh và file echo, gửi mã `media-ok-...` mà bot hướng dẫn.
Hai mã này được tạo riêng từng run và chỉ gửi qua E2EE. Đây là xác nhận từ đầu bên kia, khác
với việc RPC gửi trả thành công. Event regular và event cũ không được tính là
bằng chứng E2EE. Timeout gửi không được tự retry.
ACK text cập nhật `peer_confirmed_text`. Khi ACK media hợp lệ xác nhận đã nhận
đủ ảnh và file, bot gửi đúng một tin xác nhận cuối; không phản hồi lặp cho ACK
trùng, tin của bot, event cũ hoặc peer khác. Lỗi gửi/timeout của tin xác nhận
không xóa bằng chứng peer đã ACK và không được tự retry.
`media_ack_notice_delivery=rpc_confirmed` chỉ xác nhận RPC gửi tin cuối trả
thành công, không chứng minh peer đã đọc tin đó. Nếu kết quả gửi chưa rõ,
trường này là `unknown`; acceptance vẫn không đạt dù bằng chứng ACK media
đã được giữ lại.

Khi không thấy phản hồi, xem bộ đếm `observed` trong report: `challenge_message`
nghĩa là mã đã tới qua Go LightSpeed regular, còn `challenge_e2eeMessage` là
event E2EE. Counter không lưu nội dung hay ID. Thêm `--regular-notice` để gửi
đúng một thông báo chẩn đoán cho challenge regular mới; mặc định tắt. Kết quả
`regular_notice_rpc_ok` luôn được ghi riêng, không tính vào điều kiện đạt của
E2EE. Tùy chọn này không chuyển listener sang Python MQTT.

Mặc định mỗi run tạo nonce mới. Có thể dùng `--challenge <mã-chính-xác>` khi
khởi động lại chẩn đoán để peer không cần đổi mã; event trước thời điểm ready
vẫn bị loại. Dùng `--device-path <device-cũ.json>` để tái sử dụng thiết bị từ
run đã dừng sạch, không chạy hai listener cùng device. Path này không được
trùng config, binary, report hoặc file điều khiển.

Mỗi phút driver ghi RSS parent/bridge, generation, trạng thái kết nối và queue
drop. Đến phút thứ năm, nó kill đúng child bridge của mình để kiểm watchdog
respawn, E2EE reconnect và một lần gửi text sau reconnect. Đây là mô phỏng
bridge crash; không phải bằng chứng chịu mất mạng thật hoặc mọi trường hợp
provider outage.

`report.json` ghi từng acceptance check. Exit code `0` nghĩa là các check đều
đạt; `1` là lỗi hoặc bị dừng; `2` là chạy hết thời gian nhưng còn check thiếu
bằng chứng/không đạt. `status=completed` riêng lẻ không đồng nghĩa mọi check
đã pass. Ctrl+C yêu cầu cleanup listener/bridge trước khi ghi report cuối.
Nếu chạy nền, tạo file `stop.request` trong output directory để yêu cầu cùng
luồng shutdown sạch; không xóa device để dừng bot.

### Cold restart sau payload và test mất mạng riêng bridge

Chạy sau khi soak kết thúc và shutdown sạch; không mở hai listener dùng cùng
device. Kiểm tra driver/bridge con của run cũ đã thoát trước khi launch;
recovery lease không khóa được consumer khác không dùng cùng cơ chế.
Runner từ chối report chưa hoàn tất hoặc chưa đạt acceptance. Nó dùng
lại device đã trao đổi payload thật, yêu cầu challenge/ACK mới và echo ảnh/file
để kiểm chứng session được khôi phục, không chỉ so sánh identity.

```powershell
python scripts/recovery_e2ee.py `
  --soak-report .tmp/e2ee-receive-notice-20261015-1350/report.json `
  --binary-path .tmp/igchat-bridge-e2ee-soak.exe `
  --device-path .tmp/e2ee-soak-20261015-1329/device.json `
  --output-dir .tmp/e2ee-recovery-20261015
```

Parent giữ CONNECT proxy chỉ trên loopback và truyền proxy qua environment
riêng của tiến trình test con. Không thay proxy Windows, firewall hay network
adapter. Proxy relay byte mã hóa, không giải TLS hoặc ghi header/payload.
Sau khi cold restart roundtrip đạt, peer được hướng dẫn gửi chuỗi tin đánh số;
proxy cắt các tunnel của mình và từ chối CONNECT mới trong 30 giây rồi tự mở
lại. Đây là socket reset cộng thời gian không thể CONNECT, không phải mô phỏng
packet blackhole hay mọi dạng mạng half-open.

Phải có bằng chứng transport phục hồi, chuỗi tin đủ/không trùng và ACK E2EE mới
sau phục hồi. Report phân biệt socket tự reconnect với watchdog tạo process
mới; RPC gửi thành công không thay được xác nhận từ peer. Evidence không chứa
chat ID, tên file gốc, nội dung chat hoặc khóa media. Timeout/cancellation phải
dừng đúng child và đóng proxy trước khi kết luận cleanup đạt.
Đọc cả `report.json` của worker và `controller.json` của parent; chỉ báo đạt
khi acceptance của cả hai đều true. Worker hoàn tất không tự chứng minh proxy
đã shutdown sạch. Lệnh `--help` liệt kê timeout của từng phase; output phải mới.
Theo dõi `report.json` để lấy challenge khi `status=cold_restart_ready`; log
worker nằm trong output directory. Hai ACK text/media vẫn được gửi trong
Instagram Direct. Khi bot hướng dẫn, gửi mã `net-ready-...`, rồi gửi riêng năm tin
`netseq-...-1` đến `netseq-...-5`, cách nhau khoảng 10 giây. Cuối cùng gửi
`net-ok-...` chỉ xuất hiện trong reply E2EE sau phục hồi.

Report có `outcome` riêng: `running`, `passed`, `inconclusive`, `failed` hoặc
`cancelled`. `inconclusive` chỉ dành cho trường hợp hết hạn chờ bằng chứng từ
peer. Lỗi thực thi, transport, queue drop hoặc dọn tài nguyên vẫn là lỗi,
không được ghi thành thiếu ACK.
`phase`, `reason_code`, `missing_evidence` và `waiting_for` dùng tập giá trị cố
định để chỉ đúng bước đang chờ, không sao chép nội dung chat hoặc lỗi provider.
Controller kiểm tra kết quả worker, exit code và việc dọn tài nguyên của chính
nó. Thiếu bằng chứng không được tính là đạt.

### Diễn tập recovery hoàn toàn offline

```powershell
python -m pytest tests/test_recovery_offline_integration.py -q
```

Bài này chạy controller, subprocess worker và CONNECT proxy thật với hai
stream localhost. Chỉ session, peer và bridge RPC là fixture giả; payload/ACK
giả vẫn phải đi qua tunnel. Test đối chiếu outage, từ chối CONNECT khi bị cắt,
reconnect, timeout/cancellation, report worker/controller và cleanup process,
socket, device lease. Không mock `Popen` hoặc hành vi proxy trong bài tích hợp.

Config/device chỉ là dữ liệu tổng hợp trong thư mục test tạm; không dùng cookie,
device hoặc bridge live đang có của người dùng. Mọi kết nối đều là loopback,
không thay proxy Windows, firewall hay adapter. Report diễn tập được đánh dấu
`evidence_scope=offline_simulation`, không được dùng làm bằng chứng E2EE thật
hoặc đưa ngược vào gate live. Bài này kiểm driver/protocol giả và wiring local,
không kiểm mật mã Instagram Direct hay khả năng chịu lỗi của provider.

---

## 21. <a id="21-faq-và-troubleshooting"></a>🩺 FAQ và troubleshooting

### `dataGetHome()` trả `None`

Kiểm tra:

1. Cookie có `sessionid`, `ds_user_id`, `csrftoken` và chưa hết hạn.
2. Tài khoản không bị checkpoint.
3. Mạng/proxy truy cập được `https://www.instagram.com/`.
4. Instagram có còn trả các token homepage mà parser cần hay không.

Không in cookie để debug. Chỉ log danh sách tên cookie hoặc tên field thiếu.

### `RuntimeWarning: coroutine was never awaited`

Một hàm async đã bị gọi như sync:

```python
listener.connect_mqtt()  # Sai nếu không await hoặc create_task
```

Sửa:

```python
task = asyncio.create_task(listener.connect_mqtt())
```

Không truyền coroutine trực tiếp làm target của `threading.Thread`.

### `'coroutine' object has no attribute 'get'`

Kết quả coroutine chưa được await:

```python
info = bridge.call("connect")
user = info.get("user")
```

Sửa:

```python
info = await bridge.call("connect")
user = info.get("user", {})
```

Code blocking nội bộ phải gọi `call_blocking()`, không gọi async method rồi đọc như dict.

### Upload trả `metadata: {"0": null}`

Instagram không trả attachment metadata. Kiểm tra session, file, MIME, endpoint và response error. Bật `include_error=True` để nhận excerpt có giới hạn. Không lấy `uploadID` làm `attachmentID`.

### Listener E2EE không nhận command

Kiểm tra:

1. Callback đã đăng ký trước khi start listener.
2. `wait_until_connected(..., require_e2ee=True)` trả `True`.
3. Ứng dụng xử lý cả `e2eeMessage` và `message`.
4. Callback đã chuyển event về event loop bằng `call_soon_threadsafe`.
5. Bot không bỏ nhầm message vì self-ID, prefix hoặc dedupe.
6. `listener_task` chưa kết thúc với exception.

### Bridge binary không tìm thấy

Build từ source:

```bash
git submodule update --init --recursive bridge-e2ee/meta
cd bridge-e2ee
go mod download
mkdir -p ../build
go build -o ../build/igchat-bridge-e2ee .
```

Trên Windows thêm `.exe`. Hoặc set `IGCHAT_E2EE_BIN` tới file tuyệt đối đã tồn tại.

### Bridge liên tục respawn

Watchdog dùng retry policy và báo `bridge_fatal` khi hết budget đã cấu hình hoặc gặp lỗi không thể tự phục hồi. Đọc `connection_status` trước: `auth_required` cần cập nhật phiên, `protocol` cần build bridge đúng source, còn `device_state_lost` nghĩa là state memory-only không còn sau process crash. Không start thêm listener để che lỗi; chờ task cũ dừng hẳn trước.

### Login credential báo code `-1`

Đây thường là response transport/schema không khớp hoặc Instagram không trả error code chuẩn. Đọc description đã sanitize, kiểm tra override env và thử cookie session. Không suy diễn `-1` thành sai password nếu chưa có evidence từ response.

### `All Thread Data: 0` hoặc lỗi index

Không index thẳng response GraphQL. Kiểm tra `result.get("error")`, `dataGet` và object batch `o0`. Instagram có thể trả error object thay vì danh sách thread.

### `Get Notifications: slice(None, 2, None)`

Code caller đang slice một dict như list. Kết quả notification là dict có key `NotificationResults`; lấy list trước:

```python
result = await _notification.func(data_igs)
items = result.get("NotificationResults", [])
print(items[:2])
```

### Có nên dùng API blocking không?

Chỉ tại entry point sync hoặc integration chưa có event loop. Trong coroutine, ưu tiên API async. Nếu phải gọi thư viện legacy không có wrapper, đặt boundary rõ ràng bằng `asyncio.to_thread()` và không chia sẻ object không thread-safe.

---

Chi tiết theo module:

- [`src/igchat_v2/_core/README.md`](src/igchat_v2/_core/README.md)
- [`src/igchat_v2/_features/README.md`](src/igchat_v2/_features/README.md)
- [`src/igchat_v2/_messaging/README.md`](src/igchat_v2/_messaging/README.md)
- [`bridge-e2ee/README.md`](bridge-e2ee/README.md)
