from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

import pytest

import main as sample_main


class _FakeListener:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str, str]] = []
        self.send_result: dict[str, str] = {"messageId": "mid.reply"}

    async def send_e2ee_message(
        self,
        chat_jid: str,
        content: str,
        *,
        reply_to_id: str,
        reply_to_sender_jid: str,
    ) -> dict[str, str]:
        self.sent.append((chat_jid, content, reply_to_id, reply_to_sender_jid))
        return dict(self.send_result)


class _RecordingLoop:
    def __init__(self) -> None:
        self.calls: list[tuple[Callable[..., Any], tuple[Any, ...]]] = []

    def call_soon_threadsafe(self, callback: Callable[..., Any], *args: Any) -> None:
        self.calls.append((callback, args))


def _make_bot(
    monkeypatch: pytest.MonkeyPatch, mock_dataIGS: dict[str, Any], **kwargs: Any
) -> sample_main.SimpleBot:
    monkeypatch.setattr(
        sample_main, "listeningE2EEEvent", lambda data, **options: object()
    )
    return sample_main.SimpleBot(mock_dataIGS, **kwargs)


@pytest.mark.asyncio
async def test_e2ee_ping_flows_from_listener_event_to_reply(
    monkeypatch: pytest.MonkeyPatch, mock_dataIGS: dict[str, Any]
) -> None:
    listener = _FakeListener()
    monkeypatch.setattr(
        sample_main, "listeningE2EEEvent", lambda data, **options: listener
    )
    bot = sample_main.SimpleBot(mock_dataIGS)
    bot._queue_event(
        {
            "type": "e2eeMessage",
            "data": {
                "id": "mid.incoming",
                "text": "/ping",
                "timestampMs": 0,
                "senderId": 2000,
                "chatJid": "2000@msgr",
                "senderJid": "2000:1@msgr",
            },
        }
    )

    event = await bot._get_event(timeout=0.1)
    assert event is not None
    message = bot._message_from_event(event)
    assert message is not None
    await bot._dispatch(message)

    assert len(listener.sent) == 1
    chat_jid, content, reply_to_id, sender_jid = listener.sent[0]
    assert chat_jid == "2000@msgr"
    assert content == "🏓 pong!"
    assert reply_to_id == "mid.incoming"
    assert sender_jid == "2000:1@msgr"


def test_auxiliary_event_storm_cannot_evict_message(
    monkeypatch: pytest.MonkeyPatch, mock_dataIGS: dict[str, Any]
) -> None:
    bot = _make_bot(monkeypatch, mock_dataIGS)

    for index in range(sample_main.EVENT_QUEUE_MAXSIZE * 2):
        bot._queue_event(
            {
                "type": ("typing", "readReceipt", "reaction")[index % 3],
                "data": {"sequence": index},
            }
        )

    assert bot._event_queue.empty()

    message_event = {
        "type": "e2eeMessage",
        "data": {"id": "mid.command", "senderId": 2000, "text": "/ping"},
    }
    bot._queue_event(message_event)

    assert bot._event_queue.get_nowait() == message_event
    assert bot._event_queue.empty()


def test_listener_thread_filters_noise_before_scheduling_asyncio_callback(
    monkeypatch: pytest.MonkeyPatch, mock_dataIGS: dict[str, Any]
) -> None:
    bot = _make_bot(monkeypatch, mock_dataIGS)
    loop = _RecordingLoop()

    for index in range(sample_main.EVENT_QUEUE_MAXSIZE * 2):
        bot._forward_listener_event(
            loop,  # type: ignore[arg-type]
            {"type": "typing", "data": {"sequence": index}},
        )
    message = {"type": "message", "data": {"id": "mid.live"}}
    bot._forward_listener_event(loop, message)  # type: ignore[arg-type]

    assert loop.calls == [(bot._queue_event, (message,))]


def test_control_event_is_logged_without_using_message_queue(
    monkeypatch: pytest.MonkeyPatch, mock_dataIGS: dict[str, Any]
) -> None:
    output: list[str] = []
    monkeypatch.setattr(sample_main, "log", lambda tag, message: output.append(message))
    bot = _make_bot(monkeypatch, mock_dataIGS)

    bot._queue_event({"type": "reconnected", "data": {}})

    assert bot._event_queue.empty()
    assert output == ["reconnected"]


def test_message_queue_overflow_is_redacted_and_counted(
    monkeypatch: pytest.MonkeyPatch, mock_dataIGS: dict[str, Any]
) -> None:
    output: list[str] = []
    monkeypatch.setattr(sample_main, "log", lambda tag, message: output.append(message))
    bot = _make_bot(monkeypatch, mock_dataIGS)
    bot._event_queue = asyncio.Queue(maxsize=1)
    first = {
        "type": "message",
        "data": {"id": "mid.private-1", "text": "FIRST_SECRET"},
    }
    second = {
        "type": "message",
        "data": {"id": "mid.private-2", "text": "SECOND_SECRET"},
    }

    bot._queue_event(first)
    bot._queue_event(second)

    assert bot._event_queue.get_nowait() == second
    assert bot._dropped_message_events == 1
    assert "FIRST_SECRET" not in "\n".join(output)
    assert "SECOND_SECRET" not in "\n".join(output)
    assert "đã loại 1 event" in "\n".join(output)


@pytest.mark.asyncio
async def test_empty_event_does_not_poison_populated_event_with_same_id(
    monkeypatch: pytest.MonkeyPatch, mock_dataIGS: dict[str, Any]
) -> None:
    bot = _make_bot(monkeypatch, mock_dataIGS)
    handled: list[str] = []

    async def handle_ping(message: dict[str, Any], argument: str) -> None:
        handled.append(str(message["messageID"]))

    bot._handlers["ping"] = handle_ping
    base_message = {
        "messageID": "mid.same",
        "userID": "2000",
        "replyToID": "3000",
        "type": "thread",
    }

    await bot._dispatch({**base_message, "body": None})
    await bot._dispatch({**base_message, "body": "/ping"})

    assert handled == ["mid.same"]


@pytest.mark.asyncio
async def test_placeholder_does_not_poison_decrypted_command_with_same_id(
    monkeypatch: pytest.MonkeyPatch, mock_dataIGS: dict[str, Any]
) -> None:
    bot = _make_bot(monkeypatch, mock_dataIGS)
    handled: list[str] = []

    async def handle_ping(message: dict[str, Any], argument: str) -> None:
        handled.append(str(message["messageID"]))

    bot._handlers["ping"] = handle_ping
    base_message = {
        "messageID": "mid.placeholder",
        "userID": "2000",
        "replyToID": "3000",
        "type": "thread",
    }

    await bot._dispatch({**base_message, "body": "Encrypted placeholder"})
    await bot._dispatch({**base_message, "body": "/ping"})

    assert handled == ["mid.placeholder"]


@pytest.mark.asyncio
async def test_message_ids_are_deduplicated_out_of_order(
    monkeypatch: pytest.MonkeyPatch, mock_dataIGS: dict[str, Any]
) -> None:
    bot = _make_bot(monkeypatch, mock_dataIGS)
    handled: list[str] = []

    async def handle_ping(message: dict[str, Any], argument: str) -> None:
        handled.append(str(message["messageID"]))

    handler: Callable[[dict[str, Any], str], Awaitable[None]] = handle_ping
    bot._handlers["ping"] = handler

    for message_id in ("mid.1", "mid.2", "mid.1"):
        await bot._dispatch(
            {
                "messageID": message_id,
                "body": "/ping",
                "userID": "2000",
                "replyToID": "3000",
                "type": "thread",
            }
        )

    assert handled == ["mid.1", "mid.2"]


@pytest.mark.asyncio
async def test_plain_text_is_ignored_but_prefixed_command_runs(
    monkeypatch: pytest.MonkeyPatch, mock_dataIGS: dict[str, Any]
) -> None:
    bot = _make_bot(monkeypatch, mock_dataIGS)
    handled: list[str] = []

    async def handle_ping(message: dict[str, Any], argument: str) -> None:
        handled.append(argument)

    bot._handlers["ping"] = handle_ping
    for message_id, body in (("mid.plain", "ping"), ("mid.command", "/ping")):
        await bot._dispatch(
            {
                "messageID": message_id,
                "body": body,
                "userID": "2000",
                "replyToID": "3000",
                "type": "thread",
            }
        )

    assert handled == [""]


@pytest.mark.asyncio
async def test_unsend_is_denied_when_admin_list_is_empty(
    monkeypatch: pytest.MonkeyPatch, mock_dataIGS: dict[str, Any]
) -> None:
    bot = _make_bot(monkeypatch, mock_dataIGS, admins=[])
    replies: list[str] = []

    async def record_reply(message: dict[str, Any], text: str) -> None:
        replies.append(text)

    monkeypatch.setattr(bot, "_reply", record_reply)

    await bot._cmd_unsend(
        {"userID": "2000", "chatJid": "2000@msgr"},
        "",
    )

    assert replies == ["⛔ Lệnh này bị khóa vì chưa cấu hình admin."]


@pytest.mark.asyncio
async def test_unknown_e2ee_delivery_is_not_cached_or_logged_as_success(
    monkeypatch: pytest.MonkeyPatch, mock_dataIGS: dict[str, Any]
) -> None:
    listener = _FakeListener()
    listener.send_result = {
        "messageId": "mid-timeout",
        "deliveryStatus": sample_main.DELIVERY_STATUS_UNKNOWN,
    }
    monkeypatch.setattr(
        sample_main, "listeningE2EEEvent", lambda data, **options: listener
    )
    output: list[str] = []
    monkeypatch.setattr(sample_main, "log", lambda tag, message: output.append(message))
    bot = sample_main.SimpleBot(mock_dataIGS)

    await bot._reply(
        {
            "chatJid": "2000@msgr",
            "messageID": "mid.incoming",
            "senderJid": "2000:1@msgr",
        },
        "PRIVATE_REPLY",
    )

    assert bot._last_bot_message == {}
    assert len(output) == 1
    assert any("delivery UNKNOWN" in line for line in output)
    assert all("mid-timeout" not in line for line in output)
    assert all("2000@msgr" not in line for line in output)
    assert all("E2EE ->" not in line for line in output)
    assert all("PRIVATE_REPLY" not in line for line in output)


def test_search_rate_limiter_enforces_sender_and_global_sliding_windows() -> None:
    now = [100.0]
    limiter = sample_main._SearchRateLimiter(
        per_sender_limit=2,
        global_limit=3,
        window_seconds=10.0,
        clock=lambda: now[0],
    )

    assert limiter.check("sender-a") is None
    assert limiter.check("sender-a") is None
    assert limiter.check("sender-a") == "sender"
    assert limiter.check("sender-b") is None
    assert limiter.check("sender-c") == "global"

    now[0] = 110.0
    assert limiter.check("sender-c") is None


@pytest.mark.asyncio
async def test_search_validates_and_normalizes_query_before_provider(
    monkeypatch: pytest.MonkeyPatch, mock_dataIGS: dict[str, Any]
) -> None:
    bot = _make_bot(monkeypatch, mock_dataIGS)
    queries: list[str] = []
    replies: list[str] = []

    async def fake_search(
        dataIGS: dict[str, Any], query: str, **kwargs: Any
    ) -> dict[str, list[Any]]:
        queries.append(query)
        return {"searchResultsDict": []}

    async def record_reply(message: dict[str, Any], text: str) -> None:
        replies.append(text)

    monkeypatch.setattr(sample_main._search, "func", fake_search)
    monkeypatch.setattr(bot, "_reply", record_reply)
    message = {"userID": "sender-a"}

    await bot._cmd_search(message, "x")
    await bot._cmd_search(message, "x" * (sample_main.SEARCH_QUERY_MAX_LENGTH + 1))
    await bot._cmd_search(message, "  Alice\n  Bob  ")

    assert queries == ["Alice Bob"]
    assert "ít nhất 2 ký tự" in replies[0]
    assert "không được vượt quá 100 ký tự" in replies[1]


@pytest.mark.asyncio
async def test_search_rate_limit_blocks_provider_and_redacts_telemetry(
    monkeypatch: pytest.MonkeyPatch, mock_dataIGS: dict[str, Any]
) -> None:
    bot = _make_bot(monkeypatch, mock_dataIGS)
    bot._search_rate_limiter = sample_main._SearchRateLimiter(
        per_sender_limit=1,
        global_limit=2,
        window_seconds=60.0,
        clock=lambda: 100.0,
    )
    queries: list[str] = []
    replies: list[str] = []
    logs: list[str] = []

    async def fake_search(
        dataIGS: dict[str, Any], query: str, **kwargs: Any
    ) -> dict[str, list[Any]]:
        queries.append(query)
        return {"searchResultsDict": []}

    async def record_reply(message: dict[str, Any], text: str) -> None:
        replies.append(text)

    monkeypatch.setattr(sample_main._search, "func", fake_search)
    monkeypatch.setattr(bot, "_reply", record_reply)
    monkeypatch.setattr(sample_main, "log", lambda tag, text: logs.append(text))
    message = {"userID": "sender-a"}

    await bot._cmd_search(message, "PRIVATE_QUERY")
    await bot._cmd_search(message, "PRIVATE_QUERY")

    assert queries == ["PRIVATE_QUERY"]
    assert any("thử lại sau" in reply for reply in replies)
    assert logs == ["Từ chối /search do chạm quota sender; query đã ẩn."]
    assert all("PRIVATE_QUERY" not in line for line in logs)


@pytest.mark.asyncio
async def test_upgraded_bot_commands_hi_info_inbox_edit_pin(
    monkeypatch: pytest.MonkeyPatch, mock_dataIGS: dict[str, Any]
) -> None:
    listener = _FakeListener()
    monkeypatch.setattr(
        sample_main, "listeningE2EEEvent", lambda data, **options: listener
    )
    bot = sample_main.SimpleBot(mock_dataIGS, admins=["17846530179231976"])
    replies: list[str] = []

    async def record_reply(message: dict[str, Any], text: str) -> None:
        replies.append(text)

    async def fake_user_info(
        dataIGS: dict[str, Any], target: str, **kwargs: Any
    ) -> dict[str, Any]:
        return {
            "idUser": "17846530179231976",
            "nameUser": "Lê Phước Toàn",
            "Username": "_phwctoazn",
            "urlProfile": "https://www.instagram.com/_phwctoazn/",
        }

    class _FakeBridge:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, Any]]] = []

        async def call(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
            self.calls.append((method, params))
            if method == "getInbox":
                return {"threads": [{"id": 17846530179231976, "name": "Lê Phước Toàn"}]}
            if method == "getThreadInfo":
                return {
                    "id": 17846530179231976,
                    "shortId": "17864880735231976",
                    "name": "Lê Phước Toàn",
                    "isGroup": False,
                    "participants": [
                        {"id": 17846530179231976, "name": "Lê Phước Toàn"}
                    ],
                    "messages": [
                        {
                            "id": "mid.msg1",
                            "senderId": 17846530179231976,
                            "text": "Hello",
                            "attachments": [
                                {"type": "image", "url": "https://example.com/a.jpg"}
                            ],
                        }
                    ],
                }
            if method == "getMessageRequests":
                return {"threads": [{"id": 999, "name": "Pending User"}]}
            if method == "sendMediaFromURL":
                return {"messageId": "mid.media1"}
            if method == "fetchMedia":
                return {
                    "id": "111",
                    "shortcode": "C8abc123",
                    "author": "_phwctoazn",
                    "caption": "Test reel",
                    "likeCount": 42,
                    "playCount": 100,
                    "urls": ["https://example.com/reel.mp4"],
                }
            if method == "createGroup":
                return {"id": 888, "name": "Group A"}
            if method == "getWebProfile":
                return {
                    "id": "66871799975",
                    "fbidV2": "17846530179231976",
                    "username": "_phwctoazn",
                    "fullName": "Lê Phước Toàn",
                    "biography": "Bio test",
                    "followerCount": 120,
                    "followingCount": 50,
                    "mediaCount": 3,
                    "avatarUrl": "https://example.com/avatar.jpg",
                    "recentPosts": [{"id": "111", "shortcode": "C8abc123", "likeCount": 10}],
                }
            if method == "fetchStories":
                return {
                    "userId": "66871799975",
                    "username": "_phwctoazn",
                    "items": [{"id": "s1", "type": "video", "url": "https://example.com/story.mp4"}],
                }
            if method == "forwardMessage":
                return {"status": "ok", "messageId": "mid.fwd1"}
            return {"status": "ok"}

    async def fake_like_media(
        dataIGS: dict[str, Any], target: str, *, unlike: bool = False, **kwargs: Any
    ) -> dict[str, Any]:
        return {"status": "ok", "mediaId": "3400000000000000000", "action": "unlike" if unlike else "like"}

    fake_bridge = _FakeBridge()
    bot.listener._bridge = fake_bridge  # type: ignore[assignment]
    bot._last_bot_message["17846530179231976@msgr"] = (
        "17846530179231976@msgr",
        "mid.bot1",
    )
    monkeypatch.setattr(bot, "_reply", record_reply)
    monkeypatch.setattr(sample_main._get_user_info, "func", fake_user_info)
    monkeypatch.setattr(sample_main._reactionPost, "like_instagram_media", fake_like_media)

    msg = {
        "userID": "17846530179231976",
        "chatJid": "17846530179231976@msgr",
        "replyToID": "17846530179231976",
        "messageID": "mid.user1",
        "raw": {"replyTo": {"messageId": "mid.replied1"}},
    }

    await bot._cmd_hi(msg, "")
    await bot._cmd_info(msg, "_phwctoazn")
    await bot._cmd_profile(msg, "_phwctoazn")
    await bot._cmd_story(msg, "_phwctoazn")
    await bot._cmd_inbox(msg, "")
    await bot._cmd_thread(msg, "5")
    await bot._cmd_requests(msg, "")
    await bot._cmd_accept(msg, "999")
    await bot._cmd_rename(msg, "Nhóm Mới")
    await bot._cmd_groupavatar(msg, "https://example.com/group.jpg")
    await bot._cmd_mute(msg, "")
    await bot._cmd_unmute(msg, "")
    await bot._cmd_pinthread(msg, "")
    await bot._cmd_unpinthread(msg, "")
    await bot._cmd_image(msg, "https://example.com/photo.jpg")
    await bot._cmd_voice(msg, "https://example.com/voice.mp4")
    await bot._cmd_media(msg, "")
    await bot._cmd_dl(msg, "https://www.instagram.com/reel/C8abc123/")
    await bot._cmd_like(msg, "https://www.instagram.com/reel/C8abc123/")
    await bot._cmd_unlike(msg, "https://www.instagram.com/reel/C8abc123/")
    await bot._cmd_forward(msg, "17846530179231976 Xem tin này")
    await bot._cmd_creategroup(msg, "1001,1002 Group A")
    await bot._cmd_add(msg, "1003")
    await bot._cmd_kick(msg, "1003")
    await bot._cmd_promote(msg, "1002")
    await bot._cmd_demote(msg, "1002")
    await bot._cmd_leave(msg, "")
    await bot._cmd_block(msg, "1004")
    await bot._cmd_unblock(msg, "1004")
    await bot._cmd_edit(msg, "Edited message")
    await bot._cmd_pin(msg, "")
    await bot._cmd_unpin(msg, "")

    monkeypatch.setattr(
        sample_main._unFriend,
        "follow_instagram_user",
        lambda dataIGS, pk, **kw: asyncio.sleep(0, result={"success": 1, "userId": pk}),
    )
    monkeypatch.setattr(
        sample_main._unFriend,
        "unfollow_instagram_user",
        lambda dataIGS, pk, **kw: asyncio.sleep(0, result={"success": 1, "userId": pk}),
    )
    monkeypatch.setattr(
        sample_main._changeBio,
        "change_instagram_bio",
        lambda dataIGS, bio, **kw: asyncio.sleep(
            0, result={"success": 1, "biography": bio}
        ),
    )
    monkeypatch.setattr(
        sample_main._deletePost,
        "comment_instagram_media",
        lambda dataIGS, target, text, **kw: asyncio.sleep(
            0,
            result={
                "success": 1,
                "mediaId": "3400000000000000000",
                "commentId": "c123",
                "text": text,
            },
        ),
    )
    monkeypatch.setattr(
        sample_main._archivePost,
        "save_instagram_media",
        lambda dataIGS, target, *, unsave=False, **kw: asyncio.sleep(
            0,
            result={"success": 1, "mediaId": "3400000000000000000"},
        ),
    )

    await bot._cmd_follow(msg, "_phwctoazn")
    await bot._cmd_unfollow(msg, "66871799975")
    await bot._cmd_bio(msg, "New IG Bio")
    await bot._cmd_tagall(msg, "Họp nhóm")
    await bot._cmd_deletethread(msg, "spam")
    await bot._cmd_comment(msg, "https://www.instagram.com/reel/C8abc123/ Hay quá!")
    await bot._cmd_save(msg, "https://www.instagram.com/reel/C8abc123/")
    await bot._cmd_unsave(msg, "https://www.instagram.com/reel/C8abc123/")
    await bot._cmd_antiunsend(msg, "on")
    await bot._cmd_autodl(msg, "on")

    # Test Auto-DL on plain message containing Instagram Reel link
    await bot._dispatch(
        {
            "messageID": "mid.autodl1",
            "userID": "2000",
            "replyToID": "17846530179231976",
            "chatJid": "17846530179231976@msgr",
            "body": "Xem reel này https://www.instagram.com/reel/C8abc123/ nhé",
            "type": "e2ee",
        }
    )

    # Test Anti-Edit & Anti-Unsend
    await bot._dispatch(
        {
            "messageID": "mid.autodl1",
            "userID": "2000",
            "replyToID": "17846530179231976",
            "chatJid": "17846530179231976@msgr",
            "body": "Nội dung đã sửa",
            "type": "messageEdit",
        }
    )
    await bot._dispatch(
        {
            "messageID": "mid.autodl1",
            "userID": "2000",
            "replyToID": "17846530179231976",
            "chatJid": "17846530179231976@msgr",
            "body": "",
            "type": "messageUnsend",
        }
    )

    assert any("Xin chào! Bot Instagram E2EE" in r for r in replies)
    assert any("@_phwctoazn" in r for r in replies)
    assert any("Bio: Bio test" in r for r in replies)
    assert any("https://example.com/story.mp4" in r for r in replies)
    assert any("Hộp thư Instagram (1 hội thoại)" in r for r in replies)
    assert any("ShortID: 17864880735231976" in r for r in replies)
    assert any("Pending User" in r for r in replies)
    assert any("Đã duyệt tin nhắn chờ" in r for r in replies)
    assert any("Đã đổi tên hội thoại thành: Nhóm Mới" in r for r in replies)
    assert any("Đã cập nhật ảnh đại diện nhóm" in r for r in replies)
    assert any("https://example.com/a.jpg" in r for r in replies)
    assert any("https://example.com/reel.mp4" in r for r in replies)
    assert any("Đã thả tim bài viết" in r for r in replies)
    assert any("Đã bỏ thả tim bài viết" in r for r in replies)
    assert any("Đã chuyển tiếp tin nhắn sang hội thoại" in r for r in replies)
    assert any("Group A" in r for r in replies)
    assert any("Đã chặn người dùng `1004`" in r for r in replies)
    assert any("Đã ghim tin nhắn `mid.replied1`" in r for r in replies)
    assert any("Đã bỏ ghim tin nhắn `mid.replied1`" in r for r in replies)
    assert any("Đã theo dõi `_phwctoazn`" in r for r in replies)
    assert any("Đã bỏ theo dõi `66871799975`" in r for r in replies)
    assert any("Đã cập nhật tiểu sử Instagram: New IG Bio" in r for r in replies)
    assert any("Đã xóa hội thoại `17846530179231976` (đánh dấu Spam)" in r for r in replies)
    assert any("Đã đăng bình luận lên bài" in r for r in replies)
    assert any("Đã lưu bài viết" in r for r in replies)
    assert any("Đã bỏ lưu bài viết" in r for r in replies)
    assert any("Chống thu hồi" in r for r in replies)
    assert any("Phát hiện chỉnh sửa tin nhắn" in r for r in replies)
    called_methods = [m for m, _ in fake_bridge.calls]
    assert "getInbox" in called_methods
    assert "getWebProfile" in called_methods
    assert "fetchStories" in called_methods
    assert "getThreadInfo" in called_methods
    assert "getMessageRequests" in called_methods
    assert "acceptMessageRequest" in called_methods
    assert "renameThread" in called_methods
    assert "editGroupAvatar" in called_methods
    assert "muteThread" in called_methods
    assert "pinThread" in called_methods
    assert "sendMediaFromURL" in called_methods
    assert "fetchMedia" in called_methods
    assert "forwardMessage" in called_methods
    assert "createGroup" in called_methods
    assert "addGroupMembers" in called_methods
    assert "removeGroupMember" in called_methods
    assert "modifyGroupAdmins" in called_methods
    assert "leaveGroup" in called_methods
    assert "setUserBlocked" in called_methods
    assert "editE2EEMessage" in called_methods
    assert "pinMessage" in called_methods
    assert "unpinMessage" in called_methods
    assert "deleteThread" in called_methods
    assert "sendMessage" in called_methods
