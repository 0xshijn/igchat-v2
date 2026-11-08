"""SSRF-guarded async HTTP transport built on httpx.AsyncClient."""

from __future__ import annotations

import ipaddress
import math
import socket
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx

from .errors import SecurityViolationError
from .models import DEFAULT_IG_USER_AGENT, InstagramSession
from .utils import (
    IG_GRAPHQL_URL,
    build_graphql_form,
    build_ig_headers,
    parse_json_response,
)

DEFAULT_TIMEOUT_SECONDS = 15.0
MAX_PUBLIC_DOWNLOAD_BYTES = 20 * 1024 * 1024
MAX_REDIRECT_HOPS = 5
_CGNAT_NETWORK = ipaddress.IPv4Network("100.64.0.0/10")
_FORBIDDEN_HOST_SUFFIXES = (".local", ".internal", ".localhost", ".arpa")


def validate_timeout(timeout: float) -> float:
    """Validate that HTTP timeouts are finite positive numbers."""
    if not isinstance(timeout, (int, float)) or isinstance(timeout, bool):
        raise ValueError("HTTP timeout phải là số.")
    val = float(timeout)
    if not math.isfinite(val) or val <= 0:
        raise ValueError("HTTP timeout phải lớn hơn 0 và hữu hạn.")
    return val


def _is_forbidden_ip(
    address: ipaddress.IPv4Address | ipaddress.IPv6Address,
) -> bool:
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    if (
        address.is_loopback
        or address.is_private
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    ):
        return True
    if isinstance(address, ipaddress.IPv4Address) and address in _CGNAT_NETWORK:
        return True
    if isinstance(address, ipaddress.IPv6Address) and address.is_site_local:
        return True
    return False


def validate_public_http_url(url: str, *, resolve_dns: bool = True) -> str:
    """Ensure a URL targets public HTTP(S) space and never local/private networks."""
    raw = str(url).strip()
    if not raw:
        raise SecurityViolationError("URL không được để trống.")
    parsed = urlsplit(raw)
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"}:
        raise SecurityViolationError(
            f"Chỉ cho phép scheme http/https, từ chối {scheme!r}."
        )
    if parsed.username is not None or parsed.password is not None:
        raise SecurityViolationError("URL không được chứa thông tin xác thực nhúng.")
    host = (parsed.hostname or "").strip().lower().rstrip(".")
    if not host:
        raise SecurityViolationError("URL thiếu hostname hợp lệ.")
    if host == "localhost" or any(
        host.endswith(suffix) for suffix in _FORBIDDEN_HOST_SUFFIXES
    ):
        raise SecurityViolationError(f"Từ chối truy cập hostname nội bộ: {host!r}.")

    try:
        literal_ip = ipaddress.ip_address(host)
    except ValueError:
        literal_ip = None

    if literal_ip is not None:
        if _is_forbidden_ip(literal_ip):
            raise SecurityViolationError(
                f"Từ chối truy cập địa chỉ IP nội bộ/riêng tư: {literal_ip}."
            )
        return raw

    if resolve_dns:
        port = parsed.port or (443 if scheme == "https" else 80)
        try:
            infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        except OSError as exc:
            raise SecurityViolationError(
                f"Không phân giải được DNS công khai cho {host!r}."
            ) from exc
        if not infos:
            raise SecurityViolationError(f"Không có bản ghi IP cho {host!r}.")
        for info in infos:
            sockaddr = info[4]
            if not sockaddr:
                continue
            ip_text = str(sockaddr[0]).split("%", 1)[0]
            resolved_ip = ipaddress.ip_address(ip_text)
            if _is_forbidden_ip(resolved_ip):
                raise SecurityViolationError(
                    f"Hostname {host!r} phân giải tới IP nội bộ không an toàn."
                )

    return raw


@asynccontextmanager
async def use_async_client(
    client: httpx.AsyncClient | None = None,
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    user_agent: str = DEFAULT_IG_USER_AGENT,
) -> AsyncIterator[httpx.AsyncClient]:
    """Borrow caller's `httpx.AsyncClient` or open a scoped TLS-verified client."""
    valid_timeout = validate_timeout(timeout)
    if client is not None:
        yield client
        return
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(valid_timeout),
        headers={"User-Agent": user_agent},
        verify=True,
        follow_redirects=False,
    ) as owned:
        yield owned


async def get_async(
    url: str,
    *,
    client: httpx.AsyncClient | None = None,
    headers: Mapping[str, str] | None = None,
    params: Mapping[str, Any] | None = None,
    cookies: Mapping[str, str] | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    follow_redirects: bool = False,
) -> httpx.Response:
    """Execute an async HTTP GET request via httpx."""
    valid_timeout = validate_timeout(timeout)
    async with use_async_client(client, timeout=valid_timeout) as active:
        return await active.get(
            url,
            headers=dict(headers) if headers else None,
            params=dict(params) if params else None,
            cookies=dict(cookies) if cookies else None,
            timeout=valid_timeout,
            follow_redirects=follow_redirects,
        )


async def post_async(
    url: str,
    *,
    client: httpx.AsyncClient | None = None,
    headers: Mapping[str, str] | None = None,
    data: Mapping[str, Any] | None = None,
    content: bytes | str | None = None,
    json: Any = None,
    files: Any = None,
    cookies: Mapping[str, str] | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    follow_redirects: bool = False,
) -> httpx.Response:
    """Execute an async HTTP POST request via httpx."""
    valid_timeout = validate_timeout(timeout)
    async with use_async_client(client, timeout=valid_timeout) as active:
        req_content = content
        req_data = data
        if isinstance(req_data, (bytes, bytearray)):
            req_content = bytes(req_data)
            req_data = None
        return await active.post(
            url,
            headers=dict(headers) if headers else None,
            data=req_data,
            content=req_content,
            json=json,
            files=files,
            cookies=dict(cookies) if cookies else None,
            timeout=valid_timeout,
            follow_redirects=follow_redirects,
        )


async def post_graphql_async(
    session: InstagramSession,
    *,
    doc_id: str,
    variables: Mapping[str, Any],
    friendly_name: str = "",
    referer: str = "https://www.instagram.com/direct/inbox/",
    client: httpx.AsyncClient | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Execute a Polaris GraphQL query/mutation and return decoded JSON."""
    headers = build_ig_headers(
        session,
        referer=referer,
        extra={"X-FB-Friendly-Name": friendly_name} if friendly_name else None,
    )
    form = build_graphql_form(
        session,
        doc_id=doc_id,
        variables=variables,
        friendly_name=friendly_name,
    )
    response = await post_async(
        IG_GRAPHQL_URL,
        client=client,
        headers=headers,
        data=form,
        timeout=timeout,
    )
    response.raise_for_status()
    return parse_json_response(response.text)


async def download_public_bytes(
    url: str,
    *,
    client: httpx.AsyncClient | None = None,
    max_bytes: int = MAX_PUBLIC_DOWNLOAD_BYTES,
    timeout: float = 20.0,
    resolve_dns: bool = True,
) -> tuple[bytes, str]:
    """Safely download public HTTP(S) bytes with SSRF redirect validation & size cap."""
    if max_bytes <= 0:
        raise ValueError("max_bytes phải lớn hơn 0.")
    current_url = validate_public_http_url(url, resolve_dns=resolve_dns)
    valid_timeout = validate_timeout(timeout)

    async with use_async_client(client, timeout=valid_timeout) as active:
        for _ in range(MAX_REDIRECT_HOPS + 1):
            async with active.stream(
                "GET",
                current_url,
                timeout=valid_timeout,
                follow_redirects=False,
            ) as response:
                if 300 <= response.status_code < 400:
                    location = response.headers.get("location")
                    if not location:
                        raise SecurityViolationError("Redirect thiếu header Location.")
                    next_url = urljoin(current_url, location.strip())
                    current_url = validate_public_http_url(
                        next_url, resolve_dns=resolve_dns
                    )
                    continue
                response.raise_for_status()
                declared_len = response.headers.get("content-length")
                if declared_len and declared_len.isdigit():
                    if int(declared_len) > max_bytes:
                        raise SecurityViolationError(
                            f"Nội dung vượt quá giới hạn {max_bytes} bytes."
                        )
                buf = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(buf) + len(chunk) > max_bytes:
                        raise SecurityViolationError(
                            f"Nội dung stream vượt quá giới hạn {max_bytes} bytes."
                        )
                    buf.extend(chunk)
                content_type = response.headers.get(
                    "content-type", "application/octet-stream"
                )
                return bytes(buf), content_type.split(";", 1)[0].strip()

    raise SecurityViolationError("Vượt quá số lần redirect cho phép.")
