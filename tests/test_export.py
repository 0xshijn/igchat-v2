from __future__ import annotations

import json

from igchat.export import (
    export_thread_to_html,
    export_thread_to_json,
    export_thread_to_markdown,
)


def test_export_formats():
    messages = [
        {
            "id": "msg_1",
            "sender_id": "111",
            "text": "Hello world",
            "timestamp_ms": 1700000000000,
        },
        {
            "id": "msg_2",
            "sender_id": "222",
            "text": "Hi back! 😊",
            "timestamp_ms": 1700000005000,
            "reactions": [{"emoji": "❤️"}],
        },
    ]
    meta = {"id": "thread_123", "name": "Crush Chat"}

    # JSON Export
    json_out = export_thread_to_json(messages, meta)
    data = json.loads(json_out)
    assert data["message_count"] == 2
    assert data["thread"]["name"] == "Crush Chat"

    # Markdown Export
    md_out = export_thread_to_markdown(messages, meta)
    assert "# 💬 Instagram Direct Archive: Crush Chat" in md_out
    assert "@111" in md_out
    assert "Hello world" in md_out

    # HTML Export
    html_out = export_thread_to_html(messages, meta, current_user_id="222")
    assert "<!DOCTYPE html>" in html_out
    assert "Crush Chat" in html_out
    assert "msg-me" in html_out
    assert "msg-other" in html_out
    assert "Hi back!" in html_out
