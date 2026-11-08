"""Pure Instagram 24h Notes & Music Note APIs via Polaris Direct GraphQL/REST."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx

from ..core.http import DEFAULT_TIMEOUT_SECONDS, get_async, post_graphql_async
from ..core.models import InstagramSession, normalize_session
from ..core.utils import IG_BASE_URL, build_ig_headers, parse_json_response

DOC_ID_INBOX_TRAY = "29231580869776032"
DOC_ID_CREATE_NOTE = "28592645767037889"
DOC_ID_DELETE_NOTE = "28419182984337833"
DOC_ID_MUSIC_SEARCH = "27152225807728809"


async def fetch_notes(
    session: InstagramSession | Mapping[str, Any],
    *,
    client: httpx.AsyncClient | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Fetch active Instagram Direct 24h inbox notes (Polaris GraphQL + REST fallback)."""
    sess = normalize_session(session)
    try:
        payload = await post_graphql_async(
            sess,
            doc_id=DOC_ID_INBOX_TRAY,
            variables={"fetch_tray_items": True},
            friendly_name="IGDInboxTrayQuery",
            client=client,
            timeout=timeout,
        )
        data = payload.get("data")
        if isinstance(data, dict):
            tray = data.get("get_inbox_tray_items")
            if isinstance(tray, dict):
                items = tray.get("inbox_tray_items")
                if isinstance(items, list):
                    return {"success": True, "notes": items}
    except (httpx.HTTPError, Exception):
        pass

    try:
        resp = await get_async(
            f"{IG_BASE_URL}/api/v1/notes/get_notes/",
            client=client,
            headers=build_ig_headers(sess),
            timeout=timeout,
        )
        if resp.status_code == 200:
            data = parse_json_response(resp.text)
            return {
                "success": data.get("status") == "ok",
                "notes": data.get("items", []),
            }
    except Exception:
        pass

    return {"success": False, "notes": []}


async def search_note_music(
    session: InstagramSession | Mapping[str, Any],
    query: str,
    *,
    client: httpx.AsyncClient | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> list[dict[str, Any]]:
    """Search Instagram music catalog for attaching tracks to 24h Direct Notes."""
    sess = normalize_session(session)
    clean_query = query.strip()
    if not clean_query:
        raise ValueError("Từ khóa tìm nhạc không được rỗng.")

    payload = await post_graphql_async(
        sess,
        doc_id=DOC_ID_MUSIC_SEARCH,
        variables={"search_query": clean_query},
        friendly_name="IGDComposerRichContentMusicSearchQuery",
        client=client,
        timeout=timeout,
    )
    music_data = payload.get("data", {}).get("music_search", {})
    items = music_data.get("items") if isinstance(music_data, dict) else None
    return items if isinstance(items, list) else []


async def create_note(
    session: InstagramSession | Mapping[str, Any],
    text: str = "",
    *,
    audience: int = 0,
    audio_cluster_id: str | None = None,
    music_snippet_start_ms: int = 0,
    music_duration_ms: int = 30000,
    client: httpx.AsyncClient | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Publish a 24h Instagram Direct Note (max 60 chars) with optional music clip."""
    sess = normalize_session(session)
    clean_text = text.strip()
    if not clean_text and not audio_cluster_id:
        raise ValueError("Note phải có nội dung chữ hoặc audio_cluster_id.")
    if len(clean_text) > 60:
        raise ValueError("Instagram Note tối đa 60 ký tự.")

    input_payload: dict[str, Any] = {
        "audience": int(audience),
        "text": clean_text,
        "note_style": 1 if audio_cluster_id else 0,
    }
    if audio_cluster_id:
        input_payload["additional_params"] = {
            "note_create_meta_data": {
                "audio_cluster_id": str(audio_cluster_id).strip(),
                "music_snippet_start_time_in_ms": int(music_snippet_start_ms),
                "music_snippet_duration_in_ms": int(music_duration_ms),
            }
        }

    payload = await post_graphql_async(
        sess,
        doc_id=DOC_ID_CREATE_NOTE,
        variables={"input": input_payload},
        friendly_name="usePolarisCreateInboxTrayItemSubmitMutation",
        client=client,
        timeout=timeout,
    )
    if payload.get("errors"):
        return {"success": False, "errors": payload["errors"]}
    return {"success": True, "data": payload.get("data", {})}


async def delete_note(
    session: InstagramSession | Mapping[str, Any],
    note_id: str | int,
    *,
    client: httpx.AsyncClient | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Delete an active 24h Instagram Direct Note."""
    sess = normalize_session(session)
    clean_id = str(note_id).strip()
    if not clean_id:
        raise ValueError("note_id không được để trống.")
    payload = await post_graphql_async(
        sess,
        doc_id=DOC_ID_DELETE_NOTE,
        variables={"input": {"id": clean_id}},
        friendly_name="usePolarisDeleteInboxTrayItemSubmitMutation",
        client=client,
        timeout=timeout,
    )
    if payload.get("errors"):
        return {"success": False, "errors": payload["errors"]}
    return {"success": True, "data": payload.get("data", {})}
