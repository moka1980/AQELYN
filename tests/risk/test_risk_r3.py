"""R3 acceptance tests for Risk Intelligence stores and assessment."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest

from aqelyn.conventions import new_id
from aqelyn.conventions.errors import OptimisticConcurrencyConflict
from aqelyn.findings import Automation, Finding, InMemoryFindingStore, Remediation
from aqelyn.graph import Path
from aqelyn.mission import MissionImpact, MissionImpactResult, MissionView
from aqelyn.risk import (
    CorrelationSignal,
    InMemoryRiskSnapshotStore,
    InMemoryRiskStore,
    Risk,
    RiskConfig,
    RiskIntelligenceEngine,
    RiskSnapshot,
    RiskSnapshotStore,
    RiskStore,
    new_risk_snapshot_id,
)

PG_URL = os.getenv("AQELYN_DATABASE_URL")
NOW = datetime(2026, 7, 14, 12, 30, tzinfo=UTC)
TENANT_A = "018f0000-0000-7000-8000-000000000201"
TENANT_B = "018f0000-0000-7000-8000-000000000202"


@dataclass
class RiskPersistence:
    kind: str
    risk_store: RiskStore
    snapshot_store: RiskSnapshotStore


@pytest.fixture(params=["inmemory", "postgres"], ids=["inmemory", "postgres"])
async def risk_store(request: pytest.FixtureRequest) -> AsyncIterator[RiskStore]:
    if request.param == "inmemory":
        yield InMemoryRiskStore()
        return
    if not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")
    from aqelyn.risk.postgres import PostgresRiskStore

    store = await PostgresRiskStore.connect(PG_URL)
    async with store._pool.acquire() as conn:
        await conn.execute("TRUNCATE aq_risk_snapshot, aq_risk RESTART IDENTITY")
    try:
        yield store
    finally:
        await store.close()


@pytest.fixture(params=["inmemory", "postgres"], ids=["inmemory", "postgres"])
async def risk_snapshot_store(
    request: pytest.FixtureRequest,
) -> AsyncIterator[RiskSnapshotStore]:
    if request.param == "inmemory":
        yield InMemoryRiskSnapshotStore()
        return
    if not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")
    from aqelyn.risk.postgres import PostgresRiskSnapshotStore

    store = await PostgresRiskSnapshotStore.connect(PG_URL)
    async with store._pool.acquire() as conn:
        await conn.execute("TRUNCATE aq_risk_snapshot, aq_risk RESTART IDENTITY")
    try:
        yield store
    finally:
        await store.close()


@pytest.fixture(params=["inmemory", "postgres"], ids=["inmemory", "postgres"])
async def risk_persistence(request: pytest.FixtureRequest) -> AsyncIterator[RiskPersistence]:
    if request.param == "inmemory":
        yield RiskPersistence(
            kind="inmemory",
            risk_store=InMemoryRiskStore(),
            snapshot_store=InMemoryRiskSnapshotStore(),
        )
        return
    if not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")
    from aqelyn.risk.postgres import PostgresRiskSnapshotStore, PostgresRiskStore

    risk_store = await PostgresRiskStore.connect(PG_URL)
    snapshot_store = await PostgresRiskSnapshotStore.connect(PG_URL)
    async with risk_store._pool.acquire() as conn:
        await conn.execute("TRUNCATE aq_risk_snapshot, aq_risk RESTART IDENTITY")
    try:
        yield RiskPersistence(
            kind="postgres",
            risk_store=risk_store,
            snapshot_store=snapshot_store,
        )
    finally:
        await snapshot_store.close()
        await risk_store.close()


def _risk(
    *,
    risk_id: str = "risk:r3",
    tenant_id: str | None = None,
    correlation_key: str = "risk:r3:key",
    score: float = 30.0,
    band: str = "within_appetite",
    lifecycle: str = "identified",
    version: int = 1,
    first_seen_at: datetime = NOW,
    last_scored_at: datetime = NOW,
) -> Risk:
    return Risk.model_validate(
        {
            "id": risk_id,
            "tenant_id": tenant_id,
            "correlation_key": correlation_key,
            "title": "Risk register test",
            "category": "governance",
            "likelihood": 0.4,
            "impact": 0.2,
            "score": score,
            "band": band,
            "signals": [
                {
                    "kind": "finding",
                    "ref_id": new_id("fnd"),
                    "weight": 0.5,
                    "evidence_id": new_id("evd"),
                }
            ],
            "affected_object_ids": [new_id("obj")],
            "lifecycle": lifecycle,
            "treatment": "none",
            "reason": "Risk store contract test.",
            "factors": {"likelihood": 0.4, "impact": 0.2},
            "first_seen_at": first_seen_at,
            "last_scored_at": last_scored_at,
            "version": version,
        }
    )


def _snapshot(
    *,
    snapshot_id: str | None = None,
    tenant_id: str | None = None,
    run_at: datetime = NOW,
    total: int = 1,
    exposure: float = 50.0,
) -> RiskSnapshot:
    return RiskSnapshot(
        id=snapshot_id or new_risk_snapshot_id(),
        tenant_id=tenant_id,
        run_at=run_at,
        total=total,
        band_counts={"within_appetite": 0, "elevated": total, "over_tolerance": 0},
        top_risks=["risk:r3"],
        overall_exposure=exposure,
    )


def _finding(*, asset_id: str, tenant_id: str | None = None) -> Finding:
    return Finding(
        id=new_id("fnd"),
        tenant_id=tenant_id,
        finding_type="exposure",
        schema_version=1,
        dedup_key=new_id("fnd"),
        title="Internet-exposed service",
        severity="high",
        severity_score=80.0,
        status="open",
        what_happened="A service is reachable from an untrusted network.",
        why_it_matters="Attackers can exploit the exposed service.",
        how_determined="Risk R3 acceptance test.",
        risk_of_inaction="The asset may be compromised.",
        evidence_ids=[new_id("evd")],
        affected_object_ids=[asset_id],
        remediation=Remediation(
            summary="Restrict the service.",
            steps=["Limit ingress to trusted networks."],
            difficulty="medium",
            expected_outcome="Exposure is reduced.",
        ),
        automation=Automation(eligibility="none"),
        confidence=0.8,
        source_engine="risk-r3-test",
        correlation_id="risk:assess:web",
        first_detected_at=NOW,
        last_detected_at=NOW,
    )


def _signal(asset_id: str) -> CorrelationSignal:
    return CorrelationSignal(
        kind="config",
        ref_id="drift-r3",
        correlation_key="risk:assess:web",
        title="Config drift on exposed service",
        category="config",
        weight=0.5,
        impact=0.4,
        affected_object_ids=[asset_id],
        reason="Config drift contributes to the exposed-service risk.",
        observed_at=NOW,
    )


class _MissionEngine:
    def __init__(self, mission_id: str, impact_score: float) -> None:
        self.mission_id = mission_id
        self.impact_score = impact_score
        self.calls: list[str] = []

    async def mission_impact(self, object_id: str) -> MissionImpactResult:
        self.calls.append(object_id)
        mission = MissionView(
            id=self.mission_id,
            display_name="Critical mission",
            criticality_tier=1,
            criticality_weight=self.impact_score,
            reason="Test mission impact.",
        )
        return MissionImpactResult(
            impacts=[
                MissionImpact(
                    mission=mission,
                    impact_score=self.impact_score,
                    via=Path(node_ids=[object_id, self.mission_id], edges=[], length=1),
                    source_object_id=object_id,
                    reason="Mission depends on the affected object.",
                )
            ]
        )


async def test_risk_store_contract(risk_store: RiskStore) -> None:
    first_seen = NOW - timedelta(days=1)
    created = await risk_store.upsert(
        _risk(
            risk_id="risk:first",
            tenant_id=TENANT_A,
            correlation_key="risk:contract",
            first_seen_at=first_seen,
        )
    )
    assert created.version == 1

    changed = created.model_copy(
        update={
            "id": "risk:different-id-is-ignored",
            "score": 80.0,
            "band": "over_tolerance",
            "lifecycle": "assessed",
            "last_scored_at": NOW,
            "reason": "Updated risk score.",
        },
        deep=True,
    )
    updated = await risk_store.upsert(changed)

    assert updated.id == created.id
    assert updated.version == 2
    assert updated.first_seen_at == first_seen
    assert updated.score == 80.0
    assert await risk_store.get(created.id) == updated
    with pytest.raises(OptimisticConcurrencyConflict):
        await risk_store.upsert(changed)

    await risk_store.upsert(
        _risk(
            risk_id="risk:tenant-b",
            tenant_id=TENANT_B,
            correlation_key="risk:contract-b",
            score=90.0,
            band="over_tolerance",
            lifecycle="assessed",
        )
    )
    assert [risk.id for risk in await risk_store.query(tenant_id=TENANT_A)] == [created.id]
    assert [
        risk.id
        for risk in await risk_store.query(
            tenant_id=TENANT_B,
            band=("over_tolerance",),
            lifecycle=("assessed",),
        )
    ] == ["risk:tenant-b"]


async def test_risk_snapshot_contract(risk_snapshot_store: RiskSnapshotStore) -> None:
    first = await risk_snapshot_store.put(
        _snapshot(snapshot_id="risk-snapshot-first", tenant_id=TENANT_A, run_at=NOW)
    )
    second = await risk_snapshot_store.put(
        _snapshot(
            snapshot_id="risk-snapshot-second",
            tenant_id=TENANT_A,
            run_at=NOW + timedelta(minutes=5),
            exposure=75.0,
        )
    )
    await risk_snapshot_store.put(
        _snapshot(snapshot_id="risk-snapshot-other-tenant", tenant_id=TENANT_B, exposure=95.0)
    )

    assert await risk_snapshot_store.get(first.id) == first
    assert await risk_snapshot_store.latest(tenant_id=TENANT_A) == second
    assert await risk_snapshot_store.history(tenant_id=TENANT_A, since=NOW) == [
        first,
        second,
    ]
    with pytest.raises(OptimisticConcurrencyConflict):
        await risk_snapshot_store.put(first)


async def test_risk_assess_upsert_snapshot(risk_persistence: RiskPersistence) -> None:
    finding_store = InMemoryFindingStore()
    asset_id = new_id("obj")
    mission_id = new_id("obj")
    await finding_store.raise_finding(_finding(asset_id=asset_id))
    mission = _MissionEngine(mission_id, 0.9)
    engine = RiskIntelligenceEngine(
        finding_store,
        risk_persistence.risk_store,
        risk_persistence.snapshot_store,
        config=RiskConfig(),
        mission_engine=mission,
        clock=lambda: NOW,
    )

    first = await engine.assess(tenant_id=None, signals=[_signal(asset_id)])
    second = await engine.assess(tenant_id=None, signals=[_signal(asset_id)])
    risks = await risk_persistence.risk_store.query(tenant_id=None)

    assert len(risks) == 1
    [risk] = risks
    assert risk.version == 2
    assert risk.lifecycle == "assessed"
    assert risk.score == 95.0
    assert risk.band == "over_tolerance"
    assert risk.top_mission_id == mission_id
    assert mission.calls == [asset_id, asset_id]
    assert first.total == 1
    assert first.band_counts["over_tolerance"] == 1
    assert second.total == 1
    assert await risk_persistence.snapshot_store.latest(tenant_id=None) == second


async def test_risk_trend(risk_persistence: RiskPersistence) -> None:
    engine = RiskIntelligenceEngine(
        InMemoryFindingStore(),
        risk_persistence.risk_store,
        risk_persistence.snapshot_store,
        clock=lambda: NOW,
    )
    first = await risk_persistence.snapshot_store.put(
        _snapshot(snapshot_id="risk-snapshot-trend-1", run_at=NOW, exposure=25.0)
    )
    second = await risk_persistence.snapshot_store.put(
        _snapshot(
            snapshot_id="risk-snapshot-trend-2",
            run_at=NOW + timedelta(minutes=5),
            exposure=75.0,
        )
    )

    trend = await engine.trend(tenant_id=None, since=NOW)

    assert [point["snapshot_id"] for point in trend] == [first.id, second.id]
    assert [point["overall_exposure"] for point in trend] == [25.0, 75.0]
    assert trend[0]["band_counts"] == dict(first.band_counts)


async def test_risk_no_side_effects(risk_persistence: RiskPersistence) -> None:
    finding_store = InMemoryFindingStore()
    asset_id = new_id("obj")
    finding = await finding_store.raise_finding(_finding(asset_id=asset_id))
    unchanged = await finding_store.get(finding.id)
    assert unchanged is not None
    before = unchanged.model_dump(mode="json")
    engine = RiskIntelligenceEngine(
        finding_store,
        risk_persistence.risk_store,
        risk_persistence.snapshot_store,
        clock=lambda: NOW,
    )

    await engine.assess(tenant_id=None, signals=[_signal(asset_id)])
    still_unchanged = await finding_store.get(finding.id)
    assert still_unchanged is not None
    after = still_unchanged.model_dump(mode="json")

    assert after == before
