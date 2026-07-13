"""SnapshotStore protocol and validation helpers (EA-0010 G3)."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from aqelyn.conventions import require_tenant_id, require_typed_id
from aqelyn.conventions.errors import SchemaValidationError
from aqelyn.governance.models import ComplianceSnapshot


class SnapshotStore(Protocol):
    async def put(self, snapshot: ComplianceSnapshot) -> ComplianceSnapshot: ...

    async def get(self, snapshot_id: str) -> ComplianceSnapshot | None: ...

    async def latest(self, *, tenant_id: str | None) -> ComplianceSnapshot | None: ...

    async def history(
        self, *, tenant_id: str | None, since: datetime | None = None, limit: int = 100
    ) -> list[ComplianceSnapshot]: ...


def validate_snapshot_id(value: str, *, field: str = "snapshot_id") -> str:
    return require_typed_id(value, "snap", field=field)


def validate_snapshot(snapshot: ComplianceSnapshot) -> ComplianceSnapshot:
    return ComplianceSnapshot.model_validate(snapshot.model_dump(mode="json"))


def validate_snapshot_tenant(value: str | None) -> str | None:
    return require_tenant_id(value)


def validate_positive(value: int, *, field: str) -> int:
    if isinstance(value, bool) or value < 1:
        raise SchemaValidationError(f"{field} must be >= 1")
    return value
