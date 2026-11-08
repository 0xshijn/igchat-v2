"""Async event listener around the managed Go Instagram Direct bridge."""

from __future__ import annotations

import asyncio
import inspect
import time
from collections import deque
from collections.abc import Awaitable, Callable, Mapping
from contextlib import suppress
from pathlib import Path
from typing import Any

from ..bridge.actions import BridgeActions
from ..bridge.process import EXPECTED_BRIDGE_VERSION, BridgeProcess
from ..bridge.reconnect import (
    ConnectionStatus,
    ReconnectPolicy,
    classify_bridge_error,
)
from ..core.errors import BridgeError
from ..core.models import InstagramSession, normalize_session

EventCallback = Callable[[dict[str, Any]], Any | Awaitable[Any]]


class DirectListener:
    """Single-use async Instagram Direct event listener powered by `igchat-bridge`."""

    MAX_SEEN_IDS = 4096

    def __init__(
        self,
        session: InstagramSession | Mapping[str, Any],
        *,
        binary_path: str | Path | None = None,
        log_level: str = "warn",
        reconnect_policy: ReconnectPolicy | None = None,
        startup_timeout: float = 45.0,
        health_poll_interval: float = 5.0,
    ) -> None:
        self.session = normalize_session(session)
        self._binary_path = binary_path
        self._log_level = log_level
        self.reconnect_policy = reconnect_policy or ReconnectPolicy()
        self.startup_timeout = float(startup_timeout)
        self.health_poll_interval = float(health_poll_interval)

        self._bridge: BridgeProcess | None = None
        self._actions: BridgeActions | None = None
        self._callbacks: dict[str, list[EventCallback]] = {}
        self._seen_order: deque[str] = deque()
        self._seen_set: set[str] = set()
        self._connected_event = asyncio.Event()
        self._stop_event = asyncio.Event()
        self._started = False
        self._stopped = False
        self._status = ConnectionStatus(connected=False)
        self._user_info: dict[str, Any] = {}
        self._initial_data: dict[str, Any] = {}

    @property
    def bridge(self) -> BridgeProcess | None:
        return self._bridge

    @property
    def actions(self) -> BridgeActions:
        if self._actions is None:
            raise BridgeError("DirectListener chưa kết nối bridge.")
        return self._actions

    @property
    def connection_status(self) -> ConnectionStatus:
        return self._status

    @property
    def user_info(self) -> dict[str, Any]:
        return dict(self._user_info)

    @property
    def initial_data(self) -> dict[str, Any]:
        return dict(self._initial_data)

    def on(self, event_type: str, callback: EventCallback) -> EventCallback:
        """Register an async or sync callback for an Instagram Direct event type."""
        bucket = self._callbacks.setdefault(event_type, [])
        bucket.append(callback)
        return callback

    def on_event(self, callback: EventCallback) -> EventCallback:
        """Register a catch-all listener invoked for every bridge event envelope."""
        return self.on("*", callback)

    def on_message(self, callback: EventCallback) -> EventCallback:
        return self.on("message", callback)

    def on_edit(self, callback: EventCallback) -> EventCallback:
        return self.on("messageEdit", callback)

    def on_unsend(self, callback: EventCallback) -> EventCallback:
        return self.on("messageUnsend", callback)

    def on_reaction(self, callback: EventCallback) -> EventCallback:
        return self.on("reaction", callback)

    def on_typing(self, callback: EventCallback) -> EventCallback:
        return self.on("typing", callback)

    def on_read_receipt(self, callback: EventCallback) -> EventCallback:
        return self.on("readReceipt", callback)

    def on_thread_update(self, callback: EventCallback) -> EventCallback:
        return self.on("threadUpdate", callback)

    def on_ready(self, callback: EventCallback) -> EventCallback:
        return self.on("ready", callback)

    def on_disconnected(self, callback: EventCallback) -> EventCallback:
        return self.on("disconnected", callback)

    def on_error(self, callback: EventCallback) -> EventCallback:
        return self.on("error", callback)

    async def wait_until_connected(self, timeout: float | None = None) -> bool:
        """Wait until DGW/Slide connection reaches ready state (or timeout)."""
        if self._connected_event.is_set():
            return True
        if timeout is None:
            await self._connected_event.wait()
            return True
        try:
            await asyncio.wait_for(self._connected_event.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False

    def stop(self) -> None:
        """Request listener shutdown."""
        self._stopped = True
        self._stop_event.set()
        self._connected_event.clear()

    def _is_duplicate_message(self, event_type: str, data: Any) -> bool:
        if event_type != "message" or not isinstance(data, Mapping):
            return False
        msg_id = str(data.get("id") or "").strip()
        if not msg_id:
            return False
        if msg_id in self._seen_set:
            return True
        self._seen_set.add(msg_id)
        self._seen_order.append(msg_id)
        if len(self._seen_order) > self.MAX_SEEN_IDS:
            expired = self._seen_order.popleft()
            self._seen_set.discard(expired)
        return False

    async def _dispatch(self, event: dict[str, Any]) -> None:
        event_type = str(event.get("type") or "")
        data = event.get("data")
        if self._is_duplicate_message(event_type, data):
            return

        if event_type in {"ready", "reconnected"}:
            self._status = ConnectionStatus(connected=True)
            self._connected_event.set()
        elif event_type == "disconnected":
            self._status = ConnectionStatus(connected=False)
            self._connected_event.clear()

        targets = [
            *self._callbacks.get("*", ()),
            *self._callbacks.get(event_type, ()),
        ]
        for callback in targets:
            result = callback(event)
            if inspect.isawaitable(result):
                await result

    async def _connect_bridge_once(self) -> None:
        bridge = BridgeProcess(
            binary_path=self._binary_path,
            expected_version=EXPECTED_BRIDGE_VERSION,
        )
        self._bridge = bridge
        self._actions = BridgeActions(bridge)
        try:
            await bridge.start(handshake_timeout=min(15.0, self.startup_timeout))
            await bridge.call(
                "newClient",
                {
                    "cookies": self.session.as_cookie_dict(),
                    "platform": "instagram",
                    "logLevel": self._log_level,
                },
                timeout=15.0,
            )
            connect_result = await bridge.call(
                "connect", {}, timeout=self.startup_timeout
            )
            user_data = connect_result.get("user")
            if isinstance(user_data, dict):
                self._user_info = user_data
            initial = connect_result.get("initial")
            if isinstance(initial, dict):
                self._initial_data = initial
            self._status = ConnectionStatus(connected=True)
            self._connected_event.set()
        except BaseException:
            await bridge.close()
            if self._bridge is bridge:
                self._bridge = None
                self._actions = None
            raise

    async def listen(self) -> None:
        """Start the bridge and process Instagram Direct events until stopped."""
        if self._started:
            raise RuntimeError("DirectListener là single-use; hãy tạo instance mới.")
        self._started = True

        attempt = 0
        try:
            while not self._stop_event.is_set():
                connected_at = 0.0
                try:
                    await self._connect_bridge_once()
                    connected_at = time.monotonic()
                    assert self._bridge is not None
                    await self._pump_until_disconnect(self._bridge)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    self._connected_event.clear()
                    status = classify_bridge_error(exc)
                    self._status = status
                    await self._dispatch(
                        {
                            "type": "error",
                            "data": {
                                "message": str(exc),
                                "errorCode": status.failure_code,
                                "retryable": status.retryable,
                            },
                        }
                    )
                    if self._stop_event.is_set():
                        break
                    if (
                        connected_at
                        and time.monotonic() - connected_at
                        >= self.reconnect_policy.stable_reset_seconds
                    ):
                        attempt = 0
                    attempt += 1
                    if not self.reconnect_policy.should_retry(attempt, status):
                        raise
                    delay = self.reconnect_policy.compute_delay(attempt)
                    try:
                        await asyncio.wait_for(self._stop_event.wait(), timeout=delay)
                        break
                    except asyncio.TimeoutError:
                        continue
                finally:
                    if self._bridge is not None:
                        await self._bridge.close()
                        self._bridge = None
                        self._actions = None
        finally:
            self._stopped = True
            self._stop_event.set()
            self._connected_event.clear()

    async def _pump_until_disconnect(self, bridge: BridgeProcess) -> None:
        next_health = time.monotonic() + self.health_poll_interval
        while not self._stop_event.is_set():
            if not bridge.is_running:
                raise BridgeError(
                    "Tiến trình Go bridge đã dừng ngoài dự kiến.",
                    error_code="network_disconnected",
                    retryable=True,
                )
            wait_budget = max(0.05, min(0.5, next_health - time.monotonic()))
            event: dict[str, Any] | None = None
            try:
                event = await bridge.get_event(timeout=wait_budget)
            except asyncio.TimeoutError:
                pass

            if event is not None:
                await self._dispatch(event)
                if event.get("type") == "disconnected":
                    # Native client handles DGW reconnect internally unless permanent
                    status = await bridge.call("isConnected", {}, timeout=5.0)
                    parsed = ConnectionStatus.from_rpc(status)
                    self._status = parsed
                    if parsed.permanent:
                        raise BridgeError(
                            f"Kết nối Instagram thất bại vĩnh viễn: {parsed.failure_code}",
                            error_code=parsed.failure_code,
                            retryable=False,
                        )
                continue

            if time.monotonic() >= next_health:
                next_health = time.monotonic() + self.health_poll_interval
                raw_status = await bridge.call("isConnected", {}, timeout=8.0)
                parsed = ConnectionStatus.from_rpc(raw_status)
                self._status = parsed
                if parsed.connected:
                    self._connected_event.set()
                else:
                    self._connected_event.clear()
                    if parsed.permanent:
                        raise BridgeError(
                            f"Lỗi phiên Instagram: {parsed.failure_code}",
                            error_code=parsed.failure_code,
                            retryable=False,
                        )

    async def aclose(self) -> None:
        self.stop()
        if self._bridge is not None:
            with suppress(Exception):
                await self._bridge.close()
            self._bridge = None
            self._actions = None

    start = listen
    close = aclose
