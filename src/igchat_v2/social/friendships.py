"""Instagram social graph actions: follow, unfollow, remove follower, block."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx

from ..core.http import DEFAULT_TIMEOUT_SECONDS, post_async, post_graphql_async
from ..core.models import InstagramSession, normalize_session
from ..core.utils import IG_BASE_URL, build_ig_headers, parse_json_response

DOC_ID_BLOCK_USER = "28875204315418002"
DOC_ID_UNBLOCK_USER = "28615617751365746"


def _require_user_id(user_id: int | str) -> str:
    clean = str(user_id).strip()
    if not clean.isdigit():
        raise ValueError("user_id phải là chuỗi số hợp lệ của Instagram.")
    return clean


async def follow_user(
    session: InstagramSession | Mapping[str, Any],
    user_id: int | str,
    *,
    client: httpx.AsyncClient | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Follow an Instagram user by numeric user ID."""
    sess = normalize_session(session)
    uid = _require_user_id(user_id)
    resp = await post_async(
        f"{IG_BASE_URL}/api/v1/friendships/create/{uid}/",
        client=client,
        headers=build_ig_headers(sess, referer=f"{IG_BASE_URL}/"),
        data={},
        timeout=timeout,
    )
    resp.raise_for_status()
    parsed = parse_json_response(resp.text)
    return {"success": parsed.get("status") == "ok", "data": parsed}


async def unfollow_user(
    session: InstagramSession | Mapping[str, Any],
    user_id: int | str,
    *,
    client: httpx.AsyncClient | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Unfollow an Instagram user by numeric user ID."""
    sess = normalize_session(session)
    uid = _require_user_id(user_id)
    resp = await post_async(
        f"{IG_BASE_URL}/api/v1/friendships/destroy/{uid}/",
        client=client,
        headers=build_ig_headers(sess, referer=f"{IG_BASE_URL}/"),
        data={},
        timeout=timeout,
    )
    resp.raise_for_status()
    parsed = parse_json_response(resp.text)
    return {"success": parsed.get("status") == "ok", "data": parsed}


async def remove_follower(
    session: InstagramSession | Mapping[str, Any],
    user_id: int | str,
    *,
    client: httpx.AsyncClient | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Remove an existing follower from the authenticated account."""
    sess = normalize_session(session)
    uid = _require_user_id(user_id)
    resp = await post_async(
        f"{IG_BASE_URL}/api/v1/friendships/remove_follower/{uid}/",
        client=client,
        headers=build_ig_headers(sess, referer=f"{IG_BASE_URL}/"),
        data={},
        timeout=timeout,
    )
    resp.raise_for_status()
    parsed = parse_json_response(resp.text)
    return {"success": parsed.get("status") == "ok", "data": parsed}


async def block_user(
    session: InstagramSession | Mapping[str, Any],
    user_id: int | str,
    *,
    client: httpx.AsyncClient | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Block an Instagram user via GraphQL mutation with web REST fallback."""
    sess = normalize_session(session)
    uid = _require_user_id(user_id)
    try:
        gql = await post_graphql_async(
            sess,
            doc_id=DOC_ID_BLOCK_USER,
            variables={"target_user_id": uid, "surface": "igd_block_dialog"},
            friendly_name="IGDBlockUserDialogOffMsysMutation",
            client=client,
            timeout=timeout,
        )
        if not gql.get("errors"):
            return {"success": True, "data": gql.get("data", {})}
    except httpx.HTTPError:
        pass

    resp = await post_async(
        f"{IG_BASE_URL}/api/v1/web/friendships/{uid}/block/",
        client=client,
        headers=build_ig_headers(sess, referer=f"{IG_BASE_URL}/"),
        data={},
        timeout=timeout,
    )
    resp.raise_for_status()
    parsed = parse_json_response(resp.text)
    return {"success": parsed.get("status") == "ok", "data": parsed}


async def unblock_user(
    session: InstagramSession | Mapping[str, Any],
    user_id: int | str,
    *,
    client: httpx.AsyncClient | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Unblock a previously blocked Instagram user."""
    sess = normalize_session(session)
    uid = _require_user_id(user_id)
    try:
        gql = await post_graphql_async(
            sess,
            doc_id=DOC_ID_UNBLOCK_USER,
            variables={"target_user_id": uid, "surface": "igd_block_dialog"},
            friendly_name="IGDBlockUserDialogOffMsysUnblockMutation",
            client=client,
            timeout=timeout,
        )
        if not gql.get("errors"):
            return {"success": True, "data": gql.get("data", {})}
    except httpx.HTTPError:
        pass

    resp = await post_async(
        f"{IG_BASE_URL}/api/v1/web/friendships/{uid}/unblock/",
        client=client,
        headers=build_ig_headers(sess, referer=f"{IG_BASE_URL}/"),
        data={},
        timeout=timeout,
    )
    resp.raise_for_status()
    parsed = parse_json_response(resp.text)
    return {"success": parsed.get("status") == "ok", "data": parsed}
