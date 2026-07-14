"""Risk Intelligence persistence protocols and validation helpers (EA-0013 R3)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from aqelyn.conventions import new_uuid, require_tenant_id
from aqelyn.conventions.errors import RiskConfigInvalid
from aqelyn.risk.models import Risk, RiskBand, RiskLifecycle, RiskSnapshot

VALID_RISK_BANDS: frozenset[str] = frozenset(("within_appetite", "elevated", "over_tolerance"))
VALID_RISK_LIFECYCLES: frozenset[str] = frozenset(("identified", "assessed", "treated", "closed"))


class RiskStore(Protocol):
    async def upsert(self, risk: Risk) -> Risk: ...

    async def get(self, risk_id: str) -> Risk | None: ...

    async def query(
        self,
        *,
        tenant_id: str | None,
        band: Sequence[str] | None = None,
        lifecycle: Sequence[str] | None = None,
        limit: int = 100,
    ) -> list[Risk]: ...


class RiskSnapshotStore(Protocol):
    async def put(self, snapshot: RiskSnapshot) -> RiskSnapshot: ...

    async def get(self, snapshot_id: str) -> RiskSnapshot | None: ...

    async def latest(self, *, tenant_id: str | None) -> RiskSnapshot | None: ...

    async def history(
        self, *, tenant_id: str | None, since: datetime | None = None, limit: int = 100
    ) -> list[RiskSnapshot]: ...


def new_risk_snapshot_id() -> str:
    """Mint a module-local risk snapshot id without adding a typed-id prefix."""
    return f"risk-snapshot-{new_uuid()}"


def validate_risk_id(value: str, *, field: str = "risk_id") -> str:
    if not value.strip():
        raise RiskConfigInvalid(f"{field} must not be empty")
    return value


def validate_snapshot_id(value: str, *, field: str = "snapshot_id") -> str:
    if not value.strip():
        raise RiskConfigInvalid(f"{field} must not be empty")
    return value


def validate_risk(risk: Risk) -> Risk:
    return Risk.model_validate(risk.model_dump(mode="json"))


def validate_snapshot(snapshot: RiskSnapshot) -> RiskSnapshot:
    return RiskSnapshot.model_validate(snapshot.model_dump(mode="json"))


def validate_tenant(value: str | None) -> str | None:
    return require_tenant_id(value)


def validate_positive(value: int, *, field: str) -> int:
    if isinstance(value, bool) or value < 1:
        raise RiskConfigInvalid(f"{field} must be >= 1")
    return value


def normalize_band_filter(band: Sequence[str] | None) -> tuple[RiskBand, ...] | None:
    if band is None:
        return None
    normalized: list[RiskBand] = []
    for value in band:
        if value not in VALID_RISK_BANDS:
            raise RiskConfigInvalid(f"unknown risk band: {value!r}")
        normalized.append(value)  # type: ignore[arg-type]
    return tuple(normalized)


def normalize_lifecycle_filter(
    lifecycle: Sequence[str] | None,
) -> tuple[RiskLifecycle, ...] | None:
    if lifecycle is None:
        return None
    normalized: list[RiskLifecycle] = []
    for value in lifecycle:
        if value not in VALID_RISK_LIFECYCLES:
            raise RiskConfigInvalid(f"unknown risk lifecycle: {value!r}")
        normalized.append(value)  # type: ignore[arg-type]
    return tuple(normalized)
