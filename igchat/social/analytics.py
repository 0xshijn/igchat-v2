"""Instagram Social Graph Analytics, Close Friends & Story Viewer Forensics."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import httpx

from ..core.http import DEFAULT_TIMEOUT_SECONDS, post_graphql_async
from ..core.models import InstagramSession, normalize_session

DOC_ID_CLOSE_FRIENDS = "29481920391820192"
DOC_ID_UPDATE_CLOSE_FRIENDS = "29481920391820193"
DOC_ID_STORY_VIEWERS = "39281920391820194"


@dataclass(frozen=True, slots=True)
class FollowerAnalytics:
    """Breakdown of social relationships between following and followers."""

    unrequited: list[str]  # You follow them, they don't follow back
    fans: list[str]  # They follow you, you don't follow them back
    mutual: list[str]  # Both follow each other

    @property
    def total_unrequited(self) -> int:
        return len(self.unrequited)

    @property
    def total_fans(self) -> int:
        return len(self.fans)

    @property
    def total_mutual(self) -> int:
        return len(self.mutual)


def analyze_relationships(
    following: Sequence[str],
    followers: Sequence[str],
) -> FollowerAnalytics:
    """Compute unrequited follows, fans, and mutual connections."""
    following_set = {
        str(item).strip().lower() for item in following if str(item).strip()
    }
    followers_set = {
        str(item).strip().lower() for item in followers if str(item).strip()
    }

    unrequited = sorted(following_set - followers_set)
    fans = sorted(followers_set - following_set)
    mutual = sorted(following_set & followers_set)

    return FollowerAnalytics(unrequited=unrequited, fans=fans, mutual=mutual)


async def fetch_close_friends(
    session: InstagramSession | Mapping[str, Any],
    *,
    client: httpx.AsyncClient | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Fetch the authenticated account's Close Friends (Green Circle) list."""
    sess = normalize_session(session)
    return await post_graphql_async(
        sess,
        doc_id=DOC_ID_CLOSE_FRIENDS,
        variables={},
        friendly_name="IGDCloseFriendsQuery",
        client=client,
        timeout=timeout,
    )


async def update_close_friends(
    session: InstagramSession | Mapping[str, Any],
    *,
    add_user_ids: Sequence[int | str] = (),
    remove_user_ids: Sequence[int | str] = (),
    client: httpx.AsyncClient | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Add or remove accounts from the Close Friends list."""
    sess = normalize_session(session)
    add_list = [str(uid).strip() for uid in add_user_ids if str(uid).strip()]
    remove_list = [str(uid).strip() for uid in remove_user_ids if str(uid).strip()]

    variables = {
        "input": {
            "add": add_list,
            "remove": remove_list,
        }
    }
    return await post_graphql_async(
        sess,
        doc_id=DOC_ID_UPDATE_CLOSE_FRIENDS,
        variables=variables,
        friendly_name="IGDUpdateCloseFriendsMutation",
        client=client,
        timeout=timeout,
    )


async def fetch_story_viewers(
    session: InstagramSession | Mapping[str, Any],
    story_id: int | str,
    *,
    client: httpx.AsyncClient | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Fetch list of accounts who viewed a specific Story."""
    sess = normalize_session(session)
    clean_id = str(story_id).strip()
    if not clean_id:
        raise ValueError("story_id không được để trống.")

    variables = {
        "story_id": clean_id,
    }
    return await post_graphql_async(
        sess,
        doc_id=DOC_ID_STORY_VIEWERS,
        variables=variables,
        friendly_name="IGDStoryViewersQuery",
        client=client,
        timeout=timeout,
    )


__all__ = [
    "FollowerAnalytics",
    "analyze_relationships",
    "fetch_close_friends",
    "fetch_story_viewers",
    "update_close_friends",
]
