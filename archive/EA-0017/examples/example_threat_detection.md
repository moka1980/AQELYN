# Example Threat Detection Records

## 54.1 Example Threat Detection

```yaml
detection_id: DET-0001
source: threat_detection_engine
severity: high
confidence: 0.89
timestamp: 2026-07-07T12:00:00Z
evidence:
  - evidence://telemetry-1001
  - evidence://indicator-match-2001
mitre_mapping:
  - T1059
```

## 54.2 Example Behavior Profile

```yaml
profile_id: BP-1001
entity: ID-0001
baseline:
  login_hours: "08:00-18:00"
  typical_locations:
    - office_network
deviations:
  - after_hours_admin_access
  - unusual_geo_location
```

## 54.3 Example Anomaly

```yaml
anomaly_id: ANOM-2001
entity: ASSET-0002
confidence: 0.84
severity: moderate
reason: network behavior deviated from established baseline
```

## 54.4 Example Detection Event

```json
{
  "event_type": "threat.detected",
  "detection_id": "DET-0001",
  "severity": "high",
  "confidence": 0.89,
  "reason": "Behavioral detection correlated with high-confidence threat indicator",
  "source_engine": "aqelyn_threat_detection_analytics_engine"
}
```
