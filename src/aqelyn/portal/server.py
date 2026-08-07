"""Loopback HTTP/1.1 server for the customer portal (ECR-0121).

The portal accepts request bodies (unlike the read-only surface), so the size bound must be
enforced **at the socket**: a declared ``Content-Length`` over the limit is refused with 413
*before any body is read*, and the body read is itself capped, so a client cannot make the process
buffer an arbitrarily large upload. ECR-0118 checked the 1 MiB bound only after the body was already
in memory — on a small box that is an authenticated memory-exhaustion DoS. This closes it.

The listener binds loopback with no configuration knob: nginx is the public face and proxies here,
exactly as the deployed platform does. Bodies are still hard-bounded here regardless of what nginx
in front does.
"""

from __future__ import annotations

import asyncio
from contextlib import suppress

from aqelyn.conventions.errors import ConfigError
from aqelyn.portal.app import MAX_UPLOAD_BYTES, PortalApplication
from aqelyn.surface.models import SurfaceResponse

LOOPBACK_HOST = "127.0.0.1"
MAX_REQUEST_HEAD = 65_536
# The largest body the socket will read. Matches the application's upload bound; the point is to
# refuse before buffering, not to raise the ceiling.
MAX_REQUEST_BODY = MAX_UPLOAD_BYTES
READ_TIMEOUT_SECONDS = 15.0

_REASONS = {
    200: "OK",
    201: "Created",
    400: "Bad Request",
    401: "Unauthorized",
    403: "Forbidden",
    404: "Not Found",
    408: "Request Timeout",
    409: "Conflict",
    413: "Payload Too Large",
    422: "Unprocessable Content",
    431: "Request Header Fields Too Large",
    500: "Internal Server Error",
}


class _RequestTooLarge(Exception):
    """The declared or streamed body exceeds the socket bound."""


class _RequestInvalid(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class PortalServer:
    """Loopback HTTP/1.1 server that bounds the request body at the socket."""

    def __init__(self, application: PortalApplication, *, port: int = 8800) -> None:
        if not 0 <= port <= 65_535:
            raise ConfigError("portal port must be between 0 and 65535")
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
            self._handle_connection, host=LOOPBACK_HOST, port=self._port
        )

    async def serve_forever(self) -> None:
        if self._server is None:
            raise RuntimeError("portal server has not started")
        async with self._server:
            await self._server.serve_forever()

    async def close(self) -> None:
        if self._server is None:
            return
        self._server.close()
        await self._server.wait_closed()
        self._server = None

    async def _handle_connection(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            response = await self._read_and_dispatch(reader)
        except _RequestTooLarge:
            response = _error(413, "upload_too_large", "the request body is too large")
        except asyncio.LimitOverrunError:
            response = _error(431, "head_too_large", "request head is too large")
        except (TimeoutError, asyncio.IncompleteReadError):
            response = _error(408, "request_timeout", "the request was incomplete")
        except _RequestInvalid as exc:
            response = _error(400, "bad_request", exc.message)
        except Exception:
            response = _error(500, "portal_error", "the request could not be completed")
        writer.write(_wire_response(response))
        with suppress(ConnectionError):
            await writer.drain()
        writer.close()
        with suppress(ConnectionError):
            await writer.wait_closed()

    async def _read_and_dispatch(self, reader: asyncio.StreamReader) -> SurfaceResponse:
        raw_head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), READ_TIMEOUT_SECONDS)
        if len(raw_head) > MAX_REQUEST_HEAD:
            raise asyncio.LimitOverrunError("head too large", len(raw_head))
        method, target, headers = _parse_request_head(raw_head)
        length = _content_length(headers)
        # AT SOCKET: refuse an over-limit body before reading a single byte of it.
        if length > MAX_REQUEST_BODY:
            raise _RequestTooLarge
        body = (
            await asyncio.wait_for(reader.readexactly(length), READ_TIMEOUT_SECONDS)
            if length
            else b""
        )
        return await self._application.handle(method, target, headers, body)


def _content_length(headers: dict[str, str]) -> int:
    raw = headers.get("content-length")
    if raw is None:
        return 0
    try:
        length = int(raw)
    except ValueError as exc:
        raise _RequestInvalid("content-length is not an integer") from exc
    if length < 0:
        raise _RequestInvalid("content-length must not be negative")
    return length


def _parse_request_head(raw: bytes) -> tuple[str, str, dict[str, str]]:
    try:
        text = raw.decode("iso-8859-1")
    except UnicodeDecodeError as exc:
        raise _RequestInvalid("request head is not HTTP text") from exc
    lines = text[:-4].split("\r\n")
    try:
        method, target, version = lines[0].split(" ")
    except (IndexError, ValueError) as exc:
        raise _RequestInvalid("request line is malformed") from exc
    if version not in {"HTTP/1.0", "HTTP/1.1"}:
        raise _RequestInvalid("unsupported HTTP version")
    headers: dict[str, str] = {}
    for line in lines[1:]:
        if not line:
            continue
        if ":" not in line:
            raise _RequestInvalid("request header is malformed")
        name, value = line.split(":", 1)
        selected = name.strip().lower()
        if not selected:
            raise _RequestInvalid("request header name is empty")
        headers[selected] = value.strip()
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


def _error(status: int, code: str, message: str) -> SurfaceResponse:
    return SurfaceResponse.json(status, {"error": {"code": code, "message": message}})
