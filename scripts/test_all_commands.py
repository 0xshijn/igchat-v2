"""Comprehensive test runner for all 46 InstagramBot commands."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from igchat_v2.bot.bot import InstagramBot
from igchat_v2.core.models import InstagramSession
from igchat_v2.direct.listener import DirectListener


async def run_all_command_tests() -> None:
    session = InstagramSession(
        ig_user_id="66871799975",
        sessionid="dummy_session",
        csrftoken="dummy_csrf",
        cookies="sessionid=dummy; ds_user_id=66871799975",
    )
    listener = AsyncMock(spec=DirectListener)
    actions = AsyncMock()
    listener.actions = actions

    # Setup standard mock returns
    actions.send_message.return_value = {"messageId": "bot_mid_123"}
    actions.get_inbox.return_value = [
        {"id": 12345, "name": "Test Chat", "snippet": "Hello world"}
    ]
    actions.get_unread_count.return_value = 2
    actions.get_thread_info.return_value = {
        "id": 12345,
        "name": "Group Chat",
        "thread_title": "Group Chat",
        "participants": [
            {"pk": "111", "username": "alice", "full_name": "Alice"},
            {"pk": "222", "username": "bob", "full_name": "Bob"},
        ],
        "messages": [
            {"senderId": "111", "text": "Hi all", "timestampMs": 1000}
        ],
    }
    actions.get_thread_history.return_value = [
        {"id": "msg_1", "senderId": "111", "text": "Hi all", "timestampMs": 1000}
    ]
    actions.paginate_messages.return_value = {
        "messages": [
            {"senderId": "111", "text": "Old message 1"},
            {"senderId": "222", "text": "Old message 2"},
        ]
    }
    actions.get_message_requests.return_value = [
        {"id": 99999, "name": "Stranger", "snippet": "Want to chat?"}
    ]
    actions.accept_message_request.return_value = {"status": "ok"}
    actions.create_group.return_value = {"threadId": 888999}
    actions.search_users.return_value = [
        {"username": "target_user", "pk": "88888", "full_name": "Target"}
    ]
    actions.get_web_profile.return_value = {
        "username": "target_user",
        "fullName": "Target User",
        "id": "88888",
        "biography": "Bio here",
        "externalUrl": "https://example.com",
        "followerCount": 100,
        "followingCount": 50,
        "postCount": 10,
    }
    actions.fetch_stories.return_value = {
        "items": [{"id": "story_1", "url": "https://example.com/story.jpg"}]
    }
    actions.send_media_from_url.return_value = {"messageId": "media_mid_1"}
    actions.send_reaction.return_value = {"status": "ok"}
    actions.edit_message.return_value = {"status": "ok"}
    actions.unsend_message.return_value = {"status": "ok"}
    actions.pin_message.return_value = {"status": "ok"}
    actions.pin_thread.return_value = {"status": "ok"}
    actions.mute_thread.return_value = {"status": "ok"}
    actions.rename_thread.return_value = {"status": "ok"}
    actions.add_group_members.return_value = {"status": "ok"}
    actions.remove_group_member.return_value = {"status": "ok"}
    actions.modify_group_admins.return_value = {"status": "ok"}
    actions.leave_group.return_value = {"status": "ok"}
    actions.edit_group_avatar.return_value = {"status": "ok"}
    actions.delete_thread.return_value = {"status": "ok"}
    actions.forward_message.return_value = {"status": "ok"}

    # Mock HTTP client for social APIs
    mock_http = AsyncMock(spec=httpx.AsyncClient)
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp_dict = {
        "status": "ok",
        "result": "ok",
        "notifications": [{"text": "Thông báo 1"}],
        "notes": [{"id": "note_1", "text": "Hello note", "user": {"username": "admin"}}],
        "media": {"pk": 12345, "code": "ABCDEF"},
    }
    mock_resp.json.return_value = mock_resp_dict
    mock_resp.text = json.dumps(mock_resp_dict)
    mock_resp.content = json.dumps(mock_resp_dict).encode("utf-8")
    mock_resp.raise_for_status = MagicMock()
    mock_http.get.return_value = mock_resp
    mock_http.post.return_value = mock_resp

    bot = InstagramBot(
        session,
        listener,
        prefix="/",
        admins={"66871799975"},
        http_client=mock_http,
    )

    admin_sender = "66871799975"
    thread_id = 12345
    results: list[tuple[str, bool, str]] = []

    # Format: (cmd_text, check_type, expected_value)
    # check_type: "reply_contains", "action_called"
    test_cases = [
        # Basic
        ("/hi", "reply_contains", "chào"),
        ("/hello", "reply_contains", "chào"),
        ("/ping", "reply_contains", "pong"),
        ("/help", "reply_contains", "lệnh"),
        ("/id", "reply_contains", "#12345"),
        ("/echo test_echo_content", "reply_contains", "test_echo_content"),
        # Social & Profile
        ("/info target_user", "reply_contains", "@target_user"),
        ("/profile target_user", "reply_contains", "@target_user"),
        ("/story target_user", "action_called", actions.send_media_from_url),
        ("/search target_user", "reply_contains", "target_user"),
        # Threads & Inbox
        ("/inbox", "reply_contains", "Test Chat"),
        ("/unread", "reply_contains", "chưa đọc"),
        ("/thread", "reply_contains", "Group Chat"),
        ("/history 5", "reply_contains", "Hi all"),
        ("/more 5", "reply_contains", "Old message"),
        ("/requests", "reply_contains", "Stranger"),
        ("/accept 99999", "reply_contains", "chấp nhận"),
        ("/rename Nhóm VIP", "reply_contains", "đổi tên"),
        ("/groupavatar https://example.com/pic.jpg", "reply_contains", "ảnh đại diện"),
        ("/tagall thông báo", "reply_contains", "TAG ALL"),
        ("/everyone alo", "reply_contains", "TAG ALL"),
        ("/mute", "reply_contains", "mute"),
        ("/unmute", "reply_contains", "bật lại thông báo"),
        ("/pinthread", "reply_contains", "ghim hội thoại"),
        ("/unpinthread", "reply_contains", "bỏ ghim hội thoại"),
        # Media & DL
        ("/image https://example.com/img.jpg", "action_called", actions.send_media_from_url),
        ("/voice https://example.com/audio.mp3", "action_called", actions.send_media_from_url),
        ("/autodl on", "reply_contains", "BẬT"),
        ("/autodl off", "reply_contains", "TẮT"),
        # Group Member Management
        ("/creategroup 111,222 Nhóm Mới", "reply_contains", "đã tạo nhóm"),
        ("/add 333", "reply_contains", "thêm"),
        ("/kick 333", "reply_contains", "xóa"),
        ("/promote 111", "reply_contains", "cấp quyền admin"),
        ("/demote 111", "reply_contains", "gỡ quyền admin"),
        ("/leave", "reply_contains", "rời nhóm"),
        ("/block 444", "reply_contains", "chặn"),
        ("/unblock 444", "reply_contains", "bỏ chặn"),
        # Message controls
        ("/react 🔥", "action_called", actions.send_reaction),
        ("/pin", "reply_contains", "ghim"),
        ("/unpin", "reply_contains", "bỏ ghim"),
        ("/antiunsend on", "reply_contains", "BẬT"),
        ("/antiedit on", "reply_contains", "BẬT"),
        # Social interactions
        ("/like ABCDEF", "reply_contains", "like"),
        ("/unlike ABCDEF", "reply_contains", "bỏ like"),
        ("/save ABCDEF", "reply_contains", "lưu"),
        ("/unsave ABCDEF", "reply_contains", "bỏ lưu"),
        ("/comment ABCDEF Hay qua", "reply_contains", "bình luận"),
        ("/follow 88888", "reply_contains", "theo dõi"),
        ("/unfollow 88888", "reply_contains", "hủy theo dõi"),
        # Admin commands
        ("/bio Bio Mới", "reply_contains", "bio"),
        ("/notif", "reply_contains", "thông báo"),
        ("/note list", "reply_contains", "note"),
    ]

    print(f"Bắt đầu kiểm thử toàn diện {len(test_cases)} lệnh bot...")

    for cmd_text, check_type, expected_val in test_cases:
        actions.send_message.reset_mock()
        actions.send_media_from_url.reset_mock()
        actions.send_reaction.reset_mock()
        actions.edit_message.reset_mock()
        actions.unsend_message.reset_mock()
        actions.pin_message.reset_mock()
        actions.pin_thread.reset_mock()
        mock_http.get.reset_mock()
        mock_http.post.reset_mock()

        event = {
            "type": "message",
            "data": {
                "id": f"msg_{hash(cmd_text)}",
                "threadId": thread_id,
                "senderId": admin_sender,
                "text": cmd_text,
            },
        }

        try:
            with patch("igchat_v2.core.http.download_public_bytes", return_value=b"fake_image_bytes"):
                await bot.handle_event(event)

            sent_reply = ""
            if actions.send_message.called:
                call_args = actions.send_message.call_args[0]
                sent_reply = call_args[1] if len(call_args) > 1 else ""

            if check_type == "reply_contains":
                success = expected_val.lower() in sent_reply.lower()
                detail = f"Reply: {sent_reply[:50]!r}"
            elif check_type == "action_called":
                success = expected_val.called
                detail = f"Action called: {expected_val._mock_name or 'custom_mock'}"
            else:
                success = False
                detail = "Unknown check"

            status = "PASS" if success else "FAIL"
            results.append((cmd_text, success, detail))
            print(f"[{status}] {cmd_text:<40} -> {detail}")
        except Exception as exc:
            results.append((cmd_text, False, f"Exception: {exc}"))
            print(f"[ERROR] {cmd_text:<40} -> {exc}")

    # Test edit and unsend with cached message
    bot._last_bot_msg.set(thread_id, "bot_msg_999")
    actions.edit_message.reset_mock()
    await bot.handle_event({
        "type": "message",
        "data": {"id": "msg_edit", "threadId": thread_id, "senderId": admin_sender, "text": "/edit Nội dung mới"},
    })
    edit_ok = actions.edit_message.called
    results.append(("/edit Nội dung mới", edit_ok, "edit_message called"))
    print(f"[{'PASS' if edit_ok else 'FAIL'}] {'/edit Nội dung mới':<40} -> edit_message called={edit_ok}")

    actions.unsend_message.reset_mock()
    bot._last_bot_msg.set(thread_id, "bot_msg_999")
    await bot.handle_event({
        "type": "message",
        "data": {"id": "msg_unsend", "threadId": thread_id, "senderId": admin_sender, "text": "/unsend"},
    })
    unsend_ok = actions.unsend_message.called
    results.append(("/unsend", unsend_ok, "unsend_message called"))
    print(f"[{'PASS' if unsend_ok else 'FAIL'}] {'/unsend':<40} -> unsend_message called={unsend_ok}")

    passed_count = sum(1 for _, ok, _ in results if ok)
    total_count = len(results)
    print("\n" + "=" * 60)
    print(f"TỔNG KẾT: {passed_count}/{total_count} chức năng PASSED!")
    print("=" * 60)
    if passed_count != total_count:
        for cmd_text, ok, reason in results:
            if not ok:
                print(f" - FAIL: {cmd_text} | Chi tiết: {reason}")


if __name__ == "__main__":
    asyncio.run(run_all_command_tests())
