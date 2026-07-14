"""SOCStore protocol and validation helpers (EA-0015 S2)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, cast

from aqelyn.conventions import require_tenant_id, require_typed_id
from aqelyn.conventions.errors import SOCConfigInvalid
from aqelyn.soc.models import Alert, Incident, IncidentStatus

VALID_INCIDENT_STATUSES: frozenset[str] = frozenset(
    ("new", "triaged", "investigating", "contained", "resolved", "closed")
)


class SOCStore(Protocol):
    async def upsert_alert(self, alert: Alert) -> Alert: ...

    async def upsert_incident(self, incident: Incident) -> Incident: ...

    async def get_incident(
        self,
        incident_id: str,
        *,
        tenant_id: str | None = None,
    ) -> Incident | None: ...

    async def query_incidents(
        self,
        *,
        tenant_id: str | None,
        status: Sequence[str] | None = None,
        limit: int = 100,
    ) -> list[Incident]: ...


def validate_alert(alert: Alert) -> Alert:
    return Alert.model_validate(alert.model_dump(mode="json"))


def validate_incident(incident: Incident) -> Incident:
    return Incident.model_validate(incident.model_dump(mode="json"))


def validate_alert_id(value: str, *, field: str = "alert_id", allow_empty: bool = False) -> str:
    return require_typed_id(value, "alt", field=field, allow_empty=allow_empty)


def validate_incident_id(
    value: str,
    *,
    field: str = "incident_id",
    allow_empty: bool = False,
) -> str:
    return require_typed_id(value, "inc", field=field, allow_empty=allow_empty)


def validate_tenant(value: str | None) -> str | None:
    return require_tenant_id(value)


def validate_positive(value: int, *, field: str) -> int:
    if isinstance(value, bool) or value < 1:
        raise SOCConfigInvalid(f"{field} must be >= 1")
    return value


def normalize_status_filter(
    status: Sequence[str] | None,
) -> tuple[IncidentStatus, ...] | None:
    if status is None:
        return None
    normalized: list[IncidentStatus] = []
    for value in status:
        if value not in VALID_INCIDENT_STATUSES:
            raise SOCConfigInvalid(f"unknown incident status: {value!r}")
        normalized.append(cast(IncidentStatus, value))
    return tuple(normalized)
