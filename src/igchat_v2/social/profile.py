"""Instagram profile lookup and biography editing via Polaris web APIs."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx

from ..core.http import (
    DEFAULT_TIMEOUT_SECONDS,
    get_async,
    post_async,
    post_graphql_async,
)
from ..core.models import InstagramSession, normalize_session
from ..core.utils import IG_BASE_URL, build_ig_headers, parse_json_response
from .search import search_users

DOC_ID_PROFILE_CONTENT = "26672929172408668"
DOC_ID_USER_BY_ID = "35274961328786258"


async def get_user_profile(
    session: InstagramSession | Mapping[str, Any],
    identifier: int | str,
    *,
    client: httpx.AsyncClient | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Fetch an Instagram user profile by username or numeric user ID."""
    sess = normalize_session(session)
    clean = str(identifier).strip().lstrip("@")
    if not clean:
        raise ValueError("identifier không được rỗng.")

    if not clean.isdigit():
        resp = await get_async(
            f"{IG_BASE_URL}/api/v1/users/web_profile_info/",
            client=client,
            headers=build_ig_headers(sess, referer=f"{IG_BASE_URL}/{clean}/"),
            params={"username": clean},
            timeout=timeout,
        )
        if resp.status_code == 200:
            parsed = parse_json_response(resp.text)
            data = parsed.get("data")
            user = data.get("user") if isinstance(data, dict) else None
            if isinstance(user, dict) and user:
                return user

        hits = await search_users(sess, clean, limit=5, client=client, timeout=timeout)
        for item in hits:
            if str(item.get("username") or "").lower() == clean.lower():
                clean_pk = str(item.get("pk") or item.get("id") or "")
                if clean_pk.isdigit():
                    clean = clean_pk
                    break
                return dict(item)

    if clean.isdigit():
        gql = await post_graphql_async(
            sess,
            doc_id=DOC_ID_PROFILE_CONTENT,
            variables={"id": clean, "render_surface": "PROFILE"},
            friendly_name="PolarisProfilePageContentQuery",
            referer=f"{IG_BASE_URL}/",
            client=client,
            timeout=timeout,
        )
        user = gql.get("data", {}).get("user")
        if isinstance(user, dict) and user:
            return user

        opt = await post_graphql_async(
            sess,
            doc_id=DOC_ID_USER_BY_ID,
            variables={"id": clean},
            friendly_name="useIGDCreateOptimisticThreadUserQuery",
            client=client,
            timeout=timeout,
        )
        node = opt.get("data", {}).get("user")
        if isinstance(node, dict) and node:
            return node

    raise LookupError(f"Không tìm thấy hồ sơ Instagram cho {identifier!r}.")


async def change_bio(
    session: InstagramSession | Mapping[str, Any],
    bio: str,
    *,
    client: httpx.AsyncClient | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Update the authenticated Instagram account's profile biography."""
    sess = normalize_session(session)
    headers = build_ig_headers(sess, referer=f"{IG_BASE_URL}/accounts/edit/")
    form_resp = await get_async(
        f"{IG_BASE_URL}/api/v1/accounts/edit/web_form_data/",
        client=client,
        headers=headers,
        timeout=timeout,
    )
    form_resp.raise_for_status()
    form_data = parse_json_response(form_resp.text).get("form_data", {})
    if not isinstance(form_data, dict):
        form_data = {}

    payload = {
        "first_name": str(form_data.get("first_name") or ""),
        "email": str(form_data.get("email") or ""),
        "username": str(form_data.get("username") or ""),
        "phone_number": str(form_data.get("phone_number") or ""),
        "biography": bio,
        "external_url": str(form_data.get("external_url") or ""),
        "chaining_enabled": "on" if form_data.get("chaining_enabled", True) else "",
    }
    resp = await post_async(
        f"{IG_BASE_URL}/api/v1/web/accounts/edit/",
        client=client,
        headers=headers,
        data=payload,
        timeout=timeout,
    )
    resp.raise_for_status()
    result = parse_json_response(resp.text)
    return {"success": result.get("status") == "ok", "data": result}
