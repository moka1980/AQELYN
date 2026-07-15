"""In-memory Security Data Lake stores (EA-0019 L2)."""

from __future__ import annotations

import copy
from collections.abc import Sequence

from aqelyn.conventions.errors import OptimisticConcurrencyConflict, TenantScopeRequired
from aqelyn.lake.catalog import DatasetCatalog
from aqelyn.lake.models import Quarantine, TelemetryRecord
from aqelyn.lake.store import (
    normalize_retention_state_filter,
    validate_dataset_name,
    validate_positive,
    validate_quarantine,
    validate_record,
    validate_record_id,
    validate_tenant,
)


class InMemoryDatasetCatalog(DatasetCatalog):
    """Named in-memory backend for the L2 catalog contract suite."""


class InMemoryTelemetryRecordStore:
    def __init__(self, *, mode: str = "local") -> None:
        self._records: dict[str, TelemetryRecord] = {}
        self._quarantine: list[tuple[str | None, Quarantine]] = []
        self.mode = mode

    async def append(self, record: TelemetryRecord) -> TelemetryRecord:
        stored = validate_record(record)
        validate_record_id(stored.id, field="id")
        if stored.id in self._records:
            raise OptimisticConcurrencyConflict(f"telemetry record already exists: {stored.id}")
        self._records[stored.id] = stored
        return copy.deepcopy(stored)

    async def get(
        self,
        record_id: str,
        *,
        tenant_id: str | None = None,
    ) -> TelemetryRecord | None:
        validate_record_id(record_id)
        tenant_id = validate_tenant(tenant_id)
        record = self._records.get(record_id)
        if record is None or not self._visible(record, tenant_id):
            return None
        return copy.deepcopy(record)

    async def query(
        self,
        *,
        dataset: str,
        tenant_id: str | None,
        limit: int = 100,
        retention_state: Sequence[str] | None = None,
    ) -> list[TelemetryRecord]:
        validate_dataset_name(dataset)
        tenant_id = validate_tenant(tenant_id)
        validate_positive(limit, field="limit")
        states = normalize_retention_state_filter(retention_state)
        if self.mode == "enterprise" and tenant_id is None:
            raise TenantScopeRequired("lake record query must be tenant-scoped")
        rows = [
            copy.deepcopy(record)
            for record in self._records.values()
            if record.dataset == dataset
            and self._visible(record, tenant_id)
            and (states is None or record.retention_state in states)
        ]
        rows.sort(key=lambda record: (record.occurred_at, record.id))
        return rows[:limit]

    async def quarantine(self, item: Quarantine, *, tenant_id: str | None) -> Quarantine:
        tenant_id = validate_tenant(tenant_id)
        stored = validate_quarantine(item)
        self._quarantine.append((tenant_id, stored))
        return copy.deepcopy(stored)

    async def list_quarantine(
        self,
        *,
        tenant_id: str | None,
        limit: int = 100,
    ) -> list[Quarantine]:
        tenant_id = validate_tenant(tenant_id)
        validate_positive(limit, field="limit")
        if self.mode == "enterprise" and tenant_id is None:
            raise TenantScopeRequired("lake quarantine query must be tenant-scoped")
        rows = [
            copy.deepcopy(item)
            for row_tenant, item in self._quarantine
            if self._visible_tenant(row_tenant, tenant_id)
        ]
        rows.sort(key=lambda item: (item.received_at, item.source_id, item.reason))
        return rows[:limit]

    def _visible(self, record: TelemetryRecord, tenant_id: str | None) -> bool:
        return self._visible_tenant(record.tenant_id, tenant_id)

    def _visible_tenant(self, row_tenant: str | None, tenant_id: str | None) -> bool:
        if self.mode == "local" and row_tenant is not None:
            return False
        return tenant_id is None or row_tenant == tenant_id
