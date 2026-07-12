# Example SOC Records

## 56.1 Example Alert

```yaml
alert_id: ALERT-0001
source: threat_intelligence
severity: high
confidence: 0.91
timestamp: 2026-07-07T12:00:00Z
related_assets:
  - ASSET-0002
related_identities:
  - ID-0001
related_missions:
  - MISSION-001
evidence:
  - evidence://indicator-match-1001
```

## 56.2 Example Incident

```yaml
incident_id: INC-1001
title: Mission-critical asset matched high-confidence threat indicator
priority: critical
severity: high
status: active
owner: soc_analyst_01
affected_assets:
  - ASSET-0002
affected_missions:
  - MISSION-001
risk_score: 92
threat_context:
  campaign: CAMP-2001
evidence:
  - evidence://indicator-match-1001
  - evidence://asset-criticality-asset-0002
```

## 56.3 Example Case

```yaml
case_id: CASE-2001
incident: INC-1001
owner: senior_analyst_01
tasks:
  - collect_endpoint_evidence
  - validate_indicator_match
  - notify_mission_owner
evidence:
  - evidence://case-timeline-2001
```

## 56.4 Example SOC Event

```json
{
  "event_type": "incident.created",
  "incident_id": "INC-1001",
  "severity": "high",
  "priority": "critical",
  "reason": "High-confidence threat indicator matched mission-critical asset",
  "source_engine": "aqelyn_security_operations_engine"
}
```
