"""X0.3 — proves the offline guarantee (NFR-3) actually bites."""

from __future__ import annotations

import socket

import pytest

from tests.netban import NetworkAccessAttempted

# A documentation IP literal (TEST-NET-3, RFC 5737). Using a literal avoids any
# DNS lookup; the guard rejects it before a real connect is attempted.
_REMOTE = ("203.0.113.1", 80)


def test_remote_create_connection_blocked() -> None:
    with pytest.raises(NetworkAccessAttempted):
        socket.create_connection(_REMOTE, timeout=0.1)


def test_remote_socket_connect_blocked() -> None:
    s = socket.socket()
    try:
        with pytest.raises(NetworkAccessAttempted):
            s.connect(_REMOTE)
    finally:
        s.close()


def test_localhost_is_not_blocked_by_the_guard() -> None:
    # Connecting to a local port that nobody is listening on must fail with an
    # ordinary OSError (connection refused) — NOT our NetworkAccessAttempted —
    # which proves the guard let the local address through.
    s = socket.socket()
    s.settimeout(0.2)
    try:
        with pytest.raises(OSError) as exc:
            s.connect(("127.0.0.1", 1))
        assert not isinstance(exc.value, NetworkAccessAttempted)
    finally:
        s.close()
