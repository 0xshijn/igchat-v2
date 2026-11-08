"""Pure Instagram Web AJAX login & TOTP 2FA handler (no Facebook endpoints)."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any

import httpx
import pyotp

from ..core.errors import AuthenticationError, CheckpointRequiredError
from ..core.http import DEFAULT_TIMEOUT_SECONDS, use_async_client
from ..core.models import (
    DEFAULT_IG_USER_AGENT,
    InstagramSession,
    format_cookie_header,
)
from ..core.utils import IG_APP_ID, IG_BASE_URL
from .session import bootstrap_session

_CSRF_SHARED_RE = re.compile(r'"csrf_token"\s*:\s*"([^"]+)"')


@dataclass(frozen=True, slots=True)
class LoginResult:
    """Structured result of an Instagram Web login attempt."""

    status: str
    cookie_header: str
    user_id: str = ""
    session: InstagramSession | None = None


def _build_enc_password(password: str, *, timestamp: int | None = None) -> str:
    ts = int(time.time()) if timestamp is None else int(timestamp)
    return f"#PWD_INSTAGRAM_BROWSER:0:{ts}:{password}"


async def login_with_credentials(
    username: str,
    password: str,
    *,
    totp_secret: str = "",
    two_factor_code: str = "",
    hydrate_session: bool = True,
    client: httpx.AsyncClient | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    user_agent: str = DEFAULT_IG_USER_AGENT,
) -> LoginResult:
    """Authenticate an Instagram account via web AJAX login + optional TOTP 2FA."""
    clean_user = username.strip()
    if not clean_user or not password:
        raise ValueError("Username và password không được để trống.")

    base_headers = {
        "User-Agent": user_agent,
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Origin": IG_BASE_URL,
        "Referer": f"{IG_BASE_URL}/accounts/login/",
        "X-IG-App-ID": IG_APP_ID,
        "X-Requested-With": "XMLHttpRequest",
    }

    async with use_async_client(
        client, timeout=timeout, user_agent=user_agent
    ) as active:
        cookie_jar: dict[str, str] = {}

        # Step 1: Fetch login page / preflight endpoint for initial csrftoken & mid
        preflight = await active.get(
            f"{IG_BASE_URL}/api/v1/web/login_page/",
            headers=base_headers,
            timeout=timeout,
            follow_redirects=False,
        )
        for name, val in preflight.cookies.items():
            if val:
                cookie_jar[name] = val

        if not cookie_jar.get("csrftoken"):
            fallback_page = await active.get(
                f"{IG_BASE_URL}/accounts/login/",
                headers=base_headers,
                timeout=timeout,
                follow_redirects=False,
            )
            for name, val in fallback_page.cookies.items():
                if val:
                    cookie_jar[name] = val
            if not cookie_jar.get("csrftoken"):
                found = _CSRF_SHARED_RE.search(fallback_page.text)
                if found:
                    cookie_jar["csrftoken"] = found.group(1)

        csrftoken = cookie_jar.get("csrftoken", "")
        if not csrftoken:
            raise AuthenticationError(
                "Không lấy được csrftoken khởi tạo từ trang đăng nhập Instagram."
            )

        login_headers = {
            **base_headers,
            "X-CSRFToken": csrftoken,
            "Cookie": format_cookie_header(cookie_jar),
        }
        login_payload = {
            "username": clean_user,
            "enc_password": _build_enc_password(password),
            "queryParams": "{}",
            "optIntoOneTap": "false",
            "stopDeletionNonce": "",
            "trustedDeviceRecords": "{}",
        }

        response = await active.post(
            f"{IG_BASE_URL}/api/v1/web/accounts/login/ajax/",
            headers=login_headers,
            data=login_payload,
            timeout=timeout,
            follow_redirects=False,
        )
        for name, val in response.cookies.items():
            if val:
                cookie_jar[name] = val

        try:
            body: dict[str, Any] = response.json()
        except Exception as exc:
            raise AuthenticationError(
                f"Instagram trả về phản hồi login không hợp lệ (HTTP {response.status_code})."
            ) from exc

        # Checkpoint / challenge gate
        checkpoint_url = str(body.get("checkpoint_url") or "")
        if checkpoint_url or body.get("message") == "challenge_required":
            raise CheckpointRequiredError(
                "Instagram yêu cầu xác minh challenge/checkpoint.",
                checkpoint_path=checkpoint_url.split("?", 1)[0],
            )

        # Two-factor authentication flow
        if body.get("two_factor_required"):
            tf_info = body.get("two_factor_info")
            if not isinstance(tf_info, dict):
                raise AuthenticationError(
                    "Instagram yêu cầu 2FA nhưng thiếu identifier."
                )
            identifier = str(tf_info.get("two_factor_identifier") or "").strip()
            code = two_factor_code.strip()
            if not code and totp_secret.strip():
                code = pyotp.TOTP(totp_secret.strip().replace(" ", "")).now()
            if not code:
                raise AuthenticationError(
                    "Tài khoản bật 2FA; cần truyền two_factor_code hoặc totp_secret."
                )

            tf_headers = {
                **base_headers,
                "X-CSRFToken": cookie_jar.get("csrftoken", csrftoken),
                "Cookie": format_cookie_header(cookie_jar),
            }
            tf_payload = {
                "username": clean_user,
                "verificationCode": code,
                "identifier": identifier,
                "queryParams": '{"next":"/"}',
            }
            tf_resp = await active.post(
                f"{IG_BASE_URL}/api/v1/web/accounts/login/ajax/two_factor/",
                headers=tf_headers,
                data=tf_payload,
                timeout=timeout,
                follow_redirects=False,
            )
            for name, val in tf_resp.cookies.items():
                if val:
                    cookie_jar[name] = val
            body = tf_resp.json()

        if body.get("authenticated") is not True:
            reason = str(
                body.get("message") or body.get("error_type") or "authentication_failed"
            )
            raise AuthenticationError(
                f"Đăng nhập Instagram không thành công: {reason}."
            )

        cookie_header = format_cookie_header(cookie_jar)
        uid = str(body.get("userId") or cookie_jar.get("ds_user_id") or "").strip()
        if not hydrate_session:
            return LoginResult(
                status="authenticated",
                cookie_header=cookie_header,
                user_id=uid,
                session=None,
            )

        session = await bootstrap_session(
            cookie_jar, client=active, timeout=timeout, user_agent=user_agent
        )
        return LoginResult(
            status="authenticated",
            cookie_header=session.cookies,
            user_id=session.ig_user_id,
            session=session,
        )
