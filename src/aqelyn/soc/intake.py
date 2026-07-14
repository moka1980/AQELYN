"""Alert intake for Security Operations (EA-0015 S1)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from aqelyn.conventions import utc_now
from aqelyn.findings import Finding
from aqelyn.findings.models import Severity
from aqelyn.risk import Risk
from aqelyn.soc.models import Alert, SOCConfig
from aqelyn.threat import ThreatMatch


def intake_alerts(
    *,
    findings: Sequence[Finding] = (),
    threat_matches: Sequence[ThreatMatch] = (),
    risks: Sequence[Risk] = (),
    tenant_id: str | None = None,
    config: SOCConfig | None = None,
    now: datetime | None = None,
) -> list[Alert]:
    """Wrap upstream signals as SOC alerts without copying the signal payloads."""

    selected_config = config or SOCConfig()
    created_at = now or utc_now()
    candidates = [
        *(_alert_from_finding(finding, created_at=created_at) for finding in findings),
        *(
            _alert_from_threat_match(match, tenant_id=tenant_id, created_at=created_at)
            for match in threat_matches
        ),
        *(_alert_from_risk(risk, created_at=created_at) for risk in risks),
    ]
    deduped = _dedupe_by_source_ref(candidates)
    return deduped[: selected_config.batch_size]


def _alert_from_finding(finding: Finding, *, created_at: datetime) -> Alert:
    return Alert(
        tenant_id=finding.tenant_id,
        source_kind="finding",
        source_ref=finding.id,
        evidence_id=_first_evidence(finding.evidence_ids),
        severity=finding.severity,
        correlation_key=_finding_correlation_key(finding),
        created_at=created_at,
    )


def _alert_from_threat_match(
    match: ThreatMatch,
    *,
    tenant_id: str | None,
    created_at: datetime,
) -> Alert:
    return Alert(
        tenant_id=tenant_id,
        source_kind="threat_match",
        source_ref=_threat_match_source_ref(match),
        evidence_id=match.evidence_id,
        severity=_severity_from_score(match.confidence * 100.0),
        correlation_key=f"asset:{match.asset_id}",
        created_at=created_at,
    )


def _alert_from_risk(risk: Risk, *, created_at: datetime) -> Alert:
    return Alert(
        tenant_id=risk.tenant_id,
        source_kind="risk",
        source_ref=risk.id,
        evidence_id=_first_evidence(
            [signal.evidence_id for signal in risk.signals if signal.evidence_id is not None]
        ),
        severity=_severity_from_score(risk.score),
        correlation_key=risk.correlation_key,
        created_at=created_at,
    )


def _dedupe_by_source_ref(alerts: Sequence[Alert]) -> list[Alert]:
    by_source: dict[tuple[str | None, str], Alert] = {}
    for alert in sorted(alerts, key=_alert_sort_key):
        by_source.setdefault((alert.tenant_id, alert.source_ref), alert)
    return sorted(by_source.values(), key=_alert_sort_key)


def _alert_sort_key(alert: Alert) -> tuple[str, str, str, str]:
    return (
        alert.tenant_id or "",
        alert.source_ref,
        alert.source_kind,
        alert.evidence_id or "",
    )


def _finding_correlation_key(finding: Finding) -> str:
    if finding.correlation_id is not None and finding.correlation_id.strip():
        return finding.correlation_id
    if finding.affected_object_ids:
        return f"asset:{','.join(sorted(finding.affected_object_ids))}"
    return f"finding:{finding.finding_type}:{finding.dedup_key}"


def _threat_match_source_ref(match: ThreatMatch) -> str:
    return f"threat_match:{match.indicator_id}:{match.asset_id}:{match.match_type}"


def _first_evidence(evidence_ids: Sequence[str]) -> str | None:
    if not evidence_ids:
        return None
    return sorted(evidence_ids)[0]


def _severity_from_score(score: float) -> Severity:
    if score >= 90.0:
        return "critical"
    if score >= 70.0:
        return "high"
    if score >= 40.0:
        return "medium"
    if score > 0.0:
        return "low"
    return "info"
