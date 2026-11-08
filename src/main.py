"""Bot mẫu async-first, bắt buộc cài Go E2EE bridge.

Bot này không tự hạ cấp hoặc fallback sang Python MQTT khi bridge/E2EE lỗi.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import re
import sys
import time
import traceback
from collections import deque
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from _core._console import configure_utf8_console
from _core._permissions import create_private_json_file, set_private_file_permissions
from _core._session import dataGetHome
from _core._storage import FileSessionStorage
from _features._instagram import (
    _archivePost,
    _changeBio,
    _createPost,
    _deletePost,
    _get_user_info,
    _notification,
    _reactionPost,
    _search,
    _unFriend,
)
from _messaging import _createNotes
from _messaging._bridge_actions import BridgeActions
from _messaging._listening_e2ee import (
    DELIVERY_STATUS_UNKNOWN,
    _format_exception_chain,
    _redact_bridge_text,
    listeningE2EEEvent,
)

HERE = Path(__file__).resolve().parent
CONFIG_PATH = HERE / "config.json"
Handler = Callable[[dict[str, Any], str], Awaitable[None]]
DEFAULT_HTTP_TIMEOUT = 30.0
EVENT_QUEUE_MAXSIZE = 1000
RECENT_MESSAGE_IDS_MAXSIZE = 4096
CACHED_MESSAGES_MAXSIZE = 1024
SEARCH_QUERY_MIN_LENGTH = 2
SEARCH_QUERY_MAX_LENGTH = 100
SEARCH_RATE_WINDOW_SECONDS = 60.0
SEARCH_PER_SENDER_LIMIT = 3
SEARCH_GLOBAL_LIMIT = 20
MESSAGE_EVENT_TYPES = frozenset({"message", "e2eeMessage"})
META_MESSAGE_EVENT_TYPES = frozenset({"messageUnsend", "messageEdit"})
CONTROL_EVENT_TYPES = frozenset(
    {
        "ready",
        "e2eeConnected",
        "reconnected",
        "disconnected",
        "closed",
        "error",
    }
)
FORWARDED_EVENT_TYPES = (
    MESSAGE_EVENT_TYPES | META_MESSAGE_EVENT_TYPES | CONTROL_EVENT_TYPES
)
_IG_MEDIA_URL_RE = re.compile(
    r"https?://(?:www\.)?instagram\.com/(?:p|reel|reels|tv)/[A-Za-z0-9_-]+/?"
)

_create_private_config = create_private_json_file
_set_private_file_permissions = set_private_file_permissions


class _SearchRateLimiter:
    """Sliding-window quota for the sample bot's authenticated search API."""

    def __init__(
        self,
        *,
        per_sender_limit: int,
        global_limit: int,
        window_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if per_sender_limit <= 0 or global_limit <= 0 or window_seconds <= 0:
            raise ValueError("Giới hạn /search phải lớn hơn 0.")
        self._per_sender_limit = per_sender_limit
        self._global_limit = global_limit
        self._window_seconds = window_seconds
        self._clock = clock
        self._global_requests: deque[float] = deque()
        self._sender_requests: dict[str, deque[float]] = {}

    @staticmethod
    def _prune(requests: deque[float], cutoff: float) -> None:
        while requests and requests[0] <= cutoff:
            requests.popleft()

    def check(self, sender_id: str) -> str | None:
        """Reserve one request, or return the quota scope that rejected it."""
        now = self._clock()
        cutoff = now - self._window_seconds
        self._prune(self._global_requests, cutoff)

        for known_sender, requests in list(self._sender_requests.items()):
            self._prune(requests, cutoff)
            if not requests:
                self._sender_requests.pop(known_sender, None)

        sender_requests = self._sender_requests.get(sender_id)
        if (
            sender_requests is not None
            and len(sender_requests) >= self._per_sender_limit
        ):
            return "sender"
        if len(self._global_requests) >= self._global_limit:
            return "global"

        if sender_requests is None:
            sender_requests = deque()
            self._sender_requests[sender_id] = sender_requests
        sender_requests.append(now)
        self._global_requests.append(now)
        return None


def load_config() -> dict[str, Any]:
    """Đọc config và tạo template an toàn nếu chưa tồn tại."""
    if not CONFIG_PATH.exists():
        template = {
            "cookies": "PASTE_YOUR_INSTAGRAM_COOKIE_HERE",
            "prefix": "/",
            "admins": [],
            "log_message_content": False,
            "debug_errors": False,
        }
        if _create_private_config(CONFIG_PATH, template):
            raise RuntimeError(
                f"Đã tạo template riêng tư tại {CONFIG_PATH}. Điền cookies rồi chạy lại."
            )

    _set_private_file_permissions(CONFIG_PATH)
    with CONFIG_PATH.open("r", encoding="utf-8") as file_handle:
        config = json.load(file_handle)
    config.setdefault("prefix", "/")
    config.setdefault("admins", [])
    config.setdefault("log_message_content", False)
    config.setdefault("debug_errors", False)
    if not isinstance(config["prefix"], str) or not config["prefix"]:
        raise ValueError("config.prefix phải là chuỗi không rỗng.")
    if not isinstance(config["admins"], list):
        raise ValueError("config.admins phải là một danh sách ID.")
    if not isinstance(config["log_message_content"], bool):
        raise ValueError("config.log_message_content phải là true hoặc false.")
    if not isinstance(config["debug_errors"], bool):
        raise ValueError("config.debug_errors phải là true hoặc false.")
    return config


def is_valid_dataigs(dataIGS: object) -> bool:
    if not isinstance(dataIGS, dict):
        return False
    igs_id = str(dataIGS.get("IGSID") or "").strip()
    required = ("fb_dtsg", "jazoest", "sessionID", "clientRevision", "cookieIGS")
    return igs_id.isdigit() and all(
        str(dataIGS.get(field) or "").strip() for field in required
    )


def log(tag: str, message: str) -> None:
    line = f"[{datetime.now():%H:%M:%S}] [{tag}] {message}"
    try:
        print(line)
    except UnicodeEncodeError:
        encoding = sys.stdout.encoding or "utf-8"
        safe_line = line.encode(encoding, errors="backslashreplace").decode(
            encoding, errors="replace"
        )
        print(safe_line)


class SimpleBot:
    def __init__(
        self,
        dataIGS: dict[str, Any],
        *,
        prefix: str = "/",
        admins: list[Any] | None = None,
        log_message_content: bool = False,
        debug_errors: bool = False,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.dataIGS = dataIGS
        self.prefix = prefix
        self.admins = {str(admin_id) for admin_id in admins or []}
        self.log_message_content = log_message_content
        self.debug_errors = debug_errors
        self.http_client = http_client
        self.listener = listeningE2EEEvent(dataIGS, debug_errors=debug_errors)
        self._event_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(
            maxsize=EVENT_QUEUE_MAXSIZE
        )
        self._recent_message_ids: deque[str] = deque()
        self._recent_message_id_set: set[str] = set()
        self._dropped_message_events = 0
        self._last_bot_message: dict[str, tuple[str, str]] = {}
        self._last_attachments: dict[str, list[dict[str, Any]]] = {}
        self._bot_sent_message_ids: set[str] = set()
        self._cached_messages: dict[str, dict[str, Any]] = {}
        self._cached_message_order: deque[str] = deque()
        self._anti_unsend_threads: set[str] = set()
        self._autodl_threads: set[str] = set()
        self._thread_cursors: dict[int, str] = {}
        self._search_rate_limiter = _SearchRateLimiter(
            per_sender_limit=SEARCH_PER_SENDER_LIMIT,
            global_limit=SEARCH_GLOBAL_LIMIT,
            window_seconds=SEARCH_RATE_WINDOW_SECONDS,
        )
        self._handlers: dict[str, Handler] = {
            "hi": self._cmd_hi,
            "ping": self._cmd_ping,
            "help": self._cmd_help,
            "id": self._cmd_id,
            "info": self._cmd_info,
            "profile": self._cmd_profile,
            "story": self._cmd_story,
            "follow": self._cmd_follow,
            "unfollow": self._cmd_unfollow,
            "bio": self._cmd_bio,
            "inbox": self._cmd_inbox,
            "thread": self._cmd_thread,
            "history": self._cmd_history,
            "deletethread": self._cmd_deletethread,
            "requests": self._cmd_requests,
            "accept": self._cmd_accept,
            "rename": self._cmd_rename,
            "groupavatar": self._cmd_groupavatar,
            "tagall": self._cmd_tagall,
            "everyone": self._cmd_tagall,
            "mute": self._cmd_mute,
            "unmute": self._cmd_unmute,
            "pinthread": self._cmd_pinthread,
            "unpinthread": self._cmd_unpinthread,
            "image": self._cmd_image,
            "voice": self._cmd_voice,
            "media": self._cmd_media,
            "dl": self._cmd_dl,
            "autodl": self._cmd_autodl,
            "like": self._cmd_like,
            "unlike": self._cmd_unlike,
            "comment": self._cmd_comment,
            "save": self._cmd_save,
            "unsave": self._cmd_unsave,
            "forward": self._cmd_forward,
            "creategroup": self._cmd_creategroup,
            "add": self._cmd_add,
            "kick": self._cmd_kick,
            "promote": self._cmd_promote,
            "demote": self._cmd_demote,
            "leave": self._cmd_leave,
            "block": self._cmd_block,
            "unblock": self._cmd_unblock,
            "echo": self._cmd_echo,
            "react": self._cmd_react,
            "edit": self._cmd_edit,
            "pin": self._cmd_pin,
            "unpin": self._cmd_unpin,
            "search": self._cmd_search,
            "unsend": self._cmd_unsend,
            "antiunsend": self._cmd_antiunsend,
            "note": self._cmd_note,
            "notemusic": self._cmd_notemusic,
            "musicnote": self._cmd_notemusic,
            "notif": self._cmd_notif,
            "post": self._cmd_post,
            "upstory": self._cmd_upstory,
            "more": self._cmd_more,
        }

    async def run(self) -> None:
        log("bot", "Đang khởi động transport E2EE bắt buộc.")
        loop = asyncio.get_running_loop()
        self.listener.on_message(
            lambda event: self._forward_listener_event(loop, event)
        )
        status_callback = getattr(self.listener, "set_connection_state_callback", None)
        if callable(status_callback):
            status_callback(self._log_connection_status)
        listener_task = asyncio.create_task(
            self.listener.connect_mqtt(), name="igschat-e2ee-listener"
        )
        try:
            while True:
                ready = await asyncio.to_thread(
                    self.listener.wait_until_connected,
                    self.listener.startup_timeout,
                    require_e2ee=True,
                )
                if ready:
                    break
                if listener_task.done():
                    listener_task.result()
                    raise RuntimeError("E2EE listener đã dừng khi đang khởi động.")
                if getattr(self.listener, "connection_state", None) == "reconnecting":
                    log("bot", "Mạng chưa sẵn sàng; listener đang tự nối lại.")
                    continue
                raise RuntimeError("E2EE listener chưa sẵn sàng trước timeout.")
            log("bot", "E2EE listener đã sẵn sàng. Nhấn Ctrl+C để thoát.")
            while True:
                if listener_task.done():
                    listener_task.result()
                    raise RuntimeError("E2EE listener đã dừng ngoài dự kiến.")
                event = await self._get_event(timeout=1.0)
                message = self._message_from_event(event) if event else None
                if message is not None:
                    await self._dispatch(message)
        finally:
            await self._shutdown_listener(listener_task)

    def run_blocking(self) -> None:
        """Wrapper CLI tương thích; trong ứng dụng async hãy await run()."""
        asyncio.run(self.run())

    @staticmethod
    def _log_connection_status(status: dict[str, Any]) -> None:
        state = status.get("state")
        if isinstance(state, str) and state in {
            "starting",
            "connected",
            "reconnecting",
            "auth_required",
            "fatal",
            "stopped",
        }:
            log("transport", state)

    async def _shutdown_listener(self, listener_task: asyncio.Task[None]) -> None:
        """Dừng bridge E2EE và chờ task listener thoát gọn."""
        await asyncio.to_thread(self.listener.stop)
        try:
            await asyncio.wait_for(asyncio.shield(listener_task), timeout=5)
        except asyncio.TimeoutError:
            listener_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await listener_task
        except asyncio.CancelledError:
            if listener_task.cancelled():
                return
            if not listener_task.done():
                listener_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await listener_task
            raise
        except Exception:
            # Cleanup không được che mất lỗi startup/runtime gốc của run().
            pass

    def _forward_listener_event(
        self, loop: asyncio.AbstractEventLoop, event: dict[str, Any]
    ) -> None:
        """Lọc event ngay trên listener thread trước khi chạm asyncio queue."""
        if not isinstance(event, dict):
            return
        if event.get("type") not in FORWARDED_EVENT_TYPES:
            return
        try:
            loop.call_soon_threadsafe(self._queue_event, event)
        except RuntimeError:
            if self.debug_errors:
                log("queue", "Bỏ qua event vì asyncio loop đã đóng.")

    def _queue_event(self, event: dict[str, Any]) -> None:
        event_type = event.get("type")
        if event_type in META_MESSAGE_EVENT_TYPES:
            if not self._anti_unsend_threads:
                return
        elif event_type not in MESSAGE_EVENT_TYPES:
            # Control event được xử lý ngay trên event loop, còn
            # typing/receipt/reaction/raw bị loại trước queue message.
            if event_type in CONTROL_EVENT_TYPES:
                self._message_from_event(event)
            return
        try:
            self._event_queue.put_nowait(event)
        except asyncio.QueueFull:
            with contextlib.suppress(asyncio.QueueEmpty):
                self._event_queue.get_nowait()
            self._event_queue.put_nowait(event)
            self._dropped_message_events += 1
            # Log theo lũy thừa hai để có telemetry mà không tự tạo log storm.
            if self._dropped_message_events & (self._dropped_message_events - 1) == 0:
                log(
                    "queue",
                    "Queue message đầy; đã loại "
                    f"{self._dropped_message_events} event cũ (không log nội dung).",
                )

    def _remember_message_id(self, message_id: str) -> bool:
        """Ghi nhận ID hợp lệ; trả về False nếu event đã được xử lý."""
        if message_id in self._recent_message_id_set:
            return False
        if len(self._recent_message_ids) >= RECENT_MESSAGE_IDS_MAXSIZE:
            oldest = self._recent_message_ids.popleft()
            self._recent_message_id_set.discard(oldest)
        self._recent_message_ids.append(message_id)
        self._recent_message_id_set.add(message_id)
        return True

    def _cache_message(
        self,
        message_id: str,
        sender_id: str,
        body: str,
        attachments: list[dict[str, Any]],
        thread_key: str,
    ) -> None:
        if not message_id or message_id in self._bot_sent_message_ids:
            return
        if (
            message_id not in self._cached_messages
            and len(self._cached_message_order) >= CACHED_MESSAGES_MAXSIZE
        ):
            oldest_id = self._cached_message_order.popleft()
            self._cached_messages.pop(oldest_id, None)
        if message_id not in self._cached_messages:
            self._cached_message_order.append(message_id)
        self._cached_messages[message_id] = {
            "senderID": sender_id,
            "body": body,
            "attachments": attachments,
            "threadKey": thread_key,
        }

    async def _get_event(self, timeout: float | None = None) -> dict[str, Any] | None:
        try:
            return await asyncio.wait_for(self._event_queue.get(), timeout=timeout)
        except asyncio.TimeoutError:
            return None

    def _message_from_event(self, event: dict[str, Any]) -> dict[str, Any] | None:
        event_type = event.get("type")
        raw_data = event.get("data")
        data = raw_data if isinstance(raw_data, dict) else {}

        if event_type in {
            "ready",
            "e2eeConnected",
            "reconnected",
            "disconnected",
            "closed",
        }:
            log("e2ee", str(event_type))
            return None
        if event_type == "error":
            if self.debug_errors:
                log("e2ee", f"bridge error: {_redact_bridge_text(data)}")
            else:
                log("e2ee", "bridge error (chi tiết đã được ẩn)")
            return None
        if event_type in META_MESSAGE_EVENT_TYPES:
            chat_jid = data.get("chatJid")
            return {
                "body": str(data.get("newText") or ""),
                "timestamp": data.get("editTimestampMs")
                or data.get("unsendTimestampMs")
                or 0,
                "userID": data.get("senderId", 0),
                "messageID": data.get("messageId") or data.get("id"),
                "replyToID": data.get("threadId", 0),
                "type": str(event_type),
                "chatJid": chat_jid,
                "senderJid": data.get("senderJid"),
                "attachments": [],
                "raw": data,
            }
        if event_type not in MESSAGE_EVENT_TYPES:
            if self.debug_errors and event_type not in {"raw", None}:
                log("e2ee", f"Bỏ qua event phụ trợ: {event_type}")
            return None

        chat_jid = data.get("chatJid")
        sender_jid = data.get("senderJid")
        message_type = "e2ee" if event_type == "e2eeMessage" else "thread"
        return {
            "body": data.get("text"),
            "timestamp": data.get("timestampMs", 0),
            "userID": data.get("senderId", 0),
            "messageID": data.get("id"),
            "replyToID": data.get("threadId", 0),
            "type": message_type,
            "chatJid": chat_jid,
            "senderJid": sender_jid,
            "attachments": data.get("attachments") or [],
            "raw": data,
        }

    async def _handle_meta_message_event(self, message: dict[str, Any]) -> None:
        event_type = str(message.get("type") or "")
        msg_id = str(message.get("messageID") or "").strip()
        if not msg_id or msg_id in self._bot_sent_message_ids:
            return
        thread_key = str(message.get("replyToID") or message.get("chatJid") or "")
        cached = self._cached_messages.get(msg_id)
        if not thread_key and cached:
            thread_key = str(cached.get("threadKey") or "")
        if not thread_key or (
            thread_key not in self._anti_unsend_threads
            and "*" not in self._anti_unsend_threads
        ):
            return
        sender_id = str(
            message.get("userID") or (cached.get("senderID") if cached else "") or "N/A"
        )
        old_body = str(cached.get("body") or "") if cached else ""
        raw_cached_atts = cached.get("attachments") if cached else None
        old_atts: list[Any] = (
            raw_cached_atts if isinstance(raw_cached_atts, list) else []
        )
        reply_ctx = {
            "chatJid": message.get("chatJid"),
            "replyToID": message.get("replyToID") or (int(thread_key) if thread_key.isdigit() else 0),
            "messageID": "",
            "senderJid": "",
        }
        if event_type == "messageUnsend":
            if not old_body and not old_atts:
                await self._reply(
                    reply_ctx,
                    f"🕵️ Phát hiện UID `{sender_id}` vừa thu hồi tin nhắn `{msg_id}` (chưa có trong bộ nhớ đệm).",
                )
                return
            lines = [f"🕵️ Chống thu hồi — UID `{sender_id}` vừa thu hồi tin nhắn:"]
            if old_body:
                lines.append(f"• Nội dung: {old_body}")
            for idx, att in enumerate(old_atts[:3], 1):
                if isinstance(att, dict):
                    lines.append(
                        f"• Media {idx} [{att.get('type') or 'file'}]: {att.get('url') or att.get('previewUrl')}"
                    )
            await self._reply(reply_ctx, "\n".join(lines))
        elif event_type == "messageEdit":
            new_body = str(message.get("body") or "").strip()
            lines = [f"✏️ Phát hiện chỉnh sửa tin nhắn từ UID `{sender_id}`:"]
            if old_body:
                lines.append(f"• Trước: {old_body}")
            lines.append(f"• Sau: {new_body or '<trống>'}")
            if cached is not None:
                cached["body"] = new_body
            await self._reply(reply_ctx, "\n".join(lines))

    async def _dispatch(self, message: dict[str, Any]) -> None:
        msg_type = str(message.get("type") or "")
        if msg_type in META_MESSAGE_EVENT_TYPES:
            await self._handle_meta_message_event(message)
            return

        message_id = str(message.get("messageID") or "").strip()
        body = message.get("body")
        sender_id = str(message.get("userID") or "").strip()
        attachments_raw = message.get("attachments")
        thread_key_str = str(
            message.get("replyToID") or message.get("chatJid") or ""
        )
        clean_atts: list[dict[str, Any]] = []
        if isinstance(attachments_raw, list) and attachments_raw:
            clean_atts = [a for a in attachments_raw if isinstance(a, dict)]
            if message_id and sender_id and thread_key_str and clean_atts:
                self._last_attachments[thread_key_str] = clean_atts
                chat_jid_key = str(message.get("chatJid") or "")
                if chat_jid_key:
                    self._last_attachments[chat_jid_key] = clean_atts
        if message_id and sender_id and (isinstance(body, str) and body or clean_atts):
            self._cache_message(
                message_id,
                sender_id,
                str(body or ""),
                clean_atts,
                thread_key_str,
            )
        if not message_id or not sender_id or not isinstance(body, str) or not body:
            if self.debug_errors:
                log(
                    "recv",
                    "Bỏ qua message thiếu ID, sender hoặc nội dung; "
                    f"keys={sorted(message)}",
                )
            return

        if message_id in self._bot_sent_message_ids:
            if self.debug_errors:
                log("recv", "Bỏ qua message do chính bot vừa gửi.")
            return
        if not str(body).startswith(self.prefix):
            if (
                thread_key_str in self._autodl_threads
                or "*" in self._autodl_threads
            ):
                match = _IG_MEDIA_URL_RE.search(str(body))
                if match and self._remember_message_id(message_id):
                    with contextlib.suppress(Exception):
                        await self._cmd_dl(message, match.group(0))
                    return
            if sender_id == str(self.dataIGS.get("IGSID")):
                if self.debug_errors:
                    log("recv", "Bỏ qua message thường do chính tài khoản bot gửi.")
                return
            body_for_log = (
                repr(body)
                if self.log_message_content
                else f"<redacted length={len(str(body))}>"
            )
            log("recv", f"[{message.get('type')}] message nhận được: {body_for_log}")
            return

        body_for_log = (
            repr(body)
            if self.log_message_content
            else f"<redacted length={len(str(body))}>"
        )
        log("recv", f"[{message.get('type')}] message nhận được: {body_for_log}")

        command_line = str(body)[len(self.prefix) :].strip()
        if not command_line:
            return
        parts = command_line.split(maxsplit=1)
        command = parts[0].lower()
        argument = parts[1] if len(parts) > 1 else ""
        handler = self._handlers.get(command)
        if handler is None:
            detail = command if self.log_message_content else "<redacted>"
            log("cmd", f"Bỏ qua lệnh không tồn tại: {detail}")
            return
        if not self._remember_message_id(message_id):
            return
        try:
            await handler(message, argument)
        except Exception as error:  # bot không được chết vì một lệnh lỗi
            if self.debug_errors:
                log(
                    "err",
                    f"Lỗi khi xử lý /{command}: {_redact_bridge_text(error)}\n"
                    f"{_redact_bridge_text(traceback.format_exc())}",
                )
            else:
                log(
                    "err",
                    f"Lỗi {type(error).__name__} khi xử lý /{command}; "
                    "bật debug_errors để xem chi tiết.",
                )

    async def _reply(self, message: dict[str, Any], content: str) -> None:
        chat_jid = message.get("chatJid")
        if chat_jid:
            result = await self.listener.send_e2ee_message(
                str(chat_jid),
                content,
                reply_to_id=str(message.get("messageID") or ""),
                reply_to_sender_jid=str(message.get("senderJid") or ""),
            )
            message_id = result.get("messageId") or result.get("id")
            if result.get("deliveryStatus") == DELIVERY_STATUS_UNKNOWN:
                log(
                    "send",
                    "E2EE delivery UNKNOWN; không tự retry để tránh gửi trùng.",
                )
                return
            if message_id:
                self._bot_sent_message_ids.add(str(message_id))
                self._last_bot_message[str(chat_jid)] = (str(chat_jid), str(message_id))
                content_for_log = (
                    repr(content)
                    if self.log_message_content
                    else f"<redacted length={len(content)}>"
                )
                log("send", f"E2EE gửi thành công: {content_for_log}")
            else:
                log("send", f"E2EE gửi thất bại; keys={sorted(result)}")
            return

        thread_id = message.get("replyToID")
        if not thread_id:
            log(
                "send",
                "Bỏ qua reply vì thiếu chatJid/threadID.",
            )
            return
        result = await self.listener.send_message(
            int(thread_id),
            content,
            reply_to_id=str(message.get("messageID") or ""),
        )
        message_id = result.get("messageId") or result.get("id")
        if message_id:
            self._bot_sent_message_ids.add(str(message_id))
            content_for_log = (
                repr(content)
                if self.log_message_content
                else f"<redacted length={len(content)}>"
            )
            log("send", f"regular gửi thành công: {content_for_log}")
        else:
            log("send", f"regular gửi thất bại; keys={sorted(result)}")

    async def _cmd_hi(self, message: dict[str, Any], argument: str) -> None:
        await self._reply(
            message,
            f"👋 Xin chào! Bot Instagram E2EE đang hoạt động. Gõ {self.prefix}help để xem danh sách lệnh.",
        )

    async def _cmd_ping(self, message: dict[str, Any], argument: str) -> None:
        sent_ts = int(message.get("timestamp") or 0)
        latency = max(0, int(time.time() * 1000) - sent_ts) if sent_ts else None
        await self._reply(
            message, f"🏓 pong! ({latency} ms)" if latency is not None else "🏓 pong!"
        )

    async def _cmd_help(self, message: dict[str, Any], argument: str) -> None:
        prefix = self.prefix
        await self._reply(
            message,
            "📖 Lệnh hỗ trợ:\n"
            f"• {prefix}hi - chào và kiểm tra bot\n"
            f"• {prefix}ping - kiểm tra độ trễ\n"
            f"• {prefix}help - hiển thị trợ giúp\n"
            f"• {prefix}id - xem chatJid/threadID + userID\n"
            f"• {prefix}info [id/user] - xem thông tin tài khoản Instagram\n"
            f"• {prefix}profile <@user/id> - hồ sơ chi tiết (Bio, Follower, bài đăng)\n"
            f"• {prefix}story <@user/id> - xem & lấy link tải Story 24h đang hoạt động\n"
            f"• {prefix}follow / {prefix}unfollow <@user/id> - theo dõi/bỏ theo dõi\n"
            f"• {prefix}bio <text> - đổi tiểu sử Instagram của bot (Admin)\n"
            f"• {prefix}inbox - danh sách hội thoại gần đây\n"
            f"• {prefix}thread / {prefix}history [số tin] - chi tiết chat & lịch sử tin nhắn\n"
            f"• {prefix}deletethread [spam] - xóa hội thoại hiện tại (Admin)\n"
            f"• {prefix}requests / {prefix}accept <id> - xem & duyệt tin nhắn chờ\n"
            f"• {prefix}rename <tên> - đổi tên nhóm chat\n"
            f"• {prefix}groupavatar <url|clear> - đổi hoặc xóa ảnh đại diện nhóm\n"
            f"• {prefix}tagall / {prefix}everyone [lời nhắn] - tag toàn bộ thành viên nhóm\n"
            f"• {prefix}mute / {prefix}unmute - tắt/bật thông báo hội thoại\n"
            f"• {prefix}pinthread / {prefix}unpinthread - ghim/bỏ ghim hội thoại\n"
            f"• {prefix}image <url> - tải ảnh từ URL và gửi vào chat\n"
            f"• {prefix}voice <url> - gửi tin nhắn thoại (Voice Note) từ URL âm thanh\n"
            f"• {prefix}media - lấy link tải ảnh/video/voice/reel vừa gửi\n"
            f"• {prefix}dl <url/code> - bóc tách & lấy link tải Post/Reel Instagram\n"
            f"• {prefix}autodl [on|off] - tự động bóc link tải khi ai đó gửi link IG\n"
            f"• {prefix}like / {prefix}unlike <url/code> - thả tim/bỏ tim bài viết/Reel\n"
            f"• {prefix}comment <url/code> <nội dung> - bình luận vào bài viết/Reel\n"
            f"• {prefix}save / {prefix}unsave <url/code> - lưu/bỏ lưu bài viết/Reel\n"
            f"• {prefix}forward <threadID> [lời nhắn] - chuyển tiếp tin nhắn đang reply\n"
            f"• {prefix}creategroup <id1,id2> [tên] - tạo nhóm chat mới\n"
            f"• {prefix}add / {prefix}kick <id> - thêm/xóa thành viên nhóm\n"
            f"• {prefix}promote / {prefix}demote <id> - thăng/hạ Admin nhóm\n"
            f"• {prefix}leave - rời nhóm chat\n"
            f"• {prefix}block / {prefix}unblock <id> - chặn/bỏ chặn người dùng\n"
            f"• {prefix}echo <text> - lặp lại nội dung\n"
            f"• {prefix}react [emoji] - thả cảm xúc vào tin nhắn\n"
            f"• {prefix}edit <text> - sửa tin nhắn cuối của bot\n"
            f"• {prefix}pin / {prefix}unpin - ghim/bỏ ghim tin nhắn\n"
            f"• {prefix}search <từ> - tìm người dùng Instagram\n"
            f"• {prefix}unsend - thu hồi tin nhắn E2EE cuối của bot\n"
            f"• {prefix}antiunsend [on|off] - bật/tắt chống thu hồi & phát hiện sửa tin nhắn\n"
            f"• {prefix}note [text|clear|list] - xem, đăng hoặc xóa Ghi chú 24h (Admin)\n"
            f"• {prefix}notemusic <tên bài hát> [| lời nhắn] - đăng Note 24h kèm bài hát (Admin)\n"
            f"• {prefix}notif - xem thông báo hoạt động Instagram gần đây (Admin)\n"
            f"• {prefix}post <url_ảnh> [caption] - đăng ảnh mới lên Feed Instagram (Admin)\n"
            f"• {prefix}upstory <url_ảnh> - đăng ảnh lên Story 24h Instagram (Admin)\n"
            f"• {prefix}more [số_tin] - phân trang tải thêm tin nhắn cũ hơn trong hội thoại",
        )

    @staticmethod
    def _mask_auto_detect_id(raw_val: Any) -> str:
        s = str(raw_val or "").strip()
        if not s or not s.isdigit():
            return s or "N/A"
        return "\u200b".join(s[i : i + 3] for i in range(0, len(s), 3))

    @staticmethod
    def _mask_auto_detect_url(raw_url: Any) -> str:
        s = str(raw_url or "").strip()
        for prefix in ("https://www.", "http://www.", "https://", "http://"):
            if s.lower().startswith(prefix):
                s = s[len(prefix) :]
                break
        return s.replace(".", ".\u200b")

    async def _cmd_info(self, message: dict[str, Any], argument: str) -> None:
        target = argument.strip() or str(message.get("userID") or "")
        if not target:
            await self._reply(
                message, f"Cách dùng: {self.prefix}info [id hoặc username]"
            )
            return
        info = await _get_user_info.func(self.dataIGS, target, client=self.http_client)
        if info.get("error"):
            await self._reply(
                message,
                f"⚠️ Không lấy được thông tin cho `{target}`: {info.get('messages')}",
            )
            return
        uid = self._mask_auto_detect_id(info.get("idUser"))
        await self._reply(
            message,
            f"👤 {info.get('nameUser')} (@{info.get('Username')})\n"
            f"• EIMU ID: {uid}",
        )

    async def _cmd_profile(self, message: dict[str, Any], argument: str) -> None:
        target = argument.strip() or str(message.get("userID") or "")
        if not target:
            await self._reply(
                message, f"Cách dùng: {self.prefix}profile <@username hoặc ID>"
            )
            return
        if self.listener._bridge is None:
            await self._reply(message, "Bridge E2EE chưa sẵn sàng.")
            return
        actions = BridgeActions(self.listener._bridge)
        try:
            prof = await actions.get_web_profile(target)
        except Exception as exc:
            await self._reply(
                message,
                f"⚠️ Không lấy được hồ sơ `{target}`: {_redact_bridge_text(str(exc))}",
            )
            return
        flags: list[str] = []
        if prof.get("isVerified"):
            flags.append("☑️ Đã xác minh")
        if prof.get("isPrivate"):
            flags.append("🔒 Riêng tư")
        else:
            flags.append("🌍 Công khai")
        uname = str(prof.get("username") or target.lstrip("@")).strip()
        full_name = str(prof.get("fullName") or uname or "N/A").strip()
        ig_id = self._mask_auto_detect_id(prof.get("id"))
        eimu_id = self._mask_auto_detect_id(
            prof.get("fbid") or prof.get("fbidV2") or "N/A"
        )
        followers = int(prof.get("followerCount") or 0)
        following = int(prof.get("followingCount") or 0)
        post_count = int(prof.get("postCount", prof.get("mediaCount", 0)) or 0)
        lines = [
            f"🪪 {full_name} (@{uname})",
            f"• Trạng thái: {' · '.join(flags)}",
            f"• IG ID: {ig_id}",
            f"• EIMU: {eimu_id}",
            f"• Thống kê: {followers:,} followers · {following:,} following · {post_count:,} bài viết",
        ]
        bio = str(prof.get("biography") or "").strip()
        if bio:
            lines.append(f"• Bio: {bio}")
        ext_url = str(prof.get("externalUrl") or "").strip()
        if ext_url:
            lines.append(f"• Link: {self._mask_auto_detect_url(ext_url)}")
        await self._reply(message, "\n".join(lines))

    async def _cmd_story(self, message: dict[str, Any], argument: str) -> None:
        target = argument.strip() or str(message.get("userID") or "")
        if not target:
            await self._reply(
                message, f"Cách dùng: {self.prefix}story <@username hoặc ID>"
            )
            return
        if self.listener._bridge is None:
            await self._reply(message, "Bridge E2EE chưa sẵn sàng.")
            return
        try:
            res = await BridgeActions(self.listener._bridge).fetch_stories(target)
        except Exception as exc:
            await self._reply(
                message,
                f"⚠️ Không lấy được Story của `{target}`: {_redact_bridge_text(str(exc))}",
            )
            return
        items = res.get("items")
        item_list = items if isinstance(items, list) else []
        uname = res.get("username") or target
        if not item_list:
            await self._reply(
                message, f"📭 @{uname} hiện không có Story 24h nào đang hoạt động."
            )
            return
        lines = [
            f"⭕ Story của @{uname} ({len(item_list)} tin đang hoạt động):"
        ]
        for idx, it in enumerate(item_list[:8], 1):
            if not isinstance(it, dict):
                continue
            m_type = (
                "Video"
                if (it.get("mediaType") == 2 or it.get("type") == "video")
                else "Ảnh"
            )
            lines.append(f"{idx}. [{m_type}] {it.get('url')}")
        await self._reply(message, "\n".join(lines))

    async def _cmd_inbox(self, message: dict[str, Any], argument: str) -> None:
        if self.listener._bridge is None:
            await self._reply(message, "Bridge E2EE chưa sẵn sàng.")
            return
        threads = await BridgeActions(self.listener._bridge).get_inbox()
        if not threads:
            await self._reply(message, "📭 Hộp thư trống.")
            return
        lines = [f"📬 Hộp thư Instagram ({len(threads)} hội thoại):"]
        for idx, t in enumerate(threads[:10], 1):
            t_name = t.get("name") or "Không tên"
            t_id = t.get("id")
            lines.append(f"{idx}. {t_name} (ID: {t_id})")
        await self._reply(message, "\n".join(lines))

    async def _cmd_thread(self, message: dict[str, Any], argument: str) -> None:
        await self._cmd_history(message, argument)

    async def _cmd_history(self, message: dict[str, Any], argument: str) -> None:
        if self.listener._bridge is None:
            await self._reply(message, "Bridge E2EE chưa sẵn sàng.")
            return
        thread_id = int(message.get("replyToID") or 0)
        if not thread_id:
            await self._reply(message, "⚠️ Không xác định được threadID.")
            return
        limit = 5
        if argument.strip().isdigit():
            limit = max(1, min(20, int(argument.strip())))
        try:
            detail = await BridgeActions(self.listener._bridge).get_thread_info(
                thread_id, message_limit=limit
            )
        except Exception as exc:
            await self._reply(
                message,
                f"⚠️ Không lấy được thông tin hội thoại: {_redact_bridge_text(str(exc))}",
            )
            return
        participants = detail.get("participants")
        part_list = participants if isinstance(participants, list) else []
        part_names = [
            f"{p.get('name') or p.get('username') or p.get('id')}"
            for p in part_list[:8]
            if isinstance(p, dict)
        ]
        lines = [
            f"💬 Hội thoại: {detail.get('name') or 'Không tên'}",
            f"• Thread Key: {detail.get('id')} (ShortID: {detail.get('shortId') or 'N/A'})",
            f"• Loại: {'Nhóm' if detail.get('isGroup') else '1-1'} | Thành viên ({len(part_list)}): {', '.join(part_names) or 'Bản thân'}",
        ]
        msgs = detail.get("messages")
        msg_list = msgs if isinstance(msgs, list) else []
        if msg_list:
            lines.append(f"📜 {len(msg_list)} tin nhắn gần nhất:")
            for idx, m in enumerate(msg_list[:limit], 1):
                if not isinstance(m, dict):
                    continue
                txt = str(m.get("text") or "").strip()
                atts = m.get("attachments")
                att_count = len(atts) if isinstance(atts, list) else 0
                att_tag = f" [{att_count} media]" if att_count else ""
                preview = (txt[:60] + "…") if len(txt) > 60 else (txt or "<Media>")
                lines.append(f"{idx}. [{m.get('senderId')}]: {preview}{att_tag}")
        await self._reply(message, "\n".join(lines))

    async def _cmd_requests(self, message: dict[str, Any], argument: str) -> None:
        if self.listener._bridge is None:
            await self._reply(message, "Bridge E2EE chưa sẵn sàng.")
            return
        try:
            threads = await BridgeActions(self.listener._bridge).get_message_requests()
        except Exception as exc:
            await self._reply(
                message,
                f"⚠️ Không lấy được tin nhắn chờ: {_redact_bridge_text(str(exc))}",
            )
            return
        if not threads:
            await self._reply(message, "📭 Không có tin nhắn chờ (Pending) nào.")
            return
        lines = [f"📩 Tin nhắn chờ ({len(threads)} hội thoại):"]
        for idx, t in enumerate(threads[:10], 1):
            lines.append(
                f"{idx}. {t.get('name') or 'Không tên'} — `{self.prefix}accept {t.get('id')}`"
            )
        await self._reply(message, "\n".join(lines))

    async def _cmd_accept(self, message: dict[str, Any], argument: str) -> None:
        if self.listener._bridge is None:
            await self._reply(message, "Bridge E2EE chưa sẵn sàng.")
            return
        target_str = argument.strip()
        thread_id = (
            int(target_str)
            if target_str.isdigit()
            else int(message.get("replyToID") or 0)
        )
        if not thread_id:
            await self._reply(message, f"Cách dùng: {self.prefix}accept <threadID>")
            return
        try:
            await BridgeActions(self.listener._bridge).accept_message_request(thread_id)
            await self._reply(
                message, f"✅ Đã duyệt tin nhắn chờ cho hội thoại `{thread_id}`."
            )
        except Exception as exc:
            await self._reply(
                message,
                f"⚠️ Không duyệt được tin nhắn chờ: {_redact_bridge_text(str(exc))}",
            )

    async def _cmd_rename(self, message: dict[str, Any], argument: str) -> None:
        new_name = argument.strip()
        if not new_name:
            await self._reply(message, f"Cách dùng: {self.prefix}rename <tên nhóm mới>")
            return
        if self.listener._bridge is None:
            await self._reply(message, "Bridge E2EE chưa sẵn sàng.")
            return
        thread_id = int(message.get("replyToID") or 0)
        try:
            await BridgeActions(self.listener._bridge).rename_thread(
                thread_id, new_name
            )
            await self._reply(message, f"✏️ Đã đổi tên hội thoại thành: {new_name}")
        except Exception as exc:
            await self._reply(
                message,
                f"⚠️ Không đổi được tên hội thoại: {_redact_bridge_text(str(exc))}",
            )

    async def _cmd_groupavatar(self, message: dict[str, Any], argument: str) -> None:
        raw = argument.strip()
        if not raw:
            await self._reply(
                message,
                f"Cách dùng: {self.prefix}groupavatar <https://... hoặc clear>",
            )
            return
        clear = raw.lower() in {"clear", "remove", "delete", "none"}
        if not clear and not raw.startswith(("http://", "https://")):
            await self._reply(
                message,
                f"Cách dùng: {self.prefix}groupavatar <https://... hoặc clear>",
            )
            return
        if self.listener._bridge is None:
            await self._reply(message, "Bridge E2EE chưa sẵn sàng.")
            return
        thread_id = int(message.get("replyToID") or 0)
        try:
            await BridgeActions(self.listener._bridge).edit_group_avatar(
                thread_id, "" if clear else raw
            )
            await self._reply(
                message,
                (
                    "🗑️ Đã xóa ảnh đại diện nhóm."
                    if clear
                    else "🖼️ Đã cập nhật ảnh đại diện nhóm."
                ),
            )
        except Exception as exc:
            await self._reply(
                message,
                f"⚠️ Không cập nhật được ảnh nhóm: {_redact_bridge_text(str(exc))}",
            )

    async def _cmd_mute(self, message: dict[str, Any], argument: str) -> None:
        await self._toggle_mute(message, mute=True)

    async def _cmd_unmute(self, message: dict[str, Any], argument: str) -> None:
        await self._toggle_mute(message, mute=False)

    async def _toggle_mute(self, message: dict[str, Any], *, mute: bool) -> None:
        if self.listener._bridge is None:
            await self._reply(message, "Bridge E2EE chưa sẵn sàng.")
            return
        thread_id = int(message.get("replyToID") or 0)
        try:
            await BridgeActions(self.listener._bridge).mute_thread(
                thread_id, -1 if mute else 0
            )
            await self._reply(
                message,
                (
                    "🔕 Đã tắt thông báo hội thoại."
                    if mute
                    else "🔔 Đã bật thông báo hội thoại."
                ),
            )
        except Exception as exc:
            await self._reply(
                message,
                f"⚠️ Không thay đổi được trạng thái thông báo: {_redact_bridge_text(str(exc))}",
            )

    async def _cmd_pinthread(self, message: dict[str, Any], argument: str) -> None:
        await self._toggle_pinthread(message, pin=True)

    async def _cmd_unpinthread(self, message: dict[str, Any], argument: str) -> None:
        await self._toggle_pinthread(message, pin=False)

    async def _toggle_pinthread(self, message: dict[str, Any], *, pin: bool) -> None:
        if self.listener._bridge is None:
            await self._reply(message, "Bridge E2EE chưa sẵn sàng.")
            return
        thread_id = int(message.get("replyToID") or 0)
        try:
            await BridgeActions(self.listener._bridge).pin_thread(thread_id, pin=pin)
            await self._reply(
                message,
                (
                    "📌 Đã ghim hội thoại lên đầu hộp thư."
                    if pin
                    else "📍 Đã bỏ ghim hội thoại."
                ),
            )
        except Exception as exc:
            await self._reply(
                message,
                f"⚠️ Không ghim/bỏ ghim được hội thoại: {_redact_bridge_text(str(exc))}",
            )

    async def _cmd_image(self, message: dict[str, Any], argument: str) -> None:
        media_url = argument.strip()
        if not media_url.startswith(("http://", "https://")):
            await self._reply(message, f"Cách dùng: {self.prefix}image <https://...>")
            return
        if self.listener._bridge is None:
            await self._reply(message, "Bridge E2EE chưa sẵn sàng.")
            return
        thread_id = int(message.get("replyToID") or 0)
        msg_id = str(message.get("messageID") or "")
        try:
            res = await BridgeActions(self.listener._bridge).send_media_from_url(
                thread_id, media_url, reply_to_id=msg_id
            )
            sent_id = res.get("messageId") or res.get("id")
            if sent_id:
                self._bot_sent_message_ids.add(str(sent_id))
                chat_jid = str(message.get("chatJid") or "")
                if chat_jid:
                    self._last_bot_message[chat_jid] = (chat_jid, str(sent_id))
        except Exception as exc:
            await self._reply(
                message,
                f"⚠️ Không gửi được media từ URL: {_redact_bridge_text(str(exc))}",
            )

    async def _cmd_media(self, message: dict[str, Any], argument: str) -> None:
        atts_raw = message.get("attachments")
        atts: list[dict[str, Any]] = (
            [a for a in atts_raw if isinstance(a, dict)]
            if isinstance(atts_raw, list)
            else []
        )
        if not atts:
            thread_key_str = str(
                message.get("chatJid") or message.get("replyToID") or ""
            )
            atts = self._last_attachments.get(thread_key_str, [])
        if not atts and self.listener._bridge is not None:
            thread_id = int(message.get("replyToID") or 0)
            if thread_id:
                with contextlib.suppress(Exception):
                    detail = await BridgeActions(self.listener._bridge).get_thread_info(
                        thread_id, message_limit=10
                    )
                    msgs = detail.get("messages")
                    if isinstance(msgs, list):
                        for m in msgs:
                            if not isinstance(m, dict):
                                continue
                            m_atts = m.get("attachments")
                            if isinstance(m_atts, list) and m_atts:
                                atts = [a for a in m_atts if isinstance(a, dict)]
                                break
        if not atts:
            await self._reply(
                message,
                "ℹ️ Không tìm thấy media/attachment nào gần đây trong hội thoại này.",
            )
            return
        lines = [f"🖼️ Phát hiện {len(atts)} attachment gần nhất:"]
        for idx, att in enumerate(atts[:5], 1):
            a_type = att.get("type") or "unknown"
            a_url = att.get("url") or att.get("previewUrl") or "N/A"
            lines.append(f"{idx}. [{a_type}] {a_url}")
        await self._reply(message, "\n".join(lines))

    async def _cmd_dl(self, message: dict[str, Any], argument: str) -> None:
        target = argument.strip()
        if not target:
            await self._reply(
                message,
                f"Cách dùng: {self.prefix}dl <link bài viết/reel hoặc shortcode>",
            )
            return
        if self.listener._bridge is None:
            await self._reply(message, "Bridge E2EE chưa sẵn sàng.")
            return
        try:
            info = await BridgeActions(self.listener._bridge).fetch_media(target)
        except Exception as exc:
            await self._reply(
                message,
                f"⚠️ Không lấy được media `{target}`: {_redact_bridge_text(str(exc))}",
            )
            return
        urls = info.get("urls")
        url_list = urls if isinstance(urls, list) else []
        caption = str(info.get("caption") or "").strip()
        if len(caption) > 120:
            caption = caption[:120] + "…"
        lines = [
            f"🎬 Media `{info.get('shortcode') or info.get('id')}` (@{info.get('author') or 'unknown'}):",
            f"• ❤️ Likes: {info.get('likeCount', 0)} | ▶️ Plays: {info.get('playCount', 0)}",
        ]
        if caption:
            lines.append(f"• 📝 Caption: {caption}")
        for idx, u in enumerate(url_list[:5], 1):
            lines.append(f"• Link {idx}: {u}")
        await self._reply(message, "\n".join(lines))

    async def _cmd_voice(self, message: dict[str, Any], argument: str) -> None:
        audio_url = argument.strip()
        if not audio_url.startswith(("http://", "https://")):
            await self._reply(message, f"Cách dùng: {self.prefix}voice <https://...>")
            return
        if self.listener._bridge is None:
            await self._reply(message, "Bridge E2EE chưa sẵn sàng.")
            return
        thread_id = int(message.get("replyToID") or 0)
        msg_id = str(message.get("messageID") or "")
        try:
            res = await BridgeActions(self.listener._bridge).send_voice_from_url(
                thread_id, audio_url, reply_to_id=msg_id
            )
            sent_id = res.get("messageId") or res.get("id")
            if sent_id:
                self._bot_sent_message_ids.add(str(sent_id))
                chat_jid = str(message.get("chatJid") or "")
                if chat_jid:
                    self._last_bot_message[chat_jid] = (chat_jid, str(sent_id))
        except Exception as exc:
            await self._reply(
                message,
                f"⚠️ Không gửi được voice từ URL: {_redact_bridge_text(str(exc))}",
            )

    async def _cmd_like(self, message: dict[str, Any], argument: str) -> None:
        await self._toggle_like(message, argument, unlike=False)

    async def _cmd_unlike(self, message: dict[str, Any], argument: str) -> None:
        await self._toggle_like(message, argument, unlike=True)

    async def _toggle_like(
        self, message: dict[str, Any], argument: str, *, unlike: bool
    ) -> None:
        target = argument.strip()
        if not target:
            cmd = "unlike" if unlike else "like"
            await self._reply(
                message,
                f"Cách dùng: {self.prefix}{cmd} <link bài viết/reel hoặc shortcode>",
            )
            return
        res = await _reactionPost.like_instagram_media(
            self.dataIGS, target, unlike=unlike, client=self.http_client
        )
        if res.get("error"):
            await self._reply(
                message,
                f"⚠️ Không thể {'bỏ tim' if unlike else 'thả tim'} bài viết `{target}`: {res.get('messages')}",
            )
            return
        await self._reply(
            message,
            (
                f"💔 Đã bỏ thả tim bài viết `{res.get('mediaId')}`."
                if unlike
                else f"❤️ Đã thả tim bài viết `{res.get('mediaId')}`."
            ),
        )

    async def _cmd_forward(self, message: dict[str, Any], argument: str) -> None:
        parts = argument.strip().split(maxsplit=1)
        if not parts or not parts[0].isdigit():
            await self._reply(
                message,
                f"Cách dùng: Reply vào 1 tin nhắn và gõ `{self.prefix}forward <targetThreadID> [lời nhắn kèm]`",
            )
            return
        target_thread_id = int(parts[0])
        custom_text = parts[1].strip() if len(parts) > 1 else ""
        if self.listener._bridge is None:
            await self._reply(message, "Bridge E2EE chưa sẵn sàng.")
            return
        source_thread_id = int(message.get("replyToID") or 0)
        raw_obj = message.get("raw")
        raw: dict[str, Any] = raw_obj if isinstance(raw_obj, dict) else {}
        reply_to_obj = raw.get("replyTo")
        reply_to: dict[str, Any] = (
            reply_to_obj if isinstance(reply_to_obj, dict) else {}
        )
        target_msg_id = str(reply_to.get("messageId") or "").strip()
        try:
            res = await BridgeActions(self.listener._bridge).forward_message(
                source_thread_id,
                target_thread_id,
                message_id=target_msg_id,
                text=custom_text,
            )
            await self._reply(
                message,
                f"↪️ Đã chuyển tiếp tin nhắn sang hội thoại `{target_thread_id}` (ID mới: {res.get('messageId')}).",
            )
        except Exception as exc:
            await self._reply(
                message,
                f"⚠️ Không chuyển tiếp được tin nhắn: {_redact_bridge_text(str(exc))}",
            )

    async def _cmd_creategroup(self, message: dict[str, Any], argument: str) -> None:
        parts = argument.strip().split(maxsplit=1)
        if not parts:
            await self._reply(
                message,
                f"Cách dùng: {self.prefix}creategroup <user1,user2,...> [tên nhóm]",
            )
            return
        raw_targets = [
            s.strip() for s in parts[0].split(",") if s.strip()
        ]
        if len(raw_targets) < 2:
            await self._reply(
                message,
                "⚠️ Instagram yêu cầu tối thiểu 2 người dùng khác để tạo nhóm chat (tổng ≥ 3 thành viên tính cả bạn).\n"
                f"• Cách dùng: `{self.prefix}creategroup <user1,user2> [tên nhóm]`",
            )
            return
        title = parts[1].strip() if len(parts) > 1 else ""
        if self.listener._bridge is None:
            await self._reply(message, "Bridge E2EE chưa sẵn sàng.")
            return
        actions = BridgeActions(self.listener._bridge)
        resolved_ids: list[int] = []
        self_igsid = str(self.dataIGS.get("IGSID") or "").strip()
        for raw_t in raw_targets:
            clean_t = raw_t.lstrip("@").strip()
            eimu_val = 0
            if clean_t.isdigit():
                if len(clean_t) >= 15 or len(clean_t) < 6:
                    eimu_val = int(clean_t)
                else:
                    with contextlib.suppress(Exception):
                        uinfo = await _get_user_info.func(
                            self.dataIGS, clean_t, client=self.http_client
                        )
                        eimu_str = str(uinfo.get("eimu_id") or "").strip()
                        if eimu_str.isdigit():
                            eimu_val = int(eimu_str)
                    if not eimu_val:
                        eimu_val = int(clean_t)
            else:
                with contextlib.suppress(Exception):
                    prof = await actions.get_web_profile(clean_t)
                    fbid_raw = prof.get("fbid") or prof.get("fbidV2")
                    if fbid_raw and str(fbid_raw).isdigit():
                        eimu_val = int(fbid_raw)
            if (
                eimu_val > 0
                and str(eimu_val) != self_igsid
                and eimu_val not in resolved_ids
            ):
                resolved_ids.append(eimu_val)
        if len(resolved_ids) < 2:
            await self._reply(
                message,
                "⚠️ Cần ít nhất 2 người dùng hợp lệ (khác tài khoản bot) để lập nhóm chat trên Instagram.",
            )
            return
        try:
            group = await actions.create_group(resolved_ids, title=title)
            gid = self._mask_auto_detect_id(group.get("id"))
            await self._reply(
                message,
                f"✅ Đã tạo nhóm `{group.get('name') or title or 'Nhóm mới'}` (ID: {gid}).",
            )
        except Exception as exc:
            await self._reply(
                message,
                f"⚠️ Không tạo được nhóm: {_redact_bridge_text(str(exc))}",
            )

    async def _cmd_add(self, message: dict[str, Any], argument: str) -> None:
        raw_ids = [s.strip() for s in argument.split(",") if s.strip().isdigit()]
        if not raw_ids:
            await self._reply(message, f"Cách dùng: {self.prefix}add <userID>")
            return
        if self.listener._bridge is None:
            await self._reply(message, "Bridge E2EE chưa sẵn sàng.")
            return
        thread_id = int(message.get("replyToID") or 0)
        try:
            await BridgeActions(self.listener._bridge).add_group_members(
                thread_id, [int(x) for x in raw_ids]
            )
            await self._reply(
                message, f"✅ Đã thêm {len(raw_ids)} thành viên vào nhóm."
            )
        except Exception as exc:
            await self._reply(
                message,
                f"⚠️ Không thêm được thành viên: {_redact_bridge_text(str(exc))}",
            )

    async def _cmd_kick(self, message: dict[str, Any], argument: str) -> None:
        target = argument.strip()
        if not target.isdigit():
            await self._reply(message, f"Cách dùng: {self.prefix}kick <userID>")
            return
        if self.listener._bridge is None:
            await self._reply(message, "Bridge E2EE chưa sẵn sàng.")
            return
        thread_id = int(message.get("replyToID") or 0)
        try:
            await BridgeActions(self.listener._bridge).remove_group_member(
                thread_id, int(target)
            )
            await self._reply(message, f"✅ Đã xóa thành viên `{target}` khỏi nhóm.")
        except Exception as exc:
            await self._reply(
                message,
                f"⚠️ Không xóa được thành viên: {_redact_bridge_text(str(exc))}",
            )

    async def _cmd_promote(self, message: dict[str, Any], argument: str) -> None:
        await self._toggle_admin(message, argument, promote=True)

    async def _cmd_demote(self, message: dict[str, Any], argument: str) -> None:
        await self._toggle_admin(message, argument, promote=False)

    async def _toggle_admin(
        self, message: dict[str, Any], argument: str, *, promote: bool
    ) -> None:
        target = argument.strip()
        if not target.isdigit():
            cmd = "promote" if promote else "demote"
            await self._reply(message, f"Cách dùng: {self.prefix}{cmd} <userID>")
            return
        if self.listener._bridge is None:
            await self._reply(message, "Bridge E2EE chưa sẵn sàng.")
            return
        thread_id = int(message.get("replyToID") or 0)
        try:
            await BridgeActions(self.listener._bridge).modify_group_admins(
                thread_id, [int(target)], promote=promote
            )
            await self._reply(
                message,
                (
                    f"✅ Đã cấp quyền Admin cho `{target}`."
                    if promote
                    else f"✅ Đã gỡ quyền Admin của `{target}`."
                ),
            )
        except Exception as exc:
            await self._reply(
                message,
                f"⚠️ Không cập nhật được quyền Admin: {_redact_bridge_text(str(exc))}",
            )

    async def _cmd_leave(self, message: dict[str, Any], argument: str) -> None:
        sender_id = str(message.get("userID") or "")
        if self.admins and sender_id not in self.admins:
            await self._reply(message, "⛔ Chỉ admin mới được dùng lệnh này.")
            return
        if self.listener._bridge is None:
            await self._reply(message, "Bridge E2EE chưa sẵn sàng.")
            return
        thread_id = int(message.get("replyToID") or 0)
        try:
            await BridgeActions(self.listener._bridge).leave_group(thread_id)
        except Exception as exc:
            await self._reply(
                message,
                f"⚠️ Không rời được nhóm: {_redact_bridge_text(str(exc))}",
            )

    async def _cmd_block(self, message: dict[str, Any], argument: str) -> None:
        await self._toggle_block(message, argument, blocked=True)

    async def _cmd_unblock(self, message: dict[str, Any], argument: str) -> None:
        await self._toggle_block(message, argument, blocked=False)

    async def _toggle_block(
        self, message: dict[str, Any], argument: str, *, blocked: bool
    ) -> None:
        sender_id = str(message.get("userID") or "")
        if not self.admins or sender_id not in self.admins:
            await self._reply(message, "⛔ Chỉ admin mới được dùng lệnh này.")
            return
        target = argument.strip()
        if not target:
            cmd = "block" if blocked else "unblock"
            await self._reply(message, f"Cách dùng: {self.prefix}{cmd} <userID>")
            return
        if self.listener._bridge is None:
            await self._reply(message, "Bridge E2EE chưa sẵn sàng.")
            return
        try:
            await BridgeActions(self.listener._bridge).set_user_blocked(
                target, blocked=blocked
            )
            await self._reply(
                message,
                (
                    f"🚫 Đã chặn người dùng `{target}`."
                    if blocked
                    else f"✅ Đã bỏ chặn người dùng `{target}`."
                ),
            )
        except Exception as exc:
            await self._reply(
                message,
                f"⚠️ Không thực hiện được thao tác: {_redact_bridge_text(str(exc))}",
            )

    async def _cmd_react(self, message: dict[str, Any], argument: str) -> None:
        emoji = argument.strip() or "❤️"
        msg_id = str(message.get("messageID") or "")
        chat_jid = str(message.get("chatJid") or "")
        sender_jid = str(message.get("senderJid") or "")
        try:
            if chat_jid and msg_id:
                await self.listener.send_e2ee_reaction(
                    chat_jid, msg_id, emoji, sender_jid=sender_jid
                )
                return
            thread_id = int(message.get("replyToID") or 0)
            if thread_id and msg_id:
                await self.listener.send_reaction(thread_id, msg_id, emoji)
        except Exception as exc:
            await self._reply(
                message,
                f"⚠️ Instagram không cho thả cảm xúc trong đoạn chat này ({_redact_bridge_text(str(exc))}).",
            )

    async def _cmd_edit(self, message: dict[str, Any], argument: str) -> None:
        new_text = argument.strip()
        if not new_text:
            await self._reply(message, f"Cách dùng: {self.prefix}edit <nội dung mới>")
            return
        chat_jid = str(message.get("chatJid") or "")
        target = self._last_bot_message.get(chat_jid)
        if not target:
            await self._reply(
                message, "ℹ️ Chưa có tin nhắn nào của bot trong chat này để sửa."
            )
            return
        if self.listener._bridge is None:
            await self._reply(message, "Bridge E2EE chưa sẵn sàng.")
            return
        target_chat_jid, target_message_id = target
        try:
            await BridgeActions(self.listener._bridge).edit_e2ee_message(
                target_chat_jid, target_message_id, new_text
            )
        except Exception as exc:
            await self._reply(
                message,
                f"⚠️ Không sửa được tin nhắn: {_redact_bridge_text(str(exc))}",
            )

    async def _cmd_pin(self, message: dict[str, Any], argument: str) -> None:
        await self._toggle_pin(message, pin=True)

    async def _cmd_unpin(self, message: dict[str, Any], argument: str) -> None:
        await self._toggle_pin(message, pin=False)

    async def _toggle_pin(self, message: dict[str, Any], *, pin: bool) -> None:
        if self.listener._bridge is None:
            await self._reply(message, "Bridge E2EE chưa sẵn sàng.")
            return
        thread_id = int(message.get("replyToID") or 0)
        raw_obj = message.get("raw")
        raw: dict[str, Any] = raw_obj if isinstance(raw_obj, dict) else {}
        reply_to_obj = raw.get("replyTo")
        reply_to: dict[str, Any] = (
            reply_to_obj if isinstance(reply_to_obj, dict) else {}
        )
        target_msg_id = str(reply_to.get("messageId") or "").strip()
        if not target_msg_id:
            chat_jid = str(message.get("chatJid") or "")
            target = self._last_bot_message.get(chat_jid)
            if target:
                target_msg_id = target[1]
        if not thread_id or not target_msg_id:
            await self._reply(
                message,
                "ℹ️ Hãy reply vào một tin nhắn hoặc để bot gửi 1 tin nhắn trước khi dùng /pin.",
            )
            return
        actions = BridgeActions(self.listener._bridge)
        try:
            if pin:
                await actions.pin_message(thread_id, target_msg_id)
                await self._reply(message, f"📌 Đã ghim tin nhắn `{target_msg_id}`.")
            else:
                await actions.unpin_message(thread_id, target_msg_id)
                await self._reply(message, f"📍 Đã bỏ ghim tin nhắn `{target_msg_id}`.")
        except Exception as exc:
            await self._reply(
                message,
                f"⚠️ Không thể ghim/bỏ ghim tin nhắn: {_redact_bridge_text(str(exc))}",
            )

    async def _cmd_id(self, message: dict[str, Any], argument: str) -> None:
        await self._reply(
            message,
            f"🆔 type: {message.get('type')}\n"
            f"chatJid: {message.get('chatJid')}\n"
            f"threadID: {message.get('replyToID')}\n"
            f"userID: {message.get('userID')}\n"
            f"senderJid: {message.get('senderJid')}\n"
            f"messageID: {message.get('messageID')}",
        )

    async def _cmd_echo(self, message: dict[str, Any], argument: str) -> None:
        await self._reply(
            message, argument or f"Cách dùng: {self.prefix}echo <nội dung>"
        )

    async def _cmd_search(self, message: dict[str, Any], argument: str) -> None:
        query = " ".join(argument.split())
        if not query:
            await self._reply(message, f"Cách dùng: {self.prefix}search <từ khóa>")
            return
        if len(query) < SEARCH_QUERY_MIN_LENGTH:
            await self._reply(
                message,
                f"🔍 Từ khóa phải có ít nhất {SEARCH_QUERY_MIN_LENGTH} ký tự.",
            )
            return
        if len(query) > SEARCH_QUERY_MAX_LENGTH:
            await self._reply(
                message,
                f"🔍 Từ khóa không được vượt quá {SEARCH_QUERY_MAX_LENGTH} ký tự.",
            )
            return

        limit_scope = self._search_rate_limiter.check(str(message.get("userID") or ""))
        if limit_scope is not None:
            log("rate", f"Từ chối /search do chạm quota {limit_scope}; query đã ẩn.")
            await self._reply(
                message,
                "⏳ /search đang được dùng quá nhanh. Vui lòng thử lại sau.",
            )
            return

        result = await _search.func(self.dataIGS, query, client=self.http_client)
        users = result.get("searchResultsDict") if isinstance(result, dict) else None
        if not users:
            await self._reply(message, f"🔍 Không tìm thấy kết quả cho: {query}")
            return
        lines = [f"🔍 Kết quả cho “{query}”:"]
        lines.extend(
            f"{index}. {user.get('name')} - {user.get('id')}"
            for index, user in enumerate(users[:5], 1)
        )
        await self._reply(message, "\n".join(lines))

    async def _cmd_unsend(self, message: dict[str, Any], argument: str) -> None:
        sender_id = str(message.get("userID") or "")
        if not self.admins:
            await self._reply(message, "⛔ Lệnh này bị khóa vì chưa cấu hình admin.")
            return
        if sender_id not in self.admins:
            await self._reply(message, "⛔ Chỉ admin mới được dùng lệnh này.")
            return
        chat_jid = str(message.get("chatJid") or "")
        if not chat_jid:
            await self._reply(
                message, "Lệnh unsend E2EE cần chatJid, chat thường không dùng được."
            )
            return
        target = self._last_bot_message.get(chat_jid)
        if not target:
            await self._reply(
                message, "ℹ️ Chưa có tin E2EE nào để thu hồi trong chat này."
            )
            return
        target_chat_jid, target_message_id = target
        if self.listener._bridge is None:
            await self._reply(message, "Bridge E2EE chưa sẵn sàng để thu hồi.")
            return
        result = await BridgeActions(self.listener._bridge).unsend_e2ee_message(
            target_chat_jid, target_message_id
        )
        log("unsend", f"Đã gọi thu hồi E2EE; keys={sorted(result)}")
        self._last_bot_message.pop(chat_jid, None)

    async def _resolve_ig_pk(self, target: str) -> str:
        clean = target.strip().lstrip("@")
        if clean.isdigit():
            return clean
        if self.listener._bridge is not None:
            prof = await BridgeActions(self.listener._bridge).get_web_profile(clean)
            pk = str(prof.get("id") or "").strip()
            if pk.isdigit():
                return pk
        raise ValueError(f"Không phân giải được PK từ `{target}`.")

    async def _cmd_follow(self, message: dict[str, Any], argument: str) -> None:
        await self._toggle_follow(message, argument, unfollow=False)

    async def _cmd_unfollow(self, message: dict[str, Any], argument: str) -> None:
        await self._toggle_follow(message, argument, unfollow=True)

    async def _toggle_follow(
        self, message: dict[str, Any], argument: str, *, unfollow: bool
    ) -> None:
        sender_id = str(message.get("userID") or "")
        if not self.admins or sender_id not in self.admins:
            await self._reply(message, "⛔ Chỉ admin mới được dùng lệnh này.")
            return
        target = argument.strip()
        if not target:
            cmd = "unfollow" if unfollow else "follow"
            await self._reply(
                message, f"Cách dùng: {self.prefix}{cmd} <@username hoặc IG PK>"
            )
            return
        try:
            pk = await self._resolve_ig_pk(target)
        except Exception as exc:
            await self._reply(
                message,
                f"⚠️ Không tìm thấy người dùng `{target}`: {_redact_bridge_text(str(exc))}",
            )
            return
        res = (
            await _unFriend.unfollow_instagram_user(
                self.dataIGS, pk, client=self.http_client
            )
            if unfollow
            else await _unFriend.follow_instagram_user(
                self.dataIGS, pk, client=self.http_client
            )
        )
        if res.get("error"):
            await self._reply(
                message,
                f"⚠️ Không thể {'bỏ theo dõi' if unfollow else 'theo dõi'} `{target}`: {res.get('messages')}",
            )
            return
        await self._reply(
            message,
            (
                f"👋 Đã bỏ theo dõi `{target}` (PK: {pk})."
                if unfollow
                else f"➕ Đã theo dõi `{target}` (PK: {pk})."
            ),
        )

    async def _cmd_bio(self, message: dict[str, Any], argument: str) -> None:
        sender_id = str(message.get("userID") or "")
        if not self.admins or sender_id not in self.admins:
            await self._reply(message, "⛔ Chỉ admin mới được dùng lệnh này.")
            return
        new_bio = argument.strip()
        if not new_bio:
            await self._reply(
                message, f"Cách dùng: {self.prefix}bio <tiểu sử mới>"
            )
            return
        res = await _changeBio.change_instagram_bio(
            self.dataIGS, new_bio, client=self.http_client
        )
        if res.get("error"):
            await self._reply(
                message, f"⚠️ Không đổi được tiểu sử: {res.get('messages')}"
            )
            return
        await self._reply(message, f"📝 Đã cập nhật tiểu sử Instagram: {new_bio}")

    async def _cmd_deletethread(self, message: dict[str, Any], argument: str) -> None:
        sender_id = str(message.get("userID") or "")
        if not self.admins or sender_id not in self.admins:
            await self._reply(message, "⛔ Chỉ admin mới được dùng lệnh này.")
            return
        if self.listener._bridge is None:
            await self._reply(message, "Bridge E2EE chưa sẵn sàng.")
            return
        thread_id = int(message.get("replyToID") or 0)
        mark_spam = argument.strip().lower() == "spam"
        try:
            await BridgeActions(self.listener._bridge).delete_thread(
                thread_id, mark_as_spam=mark_spam
            )
            await self._reply(
                message,
                f"🗑️ Đã xóa hội thoại `{thread_id}`{' (đánh dấu Spam)' if mark_spam else ''}.",
            )
        except Exception as exc:
            await self._reply(
                message,
                f"⚠️ Không xóa được hội thoại: {_redact_bridge_text(str(exc))}",
            )

    async def _cmd_tagall(self, message: dict[str, Any], argument: str) -> None:
        if self.listener._bridge is None:
            await self._reply(message, "Bridge E2EE chưa sẵn sàng.")
            return
        thread_id = int(message.get("replyToID") or 0)
        if not thread_id:
            await self._reply(message, "⚠️ Không xác định được threadID.")
            return
        actions = BridgeActions(self.listener._bridge)
        try:
            detail = await actions.get_thread_info(thread_id, message_limit=1)
        except Exception as exc:
            await self._reply(
                message,
                f"⚠️ Không lấy được danh sách thành viên: {_redact_bridge_text(str(exc))}",
            )
            return
        participants = detail.get("participants")
        part_list = participants if isinstance(participants, list) else []
        header = argument.strip() or "📢 Thông báo tất cả thành viên:"
        text_parts = [f"@everyone {header}"]
        mention_ids: list[int] = [-1]
        mention_offsets: list[int] = [0]
        mention_lengths: list[int] = [len("@everyone")]
        current_text = text_parts[0]
        for p in part_list[:30]:
            if not isinstance(p, dict):
                continue
            pid = int(p.get("id") or 0)
            if not pid:
                continue
            tag_label = f"@{p.get('username') or p.get('name') or pid}"
            offset = len(current_text) + 1
            current_text = f"{current_text} {tag_label}"
            mention_ids.append(pid)
            mention_offsets.append(offset)
            mention_lengths.append(len(tag_label))
        try:
            res = await actions.send_message_with_mentions(
                thread_id,
                current_text,
                mention_ids=mention_ids,
                mention_offsets=mention_offsets,
                mention_lengths=mention_lengths,
                reply_to_id=str(message.get("messageID") or ""),
            )
            sent_id = res.get("messageId") or res.get("id")
            if sent_id:
                self._bot_sent_message_ids.add(str(sent_id))
                chat_jid = str(message.get("chatJid") or "")
                if chat_jid:
                    self._last_bot_message[chat_jid] = (chat_jid, str(sent_id))
        except Exception as exc:
            await self._reply(
                message,
                f"⚠️ Không gửi được tagall: {_redact_bridge_text(str(exc))}",
            )

    async def _cmd_comment(self, message: dict[str, Any], argument: str) -> None:
        parts = argument.strip().split(maxsplit=1)
        if len(parts) < 2:
            await self._reply(
                message,
                f"Cách dùng: {self.prefix}comment <link bài viết/reel hoặc shortcode> <nội dung bình luận>",
            )
            return
        target, comment_text = parts[0], parts[1].strip()
        res = await _deletePost.comment_instagram_media(
            self.dataIGS, target, comment_text, client=self.http_client
        )
        if res.get("error"):
            await self._reply(
                message,
                f"⚠️ Không đăng được bình luận lên `{target}`: {res.get('messages')}",
            )
            return
        await self._reply(
            message,
            f"💬 Đã đăng bình luận lên bài `{res.get('mediaId')}` (Comment ID: {res.get('commentId') or 'OK'}).",
        )

    async def _cmd_save(self, message: dict[str, Any], argument: str) -> None:
        await self._toggle_save(message, argument, unsave=False)

    async def _cmd_unsave(self, message: dict[str, Any], argument: str) -> None:
        await self._toggle_save(message, argument, unsave=True)

    async def _toggle_save(
        self, message: dict[str, Any], argument: str, *, unsave: bool
    ) -> None:
        target = argument.strip()
        if not target:
            cmd = "unsave" if unsave else "save"
            await self._reply(
                message,
                f"Cách dùng: {self.prefix}{cmd} <link bài viết/reel hoặc shortcode>",
            )
            return
        res = await _archivePost.save_instagram_media(
            self.dataIGS, target, unsave=unsave, client=self.http_client
        )
        if res.get("error"):
            await self._reply(
                message,
                f"⚠️ Không thể {'bỏ lưu' if unsave else 'lưu'} bài viết `{target}`: {res.get('messages')}",
            )
            return
        await self._reply(
            message,
            (
                f"🔖 Đã bỏ lưu bài viết `{res.get('mediaId')}` khỏi bộ sưu tập."
                if unsave
                else f"🔖 Đã lưu bài viết `{res.get('mediaId')}` vào bộ sưu tập."
            ),
        )

    async def _cmd_antiunsend(self, message: dict[str, Any], argument: str) -> None:
        thread_key = str(
            message.get("replyToID") or message.get("chatJid") or ""
        ).strip()
        if not thread_key:
            await self._reply(message, "⚠️ Không xác định được hội thoại hiện tại.")
            return
        mode = argument.strip().lower()
        if mode in {"on", "1", "true", "bat"}:
            enable = True
        elif mode in {"off", "0", "false", "tat"}:
            enable = False
        else:
            enable = thread_key not in self._anti_unsend_threads
        if enable:
            self._anti_unsend_threads.add(thread_key)
            await self._reply(
                message,
                "🕵️ Đã BẬT chế độ chống thu hồi & phát hiện sửa tin nhắn cho hội thoại này.",
            )
        else:
            self._anti_unsend_threads.discard(thread_key)
            await self._reply(
                message,
                "🕵️ Đã TẮT chế độ chống thu hồi & phát hiện sửa tin nhắn cho hội thoại này.",
            )

    async def _cmd_autodl(self, message: dict[str, Any], argument: str) -> None:
        thread_key = str(
            message.get("replyToID") or message.get("chatJid") or ""
        ).strip()
        if not thread_key:
            await self._reply(message, "⚠️ Không xác định được hội thoại hiện tại.")
            return
        mode = argument.strip().lower()
        if mode in {"on", "1", "true", "bat"}:
            enable = True
        elif mode in {"off", "0", "false", "tat"}:
            enable = False
        else:
            enable = thread_key not in self._autodl_threads
        if enable:
            self._autodl_threads.add(thread_key)
            await self._reply(
                message,
                "📥 Đã BẬT tự động bóc link tải khi phát hiện URL bài viết/Reel Instagram trong hội thoại này.",
            )
        else:
            self._autodl_threads.discard(thread_key)
            await self._reply(
                message,
                "📥 Đã TẮT tự động bóc link tải Instagram trong hội thoại này.",
            )

    async def _cmd_note(self, message: dict[str, Any], argument: str) -> None:
        sender_id = str(message.get("userID") or "")
        if not self.admins or sender_id not in self.admins:
            await self._reply(message, "⛔ Chỉ admin mới được dùng lệnh này.")
            return
        arg = argument.strip()
        parts = arg.split(maxsplit=1)
        sub = parts[0].lower() if parts else ""
        if not arg or sub == "list":
            res = await _createNotes.get_instagram_notes(
                self.dataIGS, client=self.http_client
            )
            if res.get("error"):
                await self._reply(
                    message, f"⚠️ Không lấy được danh sách Note: {res.get('messages')}"
                )
                return
            notes = res.get("notes") or []
            if not notes:
                await self._reply(message, "📝 Hiện không có Instagram Note nào đang hoạt động.")
                return
            lines = ["📝 Instagram Notes 24h hiện tại:"]
            for idx, item in enumerate(notes[:10], start=1):
                if isinstance(item, dict):
                    raw_u = item.get("user")
                    user_obj: dict[str, Any] = (
                        raw_u if isinstance(raw_u, dict) else {}
                    )
                    uname = user_obj.get("username") or item.get("user_id") or "?"
                    text = str(item.get("text") or "").strip() or "📝 (Note trống)"
                    nid = self._mask_auto_detect_id(
                        item.get("id") or item.get("inbox_tray_item_id") or ""
                    )
                    me_tag = " (Bạn)" if item.get("is_viewer") else ""
                    lines.append(f"{idx}. @{uname}{me_tag}: {text} (ID: {nid})")
            await self._reply(message, "\n".join(lines))
            return
        if sub in {"clear", "delete", "del"}:
            explicit_id = parts[1].strip() if len(parts) > 1 else ""
            my_note_id = explicit_id
            if not my_note_id:
                res = await _createNotes.get_instagram_notes(
                    self.dataIGS, client=self.http_client
                )
                notes_raw = res.get("notes")
                notes_list = notes_raw if isinstance(notes_raw, list) else []
                for n_item in notes_list:
                    if isinstance(n_item, dict) and n_item.get("is_viewer"):
                        my_note_id = str(
                            n_item.get("id") or n_item.get("inbox_tray_item_id") or ""
                        ).strip()
                        if my_note_id:
                            break
            if not my_note_id:
                await self._reply(message, "ℹ️ Không tìm thấy Note hiện tại của bạn để xóa.")
                return
            del_res = await _createNotes.delete_instagram_note(
                self.dataIGS, my_note_id, client=self.http_client
            )
            if del_res.get("error"):
                await self._reply(
                    message, f"⚠️ Không xóa được Note: {del_res.get('messages')}"
                )
                return
            await self._reply(message, f"🗑️ Đã xóa Instagram Note `{my_note_id}`.")
            return
        if sub in {"music", "nhac", "song", "🎵"} and len(parts) > 1:
            await self._cmd_notemusic(message, parts[1])
            return
        create_res = await _createNotes.create_instagram_note(
            self.dataIGS, arg, client=self.http_client
        )
        if create_res.get("error"):
            await self._reply(
                message, f"⚠️ Không đăng được Note: {create_res.get('messages')}"
            )
            return
        note_id_str = self._mask_auto_detect_id(create_res.get("noteID") or "")
        suffix = f" (ID: {note_id_str})" if note_id_str and note_id_str != "N/A" else ""
        await self._reply(
            message, f"📝 Đã đăng Instagram Note 24h: {arg[:80]}{suffix}"
        )

    async def _cmd_notemusic(self, message: dict[str, Any], argument: str) -> None:
        sender_id = str(message.get("userID") or "")
        if not self.admins or sender_id not in self.admins:
            await self._reply(message, "⛔ Chỉ admin mới được dùng lệnh này.")
            return
        arg = argument.strip()
        if not arg:
            await self._reply(
                message,
                f"Cách dùng:\n"
                f"• `{self.prefix}notemusic <tên bài hát>` — Đăng Note 24h bằng bài hát\n"
                f"• `{self.prefix}notemusic <tên bài hát> | <lời nhắn>` — Đăng Note kèm nhạc + chữ\n"
                f"• `{self.prefix}notemusic search <tên bài hát>` — Tìm danh sách bài hát & ID nhạc",
            )
            return
        parts = arg.split(maxsplit=1)
        if parts[0].lower() in {"search", "tim", "find"} and len(parts) > 1:
            q = parts[1].strip()
            sres = await _createNotes.search_instagram_music(
                self.dataIGS, q, client=self.http_client
            )
            if sres.get("error"):
                await self._reply(
                    message, f"⚠️ Không tìm được nhạc: {sres.get('messages')}"
                )
                return
            tracks = sres.get("tracks") or []
            if not tracks:
                await self._reply(
                    message, f"🎵 Không tìm thấy bài hát nào cho `{q}`."
                )
                return
            lines = [f"🎵 Kết quả tìm nhạc Note cho “{q}”:"]
            for idx, tr in enumerate(tracks[:8], start=1):
                if isinstance(tr, dict):
                    cid = self._mask_auto_detect_id(tr.get("audio_cluster_id") or "")
                    lines.append(
                        f"{idx}. {tr.get('title')} — {tr.get('display_artist')} (ID: {cid})"
                    )
            lines.append(
                f"💡 Gõ `{self.prefix}notemusic <tên bài hoặc ID> | <lời nhắn>` để đăng Note."
            )
            await self._reply(message, "\n".join(lines))
            return

        if "|" in arg:
            song_part, caption_part = arg.split("|", 1)
            song_query = song_part.strip()
            note_caption = caption_part.strip()
        else:
            song_query = arg
            note_caption = ""

        res = await _createNotes.create_instagram_music_note(
            self.dataIGS,
            song_query,
            note_caption,
            client=self.http_client,
        )
        if res.get("error"):
            await self._reply(
                message, f"⚠️ Không đăng được Note nhạc: {res.get('messages')}"
            )
            return
        title = str(res.get("music_title") or song_query).strip()
        artist = str(res.get("music_artist") or "").strip()
        song_label = f"🎵 {title} — {artist}" if artist else f"🎵 {title}"
        caption_label = f"\n💬 Lời nhắn: {note_caption}" if note_caption else ""
        nid = self._mask_auto_detect_id(res.get("noteID") or "")
        await self._reply(
            message,
            f"✅ Đã đăng Instagram Note nhạc 24h!\n"
            f"• Bài hát: {song_label}{caption_label}\n"
            f"• Note ID: {nid}",
        )

    async def _cmd_notif(self, message: dict[str, Any], argument: str) -> None:
        sender_id = str(message.get("userID") or "")
        if not self.admins or sender_id not in self.admins:
            await self._reply(message, "⛔ Chỉ admin mới được dùng lệnh này.")
            return
        res = await _notification.fetch_instagram_notifications(
            self.dataIGS, client=self.http_client
        )
        if res.get("error"):
            await self._reply(
                message, f"⚠️ Không lấy được thông báo: {res.get('messages')}"
            )
            return
        items = res.get("NotificationResults") or []
        if not items:
            await self._reply(message, "🔔 Không có thông báo mới.")
            return
        lines = ["🔔 Thông báo Instagram gần đây:"] + [str(x) for x in items[:10]]
        await self._reply(message, "\n".join(lines))

    async def _cmd_post(self, message: dict[str, Any], argument: str) -> None:
        sender_id = str(message.get("userID") or "")
        if not self.admins or sender_id not in self.admins:
            await self._reply(message, "⛔ Chỉ admin mới được dùng lệnh này.")
            return
        parts = argument.strip().split(maxsplit=1)
        if not parts:
            await self._reply(
                message, f"Cách dùng: {self.prefix}post <url_ảnh> [caption]"
            )
            return
        media_url = parts[0]
        caption = parts[1] if len(parts) > 1 else ""
        res = await _createPost.publish_instagram_photo(
            self.dataIGS, media_url, caption, is_story=False, client=self.http_client
        )
        if res.get("error"):
            await self._reply(
                message, f"⚠️ Không đăng được bài viết: {res.get('messages')}"
            )
            return
        await self._reply(
            message,
            f"📸 Đã đăng ảnh lên Feed Instagram!\n🔗 Link: {res.get('urlPost') or res.get('mediaID')}",
        )

    async def _cmd_upstory(self, message: dict[str, Any], argument: str) -> None:
        sender_id = str(message.get("userID") or "")
        if not self.admins or sender_id not in self.admins:
            await self._reply(message, "⛔ Chỉ admin mới được dùng lệnh này.")
            return
        media_url = argument.strip()
        if not media_url:
            await self._reply(
                message, f"Cách dùng: {self.prefix}upstory <url_ảnh>"
            )
            return
        res = await _createPost.publish_instagram_photo(
            self.dataIGS, media_url, "", is_story=True, client=self.http_client
        )
        if res.get("error"):
            await self._reply(
                message, f"⚠️ Không đăng được Story: {res.get('messages')}"
            )
            return
        await self._reply(
            message,
            f"✨ Đã đăng ảnh lên Story 24h Instagram! (ID: {res.get('mediaID')})",
        )

    async def _cmd_more(self, message: dict[str, Any], argument: str) -> None:
        if self.listener._bridge is None:
            await self._reply(message, "Bridge E2EE chưa sẵn sàng.")
            return
        thread_id = int(message.get("replyToID") or 0)
        if not thread_id:
            await self._reply(message, "⚠️ Không xác định được threadID.")
            return
        arg = argument.strip().lower()
        if arg == "reset":
            self._thread_cursors.pop(thread_id, None)
            await self._reply(message, "🔄 Đã đặt lại con trỏ phân trang tin nhắn.")
            return
        limit = 10
        if arg.isdigit():
            limit = max(1, min(50, int(arg)))
        cursor = self._thread_cursors.get(thread_id, "")
        try:
            page = await BridgeActions(self.listener._bridge).paginate_messages(
                thread_id, cursor=cursor, limit=limit
            )
        except Exception as exc:
            await self._reply(
                message,
                f"⚠️ Không tải thêm được tin nhắn: {_redact_bridge_text(str(exc))}",
            )
            return
        msgs = page.get("messages") if isinstance(page.get("messages"), list) else []
        next_cursor = str(page.get("nextCursor") or "")
        has_next = bool(page.get("hasNextPage"))
        if next_cursor:
            self._thread_cursors[thread_id] = next_cursor
        if not msgs:
            await self._reply(message, "📭 Không còn tin nhắn cũ hơn trong hội thoại này.")
            return
        lines = [f"📜 Tải thêm {len(msgs)} tin nhắn cũ (còn tiếp: {'Có' if has_next else 'Không'}):"]
        for m in msgs[:15]:
            if isinstance(m, dict):
                sender = m.get("senderId") or "?"
                txt = m.get("text") or "[Media]"
                lines.append(f"• [{sender}]: {txt[:80]}")
        await self._reply(message, "\n".join(lines))




async def main() -> None:
    config = load_config()
    log("boot", "Đang khởi tạo dataIGS từ cookie...")
    dataIGS = await dataGetHome(
        storage=FileSessionStorage(str(CONFIG_PATH), key="cookies")
    )
    if not is_valid_dataigs(dataIGS):
        raise RuntimeError(
            "Không lấy được dataIGS hợp lệ; cookie đã hết hạn hoặc HTML token đã đổi."
        )
    async with httpx.AsyncClient(timeout=DEFAULT_HTTP_TIMEOUT) as http_client:
        bot = SimpleBot(
            dataIGS,
            prefix=config["prefix"],
            admins=config["admins"],
            log_message_content=config["log_message_content"],
            debug_errors=config["debug_errors"],
            http_client=http_client,
        )
        await bot.run()


def main_blocking() -> None:
    configure_utf8_console()
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log("bot", "Đã dừng theo yêu cầu người dùng.")
    except (RuntimeError, ValueError, json.JSONDecodeError) as error:
        log("boot", f"❌ {_format_exception_chain(error)}")
        raise SystemExit(1) from error


if __name__ == "__main__":
    main_blocking()
