"""Portal HTTP server tests (ECR-0121), driven over a real loopback socket.

The load-bearing test is ``test_oversized_content_length_is_refused_before_the_body``: a request
declaring a body far over the limit is answered 413 **without** the server reading that body — the
authenticated memory-exhaustion DoS that ECR-0118's post-buffer bound left open.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import suppress

import pytest

from aqelyn.consent.memory import InMemoryAuditLog, InMemoryConsentStore
from aqelyn.identity.memory import (
    InMemoryAccountStore,
    InMemoryInviteStore,
    InMemorySessionStore,
)
from aqelyn.kernel.config import AQELYNConfig
from aqelyn.kernel.factory import create_inmemory_runtime
from aqelyn.portal.app import MAX_UPLOAD_BYTES, PortalApplication
from aqelyn.portal.server import PortalServer


@pytest.fixture
async def server() -> AsyncIterator[PortalServer]:
    runtime = create_inmemory_runtime(AQELYNConfig(tenant_mode="enterprise"))
    accounts = InMemoryAccountStore()
    app = PortalApplication(
        runtime,
        accounts=accounts,
        invites=InMemoryInviteStore(accounts),
        sessions=InMemorySessionStore(),
        consent=InMemoryConsentStore(),
        audit=InMemoryAuditLog(),
    )
    srv = PortalServer(app, port=0)
    await srv.start()
    try:
        yield srv
    finally:
        await srv.close()


async def _raw_request(port: int, request: bytes) -> tuple[int, bytes]:
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(request)
    await writer.drain()
    raw = await asyncio.wait_for(reader.read(-1), 5.0)
    writer.close()
    with suppress(ConnectionError):
        await writer.wait_closed()
    head, _, body = raw.partition(b"\r\n\r\n")
    status = int(head.split(b" ", 2)[1])
    return status, body


async def test_login_route_is_reachable_over_the_socket(server: PortalServer) -> None:
    body = json.dumps({"email": "nobody@example.com", "password": "x"}).encode()
    request = (
        b"POST /api/v1/login HTTP/1.1\r\n"
        b"Host: localhost\r\n"
        b"Content-Type: application/json\r\n"
        b"Content-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body
    )
    status, _ = await _raw_request(server.port, request)
    # No such account, so 401 — but it went through the socket, was parsed, and dispatched.
    assert status == 401


async def test_oversized_content_length_is_refused_before_the_body(
    server: PortalServer,
) -> None:
    # Declare a body far over the limit but send only a few bytes, then let the request sit.
    # If the server tried to read the declared length it would block; it must 413 immediately
    # on the Content-Length alone. A short read deadline proves it did not wait for the body.
    huge = MAX_UPLOAD_BYTES * 100
    request = (
        b"POST /api/v1/scans HTTP/1.1\r\n"
        b"Host: localhost\r\n"
        b"Content-Type: application/json\r\n"
        b"Content-Length: " + str(huge).encode() + b"\r\n\r\n" + b"{}"
    )
    reader, writer = await asyncio.open_connection("127.0.0.1", server.port)
    writer.write(request)
    await writer.drain()
    # The response must arrive promptly, without the full body being sent.
    raw = await asyncio.wait_for(reader.read(-1), 5.0)
    writer.close()
    status = int(raw.split(b" ", 2)[1])
    assert status == 413


async def test_content_length_one_over_the_limit_is_refused(server: PortalServer) -> None:
    # Exactly one byte over the bound, still refused on Content-Length alone (tiny body sent,
    # so there is no write-side reset race — the point is the boundary, not the stream).
    request = (
        b"POST /api/v1/scans HTTP/1.1\r\n"
        b"Host: localhost\r\n"
        b"Content-Type: application/json\r\n"
        b"Content-Length: " + str(MAX_UPLOAD_BYTES + 1).encode() + b"\r\n\r\n" + b"{}"
    )
    reader, writer = await asyncio.open_connection("127.0.0.1", server.port)
    writer.write(request)
    with suppress(ConnectionError):
        await writer.drain()
    raw = await asyncio.wait_for(reader.read(-1), 5.0)
    writer.close()
    with suppress(ConnectionError):
        await writer.wait_closed()
    assert int(raw.split(b" ", 2)[1]) == 413


async def test_unknown_route_is_404(server: PortalServer) -> None:
    request = b"GET /nope HTTP/1.1\r\nHost: localhost\r\n\r\n"
    status, _ = await _raw_request(server.port, request)
    assert status == 404


async def test_malformed_content_length_is_a_bad_request(server: PortalServer) -> None:
    request = (
        b"POST /api/v1/login HTTP/1.1\r\nHost: localhost\r\nContent-Length: not-a-number\r\n\r\n"
    )
    status, _ = await _raw_request(server.port, request)
    assert status == 400
