"""V4 acceptance tests for assessment, coverage, findings, remediation, and trends."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol, cast

import pytest

from aqelyn.conventions import ActorRef, new_id
from aqelyn.conventions.errors import CoverageUnavailable
from aqelyn.exposure import AssetRef
from aqelyn.findings import Finding, FindingQuery
from aqelyn.forecast import BasisRef, TrendRecord
from aqelyn.graph import Path
from aqelyn.mission import MissionImpact, MissionImpactResult, MissionView
from aqelyn.vuln import (
    CarriedScore,
    CoverageReport,
    InMemoryVulnerabilityStore,
    PostgresVulnerabilityStore,
    PriorityFactor,
    VulnBasis,
    VulnerabilityIntelligenceEngine,
    VulnerabilityRecord,
    VulnerabilityStore,
)

PG_URL = os.getenv("AQELYN_DATABASE_URL")
NOW = datetime(2026, 7, 17, 18, 0, tzinfo=UTC)
TENANT = "018f0000-0000-7000-8000-000000240401"
ACTOR = ActorRef(actor_type="user", actor_id="analyst@example.com")


class _Closable(Protocol):
    async def close(self) -> None: ...


@dataclass
class StoreHarness:
    kind: str
    store: VulnerabilityStore


class _CoverageSpy:
    def __init__(
        self,
        report: CoverageReport | None,
        events: list[str],
        *,
        unavailable: bool = False,
    ) -> None:
        self.report = report
        self.events = events
        self.unavailable = unavailable
        self.calls: list[str | None] = []

    async def coverage(self, *, tenant_id: str | None) -> CoverageReport:
        self.events.append("coverage")
        self.calls.append(tenant_id)
        if self.unavailable or self.report is None:
            raise CoverageUnavailable("coverage source unavailable")
        return self.report


class _OwnerSpies:
    def __init__(self, events: list[str], *, fail: bool = False) -> None:
        self.events = events
        self.fail = fail

    async def exploitation_factor(self, vulnerability: VulnerabilityRecord) -> PriorityFactor:
        self.events.append(f"threat:{vulnerability.id}")
        if self.fail:
            raise RuntimeError("threat owner unavailable")
        return PriorityFactor(0.9, "threat:tif:known-exploited", "EA-0014 exploitation.")

    async def reachability_factor(self, vulnerability: VulnerabilityRecord) -> PriorityFactor:
        self.events.append(f"exposure:{vulnerability.id}")
        return PriorityFactor(0.8, "exposure:external", "EA-0023 reachability.")

    async def mission_impact(self, object_id: str) -> MissionImpactResult:
        self.events.append(f"mission:{object_id}")
        mission_id = new_id("obj")
        return MissionImpactResult(
            impacts=[
                MissionImpact(
                    mission=MissionView(
                        id=mission_id,
                        display_name="Payments",
                        criticality_tier=1,
                        criticality_weight=1.0,
                        reason="Tier-1 mission.",
                    ),
                    impact_score=0.7,
                    via=Path(node_ids=[object_id, mission_id], length=1),
                    source_object_id=object_id,
                    reason="Mission impact from EA-0007.",
                )
            ],
            truncated=False,
        )

    async def blocking_factor(self, vulnerability: VulnerabilityRecord) -> PriorityFactor:
        self.events.append(f"baseline:{vulnerability.id}")
        return PriorityFactor(0.1, "baseline:cis", "EA-0012 partial blocking.")

    async def scanner_trust(self, vulnerability: VulnerabilityRecord) -> PriorityFactor:
        self.events.append(f"trust:{vulnerability.id}")
        return PriorityFactor(0.6, "trust:scanner:nessus", "EA-0006 scanner trust.")


class _FindingSpy:
    def __init__(self) -> None:
        self.raised: list[Finding] = []

    async def raise_finding(self, f: Finding) -> Finding:
        self.raised.append(f)
        return f

    async def get(self, finding_id: str) -> Finding | None:
        for finding in self.raised:
            if finding.id == finding_id:
                return finding
        return None

    async def query(self, q: FindingQuery) -> tuple[list[Finding], str | None]:
        return (list(self.raised[: q.limit]), None)

    async def transition(
        self,
        finding_id: str,
        to_status: str,
        *,
        by: ActorRef,
        note: str | None,
        expected_version: int,
    ) -> Finding:
        raise AssertionError("vulnerability V4 must not transition findings")

    async def add_evidence(
        self,
        finding_id: str,
        evidence_ids: list[str],
        *,
        by: ActorRef,
        expected_version: int,
    ) -> Finding:
        raise AssertionError("vulnerability V4 must not mutate findings")


class _TrendSpy:
    def __init__(self, trend: TrendRecord) -> None:
        self.trend = trend
        self.calls: list[tuple[str, int, str | None]] = []

    async def analyze_trend(
        self, *, metric: str, window_days: int, tenant_id: str | None
    ) -> TrendRecord:
        self.calls.append((metric, window_days, tenant_id))
        return self.trend


async def _store(kind: str) -> AsyncIterator[StoreHarness]:
    if kind == "inmemory":
        yield StoreHarness(kind="inmemory", store=InMemoryVulnerabilityStore(mode="enterprise"))
        return
    if not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")
    store = await PostgresVulnerabilityStore.connect(PG_URL, mode="enterprise")
    async with store._pool.acquire() as conn:
        await conn.execute("TRUNCATE aq_vuln_history, aq_vuln_record")
    try:
        yield StoreHarness(kind="postgres", store=store)
    finally:
        await cast(_Closable, store).close()


def _coverage(
    *,
    scanned: list[str],
    unscanned: list[str] | None = None,
    stale: list[str] | None = None,
) -> CoverageReport:
    return CoverageReport(
        scanned=scanned,
        unscanned=unscanned or [],
        stale=stale or [],
        computed_at=NOW,
    )


def _record(*, asset_id: str | None = None, confidence: float = 0.6) -> VulnerabilityRecord:
    selected_asset = asset_id or new_id("obj")
    return VulnerabilityRecord(
        tenant_id=TENANT,
        cve_id="CVE-2026-4242",
        scanner="nessus",
        asset_ref=AssetRef(kind="asset", ref_id=selected_asset, evidence_id=new_id("evd")),
        severity="high",
        cvss=CarriedScore(
            source="nvd:cve-2026-4242",
            value=9.8,
            vector="CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H",
            as_of=NOW,
        ),
        epss=CarriedScore(source="first:epss:2026-07-17", value=0.73, as_of=NOW),
        confidence=confidence,
        basis=[
            VulnBasis(
                kind="scanner",
                ref="scanner:nessus:run-42",
                as_of=NOW,
                evidence_id=new_id("evd"),
            )
        ],
        discovered_at=NOW,
    )


def _engine(
    store: VulnerabilityStore,
    *,
    coverage: _CoverageSpy,
    owners: _OwnerSpies,
    findings: _FindingSpy | None = None,
    trend: _TrendSpy | None = None,
) -> VulnerabilityIntelligenceEngine:
    return VulnerabilityIntelligenceEngine(
        store,
        threat_provider=owners,
        exposure_provider=owners,
        mission_provider=owners,
        baseline_provider=owners,
        trust_provider=owners,
        coverage_provider=coverage,
        finding_store=findings,
        trend_provider=trend,
    )


@pytest.mark.parametrize("kind", ["inmemory", "postgres"])
async def test_vuln_coverage_mandatory(kind: str) -> None:
    async for harness in _store(kind):
        events: list[str] = []
        saved = await harness.store.put(_record())
        coverage = _CoverageSpy(_coverage(scanned=[saved.asset_ref.ref_id]), events)
        engine = _engine(harness.store, coverage=coverage, owners=_OwnerSpies(events))

        assessment = await engine.assess(tenant_id=TENANT)

        assert events[0] == "coverage"
        assert coverage.calls == [TENANT]
        assert assessment.coverage.scanned == [saved.asset_ref.ref_id]
        assert len(assessment.priorities) == 1
        assert assessment.degraded is False
        assert assessment.unavailable == []


@pytest.mark.parametrize("kind", ["inmemory", "postgres"])
async def test_vuln_coverage_unavailable_refuses(kind: str) -> None:
    async for harness in _store(kind):
        events: list[str] = []
        saved = await harness.store.put(_record())
        coverage = _CoverageSpy(None, events, unavailable=True)
        engine = _engine(harness.store, coverage=coverage, owners=_OwnerSpies(events))

        with pytest.raises(CoverageUnavailable):
            await engine.assess(tenant_id=TENANT)

        assert events == ["coverage"]
        assert [row.id for row in await harness.store.query(tenant_id=TENANT)] == [saved.id]


@pytest.mark.parametrize("kind", ["inmemory", "postgres"])
async def test_vuln_unknown_not_clean(kind: str) -> None:
    async for harness in _store(kind):
        events: list[str] = []
        unscanned = new_id("obj")
        stale = new_id("obj")
        coverage = _CoverageSpy(
            _coverage(scanned=[], unscanned=[unscanned], stale=[stale]),
            events,
        )
        engine = _engine(harness.store, coverage=coverage, owners=_OwnerSpies(events))

        assessment = await engine.assess(tenant_id=TENANT)

        assert assessment.coverage.scanned == []
        assert assessment.coverage.unscanned == [unscanned]
        assert assessment.coverage.stale == [stale]
        assert assessment.priorities == []
        assert unscanned not in assessment.coverage.scanned
        assert stale not in assessment.coverage.scanned


@pytest.mark.parametrize("kind", ["inmemory", "postgres"])
async def test_vuln_failure_not_faked(kind: str) -> None:
    async for harness in _store(kind):
        events: list[str] = []
        saved = await harness.store.put(_record())
        engine = _engine(
            harness.store,
            coverage=_CoverageSpy(_coverage(scanned=[saved.asset_ref.ref_id]), events),
            owners=_OwnerSpies(events, fail=True),
        )

        assessment = await engine.assess(tenant_id=TENANT)

        assert assessment.priorities == []
        assert assessment.degraded is True
        assert assessment.unavailable == [
            {"vulnerability_id": saved.id, "reason": "threat owner unavailable"}
        ]
        assert "threat" in events[1]


async def test_vuln_remediation_advisory_only() -> None:
    store = InMemoryVulnerabilityStore(mode="enterprise")
    events: list[str] = []
    saved = await store.put(_record())
    engine = _engine(
        store,
        coverage=_CoverageSpy(_coverage(scanned=[saved.asset_ref.ref_id]), events),
        owners=_OwnerSpies(events),
    )
    priority = await engine.prioritize(saved.id, tenant_id=TENANT)

    plan = await engine.recommend(priority, tenant_id=TENANT)

    assert plan.vulnerability_id == priority.vulnerability_id
    assert plan.priority == priority.priority
    assert plan.proposed_campaign["requires_workflow"] is True
    assert plan.proposed_campaign["kind"] == "ea0018_response_campaign_proposal"
    assert not hasattr(engine, "scan")
    assert not hasattr(engine, "patch")
    assert not hasattr(engine, "execute")


async def test_vuln_raise_finding_path() -> None:
    store = InMemoryVulnerabilityStore(mode="enterprise")
    events: list[str] = []
    findings = _FindingSpy()
    saved = await store.put(_record())
    engine = _engine(
        store,
        coverage=_CoverageSpy(_coverage(scanned=[saved.asset_ref.ref_id]), events),
        owners=_OwnerSpies(events),
        findings=findings,
    )
    priority = await engine.prioritize(saved.id, tenant_id=TENANT)

    finding = await engine.raise_vulnerability(priority, by=ACTOR)

    assert findings.raised == [finding]
    assert finding.finding_type == "vulnerability.priority"
    assert finding.source_engine == "vuln_engine"
    assert finding.evidence_ids == [saved.basis[0].evidence_id, saved.asset_ref.evidence_id]
    assert finding.affected_object_ids == [saved.asset_ref.ref_id]
    assert finding.automation.eligibility == "none"
    assert finding.automation.action_ref is None
    assert finding.automation.requires_approval is True


async def test_vuln_trend_delegates_forecast() -> None:
    store = InMemoryVulnerabilityStore(mode="enterprise")
    events: list[str] = []
    trend = TrendRecord(
        tenant_id=TENANT,
        metric="vulnerabilities.open",
        window_days=30,
        slope=1.5,
        r_squared=0.8,
        direction="up",
        basis=[
            BasisRef(
                kind="metric",
                ref="vulnerabilities.open",
                window={"days": 30},
                evidence_id=new_id("evd"),
            )
        ],
        reason="Forecast engine detected an upward vulnerability trend.",
    )
    trend_spy = _TrendSpy(trend)
    engine = _engine(
        store,
        coverage=_CoverageSpy(_coverage(scanned=[]), events),
        owners=_OwnerSpies(events),
        trend=trend_spy,
    )

    observed = await engine.trend(
        metric="vulnerabilities.open",
        window_days=30,
        tenant_id=TENANT,
    )

    assert observed == trend
    assert trend_spy.calls == [("vulnerabilities.open", 30, TENANT)]
