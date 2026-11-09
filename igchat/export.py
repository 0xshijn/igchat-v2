"""Offline Chat Archiver & Forensic Exporter for Instagram Direct.

Exports conversation history into self-contained HTML (Instagram Dark Mode),
Markdown, and JSON formats with full attachment and reaction support.
"""

from __future__ import annotations

import html
import json
import time
from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Any


def _format_timestamp(ts_ms: int | float | None) -> str:
    if not ts_ms:
        return ""
    try:
        dt = datetime.fromtimestamp(float(ts_ms) / 1000.0, tz=timezone.utc)
        return dt.strftime("%Y-%m-%d %H:%M:%S UTC")
    except Exception:
        return str(ts_ms)


def export_thread_to_json(
    messages: Sequence[dict[str, Any]],
    metadata: dict[str, Any] | None = None,
) -> str:
    """Export thread message history into a clean JSON string."""
    payload = {
        "version": "1.0",
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "thread": metadata or {},
        "message_count": len(messages),
        "messages": list(messages),
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)


def export_thread_to_markdown(
    messages: Sequence[dict[str, Any]],
    metadata: dict[str, Any] | None = None,
) -> str:
    """Export thread message history into GitHub-flavored Markdown."""
    meta = metadata or {}
    title = (
        meta.get("name")
        or meta.get("thread_title")
        or f"Thread #{meta.get('id', 'Unknown')}"
    )
    lines = [
        f"# 💬 Instagram Direct Archive: {title}",
        "",
        f"- **Exported At:** {_format_timestamp(time.time() * 1000)}",
        f"- **Total Messages:** {len(messages)}",
        "",
        "---",
        "",
    ]

    for msg in messages:
        sender = msg.get("sender_id") or msg.get("senderId") or "Unknown"
        ts = _format_timestamp(msg.get("timestamp_ms") or msg.get("timestamp"))
        text = msg.get("text") or ""
        lines.append(f"### @{sender} `({ts})`")
        if text:
            lines.append(f"> {text}")
        attachments = msg.get("attachments") or []
        for att in attachments:
            url = att.get("url") or att.get("src") or ""
            kind = att.get("type", "attachment")
            if url:
                lines.append(f"- *[{kind}]:* [{url}]({url})")
        reactions = msg.get("reactions") or []
        if reactions:
            reaction_str = " ".join(r.get("emoji", "❤️") for r in reactions)
            lines.append(f"  *Reactions:* {reaction_str}")
        lines.append("")

    return "\n".join(lines)


def export_thread_to_html(
    messages: Sequence[dict[str, Any]],
    metadata: dict[str, Any] | None = None,
    current_user_id: int | str = "",
) -> str:
    """Generate a self-contained, standalone Dark Mode HTML archive matching Instagram Web."""
    meta = metadata or {}
    title = html.escape(
        str(
            meta.get("name")
            or meta.get("thread_title")
            or f"Thread #{meta.get('id', 'Archive')}"
        )
    )
    cid = str(current_user_id).strip()

    rows: list[str] = []
    for msg in messages:
        sender_id = str(msg.get("sender_id") or msg.get("senderId") or "Unknown")
        is_me = bool(cid and sender_id == cid)
        align_class = "msg-me" if is_me else "msg-other"
        ts = html.escape(
            _format_timestamp(msg.get("timestamp_ms") or msg.get("timestamp"))
        )
        raw_text = msg.get("text") or ""
        escaped_text = html.escape(raw_text).replace("\n", "<br/>")

        attach_html = ""
        for att in msg.get("attachments", []):
            url = html.escape(att.get("url") or att.get("src") or "")
            if url:
                attach_html += f'<div class="attachment"><a href="{url}" target="_blank">🔗 Media Attachment</a></div>'

        reactions_html = ""
        reactions = msg.get("reactions") or []
        if reactions:
            r_spans = "".join(
                f'<span class="reaction">{html.escape(r.get("emoji", "❤️"))}</span>'
                for r in reactions
            )
            reactions_html = f'<div class="reactions-bar">{r_spans}</div>'

        rows.append(f"""
            <div class="message-row {align_class}">
                <div class="sender-name">@{html.escape(sender_id)}</div>
                <div class="bubble">
                    <div class="text">{escaped_text}</div>
                    {attach_html}
                </div>
                {reactions_html}
                <div class="timestamp">{ts}</div>
            </div>
            """)

    all_messages_html = "\n".join(rows)

    return f"""<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="utf-8"/>
    <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
    <title>{title} — Instagram Direct Archive</title>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            background-color: #000000;
            color: #f5f5f5;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            display: flex;
            justify-content: center;
            min-height: 100vh;
            padding: 20px;
        }}
        .chat-container {{
            width: 100%;
            max-width: 680px;
            background: #121212;
            border-radius: 16px;
            border: 1px solid #262626;
            display: flex;
            flex-direction: column;
            overflow: hidden;
            box-shadow: 0 12px 36px rgba(0,0,0,0.7);
        }}
        .header {{
            padding: 18px 24px;
            background: #1a1a1a;
            border-bottom: 1px solid #262626;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        .header h1 {{ font-size: 1.15rem; font-weight: 600; color: #fff; }}
        .header .badge {{ font-size: 0.8rem; background: #333; padding: 4px 10px; border-radius: 12px; color: #aaa; }}
        .messages-list {{
            flex: 1;
            padding: 24px;
            display: flex;
            flex-direction: column;
            gap: 14px;
            overflow-y: auto;
        }}
        .message-row {{ display: flex; flex-direction: column; max-width: 75%; }}
        .msg-me {{ align-self: flex-end; align-items: flex-end; }}
        .msg-other {{ align-self: flex-start; align-items: flex-start; }}
        .sender-name {{ font-size: 0.75rem; color: #8e8e8e; margin-bottom: 4px; padding: 0 6px; }}
        .bubble {{
            padding: 12px 16px;
            border-radius: 20px;
            font-size: 0.95rem;
            line-height: 1.45;
            word-break: break-word;
        }}
        .msg-me .bubble {{
            background: linear-gradient(135deg, #7928ca 0%, #ff0080 100%);
            color: #ffffff;
            border-bottom-right-radius: 4px;
        }}
        .msg-other .bubble {{
            background: #262626;
            color: #efefef;
            border-bottom-left-radius: 4px;
        }}
        .timestamp {{ font-size: 0.7rem; color: #666; margin-top: 4px; padding: 0 6px; }}
        .reactions-bar {{
            display: flex;
            gap: 4px;
            margin-top: -6px;
            margin-bottom: 2px;
            background: #1e1e1e;
            padding: 2px 8px;
            border-radius: 10px;
            border: 1px solid #333;
            width: fit-content;
        }}
        .attachment {{ margin-top: 8px; font-size: 0.85rem; }}
        .attachment a {{ color: #58a6ff; text-decoration: none; }}
        .attachment a:hover {{ text-decoration: underline; }}
    </style>
</head>
<body>
    <div class="chat-container">
        <div class="header">
            <h1>{title}</h1>
            <span class="badge">{len(messages)} tin nhắn</span>
        </div>
        <div class="messages-list">
            {all_messages_html}
        </div>
    </div>
</body>
</html>"""


__all__ = [
    "export_thread_to_html",
    "export_thread_to_json",
    "export_thread_to_markdown",
]
