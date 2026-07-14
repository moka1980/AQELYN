"""S1 acceptance tests for Security Operations types and intake."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from aqelyn.conventions import is_valid, new_id
from aqelyn.conventions.errors import ALL_ERROR_CODES, SOCConfigInvalid
from aqelyn.findings import Automation, Finding, Remediation
from aqelyn.risk import Risk, SignalRef
from aqelyn.soc import SOCConfig, intake_alerts
from aqelyn.threat import ThreatMatch

TENANT_A = "018f0000-0000-7000-8000-000000000151"
NOW = datetime(2026, 7, 14, 17, 0, tzinfo=UTC)


def _finding(*, evidence_id: str, asset_id: str) -> Finding:
    return Finding(
        id=new_id("fnd"),
        tenant_id=TENANT_A,
        finding_type="soc-source-finding",
        schema_version=1,
        dedup_key="finding-dedup-key",
        title="Privileged account exposed",
        severity="high",
        severity_score=82.0,
        what_happened="The account was exposed in a risky context.",
        why_it_matters="Attackers could use the account for lateral movement.",
        how_determined="SOC S1 intake test.",
        risk_of_inaction="The account may be abused.",
        evidence_ids=[evidence_id],
        affected_object_ids=[asset_id],
        remediation=Remediation(
            summary="Review the account exposure.",
            steps=["Validate the account owner.", "Rotate credentials if needed."],
            difficulty="medium",
            expected_outcome="The exposure is contained.",
        ),
        automation=Automation(eligibility="none"),
        confidence=0.8,
        source_engine="soc-s1-test",
        correlation_id="soc:shared-account",
        first_detected_at=NOW,
        last_detected_at=NOW,
    )


def _threat_match(*, evidence_id: str, asset_id: str) -> ThreatMatch:
    return ThreatMatch(
        indicator_id=new_id("obj"),
        asset_id=asset_id,
        match_type="domain",
        confidence=0.76,
        evidence_id=evidence_id,
        reason="Indicator matched an asset attribute.",
    )


def _risk(*, evidence_id: str, asset_id: str) -> Risk:
    return Risk(
        id=f"risk:{TENANT_A}:soc:shared-account",
        tenant_id=TENANT_A,
        correlation_key="soc:shared-account",
        title="Correlated account compromise risk",
        category="identity",
        likelihood=0.7,
        impact=0.8,
        score=84.0,
        band="over_tolerance",
        signals=[
            SignalRef(
                kind="threat_intel",
                ref_id="threat-campaign-1",
                weight=0.8,
                evidence_id=evidence_id,
            )
        ],
        affected_object_ids=[asset_id],
        reason="Threat intelligence and identity signals are correlated.",
        first_seen_at=NOW,
        last_scored_at=NOW,
    )


def test_soc_intake_alerts() -> None:
    asset_id = new_id("obj")
    finding_evidence = new_id("evd")
    threat_evidence = new_id("evd")
    risk_evidence = new_id("evd")
    finding = _finding(evidence_id=finding_evidence, asset_id=asset_id)
    threat_match = _threat_match(evidence_id=threat_evidence, asset_id=asset_id)
    risk = _risk(evidence_id=risk_evidence, asset_id=asset_id)

    alerts = intake_alerts(
        findings=[finding, finding],
        threat_matches=[threat_match],
        risks=[risk],
        tenant_id=TENANT_A,
        now=NOW,
    )

    assert len(alerts) == 3
    assert len({(alert.tenant_id, alert.source_ref) for alert in alerts}) == 3
    assert all(is_valid(alert.id, "alt") for alert in alerts)
    assert all(alert.created_at == NOW for alert in alerts)
    assert all(alert.state == "new" for alert in alerts)

    by_source = {alert.source_kind: alert for alert in alerts}
    assert by_source["finding"].source_ref == finding.id
    assert by_source["finding"].evidence_id == finding_evidence
    assert by_source["finding"].correlation_key == "soc:shared-account"

    assert by_source["threat_match"].source_ref.startswith("threat_match:")
    assert by_source["threat_match"].evidence_id == threat_evidence
    assert by_source["threat_match"].correlation_key == f"asset:{asset_id}"

    assert by_source["risk"].source_ref == risk.id
    assert by_source["risk"].evidence_id == risk_evidence
    assert by_source["risk"].severity == "high"

    dumped = [alert.model_dump() for alert in alerts]
    assert all("what_happened" not in alert for alert in dumped)
    assert all("signals" not in alert for alert in dumped)

    bounded = intake_alerts(
        findings=[finding],
        threat_matches=[threat_match],
        risks=[risk],
        tenant_id=TENANT_A,
        config=SOCConfig(batch_size=2),
        now=NOW,
    )
    assert len(bounded) == 2


def test_soc_config_invalid() -> None:
    with pytest.raises(SOCConfigInvalid, match="incident_window_seconds"):
        SOCConfig(incident_window_seconds=0)
    with pytest.raises(SOCConfigInvalid, match="batch_size"):
        SOCConfig(batch_size=0)
    with pytest.raises(SOCConfigInvalid, match="correlation must be a mapping"):
        SOCConfig.model_validate({"correlation": ["asset"]})
    with pytest.raises(SOCConfigInvalid, match=r"correlation\.group_by"):
        SOCConfig(correlation={"group_by": []})
    with pytest.raises(SOCConfigInvalid, match=r"correlation\.max_alerts"):
        SOCConfig(correlation={"max_alerts": 0})

    assert "SOCConfigInvalid" in ALL_ERROR_CODES
    assert "IncidentNotFound" in ALL_ERROR_CODES
    assert "AlertNotFound" in ALL_ERROR_CODES
