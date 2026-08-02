"""Transport-neutral response types for the local operator surface."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class SurfaceResponse:
    status: int
    body: bytes
    content_type: str
    headers: dict[str, str] = field(default_factory=dict)

    @classmethod
    def json(cls, status: int, payload: Any) -> SurfaceResponse:
        body = json.dumps(
            payload,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return cls(
            status=status,
            body=body,
            content_type="application/json; charset=utf-8",
        )

    @classmethod
    def text(
        cls,
        status: int,
        body: str,
        *,
        content_type: str,
        headers: dict[str, str] | None = None,
    ) -> SurfaceResponse:
        return cls(
            status=status,
            body=body.encode("utf-8"),
            content_type=content_type,
            headers={} if headers is None else dict(headers),
        )
