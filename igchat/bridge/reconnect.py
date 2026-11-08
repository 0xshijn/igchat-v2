"""Reconnect backoff policy and structured Instagram bridge error classification."""

from __future__ import annotations

import math
import random
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

TERMINAL_FAILURE_CODES = frozenset(
    {
        "auth_failed",
        "checkpoint_required",
        "config_invalid",
        "protocol_error",
    }
)


@dataclass(frozen=True, slots=True)
class ReconnectPolicy:
    """Bounded exponential backoff with jitter for DGW/bridge recovery."""

    max_retries: int | None = None
    base_delay: float = 2.0
    max_delay: float = 60.0
    jitter_ratio: float = 0.25
    stable_reset_seconds: float = 60.0

    def __post_init__(self) -> None:
        if self.max_retries is not None and self.max_retries < 0:
            raise ValueError("max_retries phải >= 0 hoặc None.")
        for field_name, val in (
            ("base_delay", self.base_delay),
            ("max_delay", self.max_delay),
            ("stable_reset_seconds", self.stable_reset_seconds),
        ):
            if not math.isfinite(val) or val <= 0:
                raise ValueError(f"{field_name} phải > 0 và hữu hạn.")
        if self.max_delay < self.base_delay:
            raise ValueError("max_delay phải >= base_delay.")
        if (
            not math.isfinite(self.jitter_ratio)
            or self.jitter_ratio < 0
            or self.jitter_ratio > 1
        ):
            raise ValueError("jitter_ratio phải nằm trong [0, 1].")

    def compute_delay(self, attempt: int, *, rng: random.Random | None = None) -> float:
        """Compute delay in seconds for the given 1-based retry attempt."""
        step = max(0, attempt - 1)
        raw = min(self.max_delay, self.base_delay * (2**step))
        if self.jitter_ratio <= 0:
            return raw
        generator = rng or random
        spread = raw * self.jitter_ratio
        return max(0.05, raw + generator.uniform(-spread, spread))

    def should_retry(self, attempt: int, status: ConnectionStatus) -> bool:
        """Determine whether a reconnect attempt is allowed."""
        if status.permanent or status.failure_code in TERMINAL_FAILURE_CODES:
            return False
        if not status.retryable and status.failure_code:
            return False
        if self.max_retries is not None and attempt > self.max_retries:
            return False
        return True


@dataclass(frozen=True, slots=True)
class ConnectionStatus:
    """Normalized connection status returned by `isConnected` or error classification."""

    connected: bool
    native_reconnecting: bool = False
    failure_code: str = ""
    retryable: bool = False
    permanent: bool = False
    failure_transport: str = ""

    @classmethod
    def from_rpc(cls, payload: Mapping[str, Any]) -> ConnectionStatus:
        """Build `ConnectionStatus` from an `isConnected` JSON-RPC response dict."""
        code = str(payload.get("failureCode") or "").strip()
        permanent = bool(payload.get("permanent", False)) or (
            code in TERMINAL_FAILURE_CODES
        )
        retryable = bool(payload.get("retryable", False)) and not permanent
        return cls(
            connected=bool(payload.get("connected", False)),
            native_reconnecting=bool(payload.get("nativeReconnecting", False)),
            failure_code=code,
            retryable=retryable,
            permanent=permanent,
            failure_transport=str(payload.get("failureTransport") or "").strip(),
        )


def classify_bridge_error(error: BaseException | Mapping[str, Any]) -> ConnectionStatus:
    """Classify an RPC failure or exception into retryable vs permanent status."""
    if isinstance(error, Mapping):
        code = str(error.get("errorCode") or error.get("failureCode") or "").strip()
        if code in TERMINAL_FAILURE_CODES:
            return ConnectionStatus(
                connected=False,
                failure_code=code,
                retryable=False,
                permanent=True,
                failure_transport="instagram",
            )
        retryable = error.get("retryable")
        if retryable is None:
            retryable = code in {"network_disconnected", ""}
        return ConnectionStatus(
            connected=False,
            failure_code=code or "network_disconnected",
            retryable=bool(retryable),
            permanent=not bool(retryable) and bool(code),
            failure_transport="instagram",
        )

    code = str(getattr(error, "error_code", "") or "").strip()
    retryable_attr = getattr(error, "retryable", None)
    if code in TERMINAL_FAILURE_CODES or "auth" in type(error).__name__.lower():
        return ConnectionStatus(
            connected=False,
            failure_code=code or "auth_failed",
            retryable=False,
            permanent=True,
            failure_transport="instagram",
        )
    if code == "cancelled" or isinstance(error, (KeyboardInterrupt,)):
        return ConnectionStatus(
            connected=False,
            failure_code="cancelled",
            retryable=False,
            permanent=True,
            failure_transport="instagram",
        )
    retryable = True if retryable_attr is None else bool(retryable_attr)
    return ConnectionStatus(
        connected=False,
        failure_code=code or "network_disconnected",
        retryable=retryable,
        permanent=not retryable,
        failure_transport="instagram",
    )
