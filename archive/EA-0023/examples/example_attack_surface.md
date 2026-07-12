# Example Attack Surface Records

## 52.1 Example Exposure Record

```yaml
exposure_id: EXP-0001
asset_id: ASSET-1001
exposure_type: public_api
risk_score: 87
confidence: 0.91
evidence:
  - evidence://api-discovery-1001
  - evidence://network-telemetry-2001
```

## 52.2 Example Attack Surface Asset

```yaml
asset_id: ASA-2001
classification: internet_facing
exposure_level: high
discovered_at: 2026-07-07T12:00:00Z
owner: cloud_security_team
```

## 52.3 Example Exposure Assessment

```yaml
assessment_id: EXA-3001
confidence: 0.88
recommendations:
  - restrict public API access
  - validate authentication policy
  - review certificate and domain ownership
generated_at: 2026-07-07T12:15:00Z
```

## 52.4 Example Exposure Event

```json
{
  "event_type": "exposure.detected",
  "exposure_id": "EXP-0001",
  "asset_id": "ASSET-1001",
  "risk_score": 87,
  "source_engine": "aqelyn_threat_exposure_attack_surface_management_engine"
}
```
