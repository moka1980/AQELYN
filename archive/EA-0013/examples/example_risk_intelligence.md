# Example Risk Intelligence Records

## 57.1 Example Risk

```yaml
risk_id: RISK-0001
category: configuration_risk
likelihood: high
impact: critical
score: 92
confidence: 0.88
owner: security_owner
status: assessed
```

## 57.2 Example Risk Assessment

```yaml
assessment_id: RA-1001
risk_id: RISK-0001
assessment_date: 2026-07-07T12:00:00Z
methodology: aqelyn_dynamic_risk_v1
calculated_score: 92
evidence:
  - evidence://config-drift-asset-0002
  - evidence://asset-criticality-asset-0002
  - evidence://threat-intel-campaign-123
```

## 57.3 Example Risk Treatment

```yaml
treatment_id: RT-2001
risk_id: RISK-0001
strategy: reduce
owner: technical_owner
due_date: 2026-08-15
status: in_progress
```

## 57.4 Example Risk Event

```json
{
  "event_type": "risk.score.changed",
  "risk_id": "RISK-0001",
  "previous_score": 71,
  "new_score": 92,
  "reason": "Critical configuration drift on mission-critical asset",
  "source_engine": "aqelyn_risk_intelligence_engine"
}
```
