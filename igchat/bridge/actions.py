"""High-level async Instagram Direct JSON-RPC actions over BridgeProcess."""

from __future__ import annotations

import base64
from collections.abc import Sequence
from typing import Any

from ..core.errors import BridgeError, SecurityViolationError
from ..core.http import validate_public_http_url
from .process import BridgeProcess
from .reconnect import ConnectionStatus

MAX_INLINE_MEDIA_BYTES = 25 * 1024 * 1024


def _coerce_int_id(value: int | str, label: str = "id") -> int:
    if isinstance(value, bool):
        raise ValueError(f"{label} không hợp lệ.")
    if isinstance(value, int):
        if value <= 0:
            raise ValueError(f"{label} phải là số nguyên dương.")
        return value
    cleaned = str(value).strip()
    if not cleaned.isdigit() or int(cleaned) <= 0:
        raise ValueError(f"{label} phải là số nguyên dương hợp lệ.")
    return int(cleaned)


def _encode_media_bytes(data: bytes) -> str:
    if not isinstance(data, (bytes, bytearray)) or len(data) == 0:
        raise ValueError("Dữ liệu media không được rỗng.")
    if len(data) > MAX_INLINE_MEDIA_BYTES:
        raise SecurityViolationError(
            f"Media vượt quá giới hạn {MAX_INLINE_MEDIA_BYTES} bytes."
        )
    return base64.b64encode(bytes(data)).decode("ascii")


class BridgeActions:
    """Async RPC client wrapping all Instagram Direct methods of `igchat-bridge`."""

    def __init__(
        self, process: BridgeProcess, *, default_timeout: float = 30.0
    ) -> None:
        self._process = process
        self._default_timeout = default_timeout

    @property
    def process(self) -> BridgeProcess:
        return self._process

    async def status(self, *, timeout: float = 10.0) -> ConnectionStatus:
        raw = await self._process.call("isConnected", {}, timeout=timeout)
        return ConnectionStatus.from_rpc(raw)

    async def send_message(
        self,
        thread_id: int | str,
        text: str,
        *,
        reply_to_id: str = "",
        mention_ids: Sequence[int | str] | None = None,
        mention_offsets: Sequence[int] | None = None,
        mention_lengths: Sequence[int] | None = None,
        attachment_fb_ids: Sequence[int | str] | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        clean_text = str(text)
        if not clean_text and not attachment_fb_ids:
            raise ValueError("Tin nhắn phải có text hoặc attachment_fb_ids.")
        params: dict[str, Any] = {
            "threadId": _coerce_int_id(thread_id, "thread_id"),
            "text": clean_text,
        }
        if reply_to_id:
            params["replyToId"] = reply_to_id
        if mention_ids:
            params["mentionIds"] = [
                _coerce_int_id(uid, "mention_id") for uid in mention_ids
            ]
        if mention_offsets is not None:
            params["mentionOffsets"] = [int(x) for x in mention_offsets]
        if mention_lengths is not None:
            params["mentionLengths"] = [int(x) for x in mention_lengths]
        if attachment_fb_ids:
            params["attachmentFbIds"] = [
                _coerce_int_id(aid, "attachment_id") for aid in attachment_fb_ids
            ]
        return await self._process.call(
            "sendMessage", params, timeout=timeout or self._default_timeout
        )

    async def edit_message(
        self,
        thread_id: int | str,
        message_id: str,
        new_text: str,
        *,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        if not message_id.strip():
            raise ValueError("message_id không được để trống.")
        if not new_text.strip():
            raise ValueError("new_text không được để trống.")
        return await self._process.call(
            "editMessage",
            {
                "threadId": _coerce_int_id(thread_id, "thread_id"),
                "messageId": message_id.strip(),
                "newText": new_text,
            },
            timeout=timeout or self._default_timeout,
        )

    async def unsend_message(
        self,
        thread_id: int | str,
        message_id: str,
        *,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        if not message_id.strip():
            raise ValueError("message_id không được để trống.")
        return await self._process.call(
            "unsendMessage",
            {
                "threadId": _coerce_int_id(thread_id, "thread_id"),
                "messageId": message_id.strip(),
            },
            timeout=timeout or self._default_timeout,
        )

    async def send_reaction(
        self,
        thread_id: int | str,
        message_id: str,
        emoji: str = "",
        *,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        if not message_id.strip():
            raise ValueError("message_id không được để trống.")
        return await self._process.call(
            "sendReaction",
            {
                "threadId": _coerce_int_id(thread_id, "thread_id"),
                "messageId": message_id.strip(),
                "emoji": emoji,
            },
            timeout=timeout or self._default_timeout,
        )

    async def send_typing(
        self,
        thread_id: int | str,
        *,
        is_typing: bool = True,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        return await self._process.call(
            "sendTypingIndicator",
            {
                "threadId": _coerce_int_id(thread_id, "thread_id"),
                "isTyping": bool(is_typing),
            },
            timeout=timeout or self._default_timeout,
        )

    async def mark_read(
        self,
        thread_id: int | str,
        watermark_ts_ms: int,
        *,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        return await self._process.call(
            "markRead",
            {
                "threadId": _coerce_int_id(thread_id, "thread_id"),
                "watermarkTs": int(watermark_ts_ms),
            },
            timeout=timeout or self._default_timeout,
        )

    async def pin_message(
        self,
        thread_id: int | str,
        message_id: str,
        *,
        pinned: bool = True,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        if not message_id.strip():
            raise ValueError("message_id không được để trống.")
        method = "pinMessage" if pinned else "unpinMessage"
        return await self._process.call(
            method,
            {
                "threadId": _coerce_int_id(thread_id, "thread_id"),
                "messageId": message_id.strip(),
            },
            timeout=timeout or self._default_timeout,
        )

    async def pin_thread(
        self,
        thread_id: int | str,
        *,
        pinned: bool = True,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        return await self._process.call(
            "pinThread",
            {
                "threadId": _coerce_int_id(thread_id, "thread_id"),
                "pin": bool(pinned),
            },
            timeout=timeout or self._default_timeout,
        )

    async def mute_thread(
        self,
        thread_id: int | str,
        mute_seconds: int,
        *,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        return await self._process.call(
            "muteThread",
            {
                "threadId": _coerce_int_id(thread_id, "thread_id"),
                "muteSeconds": int(mute_seconds),
            },
            timeout=timeout or self._default_timeout,
        )

    async def rename_thread(
        self,
        thread_id: int | str,
        new_name: str,
        *,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        return await self._process.call(
            "renameThread",
            {
                "threadId": _coerce_int_id(thread_id, "thread_id"),
                "newName": new_name.strip(),
            },
            timeout=timeout or self._default_timeout,
        )

    async def delete_thread(
        self,
        thread_id: int | str,
        *,
        mark_as_spam: bool = False,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        return await self._process.call(
            "deleteThread",
            {
                "threadId": _coerce_int_id(thread_id, "thread_id"),
                "markAsSpam": bool(mark_as_spam),
            },
            timeout=timeout or self._default_timeout,
        )

    async def accept_message_request(
        self,
        thread_id: int | str,
        *,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        return await self._process.call(
            "acceptMessageRequest",
            {"threadId": _coerce_int_id(thread_id, "thread_id")},
            timeout=timeout or self._default_timeout,
        )

    async def create_group(
        self,
        user_ids: Sequence[int | str],
        *,
        title: str = "",
        timeout: float | None = None,
    ) -> dict[str, Any]:
        ids = [_coerce_int_id(uid, "user_id") for uid in user_ids]
        if len(ids) < 2:
            raise ValueError("Tạo nhóm Direct cần ít nhất 2 thành viên.")
        params: dict[str, Any] = {"userIds": ids}
        if title.strip():
            params["title"] = title.strip()
        return await self._process.call(
            "createGroup", params, timeout=timeout or self._default_timeout
        )

    async def add_group_members(
        self,
        thread_id: int | str,
        user_ids: Sequence[int | str],
        *,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        ids = [_coerce_int_id(uid, "user_id") for uid in user_ids]
        if not ids:
            raise ValueError("Cần ít nhất 1 user_id để thêm vào nhóm.")
        return await self._process.call(
            "addGroupMembers",
            {
                "threadId": _coerce_int_id(thread_id, "thread_id"),
                "userIds": ids,
            },
            timeout=timeout or self._default_timeout,
        )

    async def remove_group_member(
        self,
        thread_id: int | str,
        user_id: int | str,
        *,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        return await self._process.call(
            "removeGroupMember",
            {
                "threadId": _coerce_int_id(thread_id, "thread_id"),
                "userId": _coerce_int_id(user_id, "user_id"),
            },
            timeout=timeout or self._default_timeout,
        )

    async def modify_group_admins(
        self,
        thread_id: int | str,
        user_ids: Sequence[int | str],
        *,
        promote: bool = True,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        ids = [_coerce_int_id(uid, "user_id") for uid in user_ids]
        if not ids:
            raise ValueError("Cần ít nhất 1 user_id để chỉnh quyền quản trị.")
        return await self._process.call(
            "modifyGroupAdmins",
            {
                "threadId": _coerce_int_id(thread_id, "thread_id"),
                "userIds": ids,
                "promote": bool(promote),
            },
            timeout=timeout or self._default_timeout,
        )

    async def leave_group(
        self,
        thread_id: int | str,
        *,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        return await self._process.call(
            "leaveGroup",
            {"threadId": _coerce_int_id(thread_id, "thread_id")},
            timeout=timeout or self._default_timeout,
        )

    async def set_user_blocked(
        self,
        user_id: int | str,
        *,
        blocked: bool = True,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        clean = str(user_id).strip()
        if not clean:
            raise ValueError("user_id không được để trống.")
        return await self._process.call(
            "setUserBlocked",
            {"userId": clean, "blocked": bool(blocked)},
            timeout=timeout or self._default_timeout,
        )

    async def send_image(
        self,
        thread_id: int | str,
        data: bytes,
        *,
        filename: str = "image.jpg",
        caption: str = "",
        reply_to_id: str = "",
        timeout: float = 60.0,
    ) -> dict[str, Any]:
        return await self._process.call(
            "sendImage",
            {
                "threadId": _coerce_int_id(thread_id, "thread_id"),
                "data": _encode_media_bytes(data),
                "filename": filename or "image.jpg",
                "caption": caption,
                "replyToId": reply_to_id,
            },
            timeout=timeout,
        )

    async def send_video(
        self,
        thread_id: int | str,
        data: bytes,
        *,
        filename: str = "video.mp4",
        caption: str = "",
        reply_to_id: str = "",
        timeout: float = 90.0,
    ) -> dict[str, Any]:
        return await self._process.call(
            "sendVideo",
            {
                "threadId": _coerce_int_id(thread_id, "thread_id"),
                "data": _encode_media_bytes(data),
                "filename": filename or "video.mp4",
                "caption": caption,
                "replyToId": reply_to_id,
            },
            timeout=timeout,
        )

    async def send_voice(
        self,
        thread_id: int | str,
        data: bytes,
        *,
        filename: str = "voice.m4a",
        reply_to_id: str = "",
        timeout: float = 60.0,
    ) -> dict[str, Any]:
        return await self._process.call(
            "sendVoice",
            {
                "threadId": _coerce_int_id(thread_id, "thread_id"),
                "data": _encode_media_bytes(data),
                "filename": filename or "voice.m4a",
                "replyToId": reply_to_id,
            },
            timeout=timeout,
        )

    async def send_file(
        self,
        thread_id: int | str,
        data: bytes,
        *,
        filename: str = "attachment.bin",
        mime_type: str = "application/octet-stream",
        caption: str = "",
        reply_to_id: str = "",
        timeout: float = 90.0,
    ) -> dict[str, Any]:
        return await self._process.call(
            "sendFile",
            {
                "threadId": _coerce_int_id(thread_id, "thread_id"),
                "data": _encode_media_bytes(data),
                "filename": filename or "attachment.bin",
                "mimeType": mime_type or "application/octet-stream",
                "caption": caption,
                "replyToId": reply_to_id,
            },
            timeout=timeout,
        )

    async def send_media_from_url(
        self,
        thread_id: int | str,
        url: str,
        *,
        filename: str = "",
        mime_type: str = "",
        reply_to_id: str = "",
        is_voice: bool = False,
        timeout: float = 90.0,
    ) -> dict[str, Any]:
        clean_url = validate_public_http_url(url, resolve_dns=False)
        params: dict[str, Any] = {
            "threadId": _coerce_int_id(thread_id, "thread_id"),
            "url": clean_url,
            "isVoice": bool(is_voice),
        }
        if filename:
            params["filename"] = filename
        if mime_type:
            params["mimeType"] = mime_type
        if reply_to_id:
            params["replyToId"] = reply_to_id
        return await self._process.call("sendMediaFromURL", params, timeout=timeout)

    async def download_media(self, url: str, *, timeout: float = 60.0) -> bytes:
        clean_url = validate_public_http_url(url, resolve_dns=False)
        result = await self._process.call(
            "downloadMedia", {"url": clean_url}, timeout=timeout
        )
        encoded = result.get("data")
        if not isinstance(encoded, str) or not encoded:
            raise ValueError("Bridge không trả về dữ liệu media hợp lệ.")
        return base64.b64decode(encoded, validate=True)

    async def edit_group_avatar(
        self,
        thread_id: int | str,
        image_url: str,
        *,
        timeout: float = 60.0,
    ) -> dict[str, Any]:
        clean = image_url.strip()
        if clean.lower() in {"", "clear", "remove", "delete"}:
            clean_url = "clear"
        else:
            clean_url = validate_public_http_url(clean, resolve_dns=False)
        return await self._process.call(
            "editGroupAvatar",
            {
                "threadId": _coerce_int_id(thread_id, "thread_id"),
                "imageUrl": clean_url,
            },
            timeout=timeout,
        )

    async def forward_message(
        self,
        source_thread_id: int | str,
        target_thread_id: int | str,
        *,
        message_id: str = "",
        text: str = "",
        timeout: float | None = None,
    ) -> dict[str, Any]:
        return await self._process.call(
            "forwardMessage",
            {
                "sourceThreadId": _coerce_int_id(source_thread_id, "source_thread_id"),
                "targetThreadId": _coerce_int_id(target_thread_id, "target_thread_id"),
                "messageId": message_id,
                "text": text,
            },
            timeout=timeout or self._default_timeout,
        )

    async def search_users(
        self, query: str, *, timeout: float | None = None
    ) -> list[dict[str, Any]]:
        clean = query.strip()
        if not clean:
            raise ValueError("Từ khóa tìm kiếm không được rỗng.")
        res = await self._process.call(
            "searchUsers", {"query": clean}, timeout=timeout or self._default_timeout
        )
        users = res.get("users")
        return users if isinstance(users, list) else []

    async def get_user_info(
        self, user_id: int | str, *, timeout: float | None = None
    ) -> dict[str, Any]:
        return await self._process.call(
            "getUserInfo",
            {"userId": _coerce_int_id(user_id, "user_id")},
            timeout=timeout or self._default_timeout,
        )

    async def get_web_profile(
        self, identifier: str, *, timeout: float | None = None
    ) -> dict[str, Any]:
        clean = identifier.strip().lstrip("@")
        if not clean:
            raise ValueError("identifier không được rỗng.")
        return await self._process.call(
            "getWebProfile",
            {"identifier": clean},
            timeout=timeout or self._default_timeout,
        )

    async def fetch_stories(
        self, identifier: str, *, timeout: float | None = None
    ) -> dict[str, Any]:
        clean = identifier.strip()
        if not clean:
            raise ValueError("identifier không được rỗng.")
        return await self._process.call(
            "fetchStories",
            {"identifier": clean},
            timeout=timeout or self._default_timeout,
        )

    async def fetch_media(
        self, url_or_shortcode: str, *, timeout: float | None = None
    ) -> dict[str, Any]:
        clean = url_or_shortcode.strip()
        if not clean:
            raise ValueError("URL hoặc shortcode không được rỗng.")
        return await self._process.call(
            "fetchMedia",
            {"input": clean},
            timeout=timeout or self._default_timeout,
        )

    fetch_media_by_shortcode = fetch_media

    async def get_inbox(self, *, timeout: float | None = None) -> list[dict[str, Any]]:
        res = await self._process.call(
            "getInbox", {}, timeout=timeout or self._default_timeout
        )
        threads = res.get("threads")
        return threads if isinstance(threads, list) else []

    async def get_message_requests(
        self, *, timeout: float | None = None
    ) -> list[dict[str, Any]]:
        res = await self._process.call(
            "getMessageRequests", {}, timeout=timeout or self._default_timeout
        )
        threads = res.get("threads")
        return threads if isinstance(threads, list) else []

    async def get_thread_info(
        self,
        thread_id: int | str,
        *,
        message_limit: int = 20,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        return await self._process.call(
            "getThreadInfo",
            {
                "threadId": _coerce_int_id(thread_id, "thread_id"),
                "messageLimit": max(1, min(100, int(message_limit))),
            },
            timeout=timeout or self._default_timeout,
        )

    async def paginate_inbox(
        self,
        *,
        cursor: str = "",
        folder: str = "INBOX",
        timeout: float | None = None,
    ) -> dict[str, Any]:
        return await self._process.call(
            "paginateInbox",
            {"cursor": cursor, "folder": folder or "INBOX"},
            timeout=timeout or self._default_timeout,
        )

    async def paginate_messages(
        self,
        thread_id: int | str,
        *,
        cursor: str = "",
        limit: int = 20,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        return await self._process.call(
            "paginateMessages",
            {
                "threadId": _coerce_int_id(thread_id, "thread_id"),
                "cursor": cursor,
                "limit": max(1, min(50, int(limit))),
            },
            timeout=timeout or self._default_timeout,
        )

    async def get_unread_count(self, *, timeout: float | None = None) -> int:
        try:
            res = await self._process.call(
                "getUnreadCount", {}, timeout=timeout or self._default_timeout
            )
            return int(res.get("unreadCount", 0))
        except BridgeError:
            inbox = await self.get_inbox(timeout=timeout)
            return sum(1 for t in inbox if t.get("isUnread") or t.get("unread"))
