"""Shared value types for owner-provided read services."""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Any

from aqelyn.conventions.errors import SchemaValidationError


@dataclass(frozen=True, slots=True)
class ReadItem[T]:
    record: T
    explain: dict[str, Any] | None


@dataclass(frozen=True, slots=True)
class ReadPage[T]:
    items: tuple[ReadItem[T], ...]
    next_cursor: str | None
    degraded: bool = False
    degradation_reasons: tuple[str, ...] = ()


def encode_keyset_cursor(*, namespace: str, values: tuple[str, ...]) -> str:
    """Encode a complete composite key with a route-specific namespace."""

    if not namespace or len(values) < 2 or any(not value for value in values):
        raise SchemaValidationError("keyset cursor requires a namespace and composite values")
    raw = json.dumps(
        {"namespace": namespace, "values": values, "version": 1},
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_keyset_cursor(
    value: str,
    *,
    namespace: str,
    arity: int,
) -> tuple[str, ...]:
    """Decode a cursor only for the owner and key shape that issued it."""

    try:
        padded = value + "=" * (-len(value) % 4)
        payload = json.loads(base64.b64decode(padded, altchars=b"-_", validate=True))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SchemaValidationError("keyset cursor is malformed") from exc
    if not isinstance(payload, dict) or set(payload) != {"namespace", "values", "version"}:
        raise SchemaValidationError("keyset cursor has an unknown shape")
    values = payload["values"]
    if (
        payload["namespace"] != namespace
        or payload["version"] != 1
        or not isinstance(values, list)
        or len(values) != arity
        or any(not isinstance(item, str) or not item for item in values)
    ):
        raise SchemaValidationError("keyset cursor does not belong to this read")
    return tuple(values)
