# Example Data Lake Records

## 53.1 Example Telemetry Record

```yaml
telemetry_id: TEL-0001
source: aqelyn_event_bus
timestamp: 2026-07-07T12:00:00Z
classification: security_event
integrity:
  status: verified
dataset: DATASET-SECURITY-EVENTS
```

## 53.2 Example Dataset

```yaml
dataset_id: DATASET-SECURITY-EVENTS
owner: data_administrator
retention_policy: RETENTION-SECURITY-365D
classification: security_sensitive
integrity: verified
```

## 53.3 Example Archive Record

```yaml
archive_id: ARCH-1001
retention_state: archived
integrity_hash: sha256:7a0f-example
archived_at: 2026-07-07T12:30:00Z
dataset: DATASET-SECURITY-EVENTS
```

## 53.4 Example Data Event

```json
{
  "event_type": "telemetry.ingested",
  "telemetry_id": "TEL-0001",
  "dataset_id": "DATASET-SECURITY-EVENTS",
  "source_engine": "aqelyn_security_data_lake_telemetry_platform"
}
```
