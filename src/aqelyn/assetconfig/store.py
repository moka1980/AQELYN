"""Asset & Configuration Governance persistence protocols (EA-0012 A3)."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from aqelyn.assetconfig.models import Baseline, DriftSnapshot
from aqelyn.conventions import new_uuid, require_tenant_id
from aqelyn.conventions.errors import BaselineConfigInvalid


class BaselineStore(Protocol):
    async def put(self, baseline: Baseline) -> Baseline: ...

    async def get(self, baseline_id: str) -> Baseline | None: ...

    async def list(
        self, *, tenant_id: str | None, asset_class: str | None = None
    ) -> list[Baseline]: ...


class DriftSnapshotStore(Protocol):
    async def put(self, snapshot: DriftSnapshot) -> DriftSnapshot: ...

    async def get(self, snapshot_id: str) -> DriftSnapshot | None: ...

    async def latest(self, *, tenant_id: str | None) -> DriftSnapshot | None: ...

    async def history(
        self, *, tenant_id: str | None, since: datetime | None = None, limit: int = 100
    ) -> list[DriftSnapshot]: ...


def new_drift_snapshot_id() -> str:
    """Mint a module-local drift snapshot id without adding a typed-id prefix."""
    return f"drift-snapshot-{new_uuid()}"


def validate_baseline_id(value: str, *, field: str = "baseline_id") -> str:
    if not value.strip():
        raise BaselineConfigInvalid(f"{field} must not be empty")
    return value


def validate_snapshot_id(value: str, *, field: str = "snapshot_id") -> str:
    if not value.strip():
        raise BaselineConfigInvalid(f"{field} must not be empty")
    return value


def validate_baseline(baseline: Baseline) -> Baseline:
    return Baseline.model_validate(baseline.model_dump(mode="json"))


def validate_snapshot(snapshot: DriftSnapshot) -> DriftSnapshot:
    validated = DriftSnapshot.model_validate(snapshot.model_dump(mode="json"))
    if not validated.coverage_complete:
        raise BaselineConfigInvalid("new drift snapshots require complete coverage")
    return validated


def validate_tenant(value: str | None) -> str | None:
    return require_tenant_id(value)


def validate_positive(value: int, *, field: str) -> int:
    if isinstance(value, bool) or value < 1:
        raise BaselineConfigInvalid(f"{field} must be >= 1")
    return value
