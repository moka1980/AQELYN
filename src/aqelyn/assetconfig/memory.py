"""In-memory Asset & Configuration Governance stores (EA-0012 A3)."""

from __future__ import annotations

import copy
from datetime import datetime

from aqelyn.assetconfig.models import Baseline, DriftSnapshot
from aqelyn.assetconfig.store import (
    validate_baseline,
    validate_baseline_id,
    validate_positive,
    validate_snapshot,
    validate_snapshot_id,
    validate_tenant,
)
from aqelyn.conventions.errors import CrossTenantReference, OptimisticConcurrencyConflict


class InMemoryBaselineStore:
    def __init__(self) -> None:
        self._baselines: dict[str, Baseline] = {}

    async def put(self, baseline: Baseline) -> Baseline:
        stored = validate_baseline(baseline)
        existing = self._baselines.get(stored.id)
        if existing is not None and existing.tenant_id != stored.tenant_id:
            raise CrossTenantReference("baseline tenant_id cannot change")
        self._baselines[stored.id] = stored.model_copy(deep=True)
        return copy.deepcopy(stored)

    async def get(self, baseline_id: str) -> Baseline | None:
        validate_baseline_id(baseline_id)
        baseline = self._baselines.get(baseline_id)
        if baseline is None:
            return None
        return copy.deepcopy(baseline)

    async def list(
        self, *, tenant_id: str | None, asset_class: str | None = None
    ) -> list[Baseline]:
        tenant_id = validate_tenant(tenant_id)
        rows = [
            copy.deepcopy(baseline)
            for baseline in self._baselines.values()
            if _visible(baseline, tenant_id) and _matches_class(baseline, asset_class)
        ]
        rows.sort(key=_baseline_sort_key)
        return rows


class InMemoryDriftSnapshotStore:
    def __init__(self) -> None:
        self._snapshots: dict[str, DriftSnapshot] = {}

    async def put(self, snapshot: DriftSnapshot) -> DriftSnapshot:
        stored = validate_snapshot(snapshot)
        if stored.id in self._snapshots:
            raise OptimisticConcurrencyConflict(f"snapshot already exists: {stored.id}")
        self._snapshots[stored.id] = stored.model_copy(deep=True)
        return copy.deepcopy(stored)

    async def get(self, snapshot_id: str) -> DriftSnapshot | None:
        validate_snapshot_id(snapshot_id)
        snapshot = self._snapshots.get(snapshot_id)
        if snapshot is None:
            return None
        return copy.deepcopy(snapshot)

    async def latest(self, *, tenant_id: str | None) -> DriftSnapshot | None:
        tenant_id = validate_tenant(tenant_id)
        rows = [
            snapshot for snapshot in self._snapshots.values() if snapshot.tenant_id == tenant_id
        ]
        if not rows:
            return None
        latest = max(rows, key=lambda snapshot: (snapshot.run_at, snapshot.id))
        return copy.deepcopy(latest)

    async def history(
        self, *, tenant_id: str | None, since: datetime | None = None, limit: int = 100
    ) -> list[DriftSnapshot]:
        tenant_id = validate_tenant(tenant_id)
        validate_positive(limit, field="limit")
        rows = [
            copy.deepcopy(snapshot)
            for snapshot in self._snapshots.values()
            if snapshot.tenant_id == tenant_id and (since is None or snapshot.run_at >= since)
        ]
        rows.sort(key=lambda snapshot: (snapshot.run_at, snapshot.id))
        return rows[:limit]


def _visible(baseline: Baseline, tenant_id: str | None) -> bool:
    if tenant_id is None:
        return baseline.tenant_id is None
    return baseline.tenant_id is None or baseline.tenant_id == tenant_id


def _matches_class(baseline: Baseline, asset_class: str | None) -> bool:
    return asset_class is None or baseline.asset_class == asset_class


def _baseline_sort_key(baseline: Baseline) -> tuple[bool, str, str]:
    return (baseline.tenant_id is not None, baseline.tenant_id or "", baseline.id)
