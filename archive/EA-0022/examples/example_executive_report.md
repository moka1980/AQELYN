# Example Executive Report Records

## 52.1 Example Executive Report

```yaml
report_id: EXR-0001
title: Quarterly Cyber Posture Executive Report
version: v1
approval_status: pending_approval
sections:
  - cyber_posture
  - mission_health
  - strategic_risk
  - compliance_summary
```

## 52.2 Example KPI Record

```yaml
kpi_id: KPI-SEC-001
value: 87
confidence: 0.91
reporting_period: 2026-Q3
name: Security Posture Score
```

## 52.3 Example Executive Briefing

```yaml
briefing_id: BRF-1001
audience: board
recommendations:
  - increase focus on mission-critical identity exposure
  - reduce unresolved high-risk vulnerabilities
generated_at: 2026-07-07T12:00:00Z
```

## 52.4 Example Reporting Event

```json
{
  "event_type": "executive.summary.generated",
  "report_id": "EXR-0001",
  "confidence": 0.91,
  "source_engine": "aqelyn_executive_intelligence_reporting_engine"
}
```
