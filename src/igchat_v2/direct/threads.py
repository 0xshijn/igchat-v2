"""Pure Polaris GraphQL & REST Instagram Direct thread management."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx

from ..core.http import DEFAULT_TIMEOUT_SECONDS, post_async, post_graphql_async
from ..core.models import InstagramSession, normalize_session
from ..core.utils import IG_BASE_URL, build_ig_headers, parse_json_response

DOC_ID_THREAD_PAGINATION = "27712934271665380"
DOC_ID_THREAD_DETAIL = "27885241431109906"
DOC_ID_ACCEPT_REQUEST = "10051610291581092"
DOC_ID_RENAME_THREAD = "26508340268868683"
DOC_ID_PROMOTE_ADMIN = "35563011113312213"
DOC_ID_REMOVE_ADMIN = "26688907887428172"


async def fetch_inbox_threads(
    session: InstagramSession | Mapping[str, Any],
    *,
    limit: int = 20,
    cursor: str | None = None,
    folder: str = "INBOX",
    client: httpx.AsyncClient | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Fetch Instagram Direct inbox or pending folder threads via Slide GraphQL."""
    sess = normalize_session(session)
    variables: dict[str, Any] = {
        "folder": folder.upper() or "INBOX",
        "limit": max(1, min(50, int(limit))),
    }
    if cursor:
        variables["cursor"] = cursor
    return await post_graphql_async(
        sess,
        doc_id=DOC_ID_THREAD_PAGINATION,
        variables=variables,
        friendly_name="IGDThreadListOffMsysPaginationQuery",
        client=client,
        timeout=timeout,
    )


async def fetch_thread_detail(
    session: InstagramSession | Mapping[str, Any],
    thread_id: int | str,
    *,
    message_limit: int = 20,
    client: httpx.AsyncClient | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Fetch participants, title, and recent messages for an IG Direct thread."""
    sess = normalize_session(session)
    clean_thread = str(thread_id).strip()
    if not clean_thread:
        raise ValueError("thread_id không được để trống.")
    return await post_graphql_async(
        sess,
        doc_id=DOC_ID_THREAD_DETAIL,
        variables={
            "thread_id": clean_thread,
            "message_limit": max(1, min(50, int(message_limit))),
        },
        friendly_name="IGDThreadDetailOffMsysQuery",
        referer=f"{IG_BASE_URL}/direct/t/{clean_thread}/",
        client=client,
        timeout=timeout,
    )


async def accept_message_request(
    session: InstagramSession | Mapping[str, Any],
    thread_id: int | str,
    *,
    client: httpx.AsyncClient | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Accept a pending Instagram Direct message request."""
    sess = normalize_session(session)
    clean_thread = str(thread_id).strip()
    if not clean_thread:
        raise ValueError("thread_id không được để trống.")
    payload = await post_graphql_async(
        sess,
        doc_id=DOC_ID_ACCEPT_REQUEST,
        variables={"input": {"thread_id": clean_thread}},
        friendly_name="IGDMessageRequestAcceptMutation",
        referer=f"{IG_BASE_URL}/direct/requests/",
        client=client,
        timeout=timeout,
    )
    if payload.get("errors"):
        return {"success": False, "errors": payload["errors"]}
    return {"success": True, "data": payload.get("data", {})}


async def rename_thread(
    session: InstagramSession | Mapping[str, Any],
    thread_id: int | str,
    new_title: str,
    *,
    client: httpx.AsyncClient | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Rename an Instagram Direct group thread."""
    sess = normalize_session(session)
    clean_thread = str(thread_id).strip()
    clean_title = new_title.strip()
    if not clean_thread or not clean_title:
        raise ValueError("thread_id và new_title không được rỗng.")
    payload = await post_graphql_async(
        sess,
        doc_id=DOC_ID_RENAME_THREAD,
        variables={"input": {"thread_id": clean_thread, "title": clean_title}},
        friendly_name="IGDUpdateThreadTitleMutation",
        referer=f"{IG_BASE_URL}/direct/t/{clean_thread}/",
        client=client,
        timeout=timeout,
    )
    if payload.get("errors"):
        return {"success": False, "errors": payload["errors"]}
    return {"success": True, "data": payload.get("data", {})}


async def promote_admin(
    session: InstagramSession | Mapping[str, Any],
    thread_id: int | str,
    target_user_id: int | str,
    *,
    client: httpx.AsyncClient | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Promote a member to admin in an Instagram Direct group."""
    sess = normalize_session(session)
    clean_thread = str(thread_id).strip()
    clean_user = str(target_user_id).strip()
    if not clean_thread or not clean_user:
        raise ValueError("thread_id và target_user_id không được rỗng.")
    payload = await post_graphql_async(
        sess,
        doc_id=DOC_ID_PROMOTE_ADMIN,
        variables={"input": {"thread_id": clean_thread, "user_id": clean_user}},
        friendly_name="IGDPromoteAsAdminOffMsysMutation",
        referer=f"{IG_BASE_URL}/direct/t/{clean_thread}/",
        client=client,
        timeout=timeout,
    )
    if payload.get("errors"):
        return {"success": False, "errors": payload["errors"]}
    return {"success": True, "data": payload.get("data", {})}


async def demote_admin(
    session: InstagramSession | Mapping[str, Any],
    thread_id: int | str,
    target_user_id: int | str,
    *,
    client: httpx.AsyncClient | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Remove admin privileges from a member in an Instagram Direct group."""
    sess = normalize_session(session)
    clean_thread = str(thread_id).strip()
    clean_user = str(target_user_id).strip()
    if not clean_thread or not clean_user:
        raise ValueError("thread_id và target_user_id không được rỗng.")
    payload = await post_graphql_async(
        sess,
        doc_id=DOC_ID_REMOVE_ADMIN,
        variables={"input": {"thread_id": clean_thread, "user_id": clean_user}},
        friendly_name="IGDRemoveAsAdminOffMsysMutation",
        referer=f"{IG_BASE_URL}/direct/t/{clean_thread}/",
        client=client,
        timeout=timeout,
    )
    if payload.get("errors"):
        return {"success": False, "errors": payload["errors"]}
    return {"success": True, "data": payload.get("data", {})}


async def mute_thread_rest(
    session: InstagramSession | Mapping[str, Any],
    thread_id: int | str,
    *,
    mute: bool = True,
    client: httpx.AsyncClient | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Mute or unmute notifications for an Instagram Direct thread via web REST."""
    sess = normalize_session(session)
    clean_thread = str(thread_id).strip()
    if not clean_thread:
        raise ValueError("thread_id không được rỗng.")
    action = "mute" if mute else "unmute"
    resp = await post_async(
        f"{IG_BASE_URL}/api/v1/direct_v2/threads/{clean_thread}/{action}/",
        client=client,
        headers=build_ig_headers(
            sess, referer=f"{IG_BASE_URL}/direct/t/{clean_thread}/"
        ),
        data={},
        timeout=timeout,
    )
    resp.raise_for_status()
    parsed = parse_json_response(resp.text)
    return {"success": parsed.get("status") == "ok", "data": parsed}
