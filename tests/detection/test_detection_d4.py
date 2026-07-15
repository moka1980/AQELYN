"""D4 acceptance tests for detection correlation, findings, and projections."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest

from aqelyn.conventions import ActorRef, new_id
from aqelyn.conventions.errors import EvidenceNotFound
from aqelyn.detection import (
    InMemoryProfileStore,
    InMemoryRuleStore,
    SignalRef,
    ThreatDetection,
    ThreatDetectionEngine,
)
from aqelyn.evidence import EvidenceRecord, EvidenceStore, InMemoryEvidenceStore
from aqelyn.findings import Finding, FindingStore, InMemoryFindingStore
from aqelyn.objects import SourceRef
from aqelyn.threat.models import ThreatIndicator

PG_URL = os.getenv("AQELYN_DATABASE_URL")
TENANT_A = "018f0000-0000-7000-8000-000000001741"
TENANT_B = "018f0000-0000-7000-8000-000000001742"
NOW = datetime(2026, 7, 15, 18, 0, tzinfo=UTC)
ACTOR = ActorRef(actor_type="system", actor_id="detection-d4-test")


@dataclass
class D4Harness:
    kind: str
    evidence_store: EvidenceStore
    finding_store: FindingStore


@pytest.fixture(params=["inmemory", "postgres"], ids=["inmemory", "postgres"])
async def d4_harness(request: pytest.FixtureRequest) -> AsyncIterator[D4Harness]:
    if request.param == "inmemory":
        evidence_store: EvidenceStore = InMemoryEvidenceStore(mode="enterprise")

        async def evidence_exists(evidence_id: str) -> bool:
            return await _evidence_exists(evidence_store, evidence_id)

        yield D4Harness(
            kind="inmemory",
            evidence_store=evidence_store,
            finding_store=InMemoryFindingStore(
                mode="enterprise",
                evidence_exists=evidence_exists,
            ),
        )
        return

    if not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")

    from aqelyn.evidence.postgres import PostgresEvidenceStore
    from aqelyn.findings.postgres import PostgresFindingStore

    evidence_store = await PostgresEvidenceStore.connect(PG_URL, mode="enterprise")

    async def postgres_evidence_exists(evidence_id: str) -> bool:
        return await _evidence_exists(evidence_store, evidence_id)

    finding_store = await PostgresFindingStore.connect(
        PG_URL,
        mode="enterprise",
        evidence_exists=postgres_evidence_exists,
    )
    async with evidence_store._pool.acquire() as conn:
        await conn.execute(
            "TRUNCATE aq_finding_audit, aq_finding_evidence, aq_finding_asset, aq_finding, "
            "aq_evidence_custody, aq_evidence_package, aq_evidence RESTART IDENTITY CASCADE"
        )
    try:
        yield D4Harness(
            kind="postgres",
            evidence_store=evidence_store,
            finding_store=finding_store,
        )
    finally:
        await finding_store.close()
        await evidence_store.close()


async def test_det_correlate_not_incidents() -> None:
    engine = _engine()
    first = _detection(subject_ref="acct:alice", confidence=0.35, evidence_id=new_id("evd"))
    second = _detection(subject_ref="acct:alice", confidence=0.55, evidence_id=new_id("evd"))

    [correlated] = await engine.correlate_signals([first, second], tenant_id=TENANT_A)

    assert isinstance(correlated, ThreatDetection)
    assert correlated.subject_ref == "acct:alice"
    assert correlated.confidence == 0.55
    assert len(correlated.signal_refs) == 2
    assert "SOC owns incident correlation" in correlated.reason

    source = (
        Path(__file__).resolve().parents[2] / "src" / "aqelyn" / "detection" / "engine.py"
    ).read_text(encoding="utf-8")
    assert "aqelyn.soc" not in source
    assert "Incident" not in source
    assert "Alert" not in source


async def test_det_attack_mapping() -> None:
    indicator = _indicator(ttps=["T1046", "T1078"])
    detection = _detection(
        techniques=["T1059"],
        signal_refs=[
            SignalRef(
                source_type="threat_indicator",
                source_id=indicator.id,
                evidence_id=new_id("evd"),
                observed_at=NOW,
            )
        ],
    )
    engine = _engine(threat_indicators={indicator.id: indicator})

    techniques = await engine.map_techniques(detection)

    assert techniques == ["T1046", "T1059", "T1078"]
    source = (
        Path(__file__).resolve().parents[2] / "src" / "aqelyn" / "detection" / "engine.py"
    ).read_text(encoding="utf-8")
    assert "indicator.ttps" in source


async def test_det_findings_no_action(d4_harness: D4Harness) -> None:
    engine = _engine(
        evidence_store=d4_harness.evidence_store,
        finding_store=d4_harness.finding_store,
    )
    detection = _detection(subject_ref=new_id("obj"), severity_score=82.0)

    [finding_id] = await engine.detections_to_findings([detection], by=ACTOR)

    finding = await _finding(d4_harness.finding_store, finding_id)
    assert finding.finding_type == "detection.threat"
    assert finding.source_engine == "detection_engine"
    assert finding.affected_object_ids == [detection.subject_ref]
    assert finding.automation.eligibility == "none"
    assert finding.automation.action_ref is None
    assert finding.automation.requires_approval is True
    assert finding.evidence_ids
    assert finding.expert_details is not None
    assert finding.expert_details["no_action"] is True
    evidence = await d4_harness.evidence_store.get(finding.evidence_ids[0], actor=ACTOR)
    assert evidence.evidence_type == "detection.threat"
    assert evidence.method == "detection.detections_to_findings/v1"
    assert evidence.content is not None
    assert evidence.content["pinned"]["rule_version"] == detection.rule_version
    assert evidence.content["pinned"]["profile_version"] == detection.profile_version
    assert (await d4_harness.evidence_store.verify(evidence.id)).ok is True


async def test_det_projection_advisory() -> None:
    evidence_store = InMemoryEvidenceStore(mode="enterprise")
    engine = _engine(evidence_store=evidence_store)

    projection = await engine.project(
        subject_ref="acct:alice",
        horizon_days=7,
        tenant_id=TENANT_A,
        basis={"recent_detections": 2},
        confidence=0.42,
    )

    assert projection.advisory is True
    assert projection.statement.endswith("not a finding and not evidence.")
    assert projection.basis == {"recent_detections": 2}
    assert projection.confidence == 0.42
    assert evidence_store._by_id == {}
    assert not isinstance(projection, Finding)
    assert not isinstance(projection, EvidenceRecord)


async def test_det_no_network_no_side_effects() -> None:
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (Path(__file__).resolve().parents[2] / "src" / "aqelyn" / "detection").glob(
            "*.py"
        )
    )
    for forbidden in (
        "socket",
        "httpx",
        "requests",
        "urllib",
        "paramiko",
        "subprocess",
        "open_connection",
        "aqelyn.workflow",
        "WorkflowEngine",
        "workflow_engine",
    ):
        assert forbidden not in source


async def test_det_tenant_and_bounds() -> None:
    engine = _engine(config_batch_size=2)
    first = _detection(subject_ref="acct:alice", evidence_id=new_id("evd"))
    second = _detection(subject_ref="acct:bob", evidence_id=new_id("evd"))
    third = _detection(subject_ref="acct:carol", evidence_id=new_id("evd"))
    other_tenant = _detection(
        tenant_id=TENANT_B,
        subject_ref="acct:mallory",
        evidence_id=new_id("evd"),
    )

    correlated = await engine.correlate_signals(
        [first, second, third, other_tenant],
        tenant_id=TENANT_A,
    )

    assert [item.subject_ref for item in correlated] == ["acct:alice", "acct:bob"]
    assert all(item.tenant_id == TENANT_A for item in correlated)


def _engine(
    *,
    evidence_store: EvidenceStore | None = None,
    finding_store: FindingStore | None = None,
    threat_indicators: dict[str, ThreatIndicator] | None = None,
    config_batch_size: int = 100,
) -> ThreatDetectionEngine:
    from aqelyn.detection import DetectionConfig

    return ThreatDetectionEngine(
        rule_store=InMemoryRuleStore(),
        profile_store=InMemoryProfileStore(),
        evidence_store=evidence_store,
        finding_store=finding_store,
        threat_indicators=threat_indicators,
        source_id=new_id("src"),
        config=DetectionConfig(batch_size=config_batch_size),
    )


def _detection(
    *,
    tenant_id: str | None = TENANT_A,
    subject_ref: str = "acct:alice",
    rule_id: str = "rule-d4",
    rule_version: int = 3,
    profile_version: int | None = 2,
    confidence: float = 0.75,
    severity: str = "high",
    severity_score: float = 70.0,
    techniques: list[str] | None = None,
    evidence_id: str | None = None,
    signal_refs: list[SignalRef] | None = None,
) -> ThreatDetection:
    selected_evidence_id = evidence_id or new_id("evd")
    return ThreatDetection(
        tenant_id=tenant_id,
        rule_id=rule_id,
        rule_version=rule_version,
        subject_ref=subject_ref,
        kind="behavioral",
        signal_refs=signal_refs
        or [
            SignalRef(
                source_type="observation",
                source_id=f"{subject_ref}:logins:{NOW.isoformat()}",
                evidence_id=selected_evidence_id,
                observed_at=NOW,
            )
        ],
        anomaly=None,
        confidence=confidence,
        severity=severity,
        severity_score=severity_score,
        technique_ids=techniques or ["T1078"],
        evidence_id=selected_evidence_id,
        profile_version=profile_version,
        reason=f"{subject_ref} matched detection rule {rule_id}.",
        detected_at=NOW,
    )


def _indicator(*, ttps: list[str]) -> ThreatIndicator:
    return ThreatIndicator(
        id=new_id("obj"),
        tenant_id=TENANT_A,
        indicator_type="domain",
        value="evil.example",
        ttps=ttps,
        confidence=0.8,
        first_seen_at=NOW,
        last_seen_at=NOW,
        sources=[
            SourceRef(
                source_id=new_id("src"),
                evidence_id=new_id("evd"),
                observed_at=NOW,
                method="threat.feed_record/v1",
            )
        ],
    )


async def _evidence_exists(store: EvidenceStore, evidence_id: str) -> bool:
    try:
        await store.get(evidence_id, actor=ACTOR)
    except EvidenceNotFound:
        return False
    return True


async def _finding(store: FindingStore, finding_id: str) -> Finding:
    finding = await store.get(finding_id)
    assert finding is not None
    return finding
