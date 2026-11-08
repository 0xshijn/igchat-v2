"""Instagram Feed & Story media interactions: like, save, comment, configure."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import httpx

from ..core.errors import SecurityViolationError
from ..core.http import (
    DEFAULT_TIMEOUT_SECONDS,
    MAX_PUBLIC_DOWNLOAD_BYTES,
    download_public_bytes,
    post_async,
)
from ..core.models import InstagramSession, normalize_session
from ..core.permissions import require_private_file
from ..core.utils import IG_BASE_URL, build_ig_headers, parse_json_response
from ..direct.media import upload_photo_rupload

_IG_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"


def shortcode_to_media_id(shortcode: str) -> str:
    """Decode an Instagram post/reel Base64 shortcode into its numeric media ID."""
    clean = shortcode.strip().split("/")[0].split("?")[0]
    if not clean or any(ch not in _IG_ALPHABET for ch in clean):
        raise ValueError(f"Shortcode Instagram không hợp lệ: {shortcode!r}")
    value = 0
    for ch in clean:
        value = value * 64 + _IG_ALPHABET.index(ch)
    return str(value)


def media_id_to_shortcode(media_id: int | str) -> str:
    """Encode a numeric Instagram media ID into its URL shortcode."""
    raw = str(media_id).split("_", 1)[0].strip()
    if not raw.isdigit():
        raise ValueError(f"media_id không hợp lệ: {media_id!r}")
    num = int(raw)
    if num == 0:
        return "A"
    chars: list[str] = []
    while num > 0:
        num, rem = divmod(num, 64)
        chars.append(_IG_ALPHABET[rem])
    return "".join(reversed(chars))


def _resolve_media_pk(media_id_or_shortcode: int | str) -> str:
    raw = str(media_id_or_shortcode).strip()
    if "_" in raw:
        raw = raw.split("_", 1)[0]
    if raw.isdigit():
        return raw
    return shortcode_to_media_id(raw)


async def like_media(
    session: InstagramSession | Mapping[str, Any],
    media_id_or_shortcode: int | str,
    *,
    unlike: bool = False,
    client: httpx.AsyncClient | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Like or unlike an Instagram post/reel by numeric media ID or shortcode."""
    sess = normalize_session(session)
    pk = _resolve_media_pk(media_id_or_shortcode)
    verb = "unlike" if unlike else "like"
    resp = await post_async(
        f"{IG_BASE_URL}/api/v1/web/likes/{pk}/{verb}/",
        client=client,
        headers=build_ig_headers(sess, referer=f"{IG_BASE_URL}/"),
        data={},
        timeout=timeout,
    )
    resp.raise_for_status()
    parsed = parse_json_response(resp.text)
    return {"success": parsed.get("status") == "ok", "data": parsed}


async def save_media(
    session: InstagramSession | Mapping[str, Any],
    media_id_or_shortcode: int | str,
    *,
    unsave: bool = False,
    client: httpx.AsyncClient | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Bookmark (save) or unsave an Instagram post/reel."""
    sess = normalize_session(session)
    pk = _resolve_media_pk(media_id_or_shortcode)
    verb = "unsave" if unsave else "save"
    resp = await post_async(
        f"{IG_BASE_URL}/api/v1/web/save/{pk}/{verb}/",
        client=client,
        headers=build_ig_headers(sess, referer=f"{IG_BASE_URL}/"),
        data={},
        timeout=timeout,
    )
    resp.raise_for_status()
    parsed = parse_json_response(resp.text)
    return {"success": parsed.get("status") == "ok", "data": parsed}


async def comment_media(
    session: InstagramSession | Mapping[str, Any],
    media_id_or_shortcode: int | str,
    comment_text: str,
    *,
    reply_to_comment_id: str | None = None,
    client: httpx.AsyncClient | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Post a comment (or comment reply) on an Instagram post/reel."""
    sess = normalize_session(session)
    pk = _resolve_media_pk(media_id_or_shortcode)
    if not comment_text.strip():
        raise ValueError("Nội dung comment không được rỗng.")
    payload: dict[str, str] = {"comment_text": comment_text}
    if reply_to_comment_id:
        payload["replied_to_comment_id"] = str(reply_to_comment_id).strip()
    resp = await post_async(
        f"{IG_BASE_URL}/api/v1/web/comments/{pk}/add/",
        client=client,
        headers=build_ig_headers(sess, referer=f"{IG_BASE_URL}/"),
        data=payload,
        timeout=timeout,
    )
    resp.raise_for_status()
    parsed = parse_json_response(resp.text)
    return {"success": parsed.get("status") == "ok", "data": parsed}


async def delete_comment(
    session: InstagramSession | Mapping[str, Any],
    media_id_or_shortcode: int | str,
    comment_id: int | str,
    *,
    client: httpx.AsyncClient | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Delete an existing comment owned by the account."""
    sess = normalize_session(session)
    pk = _resolve_media_pk(media_id_or_shortcode)
    cid = str(comment_id).strip()
    if not cid.isdigit():
        raise ValueError("comment_id phải là chuỗi số.")
    resp = await post_async(
        f"{IG_BASE_URL}/api/v1/web/comments/{pk}/delete/{cid}/",
        client=client,
        headers=build_ig_headers(sess, referer=f"{IG_BASE_URL}/"),
        data={},
        timeout=timeout,
    )
    resp.raise_for_status()
    parsed = parse_json_response(resp.text)
    return {"success": parsed.get("status") == "ok", "data": parsed}


async def publish_photo(
    session: InstagramSession | Mapping[str, Any],
    source: str | Path | bytes,
    *,
    caption: str = "",
    to_story: bool = False,
    resolve_dns: bool = True,
    client: httpx.AsyncClient | None = None,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """Upload and configure a photo onto the Instagram Feed or Story."""
    sess = normalize_session(session)
    image_bytes: bytes
    if isinstance(source, bytes):
        if len(source) > MAX_PUBLIC_DOWNLOAD_BYTES:
            raise SecurityViolationError("Ảnh vượt quá giới hạn 20 MiB.")
        image_bytes = source
    elif isinstance(source, Path):
        target = require_private_file(source)
        if target.stat().st_size > MAX_PUBLIC_DOWNLOAD_BYTES:
            raise SecurityViolationError("File ảnh vượt quá giới hạn 20 MiB.")
        image_bytes = target.read_bytes()
    else:
        raw = str(source).strip()
        if raw.startswith(("http://", "https://")):
            image_bytes, _ = await download_public_bytes(
                raw, client=client, resolve_dns=resolve_dns
            )
        else:
            target = require_private_file(Path(raw))
            if target.stat().st_size > MAX_PUBLIC_DOWNLOAD_BYTES:
                raise SecurityViolationError("File ảnh vượt quá giới hạn 20 MiB.")
            image_bytes = target.read_bytes()

    if not image_bytes:
        raise ValueError("Không đọc được dữ liệu ảnh để đăng tải.")

    uploaded = await upload_photo_rupload(
        sess, image_bytes, client=client, timeout=timeout
    )
    endpoint = (
        f"{IG_BASE_URL}/api/v1/media/configure_to_story/"
        if to_story
        else f"{IG_BASE_URL}/api/v1/media/configure/"
    )
    config_payload: dict[str, str] = {
        "source_type": "library",
        "caption": caption,
        "upload_id": str(uploaded["upload_id"]),
    }
    if to_story:
        config_payload["configure_mode"] = "1"
    resp = await post_async(
        endpoint,
        client=client,
        headers=build_ig_headers(sess, referer=f"{IG_BASE_URL}/"),
        data=config_payload,
        timeout=timeout,
    )
    resp.raise_for_status()
    parsed = parse_json_response(resp.text)
    return {"success": parsed.get("status") == "ok", "data": parsed}
