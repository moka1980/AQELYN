"""Known-data exposure derivation and owner-engine delegations (EA-0023 E2-E3)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from pydantic import BaseModel, ConfigDict, field_validator

from aqelyn.conventions import new_id, require_tenant_id, require_typed_id, utc_now
from aqelyn.conventions.errors import ExposureConfigInvalid
from aqelyn.exposure.models import (
    VALID_REACHABILITY,
    AssetRef,
    AttackSurfaceAsset,
    ExposureBasis,
    ExposureConfig,
    ExposureRecord,
    Reachability,
    ReachablePath,
)
from aqelyn.exposure.store import ExposureStore, validate_tenant
from aqelyn.forecast.models import TrendRecord
from aqelyn.graph.models import EdgeView, Path
from aqelyn.iag.models import AccessPath, AccessRiskReport


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


class ExposurePathGraph(Protocol):
    async def paths(
        self,
        from_id: str,
        to_id: str,
        *,
        direction: str = "both",
        relation_types: Sequence[str] | None = None,
        max_depth: int = 6,
        max_paths: int = 10,
        max_work: int = 50_000,
    ) -> list[Path]: ...


class IdentityExposureProvider(Protocol):
    async def access_paths(
        self, identity_id: str, *, tenant_id: str | None = None
    ) -> list[AccessPath]: ...

    async def analyze_risk(
        self, *, tenant_id: str | None, scope: object | None = None
    ) -> AccessRiskReport: ...


class ExposureTrendProvider(Protocol):
    async def analyze_trend(
        self, *, metric: str, window_days: int, tenant_id: str | None
    ) -> TrendRecord: ...


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
        graph: ExposurePathGraph | None = None,
        identity_provider: IdentityExposureProvider | None = None,
        trend_provider: ExposureTrendProvider | None = None,
        path_roots: Sequence[str] = (),
    ) -> None:
        self.store = store
        self.source = source
        self.config = config or ExposureConfig()
        self.graph = graph
        self.identity_provider = identity_provider
        self.trend_provider = trend_provider
        self.path_roots = [require_typed_id(root, "obj", field="path_roots") for root in path_roots]

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
        except Exception as exc:
            record = _unknown_record(
                asset_ref=asset_ref,
                tenant_id=selected_tenant,
                basis=_basis_from_asset(asset_ref),
                rationale=f"Known exposure source unavailable; recorded unknown: {exc}",
            )
            return await self.store.put(record)

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
                rationale=match.rationale or "Reachability is derived from handed-in known data.",
                flagged=match.reachability == "unknown",
                discovered_at=match.observed_at or _basis_as_of(match.basis),
                validated_at=match.observed_at,
                status="open",
            )
        return await self.store.put(record)

    async def reachable_paths(
        self, *, target_ref: str, tenant_id: str | None
    ) -> list[ReachablePath]:
        _ = validate_tenant(tenant_id)
        target_id = require_typed_id(target_ref, "obj", field="target_ref")
        if self.graph is None:
            raise ExposureConfigInvalid("knowledge graph provider is unavailable")
        results: list[ReachablePath] = []
        for root_id in self.path_roots:
            delegated = await self.graph.paths(
                root_id,
                target_id,
                direction="out",
                max_paths=self.config.max_paths - len(results),
                max_work=self.config.max_work,
            )
            for path in delegated:
                results.append(
                    ReachablePath(
                        target_ref=target_id,
                        path=list(path.node_ids),
                        via="graph",
                        max_work=self.config.max_work,
                    )
                )
                if len(results) >= self.config.max_paths:
                    return results
        return results

    async def identity_exposure(
        self, *, asset_ref: AssetRef, tenant_id: str | None
    ) -> ExposureRecord:
        selected_tenant = validate_tenant(tenant_id)
        if self.identity_provider is None:
            raise ExposureConfigInvalid("identity exposure provider is unavailable")
        access_paths = await self.identity_provider.access_paths(
            asset_ref.ref_id, tenant_id=selected_tenant
        )
        risk_report = await self.identity_provider.analyze_risk(
            tenant_id=selected_tenant, scope=None
        )
        record = ExposureRecord(
            tenant_id=selected_tenant,
            asset_ref=asset_ref,
            exposure_type="identity_access",
            reachability="unknown",
            basis=_basis_from_iag(asset_ref, access_paths, risk_report),
            score=None,
            confidence=None,
            derivation=None,
            rationale="Identity exposure cites EA-0011 IAG; no entitlement verdict is re-derived.",
            flagged=True,
            discovered_at=utc_now(),
            validated_at=None,
            status="open",
        )
        return await self.store.put(record)

    async def trend(self, *, category: str, window_days: int, tenant_id: str | None) -> TrendRecord:
        selected_tenant = validate_tenant(tenant_id)
        if self.trend_provider is None:
            raise ExposureConfigInvalid("forecast trend provider is unavailable")
        return await self.trend_provider.analyze_trend(
            metric=category,
            window_days=window_days,
            tenant_id=selected_tenant,
        )


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


def _basis_from_iag(
    asset_ref: AssetRef,
    paths: Sequence[AccessPath],
    report: AccessRiskReport,
) -> list[ExposureBasis]:
    now = utc_now()
    basis: list[ExposureBasis] = []
    for index, path in enumerate(paths):
        basis.append(
            ExposureBasis(
                kind="access",
                ref=f"iag:access_path:{path.identity_id}:{index}",
                as_of=now,
                evidence_id=_first_edge_evidence(path.via.edges),
            )
        )
    for risk in report.risks:
        if risk.subject_id != asset_ref.ref_id:
            continue
        evidence_id = None
        if risk.evidence_path is not None:
            evidence_id = _first_edge_evidence(risk.evidence_path.edges)
        basis.append(
            ExposureBasis(
                kind="access",
                ref=f"iag:risk:{risk.kind}:{risk.subject_id}",
                as_of=now,
                evidence_id=evidence_id,
            )
        )
    return basis or _basis_from_asset(asset_ref)


def _first_edge_evidence(edges: Sequence[EdgeView]) -> str | None:
    for edge in edges:
        for source in edge.sources:
            if source.evidence_id is not None:
                return source.evidence_id
    return None


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
