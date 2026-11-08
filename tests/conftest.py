"""Shared pytest fixtures for igchat-v2 unit and integration tests."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from igchat_v2.core.models import InstagramSession


@pytest.fixture
def mock_session() -> InstagramSession:
    """Return a valid mock InstagramSession for testing."""
    return InstagramSession(
        ig_user_id="17841400000000001",
        ds_user_id="17841400000000001",
        eimu_id="17841400000000001",
        sessionid="17841400000000001%3Amock_session_token",
        csrftoken="mock_csrf_token_value",
        cookies="sessionid=17841400000000001%3Amock_session_token; ds_user_id=17841400000000001; csrftoken=mock_csrf_token_value; mid=mock_mid; ig_did=mock_did; rur=mock_rur",
        mid="mock_mid",
        ig_did="mock_did",
        rur="mock_rur",
        fb_dtsg="NAcMockDTSGToken",
        jazoest="22421",
        lsd="mock_lsd_token",
        client_revision="1019999999",
    )


class MockHTTPHandler:
    """Helper to mock httpx responses cleanly in unit tests."""

    def __init__(self, responses: dict[str, Any] | None = None) -> None:
        self.responses = responses or {}
        self.requests: list[httpx.Request] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        url_str = str(request.url)
        for pattern, resp_data in self.responses.items():
            if pattern in url_str:
                if callable(resp_data):
                    return resp_data(request)
                if isinstance(resp_data, tuple):
                    status, content = resp_data
                    return httpx.Response(
                        status_code=status, content=content, request=request
                    )
                return httpx.Response(status_code=200, json=resp_data, request=request)
        return httpx.Response(status_code=200, json={"status": "ok"}, request=request)
