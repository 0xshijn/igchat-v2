# igchat-bridge (v3.0.0)

High-performance Go companion bridge for `igchat-v2`, providing a real-time Instagram Direct gateway over stdin/stdout line-delimited JSON-RPC 2.0.

Built on top of `go.mau.fi/mautrix-meta/pkg/instameow` using Instagram Direct's DGW WebSocket transport, Slide GraphQL, and MQTT bypass mechanisms. Zero legacy Facebook Comet, zero Messenger, and zero experimental E2EE layers.

---

## Architecture Overview

```
+-------------------------------------------------------------+
|                     Python Layer (igchat_v2)                |
|           DirectListener  <--->  BridgeProcess              |
+------------------------------+------------------------------+
                               | stdin / stdout (JSON-RPC)
                               v
+-------------------------------------------------------------+
|                    igchat-bridge.exe (Go)                   |
|  - JSON-RPC Dispatcher       - Session Management           |
|  - instameow DGW Client      - SSRF Guard & Media Pipe      |
|  - Structured Log Redactor   - State & Health Monitor       |
+------------------------------+------------------------------+
                               | TLS / WebSocket / HTTPS
                               v
              Instagram Direct Infrastructure (Meta)
```

1. **Protocol Transport**: stdin/stdout JSON-RPC 2.0 with line-delimited envelopes (`{"jsonrpc":"2.0","id":...,"method":...,"params":...}`).
2. **Instagram Direct Client**: Driven by `instameow` for native Direct messaging, presence notifications, typing indicators, and thread operations.
3. **Log Redaction**: Zero credential leakage (`sessionid`, tokens, auth cookies, and private media signatures are automatically redacted from stderr logs).
4. **Security Hardening**:
   - SSRF protection: media downloads restrict destination IPs, blocking loopback, link-local, and RFC 1918 private addresses.
   - Atomic permissions: secure session persistence restricted to the local user process (POSIX `0600` / Windows token ACLs).

---

## JSON-RPC Method Reference

| Method | Parameters | Description |
|---|---|---|
| `ping` | `{}` | Returns `{"pong": true, "version": "3.0.0"}` |
| `health` | `{}` | Returns process health, uptime, and memory statistics |
| `status` | `{}` | Returns current IG connection state (`connected`, `disconnected`, `connecting`) |
| `connect` | `{"cookies": "...", "proxy": "..."}` | Authenticates session and initiates DGW WebSocket connection |
| `disconnect` | `{}` | Gracefully terminates WebSocket and clears active connection |
| `send_message` | `{"thread_id": "...", "text": "...", "reply_to": "..."}` | Sends a direct message with optional reply quote |
| `edit_message` | `{"thread_id": "...", "message_id": "...", "text": "..."}` | Edits an existing message within the edit window |
| `unsend_message` | `{"thread_id": "...", "message_id": "..."}` | Recalls/unsends a sent message |
| `react_message` | `{"thread_id": "...", "message_id": "...", "emoji": "..."}` | Toggles emoji reaction on a message |
| `fetch_inbox` | `{"limit": 20, "cursor": "..."}` | Retrieves paginated inbox threads |
| `fetch_thread` | `{"thread_id": "...", "limit": 20}` | Retrieves detailed thread metadata and recent messages |
| `create_group` | `{"recipient_ids": ["..."], "title": "..."}` | Creates a new group thread |
| `set_title` | `{"thread_id": "...", "title": "..."}` | Updates thread title |
| `add_participants` | `{"thread_id": "...", "user_ids": ["..."]}` | Adds users to group thread |
| `remove_participant`| `{"thread_id": "...", "user_id": "..."}` | Removes user from group thread |
| `leave_thread` | `{"thread_id": "..."}` | Leaves group conversation |
| `set_theme` | `{"thread_id": "...", "theme_id": "..."}` | Updates Direct thread visual theme |
| `set_emoji` | `{"thread_id": "...", "emoji": "..."}` | Updates thread custom emoji |
| `send_typing` | `{"thread_id": "...", "is_typing": true}` | Dispatches real-time typing indicator |
| `mark_read` | `{"thread_id": "...", "message_id": "..."}` | Acknowledges receipt and marks thread read |
| `upload_media` | `{"url": "...", "mime_type": "...", "thread_id": "..."}` | SSRF-checked media upload pipeline |

---

## Building from Source

### Prerequisites

- Go 1.23+ (or Go 1.24+ recommended)
- Git with submodule support (`git submodule update --init --recursive`)

### Compilation Commands

```bash
# Enter bridge directory
cd bridge

# Run test suite
go test -v ./...

# Run static analysis
go vet ./...

# Compile trimmed release binary to build/
go build -trimpath -ldflags="-s -w -X main.bridgeVersion=3.0.0" -o ../build/igchat-bridge.exe .
```

On Linux or macOS:

```bash
go build -trimpath -ldflags="-s -w -X main.bridgeVersion=3.0.0" -o ../build/igchat-bridge .
```

---

## License

GPL-3.0-or-later — See [LICENSE](../LICENSE) for details.

