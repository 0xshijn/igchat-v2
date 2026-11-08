"""Instagram Direct RUpload photo & video HTTP upload helpers."""

from __future__ import annotations

import json
import secrets
import time
from collections.abc import Mapping
from typing import Any

import httpx

from ..core.errors import SecurityViolationError
from ..core.http import DEFAULT_TIMEOUT_SECONDS, post_async
from ..core.models import InstagramSession, normalize_session
from ..core.utils import IG_APP_ID, build_ig_headers, parse_json_response

RUPLOAD_PHOTO_BASE = "https://i.instagram.com/rupload_igphoto"
RUPLOAD_VIDEO_BASE = "https://i.instagram.com/rupload_igvideo"
MAX_RUPLOAD_BYTES = 25 * 1024 * 1024


def generate_upload_id() -> str:
    """Return a millisecond-resolution Instagram media upload ID."""
    return str(int(time.time() * 1000))


async def upload_photo_rupload(
    session: InstagramSession | Mapping[str, Any],
    image_bytes: bytes,
    *,
    upload_id: str | None = None,
    media_type: int = 1,
    client: httpx.AsyncClient | None = None,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """Upload raw JPEG/PNG bytes to Instagram `rupload_igphoto`."""
    sess = normalize_session(session)
    if not image_bytes:
        raise ValueError("image_bytes không được rỗng.")
    if len(image_bytes) > MAX_RUPLOAD_BYTES:
        raise SecurityViolationError(
            f"Ảnh vượt quá giới hạn {MAX_RUPLOAD_BYTES} bytes."
        )

    uid = upload_id or generate_upload_id()
    object_name = f"fb_uploader_{uid}_{secrets.token_hex(4)}"
    rupload_params = json.dumps(
        {
            "media_type": media_type,
            "upload_id": uid,
            "upload_media_height": 0,
            "upload_media_width": 0,
            "xsharing_user_ids": "[]",
        },
        separators=(",", ":"),
    )
    headers = build_ig_headers(
        sess,
        extra={
            "X-IG-App-ID": IG_APP_ID,
            "X-Entity-Name": object_name,
            "X-Entity-Length": str(len(image_bytes)),
            "X-Entity-Type": "image/jpeg",
            "Offset": "0",
            "X-Instagram-Rupload-Params": rupload_params,
            "Content-Type": "application/octet-stream",
        },
    )
    resp = await post_async(
        f"{RUPLOAD_PHOTO_BASE}/{object_name}",
        client=client,
        headers=headers,
        content=image_bytes,
        timeout=timeout if timeout > 0 else DEFAULT_TIMEOUT_SECONDS,
    )
    resp.raise_for_status()
    data = parse_json_response(resp.text)
    return {
        "upload_id": str(data.get("upload_id") or uid),
        "media_id": data.get("media_id"),
        "status": data.get("status", "ok"),
    }


async def upload_video_rupload(
    session: InstagramSession | Mapping[str, Any],
    video_bytes: bytes,
    *,
    upload_id: str | None = None,
    mime_type: str = "video/mp4",
    client: httpx.AsyncClient | None = None,
    timeout: float = 60.0,
) -> dict[str, Any]:
    """Upload raw video bytes to Instagram `rupload_igvideo`."""
    sess = normalize_session(session)
    if not video_bytes:
        raise ValueError("video_bytes không được rỗng.")
    if len(video_bytes) > MAX_RUPLOAD_BYTES:
        raise SecurityViolationError(
            f"Video vượt quá giới hạn {MAX_RUPLOAD_BYTES} bytes."
        )

    uid = upload_id or generate_upload_id()
    object_name = f"fb_uploader_{uid}_{secrets.token_hex(4)}"
    rupload_params = json.dumps(
        {
            "media_type": 2,
            "upload_id": uid,
            "xsharing_user_ids": "[]",
        },
        separators=(",", ":"),
    )
    headers = build_ig_headers(
        sess,
        extra={
            "X-IG-App-ID": IG_APP_ID,
            "X-Entity-Name": object_name,
            "X-Entity-Length": str(len(video_bytes)),
            "X-Entity-Type": mime_type,
            "Offset": "0",
            "X-Instagram-Rupload-Params": rupload_params,
            "Content-Type": "application/octet-stream",
        },
    )
    resp = await post_async(
        f"{RUPLOAD_VIDEO_BASE}/{object_name}",
        client=client,
        headers=headers,
        content=video_bytes,
        timeout=timeout,
    )
    resp.raise_for_status()
    data = parse_json_response(resp.text)
    return {
        "upload_id": str(data.get("upload_id") or uid),
        "media_id": data.get("media_id"),
        "status": data.get("status", "ok"),
    }
