# Example Identity Behavior Records

## 52.1 Example Identity Behavior Record

```yaml
behavior_id: BEH-0001
identity_id: ID-1001
confidence: 0.91
risk_score: 82
behavior_summary: unusual privileged access from new geography
```

## 52.2 Example Identity Risk Assessment

```yaml
assessment_id: IDRISK-2001
severity: high
recommendation: create investigation and require step-up verification
generated_at: 2026-07-07T12:00:00Z
```

## 52.3 Example Credential Threat

```yaml
threat_id: CRED-3001
credential_status: suspected_compromised
threat_type: password_spraying
confidence: 0.87
```

## 52.4 Example Identity Event

```json
{
  "event_type": "identity.anomaly.detected",
  "identity_id": "ID-1001",
  "risk_score": 82,
  "source_engine": "aqelyn_identity_threat_detection_behavioral_analytics_engine"
}
```
