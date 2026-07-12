# Example Data Security Posture Records

## 52.1 Example Data Asset

```yaml
asset_id: DATA-0001
asset_type: object_storage_bucket
location: cloud://storage/finance-sensitive
owner: finance_data_owner
```

## 52.2 Example Data Classification

```yaml
classification_id: CLASS-2001
sensitivity: regulated_pii
confidence: 0.94
classified_at: 2026-07-07T12:00:00Z
```

## 52.3 Example Data Exposure

```yaml
exposure_id: DEXP-3001
exposure_type: public_storage_access
severity: high
detected_at: 2026-07-07T12:05:00Z
```

## 52.4 Example DSPM Event

```json
{
  "event_type": "data.exposure.detected",
  "asset_id": "DATA-0001",
  "risk_score": 89,
  "source_engine": "aqelyn_data_security_posture_management_engine"
}
```
