"""In-memory Risk Intelligence stores (EA-0013 R3)."""

from __future__ import annotations

import copy
from collections.abc import Sequence
from datetime import datetime

from aqelyn.conventions.errors import CrossTenantReference, OptimisticConcurrencyConflict
from aqelyn.risk.models import Risk, RiskSnapshot
from aqelyn.risk.store import (
    normalize_band_filter,
    normalize_lifecycle_filter,
    validate_positive,
    validate_risk,
    validate_risk_id,
    validate_snapshot,
    validate_snapshot_id,
    validate_tenant,
)


class InMemoryRiskStore:
    def __init__(self) -> None:
        self._risks: dict[str, Risk] = {}
        self._by_correlation: dict[tuple[str | None, str], str] = {}

    async def upsert(self, risk: Risk) -> Risk:
        stored = validate_risk(risk)
        key = (stored.tenant_id, stored.correlation_key)
        existing_id = self._by_correlation.get(key)
        existing = self._risks.get(existing_id) if existing_id is not None else None
        if existing is None and stored.id in self._risks:
            existing = self._risks[stored.id]
            existing_key = (existing.tenant_id, existing.correlation_key)
            if existing_key != key:
                raise CrossTenantReference("risk tenant_id/correlation_key cannot change")

        if existing is None:
            created = stored.model_copy(update={"version": 1}, deep=True)
            self._risks[created.id] = created
            self._by_correlation[key] = created.id
            return copy.deepcopy(created)

        validate_positive(stored.version, field="version")
        if existing.version != stored.version:
            raise OptimisticConcurrencyConflict(
                f"expected v{stored.version}, found v{existing.version}"
            )
        updated = stored.model_copy(
            update={
                "id": existing.id,
                "first_seen_at": existing.first_seen_at,
                "version": existing.version + 1,
            },
            deep=True,
        )
        self._risks[updated.id] = updated
        self._by_correlation[key] = updated.id
        return copy.deepcopy(updated)

    async def get(self, risk_id: str) -> Risk | None:
        validate_risk_id(risk_id)
        risk = self._risks.get(risk_id)
        return None if risk is None else copy.deepcopy(risk)

    async def query(
        self,
        *,
        tenant_id: str | None,
        band: Sequence[str] | None = None,
        lifecycle: Sequence[str] | None = None,
        limit: int = 100,
    ) -> list[Risk]:
        tenant_id = validate_tenant(tenant_id)
        bands = normalize_band_filter(band)
        lifecycles = normalize_lifecycle_filter(lifecycle)
        validate_positive(limit, field="limit")
        rows = [
            copy.deepcopy(risk)
            for risk in self._risks.values()
            if risk.tenant_id == tenant_id
            and (bands is None or risk.band in bands)
            and (lifecycles is None or risk.lifecycle in lifecycles)
        ]
        rows.sort(key=lambda risk: (-risk.score, risk.id))
        return rows[:limit]


class InMemoryRiskSnapshotStore:
    def __init__(self) -> None:
        self._snapshots: dict[str, RiskSnapshot] = {}

    async def put(self, snapshot: RiskSnapshot) -> RiskSnapshot:
        stored = validate_snapshot(snapshot)
        if stored.id in self._snapshots:
            raise OptimisticConcurrencyConflict(f"snapshot already exists: {stored.id}")
        self._snapshots[stored.id] = stored.model_copy(deep=True)
        return copy.deepcopy(stored)

    async def get(self, snapshot_id: str) -> RiskSnapshot | None:
        validate_snapshot_id(snapshot_id)
        snapshot = self._snapshots.get(snapshot_id)
        return None if snapshot is None else copy.deepcopy(snapshot)

    async def latest(self, *, tenant_id: str | None) -> RiskSnapshot | None:
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
    ) -> list[RiskSnapshot]:
        tenant_id = validate_tenant(tenant_id)
        validate_positive(limit, field="limit")
        rows = [
            copy.deepcopy(snapshot)
            for snapshot in self._snapshots.values()
            if snapshot.tenant_id == tenant_id and (since is None or snapshot.run_at >= since)
        ]
        rows.sort(key=lambda snapshot: (snapshot.run_at, snapshot.id))
        return rows[:limit]
