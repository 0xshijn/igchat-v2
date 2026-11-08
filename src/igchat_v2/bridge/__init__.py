"""Managed Go JSON-RPC bridge transport & high-level Direct action client."""

from __future__ import annotations

from .actions import BridgeActions, MAX_INLINE_MEDIA_BYTES
from .checksums import BRIDGE_RELEASE_VERSION, BRIDGE_SHA256
from .process import (
    BRIDGE_PROTOCOL_VERSION,
    EXPECTED_BRIDGE_VERSION,
    REQUIRED_CAPABILITIES,
    BridgeProcess,
    expected_platform_asset_name,
    resolve_bridge_binary,
)
from .reconnect import (
    TERMINAL_FAILURE_CODES,
    ConnectionStatus,
    ReconnectPolicy,
    classify_bridge_error,
)

__all__ = [
    "BRIDGE_PROTOCOL_VERSION",
    "BRIDGE_RELEASE_VERSION",
    "BRIDGE_SHA256",
    "BridgeActions",
    "BridgeProcess",
    "ConnectionStatus",
    "EXPECTED_BRIDGE_VERSION",
    "MAX_INLINE_MEDIA_BYTES",
    "REQUIRED_CAPABILITIES",
    "ReconnectPolicy",
    "TERMINAL_FAILURE_CODES",
    "classify_bridge_error",
    "expected_platform_asset_name",
    "resolve_bridge_binary",
]
