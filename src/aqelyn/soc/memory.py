"""In-memory SOCStore implementation (EA-0015 S2)."""

from __future__ import annotations

import copy
from collections.abc import Sequence

from aqelyn.conventions import new_id, utc_now
from aqelyn.conventions.errors import (
    CrossTenantReference,
    OptimisticConcurrencyConflict,
    TenantScopeRequired,
)
from aqelyn.soc.models import Alert, Incident
from aqelyn.soc.store import (
    normalize_status_filter,
    validate_alert,
    validate_alert_id,
    validate_incident,
    validate_incident_id,
    validate_positive,
    validate_tenant,
)


class InMemorySOCStore:
    def __init__(self, *, mode: str = "local") -> None:
        self._alerts: dict[str, Alert] = {}
        self._alerts_by_source: dict[tuple[str | None, str], str] = {}
        self._incidents: dict[str, Incident] = {}
        self.mode = mode

    async def upsert_alert(self, alert: Alert) -> Alert:
        stored = validate_alert(alert)
        if not stored.id:
            stored.id = new_id("alt")
        validate_alert_id(stored.id, field="id")
        key = (stored.tenant_id, stored.source_ref)
        existing_id = self._alerts_by_source.get(key)
        existing = self._alerts.get(existing_id) if existing_id is not None else None
        if existing is None and stored.id in self._alerts:
            existing = self._alerts[stored.id]
            existing_key = (existing.tenant_id, existing.source_ref)
            if existing_key != key:
                raise CrossTenantReference("alert tenant_id/source_ref cannot change")

        if existing is None:
            created = stored.model_copy(update={"version": 1}, deep=True)
            self._alerts[created.id] = created
            self._alerts_by_source[key] = created.id
            return copy.deepcopy(created)

        updated = stored.model_copy(
            update={
                "id": existing.id,
                "created_at": existing.created_at,
                "version": existing.version + 1,
            },
            deep=True,
        )
        self._alerts[updated.id] = updated
        self._alerts_by_source[key] = updated.id
        return copy.deepcopy(updated)

    async def upsert_incident(self, incident: Incident) -> Incident:
        stored = validate_incident(incident)
        if not stored.id:
            stored.id = new_id("inc")
        validate_incident_id(stored.id, field="id")
        existing = self._incidents.get(stored.id)
        if existing is None:
            created = stored.model_copy(update={"version": 1}, deep=True)
            self._incidents[created.id] = created
            return copy.deepcopy(created)

        if existing.tenant_id != stored.tenant_id:
            raise CrossTenantReference("incident tenant_id cannot change")
        validate_positive(stored.version, field="version")
        if existing.version != stored.version:
            raise OptimisticConcurrencyConflict(
                f"expected v{stored.version}, found v{existing.version}"
            )
        updated = stored.model_copy(
            update={
                "created_at": existing.created_at,
                "updated_at": max(utc_now(), existing.updated_at, stored.updated_at),
                "version": existing.version + 1,
            },
            deep=True,
        )
        self._incidents[updated.id] = updated
        return copy.deepcopy(updated)

    async def get_incident(
        self,
        incident_id: str,
        *,
        tenant_id: str | None = None,
    ) -> Incident | None:
        validate_incident_id(incident_id)
        tenant_id = validate_tenant(tenant_id)
        incident = self._incidents.get(incident_id)
        if incident is None or not self._visible(incident, tenant_id):
            return None
        return copy.deepcopy(incident)

    async def query_incidents(
        self,
        *,
        tenant_id: str | None,
        status: Sequence[str] | None = None,
        limit: int = 100,
    ) -> list[Incident]:
        tenant_id = validate_tenant(tenant_id)
        statuses = normalize_status_filter(status)
        validate_positive(limit, field="limit")
        if self.mode == "enterprise" and tenant_id is None:
            raise TenantScopeRequired("incident query must be tenant-scoped in enterprise mode")
        rows = [
            copy.deepcopy(incident)
            for incident in self._incidents.values()
            if self._visible(incident, tenant_id)
            and (statuses is None or incident.status in statuses)
        ]
        rows.sort(key=_incident_sort_key)
        return rows[:limit]

    def _visible(self, incident: Incident, tenant_id: str | None) -> bool:
        if self.mode == "local" and incident.tenant_id is not None:
            return False
        return tenant_id is None or incident.tenant_id == tenant_id


def _incident_sort_key(incident: Incident) -> tuple[float, float, str]:
    return (-incident.priority, -incident.updated_at.timestamp(), incident.id)
