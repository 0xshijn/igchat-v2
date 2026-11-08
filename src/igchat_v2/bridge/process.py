"""Managed subprocess JSON-RPC transport for the Go Instagram Direct bridge."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import platform
import secrets
import stat
import subprocess
from collections.abc import Mapping
from contextlib import suppress
from pathlib import Path
from typing import Any

from ..core.errors import (
    AuthenticationError,
    BridgeError,
    BridgeProtocolError,
    CheckpointRequiredError,
    SecurityViolationError,
)
from ..core.http import download_public_bytes
from ..core.redact import redact_sensitive_text
from . import checksums

BRIDGE_PROTOCOL_VERSION = 1
EXPECTED_BRIDGE_VERSION = "3.0.0"
REQUIRED_CAPABILITIES = frozenset(
    {
        "newClient",
        "connect",
        "isConnected",
        "events",
        "structuredConnectionStatus",
    }
)
MAX_RPC_LINE_BYTES = 16 * 1024 * 1024
MAX_EVENT_QUEUE_SIZE = 512
RELEASE_DOWNLOAD_BASE = "https://github.com/0xshijn/igchat-v2/releases/download"


def expected_platform_asset_name() -> str:
    """Return the canonical cross-compiled Go binary asset name for this host."""
    sys_name = platform.system().lower()
    machine = platform.machine().lower()
    if machine in {"x86_64", "amd64"}:
        arch = "amd64"
    elif machine in {"aarch64", "arm64"}:
        arch = "arm64"
    else:
        raise BridgeError(f"Kiến trúc CPU chưa được hỗ trợ cho Go bridge: {machine}")

    if sys_name == "windows":
        if arch != "amd64":
            raise BridgeError(f"Windows bridge chỉ hỗ trợ amd64, không phải {arch}.")
        return "igchat-bridge-windows-amd64.exe"
    if sys_name in {"linux", "darwin"}:
        return f"igchat-bridge-{sys_name}-{arch}"
    raise BridgeError(f"Hệ điều hành chưa được hỗ trợ: {sys_name}")


def _checkout_root() -> Path | None:
    candidate = Path(__file__).resolve().parents[3]
    if (candidate / "bridge" / "go.mod").is_file():
        return candidate
    return None


def _is_checkout_binary_stale(binary: Path, checkout_root: Path) -> bool:
    try:
        bin_mtime = binary.stat().st_mtime
    except OSError:
        return True
    bridge_dir = checkout_root / "bridge"
    watch_files = [
        bridge_dir / "go.mod",
        bridge_dir / "go.sum",
        bridge_dir / "main.go",
        *bridge_dir.glob("bridge/*.go"),
    ]
    for source in watch_files:
        try:
            if source.is_file() and source.stat().st_mtime > bin_mtime:
                return True
        except OSError:
            continue
    return False


def _user_cache_dir(version: str) -> Path:
    if os.name == "nt":
        base = Path(os.getenv("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
        return base / "igchat-v2" / "bridge" / version
    xdg = os.getenv("XDG_CACHE_HOME", "").strip()
    base = Path(xdg) if xdg else (Path.home() / ".cache")
    return base / "igchat-v2" / "bridge" / version


def _verify_sha256(path: Path, expected_digest: str) -> bool:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().lower() == expected_digest.strip().lower()


async def _download_verified_bridge(cache_target: Path, version: str) -> Path:
    asset_name = expected_platform_asset_name()
    expected_sha = os.getenv("IGCHAT_BRIDGE_SHA256", "").strip() or (
        checksums.BRIDGE_SHA256.get(asset_name, "").strip()
    )
    if not expected_sha:
        raise FileNotFoundError(
            f"Không tìm thấy bridge binary local và thiếu SHA-256 cho asset {asset_name!r}. "
            "Hãy build `bridge/` trước hoặc cấu hình IGCHAT_BRIDGE_BIN."
        )
    release_ver = checksums.BRIDGE_RELEASE_VERSION or version
    url = f"{RELEASE_DOWNLOAD_BASE}/v{release_ver}/{asset_name}"
    payload, _ = await download_public_bytes(url, max_bytes=80 * 1024 * 1024)
    actual_sha = hashlib.sha256(payload).hexdigest().lower()
    if actual_sha != expected_sha.lower():
        raise SecurityViolationError(
            f"Checksum SHA-256 của {asset_name} không khớp với manifest đã ghim."
        )
    cache_target.parent.mkdir(parents=True, exist_ok=True)
    tmp = cache_target.with_name(f".{cache_target.name}.{secrets.token_hex(6)}.tmp")
    try:
        tmp.write_bytes(payload)
        if os.name != "nt":
            os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
        tmp.replace(cache_target)
    except BaseException:
        with suppress(OSError):
            tmp.unlink(missing_ok=True)
        raise
    return cache_target


async def resolve_bridge_binary(
    binary_path: str | Path | None = None,
    *,
    allow_download: bool = True,
    expected_version: str = EXPECTED_BRIDGE_VERSION,
) -> Path:
    """Resolve the Go Instagram bridge executable with override & integrity checks."""
    if binary_path is not None:
        explicit = Path(binary_path).expanduser().resolve()
        if not explicit.is_file():
            raise FileNotFoundError(
                f"Không tìm thấy Go bridge tại binary_path: {explicit}"
            )
        return explicit

    env_override = os.getenv("IGCHAT_BRIDGE_BIN", "").strip()
    if env_override:
        override = Path(env_override).expanduser().resolve()
        if not override.is_file():
            raise FileNotFoundError(
                f"Không tìm thấy Go bridge tại IGCHAT_BRIDGE_BIN: {override}"
            )
        return override

    bin_name = "igchat-bridge.exe" if os.name == "nt" else "igchat-bridge"
    checkout = _checkout_root()
    if checkout is not None:
        built = checkout / "build" / bin_name
        if built.is_file():
            return built

    cached = _user_cache_dir(expected_version) / bin_name
    if cached.is_file():
        asset_name = expected_platform_asset_name()
        expected_sha = os.getenv("IGCHAT_BRIDGE_SHA256", "").strip() or (
            checksums.BRIDGE_SHA256.get(asset_name, "").strip()
        )
        if not expected_sha or _verify_sha256(cached, expected_sha):
            return cached

    if not allow_download:
        raise FileNotFoundError(
            f"Không tìm thấy binary {bin_name} trong build/ hoặc cache."
        )
    return await _download_verified_bridge(cached, expected_version)


class BridgeProcess:
    """Generation-fenced async JSON-RPC manager over stdin/stdout for igchat-bridge."""

    def __init__(
        self,
        *,
        binary_path: str | Path | None = None,
        expected_version: str = EXPECTED_BRIDGE_VERSION,
        max_event_queue: int = MAX_EVENT_QUEUE_SIZE,
    ) -> None:
        self._binary_path = binary_path
        self._expected_version = expected_version
        self._proc: asyncio.subprocess.Process | None = None
        self._generation = 0
        self._next_id = 1
        self._write_lock = asyncio.Lock()
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._events: asyncio.Queue[dict[str, Any]] = asyncio.Queue(
            maxsize=max(16, max_event_queue)
        )
        self._reader_task: asyncio.Task[None] | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self._dropped_events = 0
        self._tainted = False
        self._closing = False
        self._stderr_tail: list[str] = []

    @property
    def generation(self) -> int:
        return self._generation

    @property
    def pid(self) -> int | None:
        return self._proc.pid if self._proc is not None else None

    @property
    def is_running(self) -> bool:
        return (
            self._proc is not None
            and self._proc.returncode is None
            and not self._tainted
        )

    @property
    def dropped_event_count(self) -> int:
        return self._dropped_events

    @property
    def events(self) -> asyncio.Queue[dict[str, Any]]:
        return self._events

    @property
    def binary_stale(self) -> bool:
        checkout = _checkout_root()
        if checkout is None or self._binary_path is not None:
            return False
        bin_name = "igchat-bridge.exe" if os.name == "nt" else "igchat-bridge"
        return _is_checkout_binary_stale(checkout / "build" / bin_name, checkout)

    async def start(
        self, *, handshake_timeout: float = 10.0, allow_download: bool = True
    ) -> dict[str, Any]:
        """Spawn the Go bridge subprocess and validate its JSON-RPC `hello` contract."""
        if self.is_running:
            raise BridgeError("BridgeProcess đã được khởi chạy trước đó.")
        executable = await resolve_bridge_binary(
            self._binary_path,
            allow_download=allow_download,
            expected_version=self._expected_version,
        )
        self._closing = False
        self._tainted = False
        self._generation += 1
        self._pending.clear()
        self._stderr_tail.clear()

        creationflags = 0
        if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW"):
            creationflags = subprocess.CREATE_NO_WINDOW

        self._proc = await asyncio.create_subprocess_exec(
            str(executable),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            limit=MAX_RPC_LINE_BYTES,
            creationflags=creationflags,
        )
        gen = self._generation
        self._reader_task = asyncio.create_task(
            self._read_stdout_loop(gen), name=f"igchat-bridge-stdout-{gen}"
        )
        self._stderr_task = asyncio.create_task(
            self._read_stderr_loop(gen), name=f"igchat-bridge-stderr-{gen}"
        )

        try:
            hello = await self.call("hello", {}, timeout=handshake_timeout)
            self._validate_hello(hello)
            return hello
        except BaseException:
            await self.close()
            raise

    def _validate_hello(self, payload: Mapping[str, Any]) -> None:
        if payload.get("protocolVersion") != BRIDGE_PROTOCOL_VERSION:
            raise BridgeProtocolError(
                f"Bridge protocolVersion không tương thích: {payload.get('protocolVersion')!r}",
                error_code="protocol_error",
                retryable=False,
            )
        if payload.get("bridgeVersion") != self._expected_version:
            raise BridgeProtocolError(
                "Bridge version không khớp package Python: "
                f"{payload.get('bridgeVersion')!r} != {self._expected_version!r}",
                error_code="protocol_error",
                retryable=False,
            )
        platform_val = str(payload.get("platform") or "").lower()
        if platform_val and platform_val != "instagram":
            raise BridgeProtocolError(
                f"Bridge platform không hợp lệ: {platform_val!r}",
                error_code="protocol_error",
                retryable=False,
            )
        caps = payload.get("capabilities")
        if not isinstance(caps, list) or not all(isinstance(c, str) for c in caps):
            raise BridgeProtocolError(
                "Bridge trả về capabilities không hợp lệ.",
                error_code="protocol_error",
                retryable=False,
            )
        missing = REQUIRED_CAPABILITIES.difference(caps)
        if missing:
            raise BridgeProtocolError(
                f"Bridge thiếu capabilities bắt buộc: {sorted(missing)}",
                error_code="protocol_error",
                retryable=False,
            )

    def _enqueue_event(self, event: dict[str, Any]) -> None:
        if self._events.full():
            with suppress(asyncio.QueueEmpty):
                self._events.get_nowait()
                self._dropped_events += 1
        with suppress(asyncio.QueueFull):
            self._events.put_nowait(event)

    async def _read_stdout_loop(self, expected_generation: int) -> None:
        assert self._proc is not None and self._proc.stdout is not None
        stdout = self._proc.stdout
        try:
            while expected_generation == self._generation:
                raw_line = await stdout.readline()
                if not raw_line:
                    break
                text = raw_line.decode("utf-8", errors="replace").strip()
                if not text:
                    continue
                try:
                    payload = json.loads(text)
                except json.JSONDecodeError:
                    self._enqueue_event(
                        {
                            "type": "error",
                            "data": {"message": "Bridge stdout emitted invalid JSON."},
                        }
                    )
                    continue
                if not isinstance(payload, dict):
                    continue
                if "event" in payload and isinstance(payload["event"], dict):
                    self._enqueue_event(payload["event"])
                    continue
                req_id = payload.get("id")
                if isinstance(req_id, int):
                    future = self._pending.pop(req_id, None)
                    if future is not None and not future.done():
                        future.set_result(payload)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._fail_pending(
                BridgeError(
                    f"Lỗi đọc stdout của bridge: {redact_sensitive_text(exc)}",
                    error_code="network_disconnected",
                    retryable=True,
                )
            )
        finally:
            self._fail_pending(
                BridgeError(
                    "Tiến trình Go bridge đã đóng luồng stdout.",
                    error_code="network_disconnected",
                    retryable=not self._closing,
                )
            )
            if not self._closing and expected_generation == self._generation:
                self._enqueue_event(
                    {
                        "type": "disconnected",
                        "data": {"reason": "process_exited"},
                    }
                )

    async def _read_stderr_loop(self, expected_generation: int) -> None:
        assert self._proc is not None and self._proc.stderr is not None
        stderr = self._proc.stderr
        try:
            while expected_generation == self._generation:
                raw_line = await stderr.readline()
                if not raw_line:
                    break
                line = redact_sensitive_text(
                    raw_line.decode("utf-8", errors="replace").strip()
                )
                if line:
                    self._stderr_tail.append(line)
                    if len(self._stderr_tail) > 50:
                        del self._stderr_tail[0]
        except asyncio.CancelledError:
            raise

    def _fail_pending(self, error: Exception) -> None:
        pending = list(self._pending.values())
        self._pending.clear()
        for future in pending:
            if not future.done():
                future.set_exception(error)

    async def call(
        self,
        method: str,
        params: Mapping[str, Any] | None = None,
        *,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        """Send one JSON-RPC request line to the bridge and await its response."""
        if not self.is_running or self._proc is None or self._proc.stdin is None:
            raise BridgeError(
                "Go bridge chưa chạy hoặc đã bị đóng.",
                error_code="network_disconnected",
                retryable=True,
            )

        loop = asyncio.get_running_loop()
        req_id = self._next_id
        self._next_id += 1
        future: asyncio.Future[dict[str, Any]] = loop.create_future()
        self._pending[req_id] = future

        frame = (
            json.dumps(
                {
                    "id": req_id,
                    "method": method,
                    "params": dict(params) if params is not None else {},
                },
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
            + b"\n"
        )

        try:
            async with self._write_lock:
                if self._proc.stdin.is_closing():
                    raise BridgeError("Bridge stdin đã đóng.")
                self._proc.stdin.write(frame)
                await asyncio.wait_for(self._proc.stdin.drain(), timeout=timeout)
        except asyncio.CancelledError:
            self._pending.pop(req_id, None)
            self._tainted = True
            raise
        except Exception as exc:
            self._pending.pop(req_id, None)
            self._tainted = True
            raise BridgeError(
                f"Không ghi được RPC {method!r}: {redact_sensitive_text(exc)}",
                error_code="network_disconnected",
                retryable=True,
            ) from exc

        try:
            reply = await asyncio.wait_for(future, timeout=timeout)
        except asyncio.CancelledError:
            self._pending.pop(req_id, None)
            self._tainted = True
            raise
        except asyncio.TimeoutError as exc:
            self._pending.pop(req_id, None)
            raise BridgeError(
                f"RPC {method!r} vượt quá timeout {timeout:.1f}s.",
                error_code="network_disconnected",
                retryable=True,
            ) from exc

        if reply.get("ok") is True:
            data = reply.get("data")
            return data if isinstance(data, dict) else {}

        err_msg = redact_sensitive_text(reply.get("error") or f"RPC {method} failed")
        err_code = str(reply.get("errorCode") or "").strip()
        retryable = reply.get("retryable")
        if err_code == "checkpoint_required":
            raise CheckpointRequiredError(err_msg)
        if err_code == "auth_failed":
            raise AuthenticationError(err_msg)
        if err_code == "protocol_error":
            raise BridgeProtocolError(err_msg, error_code=err_code, retryable=retryable)
        raise BridgeError(err_msg, error_code=err_code, retryable=retryable)

    async def get_event(self, *, timeout: float | None = None) -> dict[str, Any]:
        """Await the next normalized bridge event."""
        if timeout is None:
            return await self._events.get()
        return await asyncio.wait_for(self._events.get(), timeout=timeout)

    async def close(self, *, wait_timeout: float = 5.0) -> None:
        """Gracefully disconnect the client, close stdin, and reap the Go child."""
        self._closing = True
        proc = self._proc
        if proc is None:
            return

        if proc.returncode is None and proc.stdin is not None and not self._tainted:
            with suppress(Exception):
                await asyncio.wait_for(
                    self.call("disconnect", {}, timeout=2.5), timeout=3.0
                )

        if proc.stdin is not None and not proc.stdin.is_closing():
            with suppress(Exception):
                proc.stdin.close()

        if proc.returncode is None:
            try:
                await asyncio.wait_for(proc.wait(), timeout=wait_timeout)
            except asyncio.TimeoutError:
                with suppress(ProcessLookupError):
                    proc.terminate()
                try:
                    await asyncio.wait_for(proc.wait(), timeout=3.0)
                except asyncio.TimeoutError:
                    with suppress(ProcessLookupError):
                        proc.kill()
                    with suppress(Exception):
                        await asyncio.wait_for(proc.wait(), timeout=2.0)

        for task in (self._reader_task, self._stderr_task):
            if task is not None and not task.done():
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task

        self._reader_task = None
        self._stderr_task = None
        self._proc = None
        self._fail_pending(
            BridgeError(
                "BridgeProcess đã đóng.", error_code="cancelled", retryable=False
            )
        )
