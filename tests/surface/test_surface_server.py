"""Listener and CLI boundary tests for ECR-0088."""

from __future__ import annotations

import asyncio
import inspect
import json

from aqelyn.kernel import AQELYNConfig, create_inmemory_runtime
from aqelyn.surface import LOOPBACK_HOST, SurfaceApplication, SurfaceServer


async def test_surface_listener_binds_loopback_and_serves_real_kernel_health() -> None:
    runtime = create_inmemory_runtime()
    await runtime.kernel.start()
    server = SurfaceServer(SurfaceApplication(runtime), port=0)
    await server.start()
    try:
        reader, writer = await asyncio.open_connection(LOOPBACK_HOST, server.port)
        writer.write(b"GET /health HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n")
        await writer.drain()
        raw = await reader.read()
        head, body = raw.split(b"\r\n\r\n", 1)
        payload = json.loads(body)

        assert head.startswith(b"HTTP/1.1 200 OK")
        assert payload["phase"] in {"running", "degraded"}
        assert "inventory_engine" in payload["services"]
        assert server._server is not None
        assert server._server.sockets[0].getsockname()[0] == LOOPBACK_HOST
    finally:
        await server.close()
        await runtime.kernel.stop(reason="surface_test")


def test_surface_has_no_bind_address_parameter_or_config_key() -> None:
    server_parameters = set(inspect.signature(SurfaceServer).parameters)
    config_fields = set(AQELYNConfig.model_fields)

    assert server_parameters == {"application", "port"}
    assert "host" not in config_fields
    assert "bind_address" not in config_fields
    assert "surface_host" not in config_fields


async def test_surface_rejects_request_bodies() -> None:
    runtime = create_inmemory_runtime()
    server = SurfaceServer(SurfaceApplication(runtime), port=0)
    await server.start()
    try:
        reader, writer = await asyncio.open_connection(LOOPBACK_HOST, server.port)
        writer.write(b"GET /health HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Length: 1\r\n\r\nx")
        await writer.drain()
        raw = await reader.read()

        assert raw.startswith(b"HTTP/1.1 400 Bad Request")
        assert b"request bodies are not accepted" in raw
    finally:
        await server.close()
