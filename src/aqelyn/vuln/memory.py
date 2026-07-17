"""In-memory VulnerabilityStore implementation (EA-0024 V2)."""

from __future__ import annotations

import copy
from typing import Any

from aqelyn.conventions import utc_now
from aqelyn.conventions.errors import CrossTenantReference
from aqelyn.vuln.models import DispositionKind, VulnerabilityRecord
from aqelyn.vuln.store import (
    validate_cve_filter,
    validate_disposition_filter,
    validate_query_limit,
    validate_tenant,
    validate_vulnerability,
    validate_vulnerability_id,
)


class InMemoryVulnerabilityStore:
    def __init__(self, *, mode: str = "local") -> None:
        self.mode = mode
        self._records: dict[str, VulnerabilityRecord] = {}
        self._history: dict[str, list[dict[str, Any]]] = {}

    async def put(self, vulnerability: VulnerabilityRecord) -> VulnerabilityRecord:
        stored = validate_vulnerability(vulnerability)
        existing = self._records.get(stored.id)
        if existing is not None and existing.tenant_id != stored.tenant_id:
            raise CrossTenantReference("vulnerability tenant_id cannot change")
        self._records[stored.id] = stored.model_copy(deep=True)
        self._append_history(stored)
        return copy.deepcopy(stored)

    async def get(
        self, vulnerability_id: str, *, tenant_id: str | None = None
    ) -> VulnerabilityRecord | None:
        validate_vulnerability_id(vulnerability_id)
        selected_tenant = validate_tenant(tenant_id)
        record = self._records.get(vulnerability_id)
        if record is None or not self._visible(record.tenant_id, selected_tenant):
            return None
        return copy.deepcopy(record)

    async def query(
        self,
        *,
        tenant_id: str | None,
        cve_id: str | None = None,
        disposition: DispositionKind | None = None,
        limit: int = 100,
    ) -> list[VulnerabilityRecord]:
        selected_tenant = validate_tenant(tenant_id)
        selected_cve_id = validate_cve_filter(cve_id)
        selected_disposition = validate_disposition_filter(disposition)
        selected_limit = validate_query_limit(limit)
        rows = [
            copy.deepcopy(record)
            for record in self._records.values()
            if self._visible(record.tenant_id, selected_tenant)
            and (selected_cve_id is None or record.cve_id == selected_cve_id)
            and (
                selected_disposition is None
                or (
                    record.disposition is not None
                    and record.disposition.kind == selected_disposition
                )
            )
        ]
        rows.sort(key=lambda record: (record.discovered_at, record.id))
        return rows[:selected_limit]

    async def history(self, vulnerability_id: str) -> list[dict[str, Any]]:
        validate_vulnerability_id(vulnerability_id)
        return copy.deepcopy(self._history.get(vulnerability_id, []))

    def _append_history(self, vulnerability: VulnerabilityRecord) -> None:
        entries = self._history.setdefault(vulnerability.id, [])
        entries.append(
            {
                "seq": len(entries) + 1,
                "vulnerability_id": vulnerability.id,
                "snapshot": vulnerability.model_dump(mode="json"),
                "changed_at": utc_now(),
            }
        )

    def _visible(self, row_tenant_id: str | None, requested_tenant_id: str | None) -> bool:
        if self.mode == "local" and row_tenant_id is not None:
            return False
        return requested_tenant_id is None or row_tenant_id == requested_tenant_id
