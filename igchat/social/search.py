"""Instagram Direct user search via Polaris OmniPicker GraphQL."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx

from ..core.http import DEFAULT_TIMEOUT_SECONDS, post_graphql_async
from ..core.models import InstagramSession, UserSummary, normalize_session

DOC_ID_USER_SEARCH = "27248216181454285"


async def search_users(
    session: InstagramSession | Mapping[str, Any],
    query: str,
    *,
    limit: int = 20,
    client: httpx.AsyncClient | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> list[UserSummary]:
    """Search Instagram accounts using Polaris `IGDOmniPickerSearchResultsListQuery`."""
    sess = normalize_session(session)
    clean_query = query.strip()
    if not clean_query:
        raise ValueError("Từ khóa tìm kiếm không được để trống.")

    payload = await post_graphql_async(
        sess,
        doc_id=DOC_ID_USER_SEARCH,
        variables={"query": clean_query},
        friendly_name="IGDOmniPickerSearchResultsListQuery",
        client=client,
        timeout=timeout,
    )
    data = payload.get("data")
    if not isinstance(data, dict):
        data = {}
    search_entry = data.get("xig_direct_search_user_or_thread")
    if not isinstance(search_entry, dict):
        search_entry = {}
    raw_items = search_entry.get("results") or data.get("results") or []
    if not isinstance(raw_items, list):
        raw_items = []

    users: list[UserSummary] = []
    for entry in raw_items[: max(1, int(limit))]:
        if not isinstance(entry, dict):
            continue
        users.append(
            UserSummary(
                id=entry.get("interop_messaging_user_fbid") or entry.get("pk") or "",
                pk=str(entry.get("pk") or entry.get("id") or ""),
                username=str(entry.get("username") or ""),
                name=str(entry.get("full_name") or entry.get("name") or ""),
                full_name=str(entry.get("full_name") or ""),
                profile_pic_url=str(entry.get("profile_pic_url") or ""),
                is_verified=bool(entry.get("is_verified", False)),
                is_private=bool(entry.get("is_private", False)),
            )
        )
    return users
