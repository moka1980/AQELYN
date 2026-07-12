# Example Configuration Compliance Records

## 52.1 Example Configuration Record

```yaml
configuration_id: CFG-0001
asset_id: ASSET-1001
baseline_version: BASELINE-LINUX-V3
compliance_status: noncompliant
confidence: 0.93
```

## 52.2 Example Baseline Definition

```yaml
baseline_id: BASELINE-LINUX
version: v3
approval_status: approved
effective_date: 2026-07-07
owner: configuration_security_team
```

## 52.3 Example Drift Assessment

```yaml
assessment_id: DRIFT-2001
drift_type: unauthorized_service_enabled
confidence: 0.89
detected_at: 2026-07-07T12:00:00Z
```

## 52.4 Example Configuration Event

```json
{
  "event_type": "configuration.drift.detected",
  "configuration_id": "CFG-0001",
  "asset_id": "ASSET-1001",
  "baseline_version": "BASELINE-LINUX-V3",
  "source_engine": "aqelyn_configuration_compliance_drift_intelligence_engine"
}
```
