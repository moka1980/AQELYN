"""Minimal stdlib listener for the local operator surface."""

from __future__ import annotations

import asyncio
from contextlib import suppress

from aqelyn.conventions.errors import ConfigError, SurfaceRequestInvalid
from aqelyn.surface.app import SurfaceApplication
from aqelyn.surface.models import SurfaceResponse

LOOPBACK_HOST = "127.0.0.1"
MAX_REQUEST_HEAD = 65_536
READ_TIMEOUT_SECONDS = 10.0

_REASONS = {
    200: "OK",
    400: "Bad Request",
    404: "Not Found",
    405: "Method Not Allowed",
    422: "Unprocessable Content",
    431: "Request Header Fields Too Large",
    500: "Internal Server Error",
    503: "Service Unavailable",
}


class SurfaceServer:
    """Loopback-only HTTP/1.1 server with no bind-address configuration seam."""

    def __init__(self, application: SurfaceApplication, *, port: int = 8765) -> None:
        if not 0 <= port <= 65_535:
            raise ConfigError("surface port must be between 0 and 65535")
        self._application = application
        self._port = port
        self._server: asyncio.Server | None = None

    @property
    def port(self) -> int:
        if self._server is None or not self._server.sockets:
            return self._port
        return int(self._server.sockets[0].getsockname()[1])

    async def start(self) -> None:
        if self._server is not None:
            return
        self._server = await asyncio.start_server(
            self._handle_connection,
            host=LOOPBACK_HOST,
            port=self._port,
            limit=MAX_REQUEST_HEAD,
        )

    async def serve_forever(self) -> None:
        if self._server is None:
            raise RuntimeError("surface server has not started")
        async with self._server:
            await self._server.serve_forever()

    async def close(self) -> None:
        if self._server is None:
            return
        self._server.close()
        await self._server.wait_closed()
        self._server = None

    async def _handle_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        try:
            response = await self._read_and_dispatch(reader)
        except asyncio.LimitOverrunError:
            response = _plain_error(431, "request head exceeds 65536 bytes")
        except (asyncio.IncompleteReadError, TimeoutError, SurfaceRequestInvalid) as exc:
            message = (
                exc.message if isinstance(exc, SurfaceRequestInvalid) else "request is malformed"
            )
            response = _plain_error(400, message)
        except Exception:
            response = _plain_error(500, "surface request failed")
        writer.write(_wire_response(response))
        with suppress(ConnectionError):
            await writer.drain()
        writer.close()
        with suppress(ConnectionError):
            await writer.wait_closed()

    async def _read_and_dispatch(self, reader: asyncio.StreamReader) -> SurfaceResponse:
        raw = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), READ_TIMEOUT_SECONDS)
        if len(raw) > MAX_REQUEST_HEAD:
            return _plain_error(431, "request head exceeds 65536 bytes")
        method, target, headers = _parse_request_head(raw)
        if headers.get("content-length", "0") != "0":
            raise SurfaceRequestInvalid("request bodies are not accepted")
        return await self._application.handle(method, target)


def _parse_request_head(raw: bytes) -> tuple[str, str, dict[str, str]]:
    try:
        text = raw.decode("iso-8859-1")
    except UnicodeDecodeError as exc:
        raise SurfaceRequestInvalid("request head is not HTTP text") from exc
    lines = text[:-4].split("\r\n")
    try:
        method, target, version = lines[0].split(" ")
    except (IndexError, ValueError) as exc:
        raise SurfaceRequestInvalid("request line is malformed") from exc
    if version not in {"HTTP/1.0", "HTTP/1.1"}:
        raise SurfaceRequestInvalid("unsupported HTTP version")
    headers: dict[str, str] = {}
    for line in lines[1:]:
        if not line or ":" not in line:
            raise SurfaceRequestInvalid("request header is malformed")
        name, value = line.split(":", 1)
        selected_name = name.strip().lower()
        if not selected_name or selected_name in headers:
            raise SurfaceRequestInvalid("request headers must be named and unique")
        headers[selected_name] = value.strip()
    return method, target, headers


def _wire_response(response: SurfaceResponse) -> bytes:
    reason = _REASONS.get(response.status, "Unknown")
    headers = {
        "Cache-Control": "no-store",
        "Connection": "close",
        "Content-Length": str(len(response.body)),
        "Content-Type": response.content_type,
        "Referrer-Policy": "no-referrer",
        "X-Content-Type-Options": "nosniff",
        **response.headers,
    }
    head = [f"HTTP/1.1 {response.status} {reason}"]
    head.extend(f"{name}: {value}" for name, value in headers.items())
    return ("\r\n".join(head) + "\r\n\r\n").encode("ascii") + response.body


def _plain_error(status: int, message: str) -> SurfaceResponse:
    return SurfaceResponse.json(status, {"error": {"code": "surface_request", "message": message}})
