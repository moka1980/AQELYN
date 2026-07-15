"""Typed, sortable identifiers (CONVENTIONS §1).

Internal key is UUIDv7 (time-ordered); canonical external form is
``{prefix}_{uuid-hex-without-dashes}``.
"""

from __future__ import annotations

import uuid

import uuid_utils

from aqelyn.conventions.errors import SchemaValidationError

# Reserved prefixes -> family (CONVENTIONS §1). One owner per prefix.
PREFIXES: dict[str, str] = {
    "obj": "object",
    "rel": "relationship",
    "src": "source",
    "evt": "event",
    "evd": "evidence",
    "pkg": "evidence_package",
    "fnd": "finding",
    "run": "workflow_run",
    "snap": "compliance_snapshot",
    "cert": "iag_certification",
    "rvi": "iag_review_item",
    "alt": "soc_alert",
    "inc": "soc_incident",
    "hnt": "soc_hunt",
    "acq": "forensics_acquisition",
    "art": "forensics_artifact",
    "det": "threat_detection",
    "prf": "behavior_profile",
    "prj": "detection_projection",
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
    parsed = uuid.UUID(hex=hexpart)
    if parsed.version != 7:
        raise ValueError(f"typed id payload must be UUIDv7: {value!r}")
    return prefix, hexpart


def require_typed_id(value: str, prefix: str, *, field: str, allow_empty: bool = False) -> str:
    """Validate a typed id field and return the original value."""
    if allow_empty and value == "":
        return value
    try:
        parsed_prefix, _ = parse_id(value)
    except ValueError as exc:
        raise SchemaValidationError(f"{field} must be a valid {prefix}_ typed id") from exc
    if parsed_prefix != prefix:
        raise SchemaValidationError(f"{field} must use {prefix}_ prefix")
    return value


def require_tenant_id(value: str | None, *, field: str = "tenant_id") -> str | None:
    """Validate a tenant id while preserving NULL/local-mode semantics."""
    if value is None:
        return None
    try:
        uuid.UUID(value)
    except ValueError as exc:
        raise SchemaValidationError(f"{field} must be a UUID string or null") from exc
    return value


def is_valid(value: str, prefix: str | None = None) -> bool:
    """True if ``value`` is a well-formed typed id (optionally of ``prefix``)."""
    try:
        p, _ = parse_id(value)
    except ValueError:
        return False
    return prefix is None or p == prefix
