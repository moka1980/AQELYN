"""R2 acceptance tests for Risk Intelligence correlation."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from aqelyn.conventions import new_id
from aqelyn.conventions.errors import RiskConfigInvalid
from aqelyn.findings import Automation, Finding, InMemoryFindingStore, Remediation
from aqelyn.findings.models import Status
from aqelyn.risk import CorrelationSignal, RiskCorrelator, explain

TENANT_A = "018f0000-0000-7000-8000-000000000101"
TENANT_B = "018f0000-0000-7000-8000-000000000102"
NOW = datetime(2026, 7, 14, 12, 0, tzinfo=UTC)


def _finding(
    *,
    tenant_id: str | None = None,
    correlation_id: str = "risk:shared-web-exposure",
    affected_object_ids: list[str] | None = None,
    severity_score: float = 80.0,
    confidence: float = 0.75,
    status: Status = "open",
    title: str = "Exposed service",
) -> Finding:
    return Finding(
        id=new_id("fnd"),
        tenant_id=tenant_id,
        finding_type="exposure",
        schema_version=1,
        dedup_key=new_id("fnd"),
        title=title,
        severity="high",
        severity_score=severity_score,
        status=status,
        what_happened="A service is reachable from an untrusted network.",
        why_it_matters="Attackers can probe and exploit the exposed surface.",
        how_determined="Risk correlation acceptance test.",
        risk_of_inaction="The service may be compromised.",
        evidence_ids=[new_id("evd")],
        affected_object_ids=affected_object_ids or [new_id("obj")],
        remediation=Remediation(
            summary="Restrict the exposed service.",
            steps=["Limit access to trusted networks."],
            difficulty="medium",
            expected_outcome="Exposure is reduced.",
        ),
        automation=Automation(eligibility="none"),
        confidence=confidence,
        source_engine="risk-r2-test",
        correlation_id=correlation_id,
        first_detected_at=NOW,
        last_detected_at=NOW,
    )


def _signal(
    *,
    kind: str = "config",
    tenant_id: str | None = None,
    ref_id: str = "drift-1",
    correlation_key: str = "risk:shared-web-exposure",
    evidence_id: str | None = None,
    affected_object_ids: list[str] | None = None,
    weight: float = 0.6,
    impact: float = 0.5,
) -> CorrelationSignal:
    return CorrelationSignal.model_validate(
        {
            "kind": kind,
            "ref_id": ref_id,
            "tenant_id": tenant_id,
            "correlation_key": correlation_key,
            "title": "Governance signal",
            "category": "governance",
            "weight": weight,
            "impact": impact,
            "affected_object_ids": affected_object_ids or [new_id("obj")],
            "evidence_id": evidence_id,
            "reason": "Governance result contributes to this risk.",
            "observed_at": NOW,
        }
    )


async def test_risk_correlate() -> None:
    store = InMemoryFindingStore()
    asset = new_id("obj")
    first = await store.raise_finding(
        _finding(affected_object_ids=[asset], severity_score=80.0, title="SSH exposed")
    )
    second = await store.raise_finding(
        _finding(affected_object_ids=[asset], severity_score=60.0, title="TLS weak")
    )
    await store.raise_finding(
        _finding(
            affected_object_ids=[asset],
            severity_score=90.0,
            status="resolved",
            title="Resolved issue",
        )
    )
    governance_signal = _signal(affected_object_ids=[asset], impact=0.7)

    risks = await RiskCorrelator(store, clock=lambda: NOW).correlate(
        tenant_id=None,
        signals=[governance_signal],
    )

    assert len(risks) == 1
    [risk] = risks
    assert risk.correlation_key == "risk:shared-web-exposure"
    assert risk.id == "risk:risk:shared-web-exposure"
    assert risk.affected_object_ids == [asset]
    assert risk.impact == 0.8
    assert [signal.kind for signal in risk.signals] == ["config", "finding", "finding"]
    assert {signal.ref_id for signal in risk.signals} == {
        governance_signal.ref_id,
        first.id,
        second.id,
    }
    assert "Correlated 3 signal(s)" in risk.reason


async def test_risk_explainable() -> None:
    store = InMemoryFindingStore()
    signal = _signal(ref_id="governance-gap-1")

    [risk] = await RiskCorrelator(store, clock=lambda: NOW).correlate(
        tenant_id=None,
        signals=[signal],
    )
    details = explain(risk)

    assert details["method"] == "correlation_key/v1"
    assert details["correlation_key"] == signal.correlation_key
    assert details["signal_count"] == 1
    assert details["affected_object_ids"] == signal.affected_object_ids
    assert details["signals"] == [risk.signals[0].model_dump(mode="json")]
    assert "governance-gap-1" in str(details["reason"])


async def test_risk_threat_intel_signal() -> None:
    store = InMemoryFindingStore()
    evidence_id = new_id("evd")
    threat = _signal(
        kind="threat_intel",
        ref_id="ti-campaign-1",
        evidence_id=evidence_id,
        weight=0.9,
        impact=0.85,
    )

    [risk] = await RiskCorrelator(store, clock=lambda: NOW).correlate(
        tenant_id=None,
        signals=[threat],
    )

    assert risk.signals[0].kind == "threat_intel"
    assert risk.signals[0].evidence_id == evidence_id
    assert risk.impact == 0.85
    with pytest.raises(RiskConfigInvalid, match="threat_intel signals require evidence_id"):
        _signal(kind="threat_intel", ref_id="ti-unaudited", evidence_id=None)


async def test_risk_tenant_isolation() -> None:
    store = InMemoryFindingStore(mode="multi")
    tenant_a_asset = new_id("obj")
    tenant_b_asset = new_id("obj")
    tenant_a_finding = await store.raise_finding(
        _finding(tenant_id=TENANT_A, affected_object_ids=[tenant_a_asset])
    )
    tenant_b_finding = await store.raise_finding(
        _finding(tenant_id=TENANT_B, affected_object_ids=[tenant_b_asset])
    )
    tenant_a_signal = _signal(
        tenant_id=TENANT_A,
        ref_id="drift-a",
        affected_object_ids=[tenant_a_asset],
    )
    tenant_b_signal = _signal(
        tenant_id=TENANT_B,
        ref_id="drift-b",
        affected_object_ids=[tenant_b_asset],
    )

    [risk] = await RiskCorrelator(store, clock=lambda: NOW).correlate(
        tenant_id=TENANT_A,
        signals=[tenant_b_signal, tenant_a_signal],
    )

    assert risk.tenant_id == TENANT_A
    assert risk.affected_object_ids == [tenant_a_asset]
    assert {signal.ref_id for signal in risk.signals} == {tenant_a_finding.id, "drift-a"}
    assert tenant_b_finding.id not in {signal.ref_id for signal in risk.signals}
