"""Typed session and Instagram Direct domain models."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, TypedDict

from .errors import SessionCookieError

DEFAULT_IG_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/136.0.0.0 Safari/537.36"
)


class UserSummary(TypedDict, total=False):
    id: int | str
    pk: str
    username: str
    name: str
    full_name: str
    profile_pic_url: str
    is_verified: bool
    is_private: bool


class ThreadSummary(TypedDict, total=False):
    id: int
    short_id: str
    long_id: str
    type: int
    name: str
    is_group: bool
    is_muted: bool
    is_pinned: bool
    last_activity_ts_ms: int
    snippet: str


class MessageEvent(TypedDict, total=False):
    id: str
    thread_id: int
    thread_name: str
    thread_type: int
    sender_id: int
    text: str
    timestamp_ms: int
    attachments: list[dict[str, Any]]
    reply_to: dict[str, Any] | None
    mentions: list[dict[str, Any]]
    is_admin_msg: bool


class SendResult(TypedDict, total=False):
    success: bool
    message_id: str
    timestamp_ms: int
    delivery_status: str
    thread_id: int


def parse_cookie_header(raw_cookies: str) -> dict[str, str]:
    """Parse an HTTP Cookie header string into an ordered mapping."""
    cookies: dict[str, str] = {}
    for segment in raw_cookies.split(";"):
        piece = segment.strip()
        if not piece or "=" not in piece:
            continue
        name, value = piece.split("=", 1)
        clean_name = name.strip()
        if clean_name:
            cookies[clean_name] = value.strip()
    return cookies


def format_cookie_header(cookie_map: Mapping[str, str]) -> str:
    """Serialize a cookie mapping back into a semicolon-delimited header string."""
    parts = [
        f"{name.strip()}={value.strip()}"
        for name, value in cookie_map.items()
        if name.strip()
    ]
    return "; ".join(parts)


@dataclass(frozen=True, slots=True)
class InstagramSession:
    """Immutable authenticated Instagram web & Direct session snapshot."""

    ig_user_id: str
    sessionid: str
    csrftoken: str
    cookies: str
    ds_user_id: str = ""
    eimu_id: str = ""
    mid: str = ""
    ig_did: str = ""
    rur: str = ""
    fb_dtsg: str = ""
    jazoest: str = ""
    lsd: str = ""
    client_revision: str = ""
    session_id: str = ""
    user_agent: str = field(default=DEFAULT_IG_USER_AGENT)

    def __post_init__(self) -> None:
        uid = (self.ig_user_id or self.ds_user_id).strip()
        if not uid.isdigit():
            raise SessionCookieError("ig_user_id / ds_user_id phải là chuỗi số hợp lệ.")
        object.__setattr__(self, "ig_user_id", uid)
        if not self.ds_user_id:
            object.__setattr__(self, "ds_user_id", uid)
        if not self.sessionid.strip():
            raise SessionCookieError("Thiếu cookie sessionid của Instagram.")

    def __repr__(self) -> str:
        return (
            f"InstagramSession(ig_user_id={self.ig_user_id!r}, "
            f"has_eimu={bool(self.eimu_id)}, has_dtsg={bool(self.fb_dtsg)})"
        )

    def as_cookie_dict(self) -> dict[str, str]:
        """Return cookie key/value pairs parsed from `cookies` plus core fields."""
        parsed = parse_cookie_header(self.cookies)
        if self.sessionid and "sessionid" not in parsed:
            parsed["sessionid"] = self.sessionid
        if self.csrftoken and "csrftoken" not in parsed:
            parsed["csrftoken"] = self.csrftoken
        if self.ds_user_id and "ds_user_id" not in parsed:
            parsed["ds_user_id"] = self.ds_user_id
        if self.mid and "mid" not in parsed:
            parsed["mid"] = self.mid
        if self.ig_did and "ig_did" not in parsed:
            parsed["ig_did"] = self.ig_did
        if self.rur and "rur" not in parsed:
            parsed["rur"] = self.rur
        return parsed

    def to_dict(self) -> dict[str, Any]:
        """Export session fields to a JSON-serializable dict for storage/tests."""
        return {
            "ig_user_id": self.ig_user_id,
            "ds_user_id": self.ds_user_id,
            "eimu_id": self.eimu_id,
            "sessionid": self.sessionid,
            "csrftoken": self.csrftoken,
            "cookies": self.cookies,
            "mid": self.mid,
            "ig_did": self.ig_did,
            "rur": self.rur,
            "fb_dtsg": self.fb_dtsg,
            "jazoest": self.jazoest,
            "lsd": self.lsd,
            "client_revision": self.client_revision,
            "session_id": self.session_id,
            "user_agent": self.user_agent,
        }

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> InstagramSession:
        """Construct an `InstagramSession` from a dictionary or saved JSON payload."""
        raw_cookies = str(data.get("cookies") or "").strip()
        cookie_map = parse_cookie_header(raw_cookies) if raw_cookies else {}
        ig_user_id = str(
            data.get("ig_user_id")
            or data.get("ds_user_id")
            or cookie_map.get("ds_user_id")
            or ""
        ).strip()
        sessionid = str(
            data.get("sessionid") or cookie_map.get("sessionid") or ""
        ).strip()
        csrftoken = str(
            data.get("csrftoken") or cookie_map.get("csrftoken") or ""
        ).strip()
        if not raw_cookies and sessionid:
            merged: dict[str, str] = {"sessionid": sessionid}
            if ig_user_id:
                merged["ds_user_id"] = ig_user_id
            if csrftoken:
                merged["csrftoken"] = csrftoken
            for key in ("mid", "ig_did", "rur"):
                val = str(data.get(key) or "").strip()
                if val:
                    merged[key] = val
            raw_cookies = format_cookie_header(merged)

        return cls(
            ig_user_id=ig_user_id,
            ds_user_id=str(data.get("ds_user_id") or ig_user_id),
            eimu_id=str(data.get("eimu_id") or "").strip(),
            sessionid=sessionid,
            csrftoken=csrftoken,
            cookies=raw_cookies,
            mid=str(data.get("mid") or cookie_map.get("mid") or "").strip(),
            ig_did=str(data.get("ig_did") or cookie_map.get("ig_did") or "").strip(),
            rur=str(data.get("rur") or cookie_map.get("rur") or "").strip(),
            fb_dtsg=str(data.get("fb_dtsg") or "").strip(),
            jazoest=str(data.get("jazoest") or "").strip(),
            lsd=str(data.get("lsd") or "").strip(),
            client_revision=str(data.get("client_revision") or "").strip(),
            session_id=str(data.get("session_id") or "").strip(),
            user_agent=str(data.get("user_agent") or DEFAULT_IG_USER_AGENT),
        )


def normalize_session(
    session: InstagramSession | Mapping[str, Any],
) -> InstagramSession:
    """Accept either an `InstagramSession` instance or a compatible mapping."""
    if isinstance(session, InstagramSession):
        return session
    return InstagramSession.from_mapping(session)
