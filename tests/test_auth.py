"""Unit tests for igchat_v2.auth storage, bootstrap and login."""

from __future__ import annotations

import os
from pathlib import Path

import httpx
import pytest

from igchat_v2.auth.login import _build_enc_password, login_with_credentials
from igchat_v2.auth.session import bootstrap_session
from igchat_v2.auth.storage import EnvSessionStorage, FileSessionStorage
from igchat_v2.core.errors import (
    CheckpointRequiredError,
    SessionCookieError,
)
from igchat_v2.core.models import InstagramSession


def test_file_session_storage(tmp_path: Path, mock_session: InstagramSession) -> None:
    path = tmp_path / "session.json"
    storage = FileSessionStorage(path)

    assert storage.load_cookies() is None
    assert storage.load_session() is None

    storage.save(mock_session)
    assert path.is_file()

    loaded_cookies = storage.load_cookies()
    assert loaded_cookies is not None
    assert "mock_session_token" in loaded_cookies

    loaded_session = storage.load_session()
    assert loaded_session is not None
    assert loaded_session.ig_user_id == mock_session.ig_user_id

    storage.clear()
    assert not path.exists()


def test_env_session_storage(mock_session: InstagramSession) -> None:
    env_name = "IGCHAT_COOKIE_TEST"
    storage = EnvSessionStorage(env_var=env_name, fallback_env_vars=())

    os.environ.pop(env_name, None)
    assert storage.load_cookies() is None

    os.environ[env_name] = mock_session.cookies
    assert storage.load_cookies() == mock_session.cookies

    os.environ.pop(env_name, None)


@pytest.mark.asyncio
async def test_bootstrap_session_success() -> None:
    html_content = (
        "<html><script>"
        '{"IG_USER_EIMU":"17841400000000001",'
        '"viewerId":"17841400000000001",'
        '"client_revision":1019999999}'
        "</script></html>"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text=html_content,
            headers={"set-cookie": "csrftoken=new_csrf_from_server; Path=/"},
            request=request,
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        sess = await bootstrap_session(
            "sessionid=17841400000000001%3Atoken; ds_user_id=17841400000000001",
            client=client,
        )
        assert sess.ig_user_id == "17841400000000001"
        assert sess.eimu_id == "17841400000000001"
        assert sess.csrftoken == "new_csrf_from_server"


@pytest.mark.asyncio
async def test_bootstrap_session_checkpoint_redirect() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            302,
            headers={"Location": "https://www.instagram.com/challenge/action/"},
            request=request,
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(CheckpointRequiredError):
            await bootstrap_session(
                "sessionid=17841400000000001%3Atoken; ds_user_id=17841400000000001",
                client=client,
            )


@pytest.mark.asyncio
async def test_bootstrap_session_missing_cookies() -> None:
    with pytest.raises(SessionCookieError):
        await bootstrap_session("")

    with pytest.raises(SessionCookieError):
        await bootstrap_session("csrftoken=only_csrf")


def test_enc_password_format() -> None:
    enc = _build_enc_password("my_secret_pass", timestamp=1700000000)
    assert enc == "#PWD_INSTAGRAM_BROWSER:0:1700000000:my_secret_pass"


@pytest.mark.asyncio
async def test_login_with_credentials_success() -> None:
    step = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal step
        url_str = str(request.url)
        if "login_page" in url_str:
            return httpx.Response(
                200,
                headers={
                    "set-cookie": "csrftoken=initial_csrf; Path=/, mid=initial_mid; Path=/"
                },
                request=request,
            )
        if "accounts/login/ajax" in url_str:
            return httpx.Response(
                200,
                json={"authenticated": True, "userId": "17841400000000001"},
                headers={
                    "set-cookie": "sessionid=17841400000000001%3Alogged_in_token; Path=/"
                },
                request=request,
            )
        return httpx.Response(200, text="{}", request=request)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        result = await login_with_credentials(
            "test_user",
            "test_pass",
            hydrate_session=False,
            client=client,
        )
        assert result.status == "authenticated"
        assert result.user_id == "17841400000000001"
        assert "logged_in_token" in result.cookie_header


@pytest.mark.asyncio
async def test_login_with_credentials_checkpoint() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        url_str = str(request.url)
        if "login_page" in url_str:
            return httpx.Response(
                200, headers={"set-cookie": "csrftoken=c1; Path=/"}, request=request
            )
        return httpx.Response(
            200,
            json={"message": "challenge_required", "checkpoint_url": "/challenge/123/"},
            request=request,
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(CheckpointRequiredError):
            await login_with_credentials("test_user", "test_pass", client=client)
