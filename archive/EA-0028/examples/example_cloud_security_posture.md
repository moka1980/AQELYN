# Example Cloud Security Posture Records

## 52.1 Example Cloud Resource

```yaml
resource_id: CLOUD-RES-0001
provider: aws
account: production-security
region: eu-west-1
resource_type: object_storage
exposure_state: public
```

## 52.2 Example Cloud Assessment

```yaml
assessment_id: CLOUD-ASSESS-1001
compliance_score: 72
risk_score: 88
generated_at: 2026-07-07T12:00:00Z
```

## 52.3 Example Cloud Exposure

```yaml
exposure_id: CLOUD-EXP-2001
exposure_type: public_storage
severity: high
confidence: 0.91
```

## 52.4 Example Cloud Event

```json
{
  "event_type": "cloud.misconfiguration.detected",
  "resource_id": "CLOUD-RES-0001",
  "risk_score": 88,
  "source_engine": "aqelyn_cloud_security_posture_management_engine"
}
```
