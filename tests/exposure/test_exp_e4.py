"""E4 acceptance tests for exposure scoring, findings, and advisory-only behavior."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

import pytest

from aqelyn.conventions import ActorRef, new_id
from aqelyn.conventions.errors import ExposureNotReplayable
from aqelyn.decision import replay
from aqelyn.events import Subject
from aqelyn.evidence import EvidenceRecord
from aqelyn.exposure import (
    AssetRef,
    ExposureBasis,
    ExposureRecord,
    InMemoryExposureStore,
    KnownDataExposureEngine,
    StaticKnownSurfaceSource,
    validate_replayable_exposure,
)
from aqelyn.findings import Finding, FindingQuery
from aqelyn.graph import Path
from aqelyn.mission import MissionImpact, MissionImpactResult, MissionView
from aqelyn.trust import TrustAssessment

NOW = datetime(2026, 7, 16, 23, 0, tzinfo=UTC)
TENANT = "018f0000-0000-7000-8000-000000230401"
SYS = ActorRef(actor_type="system", actor_id="exposure-e4-test")


class _EvidenceLookup:
    def __init__(self, records: list[EvidenceRecord]) -> None:
        self.records = {record.id: record for record in records}
        self.calls: list[tuple[str, ActorRef]] = []

    async def get(self, evidence_id: str, *, actor: ActorRef) -> EvidenceRecord:
        self.calls.append((evidence_id, actor))
        return self.records[evidence_id]


class _TrustSpy:
    def __init__(self, assessment: TrustAssessment) -> None:
        self.assessment = assessment
        self.calls: list[tuple[str, list[str], datetime | None]] = []

    async def assess(
        self,
        subject_ref: str,
        evidence: Sequence[EvidenceRecord],
        *,
        now: datetime | None = None,
    ) -> TrustAssessment:
        self.calls.append((subject_ref, [record.id for record in evidence], now))
        return self.assessment


class _MissionSpy:
    def __init__(self, result: MissionImpactResult) -> None:
        self.result = result
        self.calls: list[str] = []

    async def mission_impact(self, object_id: str) -> MissionImpactResult:
        self.calls.append(object_id)
        return self.result


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
        raise AssertionError("exposure E4 must not transition findings")

    async def add_evidence(
        self,
        finding_id: str,
        evidence_ids: list[str],
        *,
        by: ActorRef,
        expected_version: int,
    ) -> Finding:
        raise AssertionError("exposure E4 must not mutate findings")


def _evidence(evidence_id: str | None = None) -> EvidenceRecord:
    return EvidenceRecord(
        id=evidence_id or new_id("evd"),
        tenant_id=TENANT,
        evidence_type="exposure.known_data",
        schema_version=1,
        subject=Subject(object_ids=[new_id("obj")]),
        collected_at=NOW,
        recorded_at=NOW,
        collector=SYS,
        source_id=new_id("src"),
        method="known-data",
        content={"reachability": "external"},
        content_hash="sha256:exposure-e4",
        confidence=0.9,
        seq=1,
        prev_hash=None,
        record_hash="sha256:record",
    )


def _basis(evidence_id: str) -> ExposureBasis:
    return ExposureBasis(
        kind="inventory",
        ref="inventory:external-service",
        as_of=NOW,
        evidence_id=evidence_id,
    )


def _exposure(asset_id: str, evidence_id: str) -> ExposureRecord:
    return ExposureRecord(
        tenant_id=TENANT,
        asset_ref=AssetRef(kind="asset", ref_id=asset_id, evidence_id=evidence_id),
        exposure_type="reachable_service",
        reachability="external",
        basis=[_basis(evidence_id)],
        rationale="Reachability is derived from known inventory.",
        flagged=False,
        discovered_at=NOW,
    )


def _trust(evidence_id: str) -> TrustAssessment:
    return TrustAssessment(
        subject_ref="exposure:pending",
        score=0.8,
        level="high",
        method="noisy_or/v1",
        contributions=[],
        reason=f"Evidence {evidence_id} is trusted.",
        no_evidence=False,
        computed_at=NOW,
    )


def _mission(asset_id: str) -> MissionImpactResult:
    mission_id = new_id("obj")
    return MissionImpactResult(
        impacts=[
            MissionImpact(
                mission=MissionView(
                    id=mission_id,
                    display_name="Customer portal",
                    criticality_tier=1,
                    criticality_weight=1.0,
                    reason="Tier-1 mission.",
                ),
                impact_score=0.8,
                via=Path(node_ids=[asset_id, mission_id], length=1),
                source_object_id=asset_id,
                reason="The exposed asset supports a customer-facing mission.",
            )
        ],
        truncated=False,
    )


async def test_exp_score_composes_trust_mission_risk_derivation() -> None:
    evidence = _evidence()
    asset_id = new_id("obj")
    trust = _TrustSpy(_trust(evidence.id))
    mission = _MissionSpy(_mission(asset_id))
    engine = KnownDataExposureEngine(
        InMemoryExposureStore(mode="enterprise"),
        StaticKnownSurfaceSource([]),
        evidence_lookup=_EvidenceLookup([evidence]),
        trust_provider=trust,
        mission_provider=mission,
    )

    scored = await engine.score_exposure(_exposure(asset_id, evidence.id))

    assert trust.calls == [(f"exposure:{scored.id}", [evidence.id], NOW)]
    assert mission.calls == [asset_id]
    assert scored.confidence == 0.8
    assert scored.score == 90.0
    assert scored.derivation is not None
    assert replay(scored.derivation) == scored.derivation.result
    assert {claim.kind for claim in scored.derivation.inputs} == {"trust", "mission", "risk"}
    assert "EA-0013 risk band" in scored.rationale


async def test_exp_score_replay_mismatch_rejected() -> None:
    evidence = _evidence()
    asset_id = new_id("obj")
    engine = KnownDataExposureEngine(
        InMemoryExposureStore(mode="enterprise"),
        StaticKnownSurfaceSource([]),
        evidence_lookup=_EvidenceLookup([evidence]),
        trust_provider=_TrustSpy(_trust(evidence.id)),
        mission_provider=_MissionSpy(_mission(asset_id)),
    )
    scored = await engine.score_exposure(_exposure(asset_id, evidence.id))
    assert scored.derivation is not None
    tampered = scored.derivation.model_copy(
        update={"result": {"items": [], "factor": 1.0}},
        deep=True,
    )

    with pytest.raises(ExposureNotReplayable):
        validate_replayable_exposure(scored.model_copy(update={"derivation": tampered}, deep=True))


async def test_exp_material_exposure_raises_finding_only() -> None:
    evidence = _evidence()
    asset_id = new_id("obj")
    findings = _FindingSpy()
    engine = KnownDataExposureEngine(
        InMemoryExposureStore(mode="enterprise"),
        StaticKnownSurfaceSource([]),
        evidence_lookup=_EvidenceLookup([evidence]),
        trust_provider=_TrustSpy(_trust(evidence.id)),
        mission_provider=_MissionSpy(_mission(asset_id)),
        finding_store=findings,
    )
    scored = await engine.score_exposure(_exposure(asset_id, evidence.id))

    finding = await engine.raise_exposure_finding(scored)

    assert findings.raised == [finding]
    assert finding.finding_type == "attack_surface_exposure"
    assert finding.evidence_ids == [evidence.id]
    assert finding.affected_object_ids == [asset_id]
    assert finding.automation.eligibility == "none"
    assert finding.automation.action_ref is None
    assert finding.source_engine == "exposure_engine"
    assert not hasattr(engine, "execute")
    assert not hasattr(engine, "propose")
