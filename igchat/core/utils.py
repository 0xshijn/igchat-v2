"""Instagram Web & Polaris GraphQL request, JSON, and cookie helpers."""

from __future__ import annotations

import json
import secrets
import time
from collections.abc import Mapping
from typing import Any

from .models import (
    DEFAULT_IG_USER_AGENT,
    InstagramSession,
    format_cookie_header,
    parse_cookie_header,
)

IG_BASE_URL = "https://www.instagram.com"
IG_GRAPHQL_URL = "https://www.instagram.com/graphql/query"
IG_APP_ID = "936619743392459"
IG_AJAX_REVISION = "1019999999"


def compute_jazoest(token: str) -> str:
    """Compute Instagram/Polaris form `jazoest` checksum from a CSRF/DTSG token."""
    total = sum(ord(ch) for ch in token)
    return f"2{total}"


def generate_offline_threading_id() -> str:
    """Generate a 64-bit decimal offline threading ID / client context string."""
    ts_ms = int(time.time() * 1000)
    rand_bits = secrets.randbits(22)
    return str(((ts_ms & ((1 << 41) - 1)) << 22) | rand_bits)


def strip_json_prefix(raw_text: str) -> str:
    """Strip anti-JSON-hijacking `for (;;);` prefix returned by Instagram endpoints."""
    stripped = raw_text.lstrip()
    if stripped.startswith("for (;;);"):
        return stripped[len("for (;;);") :].lstrip()
    return stripped


def parse_json_response(raw_text: str) -> dict[str, Any]:
    """Decode an Instagram JSON response (including `for (;;);` prefixed payloads)."""
    cleaned = strip_json_prefix(raw_text)
    if not cleaned:
        return {}
    data = json.loads(cleaned)
    if not isinstance(data, dict):
        raise ValueError("Instagram trả về payload JSON không phải object.")
    return data


def build_ig_headers(
    session: InstagramSession,
    *,
    referer: str = f"{IG_BASE_URL}/direct/inbox/",
    extra: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Construct standard authenticated Polaris web headers for Instagram."""
    headers: dict[str, str] = {
        "User-Agent": session.user_agent or DEFAULT_IG_USER_AGENT,
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Origin": IG_BASE_URL,
        "Referer": referer,
        "X-IG-App-ID": IG_APP_ID,
        "X-ASBD-ID": "129477",
        "X-IG-WWW-Claim": "0",
        "X-Requested-With": "XMLHttpRequest",
        "Cookie": session.cookies,
    }
    if session.csrftoken:
        headers["X-CSRFToken"] = session.csrftoken
    if session.lsd:
        headers["X-FB-LSD"] = session.lsd
    if session.client_revision:
        headers["X-Instagram-AJAX"] = session.client_revision
    if extra:
        headers.update(extra)
    return headers


def build_graphql_form(
    session: InstagramSession,
    *,
    doc_id: str,
    variables: Mapping[str, Any],
    friendly_name: str = "",
) -> dict[str, str]:
    """Build a Polaris GraphQL POST form without mutating shared state."""
    form: dict[str, str] = {
        "av": session.eimu_id or session.ig_user_id,
        "__user": "0",
        "__a": "1",
        "__req": "1",
        "__hs": "20100.HYP:instagram_web_pkg.2.1...0",
        "dpr": "1",
        "__ccg": "EXCELLENT",
        "__rev": session.client_revision or IG_AJAX_REVISION,
        "__s": session.session_id or "",
        "__comet_req": "7",
        "doc_id": str(doc_id),
        "variables": json.dumps(variables, separators=(",", ":"), ensure_ascii=False),
        "server_timestamps": "true",
    }
    token = session.fb_dtsg or session.csrftoken
    if session.fb_dtsg:
        form["fb_dtsg"] = session.fb_dtsg
    if session.lsd:
        form["lsd"] = session.lsd
    if session.jazoest:
        form["jazoest"] = session.jazoest
    elif token:
        form["jazoest"] = compute_jazoest(token)
    if friendly_name:
        form["fb_api_caller_class"] = "RelayModern"
        form["fb_api_req_friendly_name"] = friendly_name
    return form


__all__ = [
    "IG_AJAX_REVISION",
    "IG_APP_ID",
    "IG_BASE_URL",
    "IG_GRAPHQL_URL",
    "build_graphql_form",
    "build_ig_headers",
    "compute_jazoest",
    "format_cookie_header",
    "generate_offline_threading_id",
    "parse_cookie_header",
    "parse_json_response",
    "strip_json_prefix",
]
