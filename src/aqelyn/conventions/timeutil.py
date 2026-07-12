"""UTC time helpers (CONVENTIONS §2). All timestamps are UTC, RFC 3339, µs."""

from __future__ import annotations

from datetime import UTC, datetime


def utc_now() -> datetime:
    """Timezone-aware current time in UTC."""
    return datetime.now(UTC)


def to_rfc3339(dt: datetime) -> str:
    """Serialize a datetime as UTC RFC3339 with microsecond precision."""
    return dt.astimezone(UTC).isoformat(timespec="microseconds")
