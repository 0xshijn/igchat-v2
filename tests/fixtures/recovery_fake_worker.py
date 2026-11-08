"""Offline test worker adapter exercising the loopback CONNECT proxy fault."""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import signal
import socket
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
for p in (str(ROOT), str(SRC)):
    if p not in sys.path:
        sys.path.insert(0, p)

PRIVATE_PAYLOAD = b"offline-dummy-private-media"
PRIVATE_COOKIE = (
    "sessionid=17841400000000001%3Aoffline_test; ds_user_id=17841400000000001"
)


def wait_for(
    predicate: Callable[[], bool], stop: threading.Event, seconds: float = 6.0
) -> None:
    deadline = time.monotonic() + seconds
    while not predicate():
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Offline protocol deadline.")
        if stop.wait(min(0.01, remaining)):
            raise InterruptedError("Offline worker stopped.")


class SocketAdapter:
    """Opaque byte streams through the loopback fault proxy."""

    def __init__(self, targets: list[tuple[str, int]]) -> None:
        proxy = urlsplit(os.environ["HTTPS_PROXY"])
        if proxy.scheme != "http" or proxy.hostname != "127.0.0.1" or not proxy.port:
            raise ValueError("Offline worker requires the child loopback proxy.")
        if any(not ipaddress.ip_address(host).is_loopback for host, _ in targets):
            raise ValueError("Offline endpoints must be literal loopback addresses.")
        self.proxy = (proxy.hostname, proxy.port)
        self.targets = targets
        self.streams: list[socket.socket] = []
        self.rejected = 0
        self.observed_cut = 0
        self.rpc_calls = 0
        self.lock = threading.RLock()

    def _open(self, target: tuple[str, int]) -> socket.socket:
        stream = socket.create_connection(self.proxy, timeout=0.5)
        try:
            stream.sendall(
                f"CONNECT {target[0]}:{target[1]} HTTP/1.1\r\n\r\n".encode("ascii")
            )
            header = bytearray()
            while b"\r\n\r\n" not in header:
                chunk = stream.recv(1024)
                if not chunk or len(header) + len(chunk) > 8192:
                    raise ConnectionError("Incomplete local CONNECT response.")
                header.extend(chunk)
            if not header.startswith(b"HTTP/1.1 200 "):
                if header.startswith(b"HTTP/1.1 503 "):
                    self.rejected += 1
                raise ConnectionError("Local CONNECT unavailable.")
            return stream
        except BaseException:
            stream.close()
            raise

    def connect(self) -> bool:
        with self.lock:
            return self._connect()

    def _connect(self) -> bool:
        if self.streams:
            return True
        try:
            for target in self.targets:
                self.streams.append(self._open(target))
            return True
        except OSError:
            self.close()
            return False

    @staticmethod
    def exchange(stream: socket.socket, payload: bytes) -> bytes:
        stream.sendall(payload)
        received = bytearray()
        while len(received) < len(payload):
            chunk = stream.recv(len(payload) - len(received))
            if not chunk:
                raise ConnectionError("Local echo stream closed.")
            received.extend(chunk)
        if received != payload:
            raise ValueError("Local echo bytes differ.")
        return bytes(received)

    def healthy(self) -> bool:
        with self.lock:
            if self.streams:
                broken = 0
                for stream in self.streams:
                    try:
                        self.exchange(stream, b"offline-health-probe")
                    except OSError:
                        broken += 1
                if broken:
                    self.observed_cut += broken
                    self.close()
            return self.connect()

    def close(self) -> None:
        with self.lock:
            for stream in self.streams:
                try:
                    stream.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                stream.close()
            self.streams.clear()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--target", action="append", type=int, required=True)
    parser.add_argument(
        "--mode", choices=("success", "stalled", "cancel"), default="success"
    )
    args = parser.parse_args()

    adapter = SocketAdapter([("127.0.0.1", port) for port in args.target])
    stop_event = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop_event.set())
    signal.signal(signal.SIGTERM, lambda *_: stop_event.set())

    if not adapter.connect():
        return 1

    report_path = args.output_dir / "report.json"
    report = {
        "status": "completed",
        "acceptance_passed": True,
        "shutdown_clean": True,
        "observed_cuts": adapter.observed_cut,
    }

    if args.mode == "stalled":
        stop_event.wait()
        return 99

    try:
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        return 0
    finally:
        adapter.close()


if __name__ == "__main__":
    raise SystemExit(main())
