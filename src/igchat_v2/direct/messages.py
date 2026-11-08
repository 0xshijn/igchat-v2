"""Pure async Polaris GraphQL Instagram Direct messaging helpers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx

from ..core.http import DEFAULT_TIMEOUT_SECONDS, post_graphql_async
from ..core.models import InstagramSession, SendResult, normalize_session
from ..core.utils import IG_BASE_URL, generate_offline_threading_id

DOC_ID_SEND_TEXT = "26939990792348244"
DOC_ID_EDIT_MESSAGE = "32480262318254796"
DOC_ID_UNSEND_MESSAGE = "26948700068153789"
DOC_ID_SEND_REACTION = "24374451552236906"


async def send_text_message(
    session: InstagramSession | Mapping[str, Any],
    thread_id: int | str,
    text: str,
    *,
    reply_to_id: str | None = None,
    client: httpx.AsyncClient | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> SendResult:
    """Send a text Direct message via Polaris `IGDSendTextMessageMutation`."""
    sess = normalize_session(session)
    clean_thread = str(thread_id).strip()
    if not clean_thread:
        raise ValueError("thread_id không được để trống.")
    if not text:
        raise ValueError("Nội dung text không được rỗng.")

    variables: dict[str, Any] = {
        "input": {
            "thread_id": clean_thread,
            "text": text,
            "client_context": generate_offline_threading_id(),
            "send_attribution": "direct_thread",
        }
    }
    if reply_to_id:
        variables["input"]["replied_to_item_id"] = str(reply_to_id).strip()

    payload = await post_graphql_async(
        sess,
        doc_id=DOC_ID_SEND_TEXT,
        variables=variables,
        friendly_name="IGDSendTextMessageMutation",
        referer=f"{IG_BASE_URL}/direct/t/{clean_thread}/",
        client=client,
        timeout=timeout,
    )
    if payload.get("errors"):
        raise RuntimeError(f"Gửi tin nhắn Instagram thất bại: {payload['errors']}")

    data = payload.get("data") or {}
    msg_node = data.get("xig_send_text_message") or data
    item_id = ""
    if isinstance(msg_node, dict):
        item_id = str(msg_node.get("item_id") or msg_node.get("message_id") or "")
    return SendResult(
        success=True,
        message_id=item_id,
        delivery_status="acknowledged" if item_id else "sent",
        thread_id=int(clean_thread) if clean_thread.isdigit() else 0,
    )


async def edit_text_message(
    session: InstagramSession | Mapping[str, Any],
    thread_id: int | str,
    message_id: str,
    new_text: str,
    *,
    client: httpx.AsyncClient | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Edit a previously sent Direct message via `IGDirectEditMessageMutation`."""
    sess = normalize_session(session)
    clean_thread = str(thread_id).strip()
    clean_msg = message_id.strip()
    if not clean_thread or not clean_msg or not new_text.strip():
        raise ValueError("thread_id, message_id và new_text không được rỗng.")

    payload = await post_graphql_async(
        sess,
        doc_id=DOC_ID_EDIT_MESSAGE,
        variables={
            "input": {
                "thread_id": clean_thread,
                "item_id": clean_msg,
                "text": new_text,
            }
        },
        friendly_name="IGDirectEditMessageMutation",
        referer=f"{IG_BASE_URL}/direct/t/{clean_thread}/",
        client=client,
        timeout=timeout,
    )
    if payload.get("errors"):
        return {"success": False, "errors": payload["errors"]}
    return {"success": True, "data": payload.get("data", {})}


async def unsend_text_message(
    session: InstagramSession | Mapping[str, Any],
    thread_id: int | str,
    message_id: str,
    *,
    client: httpx.AsyncClient | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Unsend a Direct message via `IGDMessageUnsendDialogOffMsysMutation`."""
    sess = normalize_session(session)
    clean_thread = str(thread_id).strip()
    clean_msg = message_id.strip()
    if not clean_thread or not clean_msg:
        raise ValueError("thread_id và message_id không được rỗng.")

    payload = await post_graphql_async(
        sess,
        doc_id=DOC_ID_UNSEND_MESSAGE,
        variables={
            "input": {
                "thread_id": clean_thread,
                "item_id": clean_msg,
            }
        },
        friendly_name="IGDMessageUnsendDialogOffMsysMutation",
        referer=f"{IG_BASE_URL}/direct/t/{clean_thread}/",
        client=client,
        timeout=timeout,
    )
    if payload.get("errors"):
        return {"success": False, "errors": payload["errors"]}
    return {"success": True, "data": payload.get("data", {})}


async def react_to_message(
    session: InstagramSession | Mapping[str, Any],
    thread_id: int | str,
    message_id: str,
    emoji: str = "",
    *,
    client: httpx.AsyncClient | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Send or remove an emoji reaction on an Instagram Direct message."""
    sess = normalize_session(session)
    clean_thread = str(thread_id).strip()
    clean_msg = message_id.strip()
    if not clean_thread or not clean_msg:
        raise ValueError("thread_id và message_id không được rỗng.")

    reaction_status = "created" if emoji else "deleted"
    payload = await post_graphql_async(
        sess,
        doc_id=DOC_ID_SEND_REACTION,
        variables={
            "input": {
                "thread_id": clean_thread,
                "item_id": clean_msg,
                "emoji": emoji,
                "reaction_type": "like",
                "reaction_status": reaction_status,
            }
        },
        friendly_name="IGDirectReactionSendMutation",
        referer=f"{IG_BASE_URL}/direct/t/{clean_thread}/",
        client=client,
        timeout=timeout,
    )
    if payload.get("errors"):
        return {"success": False, "errors": payload["errors"]}
    return {"success": True, "data": payload.get("data", {})}
