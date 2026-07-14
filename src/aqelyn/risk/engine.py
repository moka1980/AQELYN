"""Risk Intelligence assessment engine (EA-0013 R3)."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from typing import Protocol

from aqelyn.conventions import utc_now
from aqelyn.findings import FindingStore
from aqelyn.mission.models import MissionImpactResult
from aqelyn.risk.correlate import RiskCorrelator, explain
from aqelyn.risk.models import CorrelationSignal, Risk, RiskBand, RiskConfig, RiskSnapshot
from aqelyn.risk.scoring import score_risk
from aqelyn.risk.store import RiskSnapshotStore, RiskStore, new_risk_snapshot_id

_ASSESS_QUERY_LIMIT = 10_000
_TOP_RISK_LIMIT = 10


class MissionImpactEngine(Protocol):
    async def mission_impact(self, object_id: str) -> MissionImpactResult: ...


class RiskIntelligenceEngine:
    def __init__(
        self,
        finding_store: FindingStore,
        risk_store: RiskStore,
        snapshot_store: RiskSnapshotStore,
        *,
        config: RiskConfig | None = None,
        mission_engine: MissionImpactEngine | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.finding_store = finding_store
        self.risk_store = risk_store
        self.snapshot_store = snapshot_store
        self.config = config or RiskConfig()
        self.mission_engine = mission_engine
        self._clock = clock
        self._correlator = RiskCorrelator(finding_store, config=self.config, clock=clock)

    async def correlate(
        self,
        *,
        tenant_id: str | None,
        scope: Mapping[str, object] | None = None,
        signals: Sequence[CorrelationSignal] = (),
    ) -> list[Risk]:
        return await self._correlator.correlate(
            tenant_id=tenant_id,
            scope=scope,
            signals=signals,
        )

    async def score(self, risk: Risk) -> Risk:
        mission_factor, top_mission_id = await self._mission_context(risk)
        return score_risk(
            risk,
            config=self.config,
            mission_factor=mission_factor,
            top_mission_id=top_mission_id,
        )

    async def assess(
        self,
        *,
        tenant_id: str | None,
        scope: Mapping[str, object] | None = None,
        signals: Sequence[CorrelationSignal] = (),
    ) -> RiskSnapshot:
        correlated = await self.correlate(tenant_id=tenant_id, scope=scope, signals=signals)
        existing = await self._existing_by_correlation(tenant_id=tenant_id)
        persisted: list[Risk] = []
        for risk in correlated:
            stored = existing.get(risk.correlation_key)
            if stored is not None:
                risk = risk.model_copy(
                    update={
                        "id": stored.id,
                        "first_seen_at": stored.first_seen_at,
                        "version": stored.version,
                    },
                    deep=True,
                )
            scored = await self.score(risk)
            assessed = scored.model_copy(
                update={"lifecycle": "assessed", "last_scored_at": self._now()},
                deep=True,
            )
            persisted.append(await self.risk_store.upsert(assessed))

        snapshot = _snapshot_from_risks(
            persisted,
            tenant_id=tenant_id,
            run_at=self._now(),
        )
        return await self.snapshot_store.put(snapshot)

    async def trend(self, *, tenant_id: str | None, since: datetime) -> list[dict[str, object]]:
        snapshots = await self.snapshot_store.history(tenant_id=tenant_id, since=since)
        return [_trend_point(snapshot) for snapshot in snapshots]

    def explain(self, risk: Risk) -> dict[str, object]:
        return explain(risk)

    async def _existing_by_correlation(self, *, tenant_id: str | None) -> dict[str, Risk]:
        rows = await self.risk_store.query(tenant_id=tenant_id, limit=_ASSESS_QUERY_LIMIT)
        return {risk.correlation_key: risk for risk in rows}

    async def _mission_context(self, risk: Risk) -> tuple[float, str | None]:
        if self.mission_engine is None:
            return 0.0, None
        best_factor = 0.0
        best_mission_id: str | None = None
        for object_id in sorted(risk.affected_object_ids):
            result = await self.mission_engine.mission_impact(object_id)
            for impact in result.impacts:
                candidate = impact.impact_score
                mission_id = impact.mission.id
                if candidate > best_factor or (
                    candidate == best_factor
                    and (best_mission_id is None or mission_id < best_mission_id)
                ):
                    best_factor = candidate
                    best_mission_id = mission_id
        return best_factor, best_mission_id

    def _now(self) -> datetime:
        return self._clock() if self._clock is not None else utc_now()


def _snapshot_from_risks(
    risks: Sequence[Risk],
    *,
    tenant_id: str | None,
    run_at: datetime,
) -> RiskSnapshot:
    band_counts: dict[RiskBand, int] = {
        "within_appetite": 0,
        "elevated": 0,
        "over_tolerance": 0,
    }
    for risk in risks:
        band_counts[risk.band] += 1
    ordered = sorted(risks, key=lambda risk: (-risk.score, risk.id))
    return RiskSnapshot(
        id=new_risk_snapshot_id(),
        tenant_id=tenant_id,
        run_at=run_at,
        total=len(risks),
        band_counts=band_counts,
        top_risks=[risk.id for risk in ordered[:_TOP_RISK_LIMIT]],
        overall_exposure=_mean([risk.score for risk in risks]),
    )


def _trend_point(snapshot: RiskSnapshot) -> dict[str, object]:
    return {
        "snapshot_id": snapshot.id,
        "run_at": snapshot.run_at.isoformat(),
        "total": snapshot.total,
        "band_counts": dict(snapshot.band_counts),
        "top_risks": list(snapshot.top_risks),
        "overall_exposure": snapshot.overall_exposure,
    }


def _mean(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)
