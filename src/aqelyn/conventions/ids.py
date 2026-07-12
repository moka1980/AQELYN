"""Typed, sortable identifiers (CONVENTIONS §1).

Internal key is UUIDv7 (time-ordered); canonical external form is
``{prefix}_{uuid-hex-without-dashes}``.
"""

from __future__ import annotations

import uuid_utils

# Reserved prefixes -> family (CONVENTIONS §1). One owner per prefix.
PREFIXES: dict[str, str] = {
    "obj": "object",
    "rel": "relationship",
    "src": "source",
    "evt": "event",
    "evd": "evidence",
    "pkg": "evidence_package",
    "fnd": "finding",
    "svc": "service",
}


def new_uuid() -> str:
    """Return a fresh UUIDv7 as 32-char hex (no dashes)."""
    return uuid_utils.uuid7().hex


def new_id(prefix: str) -> str:
    """Mint a new typed id for a reserved prefix."""
    if prefix not in PREFIXES:
        raise ValueError(f"unknown id prefix: {prefix!r}")
    return f"{prefix}_{new_uuid()}"


def parse_id(value: str) -> tuple[str, str]:
    """Split a typed id into (prefix, uuid-hex); validate the prefix and shape."""
    prefix, _, hexpart = value.partition("_")
    if prefix not in PREFIXES or len(hexpart) != 32:
        raise ValueError(f"malformed typed id: {value!r}")
    int(hexpart, 16)  # raises ValueError if not hex
    return prefix, hexpart


def is_valid(value: str, prefix: str | None = None) -> bool:
    """True if ``value`` is a well-formed typed id (optionally of ``prefix``)."""
    try:
        p, _ = parse_id(value)
    except ValueError:
        return False
    return prefix is None or p == prefix
