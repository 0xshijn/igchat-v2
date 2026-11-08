"""Pluggable cookie and session storage providers (file & environment)."""

from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ..core.errors import SessionCookieError
from ..core.models import (
    InstagramSession,
    format_cookie_header,
    parse_cookie_header,
)
from ..core.permissions import create_private_json_file, require_private_file


def _serialize_session_payload(
    value: InstagramSession | Mapping[str, Any] | str,
) -> str:
    if isinstance(value, InstagramSession):
        return json.dumps(value.to_dict(), ensure_ascii=False, indent=2) + "\n"
    if isinstance(value, Mapping):
        return json.dumps(dict(value), ensure_ascii=False, indent=2) + "\n"
    if isinstance(value, str):
        parsed = parse_cookie_header(value.strip())
        if not parsed:
            raise SessionCookieError("Cookie string rỗng hoặc không hợp lệ.")
        return (
            json.dumps({"cookies": value.strip()}, ensure_ascii=False, indent=2) + "\n"
        )
    raise TypeError("Session storage chỉ chấp nhận InstagramSession, Mapping hoặc str.")


def _extract_cookie_header(payload: Any) -> str | None:
    if isinstance(payload, str):
        stripped = payload.strip()
        return stripped or None
    if isinstance(payload, Mapping):
        raw = payload.get("cookies")
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
        cookie_keys = ("sessionid", "ds_user_id", "csrftoken", "mid", "ig_did", "rur")
        present = {
            k: str(payload[k]).strip()
            for k in cookie_keys
            if payload.get(k) and isinstance(payload[k], str)
        }
        if present:
            return format_cookie_header(present)
    return None


class SessionStorage(ABC):
    """Abstract storage contract for Instagram cookie headers and sessions."""

    @abstractmethod
    def load_cookies(self) -> str | None:
        """Return a serialized HTTP Cookie header if available."""

    def load_session(self) -> InstagramSession | None:
        """Return a hydrated `InstagramSession` if JSON fields are stored."""
        return None

    @abstractmethod
    def save(self, value: InstagramSession | Mapping[str, Any] | str) -> None:
        """Persist a session snapshot or raw cookie string."""

    @abstractmethod
    def clear(self) -> None:
        """Remove stored credentials if supported."""


class FileSessionStorage(SessionStorage):
    """Atomic JSON file session storage locked with owner-only ACLs."""

    def __init__(self, path: str | Path, *, private: bool = True) -> None:
        self.path = Path(path)
        self.private = private

    def __repr__(self) -> str:
        return f"FileSessionStorage(path={str(self.path)!r}, private={self.private})"

    def _read_raw(self) -> dict[str, Any] | str | None:
        if not self.path.exists():
            return None
        target = require_private_file(self.path)
        text = target.read_text(encoding="utf-8", errors="strict").strip()
        if not text:
            return None
        if text.startswith("{"):
            loaded = json.loads(text)
            if not isinstance(loaded, dict):
                raise SessionCookieError("File session JSON phải là object.")
            return loaded
        return text

    def load_cookies(self) -> str | None:
        raw = self._read_raw()
        if raw is None:
            return None
        return _extract_cookie_header(raw)

    def load_session(self) -> InstagramSession | None:
        raw = self._read_raw()
        if not isinstance(raw, dict):
            return None
        if not (raw.get("ig_user_id") or raw.get("ds_user_id")):
            return None
        return InstagramSession.from_mapping(raw)

    def save(self, value: InstagramSession | Mapping[str, Any] | str) -> None:
        serialized = _serialize_session_payload(value)
        if self.private:
            create_private_json_file(self.path, serialized)
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(serialized, encoding="utf-8", newline="\n")

    def clear(self) -> None:
        if self.path.exists() and not self.path.is_symlink():
            self.path.unlink()


class EnvSessionStorage(SessionStorage):
    """Read-only environment variable cookie storage (never leaks secrets in repr)."""

    def __init__(
        self,
        env_var: str = "IGCHAT_COOKIE",
        *,
        fallback_env_vars: tuple[str, ...] = ("IGCHAT_COOKIES",),
    ) -> None:
        self.env_var = env_var
        self.fallback_env_vars = fallback_env_vars

    def __repr__(self) -> str:
        return f"EnvSessionStorage(env_var={self.env_var!r})"

    def load_cookies(self) -> str | None:
        for name in (self.env_var, *self.fallback_env_vars):
            raw = os.getenv(name, "").strip()
            if not raw:
                continue
            if raw.startswith("{"):
                loaded = json.loads(raw)
                extracted = _extract_cookie_header(loaded)
                if extracted:
                    return extracted
                continue
            return raw
        return None

    def load_session(self) -> InstagramSession | None:
        for name in (self.env_var, *self.fallback_env_vars):
            raw = os.getenv(name, "").strip()
            if raw.startswith("{"):
                loaded = json.loads(raw)
                if isinstance(loaded, dict) and (
                    loaded.get("ig_user_id") or loaded.get("ds_user_id")
                ):
                    return InstagramSession.from_mapping(loaded)
        return None

    def save(self, value: InstagramSession | Mapping[str, Any] | str) -> None:
        raise PermissionError(
            "EnvSessionStorage chỉ hỗ trợ đọc biến môi trường, không ghi vào env."
        )

    def clear(self) -> None:
        for name in (self.env_var, *self.fallback_env_vars):
            os.environ.pop(name, None)
