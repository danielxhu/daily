"""Test-time network ban (X0.3 → NFR-3).

Blocks any outbound socket connection to a non-local host during tests, so the
suite physically cannot hit the network or a paid API. Local addresses stay
allowed (a test SQLite/Chroma or a local server is fine). Installed as an autouse
fixture in `conftest.py`.
"""

from __future__ import annotations

import socket
from typing import Any

_ALLOWED_HOSTS = {"127.0.0.1", "::1", "localhost", "0.0.0.0", ""}

_real_connect = socket.socket.connect
_real_connect_ex = socket.socket.connect_ex
_real_create_connection = socket.create_connection


class NetworkAccessAttempted(RuntimeError):
    """Raised when test code tries to open a non-local network connection."""


def _host_of(address: Any) -> str | None:
    # AF_INET / AF_INET6 use (host, port[, ...]); AF_UNIX uses a path str.
    if isinstance(address, tuple) and address:
        return str(address[0])
    return None


def _guard(address: Any) -> None:
    host = _host_of(address)
    if host is None:
        return  # non-inet socket (e.g. AF_UNIX) — not a network egress
    if host not in _ALLOWED_HOSTS:
        raise NetworkAccessAttempted(
            f"Test attempted a network connection to {host!r}. The suite must be "
            "offline (NFR-3) — mock the client or replay a cassette instead."
        )


def install(monkeypatch: Any) -> None:
    """Patch socket connect paths to enforce the ban for one test."""

    def connect(self: socket.socket, address: Any) -> None:
        _guard(address)
        return _real_connect(self, address)

    def connect_ex(self: socket.socket, address: Any) -> int:
        _guard(address)
        return _real_connect_ex(self, address)

    def create_connection(address: Any, *args: Any, **kwargs: Any) -> socket.socket:
        _guard(address)
        return _real_create_connection(address, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket.socket, "connect_ex", connect_ex)
    monkeypatch.setattr(socket, "create_connection", create_connection)
