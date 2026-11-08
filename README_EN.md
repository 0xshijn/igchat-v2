<div align="center">

# IGChat-v2 - Open Source

### Async-first Python library for Instagram Direct & E2EE API

[![Status](https://img.shields.io/badge/status-active-22c55e)](https://github.com/0xshijn/igchat-v2)
[![PyPI](https://img.shields.io/pypi/v/igchat-v2?color=3775A9&logo=pypi&logoColor=white)](https://pypi.org/project/igchat-v2/)
[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Version](https://img.shields.io/badge/version-2.3.4-blue)](https://github.com/0xshijn/igchat-v2/releases)
[![Issues](https://img.shields.io/github/issues/0xshijn/igchat-v2?color=orange)](https://github.com/0xshijn/igchat-v2/issues)
[![License](https://img.shields.io/badge/license-See%20LICENSE-lightgrey)](LICENSE)

[🇻🇳 Tiếng Việt](README.md) · [📖 Documentation](DOCS.md) · [📦 PyPI](https://pypi.org/project/igchat-v2/) · [ 📊 Flowchart](FLOWCHART.md) · [🐛 Report bugs](https://github.com/0xshijn/igchat-v2/issues)

</div>

---

> [!IMPORTANT]
> Version 2.3.4 uses `async/await`. If you are upgrading from an older version, update your function calls using the examples below. To keep using the synchronous API, use [v2.1.4](https://github.com/0xshijn/igchat-v2/tree/v2.1.4).

> [!WARNING]
> This is not an official product of Meta / Instagram. For the official chatbot API, see the [Instagram Platform](https://developers.facebook.com/docs/instagram-platform/). `igchat-v2` uses personal Instagram accounts and session cookies, which carries risks for your session credentials and account. Consider those risks before using it.

---

## 👋 Introduction

I'm Phước Toàn (Shiin) (`0xshijn`), the author and maintainer of this project.

`igchat-v2` is a Python library for sending and receiving Instagram Direct messages through a personal Instagram account. It uses `async/await`, with a Go bridge for E2EE. The codebase was reorganized in v2.2.0 and has continued to receive fixes based on user reports.

Version 2.3.4 adds MQTT/E2EE reconnect support: network retries, separate
authentication failures, and connection-state callbacks.
See the [configuration guide](DOCS.md#tự-nối-lại).
E2EE requires the 2.3.4 bridge; the wrapper rejects older binaries without the reconnect contract.

Thanks to everyone who has shared ideas and reported bugs. This is an unofficial API, so features can break when Instagram changes. If you run into a problem, open an issue on [GitHub](https://github.com/0xshijn/igchat-v2/issues) with reproduction steps and redacted logs, or reach me on [Telegram](https://t.me/ShiinNoHacker).

---

## 📚 Table of Contents

- [Features](#features)
- [Architecture Overview](#architecture-overview)
- [Project Structure](#project-structure)
- [System Requirements](#system-requirements)
- [Installation](#installation)
- [Configuration](#configuration)
- [Quick Start](#quick-start)
- [Using the Async API](#using-the-async-api)
- [E2EE Listener](#e2ee-listener)
- [Sample Bot](#sample-bot)
- [Module Documentation](#module-documentation)
- [Quality Checks](#quality-checks)
- [License](#license)

---

## <a id="features"></a>✨ Features

The library uses a personal account's cookies or login credentials rather than the Page `access_token` used by the official chatbot API. It includes the following features:

### Authentication

- Log in with a username/password or session cookie (*).
- Reuse a session instead of logging in every time the program starts.

### Messaging

- Read messages from users and group chats (threads).
- Receive E2EE personal messages (Secret Conversations / Labyrinth) through the Go bridge.
- Send text, attachments, stickers, and user mentions.
- Search messages and conversations.
- Edit sent messages, react, unsend, and handle message requests.
- Change thread themes/backgrounds and manage 24-hour Instagram Notes.
- Receive events in real time for bot command handling.

### Threads & Groups

- Create groups, add admins, and change group names/emojis/nicknames.
- Create polls and fetch thread metadata.

### Instagram Features (`_features._instagram`)

- React and unreact to timeline posts ([`_reactionPost`](src/igchat_v2/_features/_instagram/README_EN.md#-spotlight-_reactionpostpy-post-reactions): Like, Love, Care, Haha, Wow, Sad, Angry, Undo).
- Create posts (`_createPost`), archive posts (`_archivePost`), and delete posts (`_deletePost`).
- Search users (`_search`), fetch profile info (`_get_user_info`), and manage notifications (`_notification`).
- Block/unblock (`_blocking`), unfollow/unfriend users (`_unFriend`), and manage Marketplace and Professional Mode.
- See the [Instagram Features Documentation](src/igchat_v2/_features/_instagram/README_EN.md) for usage details.

### Recently Updated

- The main APIs use `async/await`; some compatibility paths are still blocking.
- The E2EE bridge has a binary build and distribution workflow for Windows, Linux, and macOS.

> [!CAUTION]
> (*) Cookies and login credentials grant access to your account. Keep them out of source code, issues, and public logs.

---

## <a id="architecture-overview"></a>📂 Architecture Overview

The codebase has three layers. Core manages sessions and HTTP transport; feature and messaging modules reuse them rather than storing credentials in code.

| Layer | Path | Responsibility |
|---|---|---|
| Core | `src/igchat_v2/_core/` | HTTP transport, session, storage, login, and utilities |
| Features | `src/igchat_v2/_features/` | Instagram business features and thread administration |
| Messaging | `src/igchat_v2/_messaging/` | Send, listen, E2EE, attachment, reaction, theme, and notes |

```mermaid
flowchart LR
    A[Cookie or storage] --> B[dataGetHome]
    B --> C[dataIGS]
    C --> D[HTTP features]
    D --> E[httpx.AsyncClient]
    C --> F[MQTT listener]
    C --> G[Python E2EE wrapper]
    G <--> H[Go JSON-RPC bridge]
    H <--> I[Instagram Direct E2EE]
    F --> J[asyncio application]
    G --> J
```

See [FLOWCHART.md](FLOWCHART.md) for the full flow.

---

## <a id="project-structure"></a>🗂️ Project Structure

```text
igchat-v2/
├── src/
│   ├── main.py                       # Sample async bot using the E2EE listener
│   ├── config.example.json           # Configuration template safe to commit
│   ├── config.json                   # Local configuration, gitignored
│   ├── _core/
│   │   ├── _http.py                  # Shared sync/async httpx transport
│   │   ├── _session.py               # Cookie -> dataIGS
│   │   ├── _storage.py               # File/env session storage
│   │   ├── _instagramLogin.py        # Credential login and 2FA
│   │   ├── _utils.py                 # Form, parser, cookie, and ID helpers
│   │   └── README.md
│   ├── _features/
│   │   ├── _instagram/               # Account, profile, Marketplace
│   │   ├── _thread/                  # Thread and group administration
│   │   └── README.md
│   └── _messaging/
│       ├── _send.py                  # Send regular messages through HTTP
│       ├── _attachments.py           # Upload files
│       ├── _listening.py             # Regular MQTT listener
│       ├── _listening_e2ee.py        # E2EE listener and bridge process
│       ├── _bridge_actions.py        # Async actions through the bridge
│       ├── _send_e2ee.py             # Standalone compatibility sender
│       ├── _changeTheme.py
│       ├── _createNotes.py
│       ├── _editMessage.py
│       ├── _message_requests.py
│       ├── _reactions.py
│       ├── _unsend.py
│       └── README.md
├── bridge-e2ee/
│   ├── main.go                       # JSON-RPC dispatcher
│   ├── bridge/                       # Instagram Direct/E2EE operations
│   ├── meta/                         # mautrix-meta Git submodule
│   ├── go.mod
│   └── README.md
├── build/                            # Local bridge binary
├── tests/                            # Unit and async contract tests
├── DOCS.md                           # Full API guide
├── FLOWCHART.md                      # Runtime flow
├── mindmap-mermaid.md                # Codebase map
├── CHANGELOG.md
└── pyproject.toml
```

---

## <a id="system-requirements"></a>🔧 System Requirements

| Component | Minimum | Recommended | Notes |
|---|---|---|---|
| Python | 3.10 | 3.11 / 3.12 | Required |
| Go (toolchain) | 1.26.10 | 1.26.10+ | **Only required for E2EE** - used to build `igchat-bridge-e2ee` |
| Git | any | latest | Needed for `go mod tidy` to pull `mautrix/meta` |
| OS | Windows / Linux / macOS | - | - |
| RAM | 256 MB | 1 GB+ | The E2EE bridge uses about 80-150 MB while running |
| Network | Stable connection, not blocked from `instagram.com` and `edge-chat.instagram.com` | - | - |

Main Python dependencies in `pyproject.toml`:

```toml
dependencies = [
    "httpx>=0.27.0",
    "paho-mqtt>=1.6.1",
    "pyotp>=2.9.0",
    "requests>=2.32.0",
]
```

`httpx` handles HTTP for sessions and async features. Credential login and compatibility upload still use `requests` in blocking code.

---

## <a id="installation"></a>📦 Installation

> These steps install the project from source. The virtual environment in step 2 is optional; step 5 is required for the `src/main.py` sample bot or any E2EE usage.

### 1. Clone the source

```bash
git clone --recurse-submodules https://github.com/0xshijn/igchat-v2.git
cd igchat-v2
```

> Alternative: use `Code -> Download ZIP` on GitHub.

### 2. Create a virtual environment *(optional but recommended)*

```bash
python -m venv .venv
```

Activate the environment:

```bash
# Windows (PowerShell)
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate
```

### 3. Install Python dependencies

```bash
python -m pip install --upgrade pip
python -m pip install -e .
```

Quick check:

```bash
python -c "import igchat_v2; from igchat_v2._features._instagram import _unFriend; print('OK')"
```

### 4. Verify the installed packages

Check that the installed package exposes the public `igchat_v2` namespace. This applies to both editable installs and wheels:

```bash
python scripts/verify_distribution.py
```

You do not need `PYTHONPATH=src`, and imports must not use a `src.` prefix.

### 5. Build the E2EE bridge - required for the sample bot

You can skip this step if you only use HTTP APIs or the regular MQTT listener. The `src/main.py`, `_e2ee_listening_test.py`, and `_e2ee_send_test.py` entrypoints need the Go `igchat-bridge-e2ee` binary: if the bridge is not ready, they stop instead of falling back to Python MQTT.

#### 5.1. Install the Go toolchain

- Download it from: <https://go.dev/dl/> (Go >= 1.26.10).
- After installation, open a new terminal and check:

  ```bash
  go version
  ```

#### 5.2. Pull the `mautrix/meta` source

The repo declares `bridge-e2ee/meta` in `.gitmodules`. For a Git checkout, use the submodule:

```bash
git submodule update --init --recursive bridge-e2ee/meta
```

If you are building from a source copy without `.gitmodules`, clone it manually:

```bash
cd bridge-e2ee
git clone https://github.com/mautrix/meta.git ./meta
```

> `bridge-e2ee/go.mod` uses a `replace` directive pointing to `./meta`, so the path `bridge-e2ee/meta` must exist before `go mod tidy` / `go build`.

#### 5.3. Download dependencies & build

```bash
cd bridge-e2ee
go mod download

# Windows
go build -ldflags="-s -w" -o ../build/igchat-bridge-e2ee.exe .

# Linux / macOS
go build -ldflags="-s -w" -o ../build/igchat-bridge-e2ee .
```

The first build may take a few minutes and about 300 MB of Go module cache. After that, the binary is about 25-40 MB and is placed in `igchat-v2/build/`.

#### 5.4. Verify

```bash
cd ..
# Windows
python scripts/smoke_bridge_rpc.py .\build\igchat-bridge-e2ee.exe --expected-version 2.3.4
# Linux/macOS
python scripts/smoke_bridge_rpc.py ./build/igchat-bridge-e2ee --expected-version 2.3.4
```

If the binary is not in the default location, set the environment variable:

```bash
# Windows
$env:IGCHAT_E2EE_BIN = "C:\path\to\igchat-bridge-e2ee.exe"
# Linux/macOS
export IGCHAT_E2EE_BIN=/path/to/igchat-bridge-e2ee
```

More details: [`bridge-e2ee/README.md`](bridge-e2ee/README.md).

### 6. Configure cookies

Copy [`src/config.example.json`](src/config.example.json) to `src/config.json`, then paste your Instagram session cookie into the `cookies` field. See the [Configuration](#️-configuration) section for details.

### 7. Smoke test

```bash
python src/main.py
```

When the console prints `E2EE listener đã sẵn sàng`, the bot has connected its listener. This does not yet prove that sending and receiving messages works. The sample bot does not print account IDs, cookies, or `last_seq_id` metadata.

---

## <a id="configuration"></a>⚙️ Configuration

Create a local configuration file from the template:

```powershell
Copy-Item src\config.example.json src\config.json
```

```bash
cp src/config.example.json src/config.json
```

Example:

```json
{
  "botName": "igchat-v2 demo bot",
  "prefix": "/",
  "cookies": "sessionid=...; ds_user_id=...; csrftoken=...;",
  "admins": [
    "1000xxxxxxxxxx"
  ],
  "log_message_content": false,
  "debug_errors": false,
  "version": "0.0.1"
}
```

| Key | Required | Meaning |
|---|---|---|
| `cookies` | Yes | Instagram session cookie as a string |
| `prefix` | No | Command prefix, defaults to `/` |
| `admins` | No | List of Instagram IDs / FBIDs allowed to use admin commands |
| `log_message_content` | No | Allow plaintext message logging; defaults to `false` for privacy |
| `debug_errors` | No | Print redacted bridge diagnostics; defaults to `false` |
| `botName` | No | Config metadata, currently unused by the sample bot |
| `version` | No | Config metadata, currently unused by the sample bot |

`src/config.json` is gitignored, and the sample bot restricts it to mode `0600`
on POSIX or a current-user/SYSTEM ACL on Windows. Do not store real cookies in
`config.example.json`, and only enable the two logging options while debugging
in a controlled environment.

---

## <a id="quick-start"></a>🚀 Quick Start

After configuring cookies and the bridge:

```bash
python src/main.py
```

The bot waits until both the regular connection and E2EE connection are ready before processing commands. Sample commands:

```text
/ping
/help
/id
/echo hello
/search Minh
/unsend
```

`/unsend` only recalls the latest E2EE message sent by the bot in the current chat. Regular chats without `chatJid` are rejected with a clear message.

---

## <a id="using-the-async-api"></a>⚡ Using the Async API

### Create a session from cookies

```python
import asyncio

from igchat_v2._core._session import dataGetHome


async def main() -> None:
    data_igs = await dataGetHome("sessionid=...; ds_user_id=...; csrftoken=...;")
    if data_igs is None:
        raise RuntimeError("Cookie expired or Instagram changed the HTML token flow.")
    print(data_igs["IGSID"])


asyncio.run(main())
```

In FastAPI, Jupyter, or any bot framework that already has an event loop, call `await dataGetHome(...)` directly. Do not nest another `asyncio.run()`.

### Send a regular message

```python
from igchat_v2._messaging._send import api as SendAPI

sender = SendAPI()
result = await sender.send(
    data_igs,
    "Hello from igchat-v2",
    threadID="100012345678"
)
if result.get("error"):
    raise RuntimeError(result["payload"]["error-description"])
```

`threadID` can be a single ID or a list of IDs when `typeChat="user"`. When sending an attachment, `typeAttachment` and `attachmentID` must be passed together.

### Reuse HTTP connections

```python
import asyncio
import httpx

from igchat_v2._features._instagram import _notification, _search

async with httpx.AsyncClient(timeout=30) as client:
    notifications, users = await asyncio.gather(
        _notification.func(data_igs, client=client),
        _search.func(data_igs, "Minh", client=client),
    )
```

If you create the client, close it when you are done. Do not reuse a closed client or pass a sync `httpx.Client` to the `client=` parameter of an async API.

### Upload an attachment

```python
from igchat_v2._messaging import _attachments
from igchat_v2._messaging._send import api as SendAPI

uploaded = await _attachments.func("photo.jpg", data_igs, include_error=True)
if not uploaded or not uploaded.get("attachmentID"):
    raise RuntimeError(f"Upload failed: {uploaded}")

await SendAPI().send(
    data_igs,
    "Attached image (file path)",
    threadID="100012345678",
    typeAttachment=uploaded["typeAttachment"],
    attachmentID=uploaded["attachmentID"],
)
```

### Regular MQTT listener

```python
import asyncio

from igchat_v2._messaging._listening import listeningEvent

listener = listeningEvent(data_igs, message_queue_maxsize=1000)
listener_task = asyncio.create_task(listener.connect_mqtt())
try:
    while True:
        event = await listener.get_message(timeout=30)
        if event is not None:
            print(event)
finally:
    await listener.disconnect()
    await listener_task
```

Read each event through `get_message()`. `bodyResults` keeps a snapshot for compatibility with older code, so it can miss events when messages arrive in bursts.

---

## <a id="e2ee-listener"></a>🔐 E2EE Listener

`listeningE2EEEvent` starts the Go bridge and exchanges JSON-RPC through stdin/stdout. Bridge callbacks run outside the event loop. In an asyncio application, use `loop.call_soon_threadsafe` to put events into an `asyncio.Queue`, as shown below.

```python
import asyncio

from igchat_v2._messaging._listening_e2ee import listeningE2EEEvent


async def run_listener(data_igs: dict) -> None:
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
    listener_task = asyncio.create_task(listener.connect_mqtt())

    try:
        ready = await asyncio.to_thread(
            listener.wait_until_connected,
            listener.startup_timeout,
            require_e2ee=True,
        )
        if not ready:
            raise TimeoutError("E2EE handshake did not complete.")

        await listener.send_e2ee_message(
            "100012345678@msgr",
            "Hello E2EE",
        )

        while True:
            event = await events.get()
            if event.get("type") in {"e2eeMessage", "message"}:
                print(event["data"])
    finally:
        listener.stop()
        await listener_task
```

Main events:

| Type | Notable data | Meaning |
|---|---|---|
| `ready` | `isNewSession` | Bridge client has been created |
| `e2eeConnected` | handshake status | Signal/Labyrinth is ready |
| `e2eeMessage` | `chatJid`, `senderJid`, `id`, `text` | Decrypted personal message |
| `message` | `threadId`, `senderId`, `id`, `text` | Regular message |
| `error` | bridge/transport error | Should be logged and monitored |
| `bridge_fatal` | retry count | Watchdog gave up |

`BridgeActions` provides edit, unsend, typing, mark-read, image/audio sending, and media download actions. See the [messaging documentation](src/igchat_v2/_messaging/README.md) for usage details.

---

## <a id="sample-bot"></a>🤖 Sample Bot

[`src/main.py`](src/main.py) brings these pieces together in an async bot:

1. Read config with `FileSessionStorage`.
2. Call `await dataGetHome(...)` and validate required fields.
3. Open one shared `httpx.AsyncClient` for HTTP commands.
4. Start `listeningE2EEEvent.connect_mqtt()` as a task.
5. Move bridge callbacks into a thread-safe `asyncio.Queue`.
6. Parse commands and ignore messages sent by the bot itself.
7. Reply through E2EE when `chatJid` exists, or send a regular message when only `threadId` exists.
8. Stop the bridge, await the task, and close the HTTP client during shutdown.

The bot queue holds up to 1000 events and drops the oldest event when full. This bounds memory use during bursts, but events can be lost; it is not a delivery guarantee.

### Built-in commands in `SimpleBot` (`src/main.py`)

| Command | Description |
|---|---|
| `/hi` | Greet and check bot operational status |
| `/ping` | Measure response latency (ms) |
| `/help` | Show full list of commands |
| `/id` | Show `chatJid`, `threadID`, `userID`, `messageID` |
| `/info [id/user]` | View Instagram account info by ID or `@username` |
| `/profile <@user/id>` | View detailed Instagram profile (Bio, Followers/Following, HD Avatar, latest posts) |
| `/story <@user/id>` | View and get direct download links for active 24h Stories |
| `/follow` / `/unfollow <@user/id>` | Follow or unfollow an Instagram user (Admin only) |
| `/bio <text>` | Update the bot's Instagram Bio (Admin only) |
| `/inbox` | List recent conversations in inbox |
| `/thread` / `/history [limit]` | View conversation details, participants, and message history |
| `/deletethread [spam]` | Delete current conversation (or mark as Spam, Admin only) |
| `/requests` / `/accept <id>` | View and approve Message Requests |
| `/rename <name>` | Rename Instagram group chat |
| `/groupavatar <url\|clear>` | Change or remove Instagram group avatar |
| `/tagall` / `/everyone [text]` | Tag `@everyone` and all members in group chat |
| `/mute` / `/unmute` | Mute / unmute conversation notifications |
| `/pinthread` / `/unpinthread` | Pin / unpin conversation to top of inbox |
| `/image <url>` | Download image/media from URL and send directly to chat |
| `/voice <url>` | Send Instagram Voice Note from audio URL |
| `/media` | Get direct CDN link for latest image/video/voice/reel in chat |
| `/dl <url/shortcode>` | Extract info & get original download link for Instagram Post/Reel |
| `/autodl [on\|off]` | Toggle auto-download when Instagram post/Reel link is received |
| `/like` / `/unlike <url/code>` | Like or unlike Instagram Post/Reel |
| `/comment <url/code> <text>` | Post comment directly on Instagram Post/Reel |
| `/save` / `/unsave <url/code>` | Save or unsave Instagram Post/Reel to collection |
| `/forward <threadID> [text]` | Forward replied message to another conversation |
| `/creategroup <id1,id2> [name]` | Create new Instagram group chat |
| `/add <id>` / `/kick <id>` | Add or remove member from group chat |
| `/promote <id>` / `/demote <id>` | Promote or demote group Admin |
| `/leave` | Make bot leave group chat (Admin only) |
| `/block <id>` / `/unblock <id>` | Block or unblock Instagram user (Admin only) |
| `/echo <text>` | Echo text message |
| `/react [emoji]` | React to message with emoji |
| `/edit <text>` | Edit latest bot message |
| `/pin` / `/unpin` | Pin / unpin message |
| `/search <keyword>` | Search Instagram users |
| `/unsend` | Recall latest bot message (Admin only) |
| `/antiunsend [on\|off]` | Toggle anti-unsend & real-time message edit detection |

---

## <a id="module-documentation"></a>📖 Module Documentation

| Documentation | Content |
|---|---|
| [DOCS.md](DOCS.md) | Full API and workflow guide |
| [Core](src/igchat_v2/_core/README.md) | Session, HTTP, storage, and login |
| [Features](src/igchat_v2/_features/README.md) | Instagram features and threads |
| [Messaging](src/igchat_v2/_messaging/README.md) | Send, listener, attachment, and E2EE |
| [Bridge E2EE](bridge-e2ee/README.md) | Build, binary discovery, and JSON-RPC |
| [Flowchart](FLOWCHART.md) | Session, HTTP, MQTT, E2EE, and shutdown flow |
| [Mindmap](mindmap-mermaid.md) | Codebase-wide module map |

---

## <a id="quality-checks"></a>✅ Quality Checks

Run the test command used by CI:

```bash
pytest tests/ -v --tb=short
```

Before committing, run these checks as well:

```bash
python -m compileall -q src tests scripts
ruff check src tests scripts
black --check src tests scripts
mypy
python -m build --wheel
python scripts/verify_distribution.py dist/igchat_v2-2.3.4-py3-none-any.whl
git diff --check
```

CI installs the wheel and editable project into separate clean virtual environments before running the import smoke test.

For the bridge:

```bash
cd bridge-e2ee
go test ./...
go vet ./...
```

Save Vietnamese documentation as UTF-8. If PowerShell displays strange characters, inspect the codepoints or read the file with `encoding="utf-8"` before editing it; a terminal display problem does not necessarily mean the file is corrupted.

---

## <a id="license"></a>📜 License

This project is distributed under the terms in [LICENSE](LICENSE). The bridge includes upstream components with separate licenses; review [bridge-e2ee/README.md](bridge-e2ee/README.md) before distributing binaries.

<div align="center">

[Phước Toàn (Shiin)](https://github.com/0xshijn) | [Telegram](https://t.me/ShiinNoHacker)

</div>
