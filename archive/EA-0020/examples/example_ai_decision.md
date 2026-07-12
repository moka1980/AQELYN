# Example AI Decision Records

## 53.1 Example Recommendation

```yaml
recommendation_id: REC-0001
confidence: 0.87
status: pending_review
explanation: High-confidence behavioral anomaly with matching threat intelligence and mission impact.
evidence:
  - evidence://detection-1001
  - evidence://risk-score-asset-0002
policy_references:
  - policy://response-human-review-required
```

## 53.2 Example Decision Record

```yaml
decision_id: DEC-1001
recommendation_id: REC-0001
approver: incident_commander_01
outcome: accepted
timestamp: 2026-07-07T12:10:00Z
reason: Evidence supports containment recommendation.
```

## 53.3 Example Confidence Score

```yaml
score_id: CONF-2001
value: 0.87
evidence_reference: evidence://detection-1001
rationale: Evidence quality high, threat confidence high, historical match moderate.
```

## 53.4 Example AI Decision Event

```json
{
  "event_type": "recommendation.generated",
  "recommendation_id": "REC-0001",
  "confidence": 0.87,
  "status": "pending_review",
  "source_engine": "aqelyn_ai_decision_intelligence_engine"
}
```
