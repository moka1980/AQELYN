"""Known-data exposure derivation (EA-0023 E2)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from pydantic import BaseModel, ConfigDict, field_validator

from aqelyn.conventions import new_id, require_tenant_id, utc_now
from aqelyn.conventions.errors import ExposureConfigInvalid
from aqelyn.exposure.models import (
    VALID_REACHABILITY,
    AssetRef,
    AttackSurfaceAsset,
    ExposureBasis,
    ExposureConfig,
    ExposureRecord,
    Reachability,
)
from aqelyn.exposure.store import ExposureStore, validate_tenant


class KnownSurfaceRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_ref: AssetRef
    classification: str = "known_asset"
    exposure_type: str = "known_surface"
    reachability: Reachability | None = None
    basis: list[ExposureBasis]
    observed_at: datetime | None = None
    rationale: str | None = None

    @field_validator("classification", "exposure_type")
    @classmethod
    def _text(cls, value: str) -> str:
        if not value.strip():
            raise ExposureConfigInvalid("known surface text fields must not be empty")
        return value

    @field_validator("reachability")
    @classmethod
    def _reachability(cls, value: Reachability | None) -> Reachability | None:
        if value is not None and value not in VALID_REACHABILITY:
            raise ExposureConfigInvalid(f"unknown reachability: {value!r}")
        return value

    @field_validator("basis")
    @classmethod
    def _basis(cls, values: list[ExposureBasis]) -> list[ExposureBasis]:
        if not values:
            raise ExposureConfigInvalid("known surface record requires at least one basis")
        return values


class KnownSurfaceSource(Protocol):
    async def list_known_surface(
        self, *, tenant_id: str | None
    ) -> Sequence[KnownSurfaceRecord]: ...


class StaticKnownSurfaceSource:
    def __init__(self, records: Sequence[KnownSurfaceRecord], *, unavailable: bool = False) -> None:
        self.records = [record.model_copy(deep=True) for record in records]
        self.unavailable = unavailable
        self.reads: list[str | None] = []

    async def list_known_surface(self, *, tenant_id: str | None) -> Sequence[KnownSurfaceRecord]:
        self.reads.append(tenant_id)
        if self.unavailable:
            raise ExposureConfigInvalid("known surface source unavailable")
        return [record.model_copy(deep=True) for record in self.records]


class KnownDataExposureEngine:
    def __init__(
        self,
        store: ExposureStore,
        source: KnownSurfaceSource,
        *,
        config: ExposureConfig | None = None,
    ) -> None:
        self.store = store
        self.source = source
        self.config = config or ExposureConfig()

    async def derive_surface(self, *, tenant_id: str | None) -> list[AttackSurfaceAsset]:
        selected_tenant = validate_tenant(tenant_id)
        rows = await self.source.list_known_surface(tenant_id=selected_tenant)
        assets = [
            AttackSurfaceAsset(
                tenant_id=selected_tenant,
                asset_ref=row.asset_ref,
                classification=row.classification,
                exposure_level=_level_for(row.reachability, default=self.config.default_level),
                discovered_at=row.observed_at or _basis_as_of(row.basis),
                validated_at=row.observed_at,
                basis=row.basis,
            )
            for row in rows
        ]
        assets.sort(key=lambda asset: (asset.asset_ref.kind, asset.asset_ref.ref_id, asset.id))
        return assets

    async def analyze_exposure(
        self, *, asset_ref: AssetRef, tenant_id: str | None
    ) -> ExposureRecord:
        selected_tenant = require_tenant_id(tenant_id)
        try:
            rows = await self.source.list_known_surface(tenant_id=selected_tenant)
            match = _find_row(rows, asset_ref)
            if match is None or match.reachability is None:
                record = _unknown_record(
                    asset_ref=asset_ref,
                    tenant_id=selected_tenant,
                    basis=_basis_from_asset(asset_ref),
                    rationale="Reachability could not be derived from known data.",
                )
            else:
                record = ExposureRecord(
                    tenant_id=selected_tenant,
                    asset_ref=asset_ref,
                    exposure_type=match.exposure_type,
                    reachability=match.reachability,
                    basis=match.basis,
                    score=None,
                    confidence=None,
                    derivation=None,
                    rationale=match.rationale
                    or "Reachability is derived from handed-in known data.",
                    flagged=match.reachability == "unknown",
                    discovered_at=match.observed_at or _basis_as_of(match.basis),
                    validated_at=match.observed_at,
                    status="open",
                )
        except Exception as exc:
            record = _unknown_record(
                asset_ref=asset_ref,
                tenant_id=selected_tenant,
                basis=_basis_from_asset(asset_ref),
                rationale=f"Known exposure source unavailable; recorded unknown: {exc}",
            )
        return await self.store.put(record)


def _find_row(rows: Sequence[KnownSurfaceRecord], asset_ref: AssetRef) -> KnownSurfaceRecord | None:
    for row in rows:
        if row.asset_ref.kind == asset_ref.kind and row.asset_ref.ref_id == asset_ref.ref_id:
            return row
    return None


def _basis_from_asset(asset_ref: AssetRef) -> list[ExposureBasis]:
    return [
        ExposureBasis(
            kind="inventory",
            ref=asset_ref.ref_id,
            as_of=utc_now(),
            evidence_id=asset_ref.evidence_id,
        )
    ]


def _basis_as_of(values: Sequence[ExposureBasis]) -> datetime:
    return min(value.as_of for value in values)


def _level_for(reachability: Reachability | None, *, default: str) -> str:
    if reachability == "external":
        return "high"
    if reachability == "internal":
        return "low"
    return default


def _unknown_record(
    *,
    asset_ref: AssetRef,
    tenant_id: str | None,
    basis: list[ExposureBasis],
    rationale: str,
) -> ExposureRecord:
    return ExposureRecord(
        id=new_id("exp"),
        tenant_id=tenant_id,
        asset_ref=asset_ref,
        exposure_type="known_surface",
        reachability="unknown",
        basis=basis,
        score=None,
        confidence=None,
        derivation=None,
        rationale=rationale,
        flagged=True,
        discovered_at=utc_now(),
        validated_at=None,
        status="open",
    )
