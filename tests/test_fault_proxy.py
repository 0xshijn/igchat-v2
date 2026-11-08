"""Unit tests for scripts._fault_proxy LoopbackConnectProxy."""

from __future__ import annotations


import pytest

from scripts._fault_proxy import (
    LoopbackConnectProxy,
    child_environment,
)


def test_child_environment() -> None:
    base = {"USER": "test", "PATH": "/bin"}
    env = child_environment("http://127.0.0.1:8080", base)
    assert env["HTTPS_PROXY"] == "http://127.0.0.1:8080"
    assert env["HTTP_PROXY"] == "http://127.0.0.1:8080"
    assert env["NO_PROXY"] == ""
    assert env["USER"] == "test"

    with pytest.raises(ValueError):
        child_environment("https://external.com", base)


def test_loopback_proxy_lifecycle() -> None:
    with LoopbackConnectProxy() as proxy:
        assert proxy.url.startswith("http://127.0.0.1:")
        snap = proxy.snapshot()
        assert snap["connect_requests"] == 0
        assert snap["active_tunnels"] == 0

        proxy.begin_outage(5.0)
        snap_outage = proxy.snapshot()
        assert snap_outage["cut_tunnels"] == 0
