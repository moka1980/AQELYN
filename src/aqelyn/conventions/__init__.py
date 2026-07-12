"""Platform-wide conventions (T1). Implements CONVENTIONS.spec.md:
typed IDs, UTC time, canonical JSON, error taxonomy, structured logging."""

from aqelyn.conventions import errors
from aqelyn.conventions.actors import ActorRef, ActorType
from aqelyn.conventions.canonical import canonical_json, sha256_hex
from aqelyn.conventions.errors import ALL_ERROR_CODES, AQError
from aqelyn.conventions.ids import (
    PREFIXES,
    is_valid,
    new_id,
    new_uuid,
    parse_id,
    require_tenant_id,
    require_typed_id,
)
from aqelyn.conventions.logging import configure_logging, get_logger
from aqelyn.conventions.timeutil import to_rfc3339, utc_now

__all__ = [
    "ALL_ERROR_CODES",
    "PREFIXES",
    "AQError",
    "ActorRef",
    "ActorType",
    "canonical_json",
    "configure_logging",
    "errors",
    "get_logger",
    "is_valid",
    "new_id",
    "new_uuid",
    "parse_id",
    "require_tenant_id",
    "require_typed_id",
    "sha256_hex",
    "to_rfc3339",
    "utc_now",
]
