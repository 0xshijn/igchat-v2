"""Instagram activity feed / notifications inbox via Polaris REST API."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx

from ..core.http import DEFAULT_TIMEOUT_SECONDS, get_async
from ..core.models import InstagramSession, normalize_session
from ..core.utils import IG_BASE_URL, build_ig_headers, parse_json_response


async def fetch_notifications(
    session: InstagramSession | Mapping[str, Any],
    *,
    mark_as_seen: bool = False,
    client: httpx.AsyncClient | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Fetch Instagram activity notifications from `/api/v1/news/inbox/`."""
    sess = normalize_session(session)
    resp = await get_async(
        f"{IG_BASE_URL}/api/v1/news/inbox/",
        client=client,
        headers=build_ig_headers(sess, referer=f"{IG_BASE_URL}/"),
        params={"mark_as_seen": "true" if mark_as_seen else "false"},
        timeout=timeout,
    )
    resp.raise_for_status()
    data = parse_json_response(resp.text)
    return {
        "success": data.get("status") == "ok"
        or "new_stories" in data
        or "old_stories" in data,
        "new_stories": data.get("new_stories", []),
        "old_stories": data.get("old_stories", []),
        "counts": data.get("counts", {}),
    }
