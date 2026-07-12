"""Deterministic canonical JSON + hashing (CONVENTIONS §3).

Used wherever content is hashed (Evidence hash-chain, package manifests).
"""

from __future__ import annotations

import hashlib
import json
import unicodedata
from typing import Any


def _normalize(value: Any) -> Any:
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, dict):
        return {k: _normalize(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalize(v) for v in value]
    return value


def canonical_json(value: Any) -> bytes:
    """Return the canonical UTF-8 JSON encoding: sorted keys, no whitespace."""
    return json.dumps(
        _normalize(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def sha256_hex(value: Any) -> str:
    """SHA-256 hex digest over the canonical JSON of ``value``."""
    return hashlib.sha256(canonical_json(value)).hexdigest()
