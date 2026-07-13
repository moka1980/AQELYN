"""In-memory SnapshotStore implementation (EA-0010 G3)."""

from __future__ import annotations

import copy
from datetime import datetime

from aqelyn.conventions.errors import OptimisticConcurrencyConflict
from aqelyn.governance.models import ComplianceSnapshot
from aqelyn.governance.store import (
    validate_positive,
    validate_snapshot,
    validate_snapshot_id,
    validate_snapshot_tenant,
)


class InMemorySnapshotStore:
    def __init__(self) -> None:
        self._snapshots: dict[str, ComplianceSnapshot] = {}

    async def put(self, snapshot: ComplianceSnapshot) -> ComplianceSnapshot:
        stored = validate_snapshot(snapshot)
        if stored.id in self._snapshots:
            raise OptimisticConcurrencyConflict(f"snapshot already exists: {stored.id}")
        self._snapshots[stored.id] = stored.model_copy(deep=True)
        return copy.deepcopy(stored)

    async def get(self, snapshot_id: str) -> ComplianceSnapshot | None:
        validate_snapshot_id(snapshot_id)
        snapshot = self._snapshots.get(snapshot_id)
        if snapshot is None:
            return None
        return copy.deepcopy(snapshot)

    async def latest(self, *, tenant_id: str | None) -> ComplianceSnapshot | None:
        tenant_id = validate_snapshot_tenant(tenant_id)
        rows = [
            snapshot for snapshot in self._snapshots.values() if snapshot.tenant_id == tenant_id
        ]
        if not rows:
            return None
        latest = max(rows, key=lambda snapshot: (snapshot.run_at, snapshot.id))
        return copy.deepcopy(latest)

    async def history(
        self, *, tenant_id: str | None, since: datetime | None = None, limit: int = 100
    ) -> list[ComplianceSnapshot]:
        tenant_id = validate_snapshot_tenant(tenant_id)
        validate_positive(limit, field="limit")
        rows = [
            copy.deepcopy(snapshot)
            for snapshot in self._snapshots.values()
            if snapshot.tenant_id == tenant_id and (since is None or snapshot.run_at >= since)
        ]
        rows.sort(key=lambda snapshot: (snapshot.run_at, snapshot.id))
        return rows[:limit]
