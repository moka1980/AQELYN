# Example Asset Governance Records

## 56.1 Example Asset

```yaml
asset_id: ASSET-0001
asset_type: cloud_instance
owner: ID-0001
classification: production
lifecycle_state: operational
trust_score: 0.88
criticality: high
```

## 56.2 Example Configuration Item

```yaml
configuration_id: CFG-1001
asset_id: ASSET-0001
source: cloud_api
baseline: BASELINE-LINUX-HARDENED-v1
observed_state:
  ssh_root_login: disabled
  disk_encryption: enabled
expected_state:
  ssh_root_login: disabled
  disk_encryption: enabled
drift_status: no_drift
```

## 56.3 Example Drift Finding

```yaml
finding_id: DRIFT-2001
asset_id: ASSET-0002
severity: critical
baseline: BASELINE-CLOUD-STORAGE-v2
evidence: evidence://config-snapshot-2026-07-07
reason: public_access_enabled differs from baseline expectation
```

## 56.4 Example Asset Event

```json
{
  "event_type": "configuration.drift.detected",
  "asset_id": "ASSET-0002",
  "configuration_id": "CFG-1002",
  "severity": "critical",
  "baseline_id": "BASELINE-CLOUD-STORAGE-v2",
  "source_engine": "aqelyn_asset_configuration_governance_engine"
}
```
