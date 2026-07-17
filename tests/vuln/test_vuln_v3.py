"""V3 acceptance tests for vulnerability prioritization composition."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol, cast

import pytest

from aqelyn.conventions import new_id
from aqelyn.conventions.errors import VulnNotReplayable
from aqelyn.decision import replay
from aqelyn.exposure import AssetRef
from aqelyn.graph import Path
from aqelyn.mission import MissionImpact, MissionImpactResult, MissionView
from aqelyn.vuln import (
    CarriedScore,
    InMemoryVulnerabilityStore,
    PostgresVulnerabilityStore,
    PriorityFactor,
    VulnBasis,
    VulnConfig,
    VulnerabilityIntelligenceEngine,
    VulnerabilityRecord,
    VulnerabilityStore,
    validate_replayable_priority,
)

PG_URL = os.getenv("AQELYN_DATABASE_URL")
NOW = datetime(2026, 7, 17, 16, 0, tzinfo=UTC)
TENANT = "018f0000-0000-7000-8000-000000240301"


class _Closable(Protocol):
    async def close(self) -> None: ...


@dataclass
class StoreHarness:
    kind: str
    store: VulnerabilityStore


class _OwnerSpies:
    def __init__(
        self,
        *,
        threat: float = 0.9,
        exposure: float = 0.8,
        mission: float = 0.7,
        baseline_blocked: float = 0.25,
        trust: float = 0.6,
    ) -> None:
        self.threat = threat
        self.exposure = exposure
        self.mission = mission
        self.baseline_blocked = baseline_blocked
        self.trust = trust
        self.threat_calls: list[str] = []
        self.exposure_calls: list[str] = []
        self.mission_calls: list[str] = []
        self.baseline_calls: list[str] = []
        self.trust_calls: list[str] = []

    async def exploitation_factor(self, vulnerability: VulnerabilityRecord) -> PriorityFactor:
        self.threat_calls.append(vulnerability.id)
        return PriorityFactor(
            self.threat,
            "threat:tif:known-exploited",
            "EA-0014 reports active exploitation.",
        )

    async def reachability_factor(self, vulnerability: VulnerabilityRecord) -> PriorityFactor:
        self.exposure_calls.append(vulnerability.id)
        return PriorityFactor(
            self.exposure,
            "exposure:external:path",
            "EA-0023 reports reachable external exposure.",
        )

    async def mission_impact(self, object_id: str) -> MissionImpactResult:
        self.mission_calls.append(object_id)
        mission_id = new_id("obj")
        return MissionImpactResult(
            impacts=[
                MissionImpact(
                    mission=MissionView(
                        id=mission_id,
                        display_name="Payments",
                        criticality_tier=1,
                        criticality_weight=1.0,
                        reason="Tier-1 customer payments mission.",
                    ),
                    impact_score=self.mission,
                    via=Path(node_ids=[object_id, mission_id], length=1),
                    source_object_id=object_id,
                    reason="EA-0007 reports the vulnerable asset supports payments.",
                )
            ],
            truncated=False,
        )

    async def blocking_factor(self, vulnerability: VulnerabilityRecord) -> PriorityFactor:
        self.baseline_calls.append(vulnerability.id)
        return PriorityFactor(
            self.baseline_blocked,
            "baseline:cis:compensating-control",
            "EA-0012 reports a compensating control is partially blocking the path.",
        )

    async def scanner_trust(self, vulnerability: VulnerabilityRecord) -> PriorityFactor:
        self.trust_calls.append(vulnerability.id)
        return PriorityFactor(
            self.trust,
            f"trust:scanner:{vulnerability.scanner}",
            "EA-0006 scanner reliability assessment.",
        )


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


def _record(
    *,
    asset_id: str | None = None,
    severity: str = "high",
    cvss_value: float = 9.8,
    epss_value: float | None = 0.73,
    confidence: float = 0.6,
) -> VulnerabilityRecord:
    selected_asset = asset_id or new_id("obj")
    epss = (
        None
        if epss_value is None
        else CarriedScore(source="first:epss:2026-07-17", value=epss_value, as_of=NOW)
    )
    return VulnerabilityRecord(
        tenant_id=TENANT,
        cve_id="CVE-2026-4242",
        scanner="nessus",
        asset_ref=AssetRef(kind="asset", ref_id=selected_asset, evidence_id=new_id("evd")),
        severity=severity,
        cvss=CarriedScore(
            source="nvd:cve-2026-4242",
            value=cvss_value,
            vector="CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H",
            as_of=NOW,
        ),
        epss=epss,
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


def _engine(store: VulnerabilityStore, owners: _OwnerSpies) -> VulnerabilityIntelligenceEngine:
    return VulnerabilityIntelligenceEngine(
        store,
        threat_provider=owners,
        exposure_provider=owners,
        mission_provider=owners,
        baseline_provider=owners,
        trust_provider=owners,
    )


@pytest.mark.parametrize("kind", ["inmemory", "postgres"])
async def test_vuln_priority_replayable(kind: str) -> None:
    async for harness in _store(kind):
        owners = _OwnerSpies()
        saved = await harness.store.put(_record())
        engine = _engine(harness.store, owners)

        priority = await engine.prioritize(saved.id, tenant_id=TENANT)

        assert priority.score == pytest.approx(81.65)
        assert priority.priority == "high"
        assert priority.confidence == 0.6
        assert replay(priority.derivation) == priority.derivation.result
        assert max(item["score"] for item in priority.derivation.result["items"]) == pytest.approx(
            priority.score / 100.0
        )
        assert priority.derivation.steps[1].params["factor_sources"] == priority.factors
        assert set(priority.factors) == {
            "cvss",
            "epss",
            "threat",
            "exposure",
            "mission",
            "baseline",
            "trust",
        }


@pytest.mark.parametrize("kind", ["inmemory", "postgres"])
async def test_vuln_priority_replay_mismatch(kind: str) -> None:
    async for harness in _store(kind):
        saved = await harness.store.put(_record())
        priority = await _engine(harness.store, _OwnerSpies()).prioritize(
            saved.id, tenant_id=TENANT
        )
        tampered = priority.derivation.model_copy(
            update={"result": {"items": [], "factor": 1.0}},
            deep=True,
        )

        with pytest.raises(VulnNotReplayable):
            validate_replayable_priority(
                priority.model_copy(update={"derivation": tampered}, deep=True)
            )


@pytest.mark.parametrize("kind", ["inmemory", "postgres"])
async def test_vuln_factors_from_owners(kind: str) -> None:
    async for harness in _store(kind):
        owners = _OwnerSpies()
        saved = await harness.store.put(_record())

        priority = await _engine(harness.store, owners).prioritize(saved.id, tenant_id=TENANT)

        assert owners.threat_calls == [saved.id]
        assert owners.exposure_calls == [saved.id]
        assert owners.mission_calls == [saved.asset_ref.ref_id]
        assert owners.baseline_calls == [saved.id]
        assert owners.trust_calls == [saved.id]
        assert priority.factors["threat"]["source"] == "threat:tif:known-exploited"
        assert priority.factors["exposure"]["source"] == "exposure:external:path"
        assert priority.factors["baseline"]["value"] == 0.75
        assert "EA-0012 blocking factor" in priority.factors["baseline"]["reason"]
        assert priority.factors["trust"]["source"] == "trust:scanner:nessus"


@pytest.mark.parametrize("kind", ["inmemory", "postgres"])
async def test_vuln_cvss_carried_not_recomputed(kind: str) -> None:
    async for harness in _store(kind):
        saved = await harness.store.put(
            _record(severity="none", cvss_value=10.0, epss_value=None, confidence=0.2)
        )
        owners = _OwnerSpies(threat=0.0, exposure=0.0, mission=0.0, baseline_blocked=1.0, trust=0.0)
        engine = VulnerabilityIntelligenceEngine(
            harness.store,
            config=VulnConfig(score_weights={"cvss": 1.0}),
            threat_provider=owners,
            exposure_provider=owners,
            mission_provider=owners,
            baseline_provider=owners,
            trust_provider=owners,
        )

        priority = await engine.prioritize(saved.id, tenant_id=TENANT)

        assert saved.severity == "none"
        assert priority.score == 100.0
        assert priority.factors["cvss"]["value"] == 1.0
        assert priority.factors["cvss"]["carried_value"] == 10.0
        assert priority.factors["cvss"]["source"] == "nvd:cve-2026-4242"
        assert "carried verbatim" in priority.factors["cvss"]["reason"]
