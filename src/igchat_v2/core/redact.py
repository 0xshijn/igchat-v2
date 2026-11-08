"""Sensitive cookie, token, URL, and identity redaction helpers."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

_SENSITIVE_COOKIE_RE = re.compile(
    r"(?i)\b(sessionid|csrftoken|ds_user_id|mid|ig_did|rur|fb_dtsg|lsd|"
    r"password|pass|authorization|x-ig-set-www-claim|token|secret)\b"
    r"([=:\s]+)(?:\"[^\"]*\"|'[^']*'|[^\s;,&\"'<>]+)"
)
_BEARER_RE = re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9\-._~+/]+=*")
_URL_RE = re.compile(r"https?://[^\s<>\"']+")
_XML_TAG_RE = re.compile(r"<[^>]+>")
_UUID_RE = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)
_LONG_ID_RE = re.compile(r"\b\d{8,24}\b")

_SENSITIVE_KEYS = frozenset(
    {
        "cookie",
        "cookies",
        "sessionid",
        "csrftoken",
        "ds_user_id",
        "ig_user_id",
        "eimu_id",
        "mid",
        "ig_did",
        "rur",
        "fb_dtsg",
        "lsd",
        "password",
        "totp_secret",
        "authorization",
        "token",
        "access_token",
        "secret",
    }
)


def _redact_url(match: re.Match[str]) -> str:
    raw = match.group(0)
    scheme, _, rest = raw.partition("://")
    host_part = rest.split("/", 1)[0]
    if "@" in host_part:
        _, _, host_part = host_part.rpartition("@")
    return f"{scheme}://{host_part}/[redacted-path]"


def redact_sensitive_text(value: object) -> str:
    """Scrub cookies, tokens, URL paths/queries, XML, UUIDs, and long numeric IDs."""
    text = str(value)
    text = _SENSITIVE_COOKIE_RE.sub(r"\1\2[redacted]", text)
    text = _BEARER_RE.sub(r"\1 [redacted]", text)
    text = _URL_RE.sub(_redact_url, text)
    text = _XML_TAG_RE.sub("[redacted-xml]", text)
    text = _UUID_RE.sub("[redacted-uuid]", text)
    text = _LONG_ID_RE.sub("[redacted-id]", text)
    return text


def redact_sensitive_data(value: Any, *, max_depth: int = 8) -> Any:
    """Recursively sanitize dicts, sequences, and strings before logging."""
    if max_depth <= 0:
        return "[truncated]"
    if isinstance(value, Mapping):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            key_str = str(key)
            if key_str.lower() in _SENSITIVE_KEYS:
                sanitized[key_str] = "[redacted]"
            else:
                sanitized[key_str] = redact_sensitive_data(
                    item, max_depth=max_depth - 1
                )
        return sanitized
    if isinstance(value, list):
        return [redact_sensitive_data(item, max_depth=max_depth - 1) for item in value]
    if isinstance(value, tuple):
        return tuple(
            redact_sensitive_data(item, max_depth=max_depth - 1) for item in value
        )
    if isinstance(value, str):
        return redact_sensitive_text(value)
    if isinstance(value, (bytes, bytearray)):
        return f"[{len(value)} bytes redacted]"
    return value


def sanitize_log_message(prefix: str, details: object = None) -> str:
    """Build a bounded log line with all sensitive fields scrubbed."""
    clean_prefix = redact_sensitive_text(prefix).strip()
    if details is None:
        return clean_prefix
    if isinstance(details, (Mapping, list, tuple)):
        return f"{clean_prefix}: {redact_sensitive_data(details)}"
    return f"{clean_prefix}: {redact_sensitive_text(details)}"
