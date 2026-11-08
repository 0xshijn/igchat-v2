"""Unit tests for igchat_v2.bridge transport, reconnect policy and actions."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from igchat_v2.bridge.actions import BridgeActions
from igchat_v2.bridge.process import BridgeProcess, expected_platform_asset_name
from igchat_v2.bridge.reconnect import (
    ConnectionStatus,
    ReconnectPolicy,
    classify_bridge_error,
)
from igchat_v2.core.errors import (
    AuthenticationError,
    BridgeError,
    BridgeProtocolError,
)


def test_reconnect_policy() -> None:
    policy = ReconnectPolicy(
        max_retries=3, base_delay=1.0, max_delay=10.0, jitter_ratio=0.0
    )
    assert policy.compute_delay(1) == 1.0
    assert policy.compute_delay(2) == 2.0
    assert policy.compute_delay(3) == 4.0
    assert policy.compute_delay(10) == 10.0

    ok_status = ConnectionStatus(
        connected=False, failure_code="network_disconnected", retryable=True
    )
    assert policy.should_retry(1, ok_status)
    assert policy.should_retry(3, ok_status)
    assert not policy.should_retry(4, ok_status)

    perm_status = ConnectionStatus(
        connected=False, failure_code="auth_failed", permanent=True
    )
    assert not policy.should_retry(1, perm_status)


def test_classify_bridge_error() -> None:
    err_dict = {"errorCode": "checkpoint_required", "retryable": False}
    status = classify_bridge_error(err_dict)
    assert status.failure_code == "checkpoint_required"
    assert status.permanent is True
    assert status.retryable is False

    err_auth = AuthenticationError("Session expired")
    status_auth = classify_bridge_error(err_auth)
    assert status_auth.permanent is True
    assert status_auth.retryable is False

    err_transient = BridgeError(
        "Connection reset by peer", error_code="network_disconnected", retryable=True
    )
    status_transient = classify_bridge_error(err_transient)
    assert status_transient.retryable is True
    assert status_transient.permanent is False


def test_expected_platform_asset() -> None:
    asset = expected_platform_asset_name()
    assert "igchat-bridge-" in asset


@pytest.mark.asyncio
async def test_bridge_actions_argument_validation() -> None:
    mock_process = AsyncMock(spec=BridgeProcess)
    actions = BridgeActions(mock_process)

    with pytest.raises(ValueError):
        await actions.send_message("not_a_number", "hello")

    with pytest.raises(ValueError):
        await actions.send_message(12345, "")

    mock_process.call.return_value = {
        "messageId": "mid_123",
        "deliveryStatus": "acknowledged",
    }
    res = await actions.send_message(12345, "hello world")
    assert res["messageId"] == "mid_123"
    mock_process.call.assert_called_with(
        "sendMessage", {"threadId": 12345, "text": "hello world"}, timeout=30.0
    )

    with pytest.raises(ValueError):
        await actions.create_group([123], title="Too few members")

    mock_process.call.return_value = {"threadId": 99999}
    await actions.create_group([101, 102], title="My Group")
    mock_process.call.assert_called_with(
        "createGroup", {"userIds": [101, 102], "title": "My Group"}, timeout=30.0
    )


@pytest.mark.asyncio
async def test_bridge_process_hello_validation() -> None:
    bp = BridgeProcess()
    with pytest.raises(BridgeProtocolError):
        bp._validate_hello(
            {"protocolVersion": 2, "bridgeVersion": "3.0.0", "capabilities": []}
        )

    with pytest.raises(BridgeProtocolError):
        bp._validate_hello(
            {"protocolVersion": 1, "bridgeVersion": "2.3.4", "capabilities": []}
        )

    with pytest.raises(BridgeProtocolError):
        bp._validate_hello(
            {
                "protocolVersion": 1,
                "bridgeVersion": "3.0.0",
                "capabilities": ["connect"],
            }
        )

    valid_hello = {
        "protocolVersion": 1,
        "bridgeVersion": "3.0.0",
        "platform": "instagram",
        "capabilities": [
            "newClient",
            "connect",
            "isConnected",
            "events",
            "structuredConnectionStatus",
        ],
    }
    bp._validate_hello(valid_hello)
