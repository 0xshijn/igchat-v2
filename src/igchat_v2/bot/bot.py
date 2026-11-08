"""Async reference Instagram Direct automation bot built on DirectListener."""

from __future__ import annotations

import asyncio
import json
import re
import signal
import time
from collections import OrderedDict, deque
from collections.abc import Iterable, Mapping
from contextlib import suppress
from pathlib import Path
from typing import Any, Generic, TypeVar

import httpx

from ..auth.session import bootstrap_session
from ..auth.storage import EnvSessionStorage, FileSessionStorage
from ..bridge.actions import BridgeActions
from ..core.console import configure_utf8_console, safe_print
from ..core.models import InstagramSession, normalize_session
from ..core.permissions import require_private_file
from ..core.redact import redact_sensitive_text
from ..direct.listener import DirectListener
from ..direct.notes import create_note, delete_note, fetch_notes, search_note_music
from ..social.friendships import block_user, follow_user, unblock_user, unfollow_user
from ..social.notifications import fetch_notifications
from ..social.posts import comment_media, like_media, publish_photo, save_media
from ..social.profile import change_bio

K = TypeVar("K")
V = TypeVar("V")

IG_MEDIA_URL_RE = re.compile(
    r"https?://(?:www\.)?instagram\.com/(?:p|reel|reels|tv)/([A-Za-z0-9_-]+)",
    re.IGNORECASE,
)


class _BoundedLRU(Generic[K, V]):
    """OrderedDict-backed bounded cache preserving insertion/access recency."""

    def __init__(self, maxsize: int = 2048) -> None:
        self._maxsize = max(16, int(maxsize))
        self._data: OrderedDict[K, V] = OrderedDict()

    def get(self, key: K, default: V | None = None) -> V | None:
        if key not in self._data:
            return default
        self._data.move_to_end(key)
        return self._data[key]

    def set(self, key: K, value: V) -> None:
        self._data[key] = value
        self._data.move_to_end(key)
        while len(self._data) > self._maxsize:
            self._data.popitem(last=False)

    def pop(self, key: K, default: V | None = None) -> V | None:
        return self._data.pop(key, default)

    def __contains__(self, key: object) -> bool:
        return key in self._data

    def __len__(self) -> int:
        return len(self._data)


class PerUserRateLimiter:
    """Sliding-window per-sender rate limiter with bounded bucket eviction."""

    def __init__(
        self,
        *,
        max_calls: int = 6,
        window_seconds: float = 10.0,
        max_users: int = 2048,
    ) -> None:
        self.max_calls = max(1, int(max_calls))
        self.window_seconds = max(0.5, float(window_seconds))
        self._max_users = max(32, int(max_users))
        self._buckets: OrderedDict[str, deque[float]] = OrderedDict()

    def allow(self, sender_id: str, *, now: float | None = None) -> bool:
        current = time.monotonic() if now is None else float(now)
        bucket = self._buckets.get(sender_id)
        if bucket is None:
            bucket = deque()
            self._buckets[sender_id] = bucket
            while len(self._buckets) > self._max_users:
                self._buckets.popitem(last=False)
        else:
            self._buckets.move_to_end(sender_id)

        cutoff = current - self.window_seconds
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()
        if len(bucket) >= self.max_calls:
            return False
        bucket.append(current)
        return True


def load_bot_config(config_path: str | Path) -> dict[str, Any]:
    """Load and validate bot JSON config without leaking credentials on error."""
    target = require_private_file(config_path)
    try:
        loaded = json.loads(target.read_text(encoding="utf-8", errors="strict"))
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"File cấu hình không phải JSON hợp lệ: {target.name}"
        ) from exc
    if not isinstance(loaded, dict):
        raise ValueError("Cấu hình bot phải là JSON object.")

    prefix = str(loaded.get("prefix") or "/").strip() or "/"
    raw_admins = loaded.get("admins") or []
    admins = {str(item).strip().lstrip("#@") for item in raw_admins if str(item).strip()}
    cookies = str(loaded.get("cookies") or loaded.get("cookie") or "").strip()
    if cookies.upper().startswith("PASTE_YOUR_"):
        cookies = ""

    return {
        "cookies": cookies,
        "prefix": prefix,
        "admins": admins,
        "auto_download_links": bool(loaded.get("auto_download_links", False)),
    }


class InstagramBot:
    """Async command & anti-unsend automation bot for Instagram Direct."""

    def __init__(
        self,
        session: InstagramSession | Mapping[str, Any],
        listener: DirectListener,
        *,
        prefix: str = "/",
        admins: Iterable[str | int] = (),
        auto_download_links: bool = False,
        rate_limiter: PerUserRateLimiter | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.session = normalize_session(session)
        self.listener = listener
        self.prefix = prefix.strip() or "/"
        self.admins = {str(uid).strip() for uid in admins if str(uid).strip()}
        self.auto_download_links = auto_download_links
        self.rate_limiter = rate_limiter or PerUserRateLimiter()
        self.http_client = http_client

        self.anti_unsend_threads: set[int] = set()
        self.anti_edit_threads: set[int] = set()
        self._processed_ids: _BoundedLRU[str, bool] = _BoundedLRU(4096)
        self._msg_cache: _BoundedLRU[str, dict[str, Any]] = _BoundedLRU(4096)
        self._last_bot_msg: _BoundedLRU[int, str] = _BoundedLRU(512)
        self._started_at = time.monotonic()

    @property
    def actions(self) -> BridgeActions:
        return self.listener.actions

    def is_admin(self, sender_id: int | str) -> bool:
        sid = str(sender_id).strip().lstrip("#@")
        my_ids = {
            self.session.ig_user_id,
            self.session.ds_user_id,
            self.session.eimu_id,
        }
        if self.listener and self.listener.user_info:
            u_id = self.listener.user_info.get("id")
            if u_id:
                my_ids.add(str(u_id).strip().lstrip("#@"))
        if sid in my_ids:
            return True
        clean_admins = {str(a).strip().lstrip("#@") for a in self.admins}
        return sid in clean_admins

    async def reply(
        self, thread_id: int, text: str, *, reply_to_id: str = ""
    ) -> dict[str, Any]:
        safe_print(f"[igchat-v2] Bot reply -> thread={thread_id}: {text!r}")
        try:
            result = await self.actions.send_message(
                thread_id, text, reply_to_id=reply_to_id
            )
        except Exception as exc:
            if reply_to_id:
                safe_print(
                    f"[igchat-v2] Quote reply thất bại ({exc}), gửi tin nhắn độc lập..."
                )
                result = await self.actions.send_message(thread_id, text)
            else:
                raise
        mid = str(result.get("messageId") or "").strip()
        if mid:
            self._last_bot_msg.set(thread_id, mid)
        return result

    async def handle_event(self, event: dict[str, Any]) -> None:
        event_type = str(event.get("type") or "")
        data = event.get("data")
        if not isinstance(data, dict):
            return

        if event_type == "message":
            await self._on_message(data)
        elif event_type == "messageUnsend":
            await self._on_message_unsend(data)
        elif event_type == "messageEdit":
            await self._on_message_edit(data)

    async def _on_message(self, data: dict[str, Any]) -> None:
        msg_id = str(data.get("id") or "").strip()
        raw_thread = data.get("threadId") or data.get("thread_id")
        try:
            thread_id = int(raw_thread) if raw_thread is not None else 0
        except (ValueError, TypeError):
            thread_id = 0
        sender_id = str(data.get("senderId") or data.get("sender_id") or "").strip()
        text = str(data.get("text") or "")

        if thread_id <= 0 or not msg_id:
            return
        if msg_id in self._processed_ids:
            return
        self._processed_ids.set(msg_id, True)
        self._msg_cache.set(msg_id, data)

        self_ids = {self.session.ig_user_id, self.session.eimu_id}
        if self.listener and self.listener.user_info:
            u_id = self.listener.user_info.get("id")
            if u_id:
                self_ids.add(str(u_id))
        is_self = sender_id in self_ids

        safe_print(
            f"[igchat-v2] Tin nhắn mới từ sender={sender_id} trong thread={thread_id} (is_self={is_self}): {text!r}"
        )

        if is_self and not text.strip().startswith(self.prefix):
            return

        stripped = text.strip()
        if stripped.startswith(self.prefix):
            if not is_self and not self.rate_limiter.allow(sender_id):
                safe_print(f"[igchat-v2] Rate limit hit cho sender={sender_id}")
                return
            await self._dispatch_command(thread_id, msg_id, sender_id, stripped)
            return

        # Friendly fallback khi người dùng gửi tin chào / test không có prefix
        lower = stripped.lower()
        if lower in {"hi", "hello", "ping", "test", "bot"}:
            if not is_self and not self.rate_limiter.allow(sender_id):
                return
            if lower in {"hi", "hello"}:
                await self.reply(
                    thread_id,
                    f"Chào bạn! Bot igchat-v2 v3.0.0 đang online. Gõ {self.prefix}help để xem danh sách lệnh nhé!",
                    reply_to_id=msg_id,
                )
            elif lower == "ping":
                uptime = int(time.monotonic() - self._started_at)
                await self.reply(
                    thread_id, f"pong! uptime={uptime}s", reply_to_id=msg_id
                )
            elif lower in {"test", "bot"}:
                await self.reply(
                    thread_id,
                    f"igchat-v2 bot online! Dùng {self.prefix}ping hoặc {self.prefix}help.",
                    reply_to_id=msg_id,
                )
            return

        if self.auto_download_links and not is_self:
            match = IG_MEDIA_URL_RE.search(stripped)
            if match:
                with suppress(Exception):
                    info = await self.actions.fetch_media(match.group(0))
                    urls = info.get("urls") or []
                    if urls:
                        await self.actions.send_media_from_url(
                            thread_id, str(urls[0]), reply_to_id=msg_id
                        )

    async def _on_message_unsend(self, data: dict[str, Any]) -> None:
        raw_thread = data.get("threadId") or data.get("thread_id")
        try:
            thread_id = int(raw_thread) if raw_thread is not None else 0
        except (ValueError, TypeError):
            thread_id = 0
        msg_id = str(data.get("messageId") or data.get("message_id") or "").strip()
        if thread_id <= 0 or thread_id not in self.anti_unsend_threads:
            return
        cached = self._msg_cache.get(msg_id)
        if not isinstance(cached, dict):
            return
        sender = str(cached.get("senderId") or cached.get("sender_id") or "unknown")
        old_text = str(cached.get("text") or "").strip() or "[media/no text]"
        await self.reply(
            thread_id,
            f"[anti-unsend] user={sender} đã thu hồi tin nhắn: {old_text}",
        )

    async def _on_message_edit(self, data: dict[str, Any]) -> None:
        raw_thread = data.get("threadId") or data.get("thread_id")
        try:
            thread_id = int(raw_thread) if raw_thread is not None else 0
        except (ValueError, TypeError):
            thread_id = 0
        msg_id = str(data.get("messageId") or data.get("message_id") or "").strip()
        new_text = str(data.get("newText") or data.get("new_text") or "").strip()
        if thread_id <= 0 or thread_id not in self.anti_edit_threads:
            return
        cached = self._msg_cache.get(msg_id)
        if not isinstance(cached, dict):
            return
        old_text = str(cached.get("text") or "").strip()
        if old_text and old_text != new_text:
            await self.reply(
                thread_id,
                f"[anti-edit]\nTrước: {old_text}\nSau: {new_text}",
                reply_to_id=msg_id,
            )

    async def _dispatch_command(
        self, thread_id: int, msg_id: str, sender_id: str, raw_text: str
    ) -> None:
        body = raw_text[len(self.prefix) :].strip()
        if not body:
            return
        parts = body.split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1].strip() if len(parts) > 1 else ""

        try:
            if cmd == "help":
                p = self.prefix
                help_text = (
                    "📖 Lệnh hỗ trợ igchat-v2 v3.0.0:\n"
                    f"• {p}hi - chào và kiểm tra bot\n"
                    f"• {p}ping - kiểm tra độ trễ\n"
                    f"• {p}help - hiển thị trợ giúp\n"
                    f"• {p}id - xem threadID + senderID\n"
                    f"• {p}info [id/user] - xem thông tin tài khoản Instagram\n"
                    f"• {p}profile <@user/id> - hồ sơ chi tiết (Bio, Follower, bài đăng)\n"
                    f"• {p}story <@user/id> - xem & lấy link tải Story 24h đang hoạt động\n"
                    f"• {p}follow / {p}unfollow <@user/id> - theo dõi/bỏ theo dõi\n"
                    f"• {p}bio <text> - đổi tiểu sử Instagram của bot (Admin)\n"
                    f"• {p}inbox - danh sách hội thoại gần đây\n"
                    f"• {p}thread / {p}history [số tin] - chi tiết chat & lịch sử tin nhắn\n"
                    f"• {p}deletethread [spam] - xóa hội thoại hiện tại (Admin)\n"
                    f"• {p}requests / {p}accept <id> - xem & duyệt tin nhắn chờ\n"
                    f"• {p}rename <tên> - đổi tên nhóm chat\n"
                    f"• {p}groupavatar <url|clear> - đổi hoặc xóa ảnh đại diện nhóm\n"
                    f"• {p}tagall / {p}everyone [lời nhắn] - tag toàn bộ thành viên nhóm\n"
                    f"• {p}mute / {p}unmute - tắt/bật thông báo hội thoại\n"
                    f"• {p}pinthread / {p}unpinthread - ghim/bỏ ghim hội thoại\n"
                    f"• {p}image <url> - tải ảnh từ URL và gửi vào chat\n"
                    f"• {p}voice <url> - gửi tin nhắn thoại từ URL âm thanh\n"
                    f"• {p}media - lấy link tải ảnh/video/voice/reel vừa gửi\n"
                    f"• {p}dl <url/code> - bóc tách & lấy link tải Post/Reel Instagram\n"
                    f"• {p}autodl [on|off] - tự động bóc link tải khi gửi link IG\n"
                    f"• {p}like / {p}unlike <url/code> - thả tim/bỏ tim bài viết/Reel\n"
                    f"• {p}comment <url/code> <nội dung> - bình luận vào bài viết/Reel\n"
                    f"• {p}save / {p}unsave <url/code> - lưu/bỏ lưu bài viết/Reel\n"
                    f"• {p}forward <threadID> [lời nhắn] - chuyển tiếp tin nhắn\n"
                    f"• {p}creategroup <id1,id2> [tên] - tạo nhóm chat mới\n"
                    f"• {p}add / {p}kick <id> - thêm/xóa thành viên nhóm\n"
                    f"• {p}promote / {p}demote <id> - thăng/hạ Admin nhóm\n"
                    f"• {p}leave - rời nhóm chat\n"
                    f"• {p}block / {p}unblock <id> - chặn/bỏ chặn người dùng\n"
                    f"• {p}echo <text> - lặp lại nội dung\n"
                    f"• {p}react [emoji] - thả cảm xúc vào tin nhắn\n"
                    f"• {p}edit <text> - sửa tin nhắn cuối của bot\n"
                    f"• {p}pin / {p}unpin - ghim/bỏ ghim tin nhắn\n"
                    f"• {p}search <từ> - tìm người dùng Instagram\n"
                    f"• {p}unsend - thu hồi tin nhắn cuối của bot\n"
                    f"• {p}antiunsend [on|off] - bật/tắt chống thu hồi tin nhắn\n"
                    f"• {p}antiedit [on|off] - bật/tắt phát hiện sửa tin nhắn\n"
                    f"• {p}note [text|clear|list] - xem, đăng hoặc xóa Ghi chú 24h (Admin)\n"
                    f"• {p}notemusic <tên bài hát> [| lời nhắn] - đăng Note 24h kèm bài hát (Admin)\n"
                    f"• {p}notif - xem thông báo hoạt động gần đây (Admin)\n"
                    f"• {p}post <url_ảnh> [caption] - đăng ảnh mới lên Feed (Admin)\n"
                    f"• {p}upstory <url_ảnh> - đăng ảnh lên Story 24h (Admin)\n"
                    f"• {p}more [số_tin] - tải thêm tin nhắn cũ hơn"
                )
                await self.reply(thread_id, help_text, reply_to_id=msg_id)
                return

            if cmd in {"hi", "hello"}:
                await self.reply(
                    thread_id,
                    f"👋 Chào bạn! Bot igchat-v2 v3.0.0 đang hoạt động. Gõ {self.prefix}help để xem danh sách lệnh nhé!",
                    reply_to_id=msg_id,
                )
                return

            if cmd == "echo":
                await self.reply(
                    thread_id,
                    arg or "Bạn chưa nhập nội dung echo!",
                    reply_to_id=msg_id,
                )
                return

            if cmd == "ping":
                uptime = int(time.monotonic() - self._started_at)
                await self.reply(
                    thread_id, f"🏓 Pong! Uptime: {uptime}s | Kết nối: OK", reply_to_id=msg_id
                )
                return

            if cmd in {"id", "uid"}:
                await self.reply(
                    thread_id,
                    f"• ThreadID: #{thread_id}\n• SenderID: #{sender_id}\n• BotID: #{self.session.ig_user_id}",
                    reply_to_id=msg_id,
                )
                return

            if cmd == "info":
                target = arg or sender_id
                prof = await self.actions.get_web_profile(target)
                await self.reply(
                    thread_id,
                    (
                        f"@{prof.get('username', '')} ({prof.get('fullName', '')})\n"
                        f"UID: #{prof.get('id')} | MessagingID: #{prof.get('messagingId', 0)}\n"
                        f"Followers: {prof.get('followerCount', 0):,} | "
                        f"Following: {prof.get('followingCount', 0):,} | "
                        f"Posts: {prof.get('postCount', 0):,}"
                    ),
                    reply_to_id=msg_id,
                )
                return

            if cmd == "profile":
                target = arg or sender_id
                prof = await self.actions.get_web_profile(target)
                bio = prof.get("biography") or "[Chưa cập nhật bio]"
                ext_url = prof.get("externalUrl") or "Không"
                await self.reply(
                    thread_id,
                    (
                        f"👤 Hồ sơ Instagram: @{prof.get('username', '')}\n"
                        f"• Tên: {prof.get('fullName', 'N/A')}\n"
                        f"• UID: #{prof.get('id')}\n"
                        f"• Bio: {bio}\n"
                        f"• Website: {ext_url}\n"
                        f"• Người theo dõi: {prof.get('followerCount', 0):,}\n"
                        f"• Đang theo dõi: {prof.get('followingCount', 0):,}\n"
                        f"• Tổng bài đăng: {prof.get('postCount', 0):,}"
                    ),
                    reply_to_id=msg_id,
                )
                return

            if cmd == "story" and arg:
                stories = await self.actions.fetch_stories(arg)
                items = stories.get("items") or []
                if not items:
                    await self.reply(
                        thread_id, f"Tài khoản @{arg} hiện không có Story 24h nào đang hoạt động.", reply_to_id=msg_id
                    )
                    return
                first_url = str(items[0].get("url") or "")
                await self.actions.send_media_from_url(
                    thread_id, first_url, reply_to_id=msg_id
                )
                return

            if cmd in {"follow", "unfollow"} and arg:
                clean_target = arg.strip().lstrip("@")
                uid_to_follow = clean_target
                if not uid_to_follow.isdigit():
                    with suppress(Exception):
                        p_info = await self.actions.get_web_profile(clean_target)
                        uid_to_follow = str(p_info.get("id") or "")
                if not uid_to_follow.isdigit():
                    await self.reply(thread_id, f"Không tìm thấy UID cho người dùng: {arg}", reply_to_id=msg_id)
                    return
                if cmd == "follow":
                    await follow_user(self.session, uid_to_follow, client=self.http_client)
                    await self.reply(thread_id, f"✅ Đã gửi yêu cầu theo dõi @{clean_target} (#{uid_to_follow}).", reply_to_id=msg_id)
                else:
                    await unfollow_user(self.session, uid_to_follow, client=self.http_client)
                    await self.reply(thread_id, f"✅ Đã hủy theo dõi @{clean_target} (#{uid_to_follow}).", reply_to_id=msg_id)
                return

            if cmd == "search" and arg:
                users = await self.actions.search_users(arg)
                if not users:
                    await self.reply(
                        thread_id, "Không tìm thấy kết quả.", reply_to_id=msg_id
                    )
                    return
                lines = [
                    f"@{u.get('username')} — {u.get('name')} (uid=#{u.get('id') or u.get('pk')})"
                    for u in users[:8]
                ]
                await self.reply(thread_id, "\n".join(lines), reply_to_id=msg_id)
                return

            if cmd == "image" and arg:
                await self.actions.send_media_from_url(thread_id, arg, reply_to_id=msg_id)
                return

            if cmd == "voice" and arg:
                await self.actions.send_media_from_url(thread_id, arg, is_voice=True, reply_to_id=msg_id)
                return

            if cmd == "media":
                cached = self._msg_cache.get(msg_id)
                target_data = cached
                if isinstance(cached, dict) and cached.get("replyTo"):
                    reply_mid = str(cached["replyTo"].get("messageId") or "")
                    if reply_mid and reply_mid in self._msg_cache:
                        target_data = self._msg_cache.get(reply_mid)
                atts = target_data.get("attachments") if isinstance(target_data, dict) else []
                if atts:
                    urls = [a.get("url") or a.get("previewUrl") for a in atts if a.get("url") or a.get("previewUrl")]
                    if urls:
                        await self.reply(thread_id, "🔗 Media URLs:\n" + "\n".join(str(u) for u in urls), reply_to_id=msg_id)
                        return
                await self.reply(thread_id, "Không tìm thấy URL tệp đính kèm trong tin nhắn này.", reply_to_id=msg_id)
                return

            if cmd == "dl" and arg:
                media = await self.actions.fetch_media(arg)
                urls = media.get("urls") or []
                if not urls:
                    await self.reply(
                        thread_id, "Không lấy được link media.", reply_to_id=msg_id
                    )
                    return
                await self.actions.send_media_from_url(
                    thread_id, str(urls[0]), reply_to_id=msg_id
                )
                return

            if cmd == "inbox":
                threads = await self.actions.get_inbox()
                summary = [
                    f"• #{t.get('id')} | {t.get('name') or 'Direct'} — {t.get('snippet', '')}"
                    for t in threads[:10]
                ]
                await self.reply(
                    thread_id,
                    "\n".join(summary) or "Hộp thư trống.",
                    reply_to_id=msg_id,
                )
                return

            if cmd == "unread":
                cnt = await self.actions.get_unread_count()
                await self.reply(
                    thread_id, f"Số thread chưa đọc: {cnt}", reply_to_id=msg_id
                )
                return

            if cmd in {"thread", "history"}:
                limit = int(arg) if arg.isdigit() else 5
                detail = await self.actions.get_thread_info(thread_id, message_limit=limit)
                msgs = detail.get("messages") or []
                msg_lines = []
                for m in msgs[-limit:]:
                    snd = m.get("senderId") or m.get("sender_id") or "unknown"
                    txt = m.get("text") or "[media/attachment]"
                    msg_lines.append(f"  [#{snd}]: {txt}")
                history_text = "\n".join(msg_lines) if msg_lines else "Chưa có tin nhắn nào."
                await self.reply(
                    thread_id,
                    (
                        f"📋 Thông tin hội thoại: {detail.get('name')} (ID: #{detail.get('id')})\n"
                        f"• Nhóm: {detail.get('isGroup')} | Muted: {detail.get('isMuted')}\n"
                        f"• Thành viên: {len(detail.get('participants') or [])}\n"
                        f"• Lịch sử {len(msg_lines)} tin nhắn gần nhất:\n{history_text}"
                    ),
                    reply_to_id=msg_id,
                )
                return

            if cmd == "requests":
                reqs = await self.actions.get_message_requests()
                lines = [f"• #{t.get('id')} | {t.get('name') or 'Direct'}" for t in reqs[:10]]
                await self.reply(
                    thread_id,
                    "\n".join(lines) or "Không có tin nhắn chờ.",
                    reply_to_id=msg_id,
                )
                return

            if cmd == "react":
                target_mid = msg_id
                cached = self._msg_cache.get(msg_id)
                if isinstance(cached, dict) and cached.get("replyTo"):
                    target_mid = str(cached["replyTo"].get("messageId") or msg_id)
                await self.actions.send_reaction(thread_id, target_mid, arg or "❤️")
                return

            if cmd == "note":
                if not self.is_admin(sender_id):
                    return
                arg_low = arg.lower().strip()
                if not arg or arg_low == "list":
                    res = await fetch_notes(self.session, client=self.http_client)
                    notes = res.get("notes") or []
                    lines = [
                        f"• [#{n.get('id')}] @{n.get('user', {}).get('username', '?')}: {n.get('text', '')}"
                        for n in notes[:10]
                        if isinstance(n, dict)
                    ]
                    await self.reply(thread_id, "\n".join(lines) or "Chưa có Notes nào.", reply_to_id=msg_id)
                elif arg_low == "clear":
                    res = await fetch_notes(self.session, client=self.http_client)
                    notes = res.get("notes") or []
                    deleted_any = False
                    my_note_ids = {
                        self.session.ig_user_id,
                        self.session.ds_user_id,
                        self.session.eimu_id,
                    }
                    for n in notes:
                        if (
                            isinstance(n, dict)
                            and str(n.get("user", {}).get("pk") or "") in my_note_ids
                        ):
                            await delete_note(
                                self.session, str(n.get("id")), client=self.http_client
                            )
                            deleted_any = True
                    await self.reply(
                        thread_id,
                        (
                            "✅ Đã xóa Note 24h hiện tại."
                            if deleted_any
                            else "Không tìm thấy Note của bot để xóa."
                        ),
                        reply_to_id=msg_id,
                    )
                else:
                    await create_note(self.session, arg, client=self.http_client)
                    await self.reply(
                        thread_id,
                        f'✅ Đã đăng Note 24h mới:\n"{arg}"',
                        reply_to_id=msg_id,
                    )
                return

            if cmd in {"delnote", "deletenote"} and arg:
                if not self.is_admin(sender_id):
                    return
                note_id = arg.strip().lstrip("#")
                await delete_note(self.session, note_id, client=self.http_client)
                await self.reply(
                    thread_id, f"✅ Đã xóa Note #{note_id}.", reply_to_id=msg_id
                )
                return

            if cmd == "notes":
                res = await fetch_notes(self.session, client=self.http_client)
                notes = res.get("notes") or []
                lines = [
                    f"• [#{n.get('id')}] @{n.get('user', {}).get('username', '?')}: {n.get('text', '')}"
                    for n in notes[:10]
                    if isinstance(n, dict)
                ]
                await self.reply(
                    thread_id, "\n".join(lines) or "Chưa có Notes.", reply_to_id=msg_id
                )
                return

            if cmd == "notemusic" and arg:
                if not self.is_admin(sender_id):
                    return
                song_part = arg
                note_msg = ""
                if "|" in arg:
                    song_part, note_msg = [p.strip() for p in arg.split("|", 1)]
                tracks = await search_note_music(self.session, song_part, client=self.http_client)
                if not tracks:
                    await self.reply(thread_id, f"Không tìm thấy bài hát: {song_part}", reply_to_id=msg_id)
                    return
                first_track = tracks[0]
                audio_id = first_track.get("audio_cluster_id")
                track_title = first_track.get("title", "Unknown")
                track_artist = first_track.get("display_artist", "Unknown")
                await create_note(self.session, note_msg, audio_cluster_id=audio_id, client=self.http_client)
                await self.reply(
                    thread_id,
                    f"✅ Đã đăng Note 24h kèm nhạc:\n🎵 {track_title} - {track_artist}" + (f"\n💬 {note_msg}" if note_msg else ""),
                    reply_to_id=msg_id,
                )
                return

            if cmd == "music" and arg:
                tracks = await search_note_music(
                    self.session, arg, client=self.http_client
                )
                lines = [
                    f"• {t.get('audio_cluster_id', '')} | {t.get('title', '')} - {t.get('display_artist', '')}"
                    for t in tracks[:5]
                ]
                await self.reply(
                    thread_id,
                    "\n".join(lines) or "Không tìm thấy bài hát.",
                    reply_to_id=msg_id,
                )
                return

            if cmd == "antiunsend":
                enable = (
                    arg.lower() != "off"
                    if arg
                    else (thread_id not in self.anti_unsend_threads)
                )
                if enable:
                    self.anti_unsend_threads.add(thread_id)
                else:
                    self.anti_unsend_threads.discard(thread_id)
                await self.reply(
                    thread_id,
                    f"🕵️ Chế độ chống thu hồi: {'BẬT' if enable else 'TẮT'}",
                    reply_to_id=msg_id,
                )
                return

            if cmd == "antiedit":
                enable = (
                    arg.lower() != "off"
                    if arg
                    else (thread_id not in self.anti_edit_threads)
                )
                if enable:
                    self.anti_edit_threads.add(thread_id)
                else:
                    self.anti_edit_threads.discard(thread_id)
                await self.reply(
                    thread_id,
                    f"🕵️ Chế độ phát hiện sửa tin: {'BẬT' if enable else 'TẮT'}",
                    reply_to_id=msg_id,
                )
                return

            if cmd in {"tagall", "everyone"}:
                detail = await self.actions.get_thread_info(thread_id, message_limit=1)
                parts = detail.get("participants") or []
                names = [
                    f"@{p['username']}"
                    for p in parts
                    if isinstance(p, dict) and p.get("username")
                ]
                if not names:
                    await self.reply(thread_id, "Không tìm thấy danh sách thành viên trong nhóm.", reply_to_id=msg_id)
                    return
                tag_str = " ".join(names)
                msg_content = f"📢 [TAG ALL]\n{tag_str}"
                if arg:
                    msg_content += f"\n\n💬 Lời nhắn: {arg}"
                await self.reply(thread_id, msg_content, reply_to_id=msg_id)
                return

            if cmd == "forward" and arg:
                parts_fwd = arg.split(maxsplit=1)
                target_tid = int(parts_fwd[0]) if parts_fwd[0].isdigit() else 0
                fwd_text = parts_fwd[1] if len(parts_fwd) > 1 else ""
                if target_tid:
                    await self.actions.forward_message(thread_id, target_tid, message_id=msg_id, text=fwd_text)
                    await self.reply(thread_id, f"✅ Đã chuyển tiếp tin nhắn sang thread #{target_tid}.", reply_to_id=msg_id)
                return

            if cmd == "more":
                limit = int(arg) if arg.isdigit() else 10
                paged = await self.actions.paginate_messages(thread_id, limit=limit)
                msgs = paged.get("messages") or []
                lines = []
                for m in msgs:
                    snd = m.get("senderId") or "unknown"
                    txt = m.get("text") or "[media]"
                    lines.append(f"• [#{snd}]: {txt}")
                await self.reply(thread_id, f"📜 Đã tải thêm {len(lines)} tin nhắn cũ:\n" + "\n".join(lines), reply_to_id=msg_id)
                return

            # Admin-only commands below
            if not self.is_admin(sender_id):
                return

            if cmd == "bio" and arg:
                await change_bio(self.session, arg, client=self.http_client)
                await self.reply(thread_id, f"✅ Đã cập nhật Bio tài khoản thành:\n{arg}", reply_to_id=msg_id)
            elif cmd == "deletethread":
                is_spam = "spam" in arg.lower()
                await self.reply(thread_id, "🗑️ Đã xóa hội thoại.")
                await self.actions.delete_thread(thread_id, mark_as_spam=is_spam)
            elif cmd == "groupavatar" and arg:
                await self.actions.edit_group_avatar(thread_id, arg)
                is_clear = arg.lower().strip() in {"clear", "remove", "delete"}
                await self.reply(
                    thread_id,
                    "✅ Đã xóa ảnh đại diện nhóm." if is_clear else "✅ Đã cập nhật ảnh đại diện nhóm.",
                    reply_to_id=msg_id,
                )
            elif cmd == "autodl":
                self.auto_download_links = (arg.lower() != "off") if arg else not self.auto_download_links
                await self.reply(thread_id, f"✅ Tự động tải media link IG: {'BẬT' if self.auto_download_links else 'TẮT'}", reply_to_id=msg_id)
            elif cmd == "creategroup" and arg:
                grp_parts = arg.split(maxsplit=1)
                uids_raw = grp_parts[0].split(",")
                grp_title = grp_parts[1] if len(grp_parts) > 1 else "New Group"
                uids = [int(u.strip()) for u in uids_raw if u.strip().isdigit()]
                if uids:
                    res = await self.actions.create_group(uids, title=grp_title)
                    new_tid = res.get("threadId") or res.get("id") or "mới"
                    await self.reply(thread_id, f"✅ Đã tạo nhóm thành công: {grp_title} (#{new_tid}).", reply_to_id=msg_id)
            elif cmd == "notif":
                notifs = await fetch_notifications(self.session, client=self.http_client)
                items = notifs.get("notifications") or notifs.get("items") or []
                if not items:
                    await self.reply(thread_id, "Không có thông báo hoạt động mới.", reply_to_id=msg_id)
                else:
                    lines = [f"• {n.get('text') or n.get('title', 'Thông báo')}" for n in items[:8] if isinstance(n, dict)]
                    await self.reply(thread_id, "🔔 Thông báo gần đây:\n" + "\n".join(lines), reply_to_id=msg_id)
            elif cmd == "post" and arg:
                post_parts = arg.split(maxsplit=1)
                img_url = post_parts[0]
                caption_text = post_parts[1] if len(post_parts) > 1 else ""
                await publish_photo(self.session, img_url, caption=caption_text, to_story=False, client=self.http_client)
                await self.reply(thread_id, "✅ Đã đăng ảnh mới lên Feed Instagram!", reply_to_id=msg_id)
            elif cmd == "upstory" and arg:
                await publish_photo(self.session, arg.strip(), to_story=True, client=self.http_client)
                await self.reply(thread_id, "✅ Đã đăng ảnh lên Story 24h Instagram!", reply_to_id=msg_id)
            elif cmd == "say" and arg:
                await self.reply(thread_id, arg)
            elif cmd == "unsend":
                target_mid = arg or self._last_bot_msg.pop(thread_id, "") or ""
                if target_mid:
                    await self.actions.unsend_message(thread_id, target_mid)
            elif cmd == "edit" and arg:
                last_mid = self._last_bot_msg.get(thread_id)
                if last_mid:
                    await self.actions.edit_message(thread_id, last_mid, arg)
            elif cmd == "accept":
                tid = int(arg) if arg.isdigit() else thread_id
                await self.actions.accept_message_request(tid)
                await self.reply(thread_id, f"✅ Đã chấp nhận yêu cầu thread #{tid}.")
            elif cmd == "rename" and arg:
                await self.actions.rename_thread(thread_id, arg)
                await self.reply(thread_id, f"✅ Đã đổi tên nhóm thành: {arg}")
            elif cmd == "mute":
                secs = (
                    -1
                    if not arg or arg == "forever"
                    else (0 if arg == "off" else int(arg) * 60)
                )
                await self.actions.mute_thread(thread_id, secs)
                await self.reply(thread_id, f"✅ Đã cập nhật mute ({secs}s).")
            elif cmd == "unmute":
                await self.actions.mute_thread(thread_id, 0)
                await self.reply(thread_id, "✅ Đã bật lại thông báo hội thoại.")
            elif cmd == "pin":
                cached = self._msg_cache.get(msg_id)
                if isinstance(cached, dict) and cached.get("replyTo"):
                    quoted_mid = str(cached["replyTo"].get("messageId") or "")
                    if quoted_mid:
                        await self.actions.pin_message(thread_id, quoted_mid, pinned=True)
                        await self.reply(thread_id, "✅ Đã ghim tin nhắn.", reply_to_id=msg_id)
                        return
                await self.actions.pin_thread(thread_id, pinned=True)
                await self.reply(thread_id, "✅ Đã ghim hội thoại.")
            elif cmd == "unpin":
                cached = self._msg_cache.get(msg_id)
                if isinstance(cached, dict) and cached.get("replyTo"):
                    quoted_mid = str(cached["replyTo"].get("messageId") or "")
                    if quoted_mid:
                        await self.actions.pin_message(thread_id, quoted_mid, pinned=False)
                        await self.reply(thread_id, "✅ Đã bỏ ghim tin nhắn.", reply_to_id=msg_id)
                        return
                await self.actions.pin_thread(thread_id, pinned=False)
                await self.reply(thread_id, "✅ Đã bỏ ghim hội thoại.")
            elif cmd == "pinthread":
                await self.actions.pin_thread(thread_id, pinned=True)
                await self.reply(thread_id, "✅ Đã ghim hội thoại.")
            elif cmd == "unpinthread":
                await self.actions.pin_thread(thread_id, pinned=False)
                await self.reply(thread_id, "✅ Đã bỏ ghim hội thoại.")
            elif cmd == "add" and arg:
                uids = [
                    int(tok)
                    for tok in arg.replace(",", " ").split()
                    if tok.lstrip("#@").isdigit()
                ]
                if uids:
                    await self.actions.add_group_members(thread_id, uids)
                    await self.reply(thread_id, f"✅ Đã thêm {len(uids)} thành viên.")
            elif cmd == "kick" and arg:
                clean_uid = arg.strip().lstrip("#@")
                if clean_uid.isdigit():
                    await self.actions.remove_group_member(thread_id, int(clean_uid))
                    await self.reply(thread_id, f"✅ Đã xóa #{clean_uid} khỏi nhóm.")
            elif cmd == "promote" and arg:
                clean_uid = arg.strip().lstrip("#@")
                if clean_uid.isdigit():
                    await self.actions.modify_group_admins(
                        thread_id, [int(clean_uid)], promote=True
                    )
                    await self.reply(thread_id, f"✅ Đã cấp quyền admin cho #{clean_uid}.")
            elif cmd == "demote" and arg:
                clean_uid = arg.strip().lstrip("#@")
                if clean_uid.isdigit():
                    await self.actions.modify_group_admins(
                        thread_id, [int(clean_uid)], promote=False
                    )
                    await self.reply(thread_id, f"✅ Đã gỡ quyền admin của #{clean_uid}.")
            elif cmd == "leave":
                await self.reply(thread_id, "👋 Tạm biệt mọi người! Bot rời nhóm.")
                await self.actions.leave_group(thread_id)
            elif cmd in {"block", "unblock"} and arg:
                clean_target = arg.strip().lstrip("#@")
                uid_to_block = clean_target
                if not uid_to_block.isdigit():
                    with suppress(Exception):
                        p_info = await self.actions.get_web_profile(clean_target)
                        uid_to_block = str(p_info.get("id") or "")
                if not uid_to_block.isdigit():
                    await self.reply(
                        thread_id, f"Không tìm thấy UID cho @{clean_target}.", reply_to_id=msg_id
                    )
                elif cmd == "block":
                    await block_user(self.session, uid_to_block, client=self.http_client)
                    await self.reply(thread_id, f"🚫 Đã chặn #{uid_to_block} (@{clean_target}).")
                else:
                    await unblock_user(self.session, uid_to_block, client=self.http_client)
                    await self.reply(thread_id, f"✅ Đã bỏ chặn #{uid_to_block} (@{clean_target}).")
            elif cmd == "like" and arg:
                await like_media(self.session, arg, unlike=False, client=self.http_client)
                await self.reply(thread_id, f"❤️ Đã like bài viết {arg}.")
            elif cmd == "unlike" and arg:
                await like_media(self.session, arg, unlike=True, client=self.http_client)
                await self.reply(thread_id, f"💔 Đã bỏ like bài viết {arg}.")
            elif cmd == "save" and arg:
                await save_media(self.session, arg, unsave=False, client=self.http_client)
                await self.reply(thread_id, f"🔖 Đã lưu bài viết {arg}.")
            elif cmd == "unsave" and arg:
                await save_media(self.session, arg, unsave=True, client=self.http_client)
                await self.reply(thread_id, f"🗑️ Đã bỏ lưu bài viết {arg}.")
            elif cmd == "comment" and " " in arg:
                target_media, comment_body = arg.split(" ", 1)
                await comment_media(
                    self.session, target_media, comment_body, client=self.http_client
                )
                await self.reply(thread_id, f"💬 Đã bình luận lên {target_media}.")
        except Exception as exc:
            await self.reply(
                thread_id,
                f"Lỗi thực thi {self.prefix}{cmd}: {redact_sensitive_text(exc)}",
                reply_to_id=msg_id,
            )


async def run_bot(config_path: str | Path | None = None) -> int:
    """Bootstrap Instagram session from env or config file and run InstagramBot."""
    configure_utf8_console()
    default_cfg = Path(__file__).resolve().parents[2] / "config.json"
    cfg_path = Path(config_path) if config_path else default_cfg

    env_cookies = EnvSessionStorage().load_cookies()
    config: dict[str, Any] = {
        "prefix": "/",
        "admins": set(),
        "auto_download_links": False,
    }
    cookies = env_cookies or ""
    if cfg_path.exists():
        loaded = load_bot_config(cfg_path)
        config.update(loaded)
        if not cookies:
            cookies = loaded["cookies"]

    if not cookies:
        safe_print(
            "[igchat-v2] Chưa có cookie Instagram. Hãy đặt IGCHAT_COOKIE hoặc điền src/config.json."
        )
        return 1

    session_store = FileSessionStorage(cfg_path.with_name(".session_cache.json"))
    async with httpx.AsyncClient(timeout=httpx.Timeout(15.0), verify=True) as client:
        session = await bootstrap_session(cookies, client=client)
        with suppress(Exception):
            session_store.save(session)

        listener = DirectListener(session)
        bot = InstagramBot(
            session,
            listener,
            prefix=config["prefix"],
            admins=config["admins"],
            auto_download_links=config["auto_download_links"],
            http_client=client,
        )
        listener.on_event(bot.handle_event)

        def _handle_stop(*_: object) -> None:
            listener.stop()

        with suppress(NotImplementedError):
            loop = asyncio.get_running_loop()
            for sig in (signal.SIGINT, signal.SIGTERM):
                with suppress(Exception):
                    loop.add_signal_handler(sig, _handle_stop)

        safe_print(
            f"[igchat-v2] Bot v3.0.0 đang chạy (uid={session.ig_user_id}, prefix={bot.prefix!r})..."
        )
        try:
            await listener.listen()
        finally:
            await listener.aclose()
    return 0


def main_blocking(config_path: str | Path | None = None) -> int:
    """Synchronous CLI entrypoint wrapping `asyncio.run(run_bot(...))`."""
    try:
        return asyncio.run(run_bot(config_path))
    except KeyboardInterrupt:
        return 0
