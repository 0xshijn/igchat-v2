"""Bootstrap authenticated Instagram web & Polaris GraphQL sessions."""

from __future__ import annotations

import re
from collections.abc import Mapping
from urllib.parse import unquote

import httpx

from ..core.errors import CheckpointRequiredError, SessionCookieError, SessionError
from ..core.http import DEFAULT_TIMEOUT_SECONDS, get_async
from ..core.models import (
    DEFAULT_IG_USER_AGENT,
    InstagramSession,
    format_cookie_header,
    parse_cookie_header,
)
from ..core.utils import IG_BASE_URL, compute_jazoest
from .storage import SessionStorage

_EIMU_PATTERNS = (
    re.compile(r'"IG_USER_EIMU"\s*:\s*"(\d+)"'),
    re.compile(r'"eimu"\s*:\s*"(\d+)"'),
    re.compile(r'"viewerId"\s*:\s*"(\d+)"'),
    re.compile(r'"actorID"\s*:\s*"(\d+)"'),
)
_DTSG_PATTERNS = (
    re.compile(r'\["DTSGInitialData",\[\],\{"token":"([^"]+)"'),
    re.compile(r'"dtsg":\{"token":"([^"]+)"'),
    re.compile(r'name="fb_dtsg"\s+value="([^"]+)"'),
)
_LSD_PATTERNS = (
    re.compile(r'\["LSD",\[\],\{"token":"([^"]+)"'),
    re.compile(r'"lsd":\{"token":"([^"]+)"'),
)
_CSRF_PATTERNS = (
    re.compile(r'"csrf_token"\s*:\s*"([^"]+)"'),
    re.compile(r'csrf_token\\":\\"([^\\"]+)\\"'),
)
_REV_PATTERNS = (
    re.compile(r'"client_revision"\s*:\s*(\d+)'),
    re.compile(r'"server_revision"\s*:\s*(\d+)'),
)
_UID_PATTERNS = (
    re.compile(r'"viewerId"\s*:\s*"(\d+)"'),
    re.compile(r'"ds_user_id"\s*:\s*"(\d+)"'),
)


def _match_first(patterns: tuple[re.Pattern[str], ...], html: str) -> str:
    for pattern in patterns:
        found = pattern.search(html)
        if found:
            return found.group(1)
    return ""


def _infer_user_id_from_sessionid(sessionid: str) -> str:
    decoded = unquote(sessionid)
    head, _, _ = decoded.partition(":")
    if head.isdigit():
        return head
    return ""


def _resolve_cookie_input(
    source: str | Mapping[str, str] | SessionStorage,
) -> dict[str, str]:
    if isinstance(source, SessionStorage):
        raw = source.load_cookies()
        if not raw:
            raise SessionCookieError("Không tìm thấy cookie Instagram trong storage.")
        return parse_cookie_header(raw)
    if isinstance(source, str):
        parsed = parse_cookie_header(source)
        if not parsed:
            raise SessionCookieError("Chuỗi cookie Instagram rỗng hoặc sai định dạng.")
        return parsed
    if isinstance(source, Mapping):
        if "cookies" in source and isinstance(source["cookies"], str):
            return parse_cookie_header(source["cookies"])
        if "cookie" in source and isinstance(source["cookie"], str):
            return parse_cookie_header(source["cookie"])
        return {
            str(k).strip(): str(v).strip() for k, v in source.items() if str(k).strip()
        }
    raise TypeError("source phải là cookie str, dict hoặc SessionStorage.")


async def bootstrap_session(
    cookie_source: str | Mapping[str, str] | SessionStorage,
    *,
    client: httpx.AsyncClient | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    user_agent: str = DEFAULT_IG_USER_AGENT,
) -> InstagramSession:
    """Hydrate an `InstagramSession` from cookies by querying Instagram Direct inbox."""
    cookie_map = _resolve_cookie_input(cookie_source)
    sessionid = cookie_map.get("sessionid", "").strip()
    if not sessionid:
        raise SessionCookieError("Cookie Instagram bắt buộc phải có 'sessionid'.")

    ds_user_id = cookie_map.get("ds_user_id", "").strip()
    if not ds_user_id:
        ds_user_id = _infer_user_id_from_sessionid(sessionid)
        if ds_user_id:
            cookie_map["ds_user_id"] = ds_user_id

    if not ds_user_id or not ds_user_id.isdigit():
        raise SessionCookieError(
            "Cookie Instagram thiếu 'ds_user_id' hợp lệ (số nguyên dương)."
        )

    headers = {
        "User-Agent": user_agent,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Cookie": format_cookie_header(cookie_map),
    }

    response = await get_async(
        f"{IG_BASE_URL}/direct/inbox/",
        client=client,
        headers=headers,
        timeout=timeout,
        follow_redirects=False,
    )

    # Merge updated Set-Cookie values returned by Instagram (e.g., refreshed csrftoken)
    for name, value in response.cookies.items():
        if value:
            cookie_map[name] = value

    if 300 <= response.status_code < 400:
        location = response.headers.get("location", "").lower()
        if "challenge" in location or "checkpoint" in location:
            raise CheckpointRequiredError(
                "Tài khoản Instagram đang yêu cầu xác minh checkpoint/challenge.",
                checkpoint_path=location,
            )
        if "accounts/login" in location:
            raise SessionError("Cookie Instagram đã hết hạn (chuyển hướng login).")

    if response.status_code >= 400:
        raise SessionError(
            f"Bootstrap Instagram session thất bại với HTTP {response.status_code}."
        )

    html = response.text
    lower_html = html.lower()
    if "/challenge/" in lower_html and "ig_user_eimu" not in lower_html:
        raise CheckpointRequiredError(
            "Instagram trả về trang checkpoint/challenge khi tải /direct/inbox/."
        )

    eimu_id = _match_first(_EIMU_PATTERNS, html)
    fb_dtsg = _match_first(_DTSG_PATTERNS, html)
    lsd = _match_first(_LSD_PATTERNS, html)
    csrftoken = cookie_map.get("csrftoken", "").strip() or _match_first(
        _CSRF_PATTERNS, html
    )
    if csrftoken and not cookie_map.get("csrftoken"):
        cookie_map["csrftoken"] = csrftoken
    client_revision = _match_first(_REV_PATTERNS, html)
    if not ds_user_id:
        ds_user_id = _match_first(_UID_PATTERNS, html)

    # Secondary lightweight probe on homepage only if EIMU or CSRF was omitted
    if not eimu_id or not csrftoken:
        home_resp = await get_async(
            f"{IG_BASE_URL}/",
            client=client,
            headers={**headers, "Cookie": format_cookie_header(cookie_map)},
            timeout=timeout,
            follow_redirects=False,
        )
        for name, value in home_resp.cookies.items():
            if value:
                cookie_map[name] = value
        if home_resp.status_code < 400:
            home_html = home_resp.text
            eimu_id = eimu_id or _match_first(_EIMU_PATTERNS, home_html)
            fb_dtsg = fb_dtsg or _match_first(_DTSG_PATTERNS, home_html)
            lsd = lsd or _match_first(_LSD_PATTERNS, home_html)
            csrftoken = cookie_map.get("csrftoken", "") or _match_first(
                _CSRF_PATTERNS, home_html
            )
            client_revision = client_revision or _match_first(_REV_PATTERNS, home_html)

    if csrftoken:
        cookie_map["csrftoken"] = csrftoken

    token_for_jazoest = fb_dtsg or csrftoken
    jazoest = compute_jazoest(token_for_jazoest) if token_for_jazoest else ""

    return InstagramSession(
        ig_user_id=ds_user_id,
        ds_user_id=ds_user_id,
        eimu_id=eimu_id,
        sessionid=sessionid,
        csrftoken=csrftoken,
        cookies=format_cookie_header(cookie_map),
        mid=cookie_map.get("mid", ""),
        ig_did=cookie_map.get("ig_did", ""),
        rur=cookie_map.get("rur", ""),
        fb_dtsg=fb_dtsg,
        jazoest=jazoest,
        lsd=lsd,
        client_revision=client_revision,
        user_agent=user_agent,
    )
