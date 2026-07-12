# Example Asset Inventory Records

## 52.1 Example Asset Record

```yaml
asset_id: ASSET-0001
asset_type: cloud_instance
owner: infrastructure_security_team
lifecycle_state: active
classification: mission_critical
confidence: 0.94
```

## 52.2 Example Asset Relationship

```yaml
relationship_id: REL-1001
source_asset: ASSET-0001
target_asset: APP-2001
relationship_type: supports_application
confidence: 0.88
```

## 52.3 Example Asset Classification

```yaml
classification_id: CLASS-3001
business_criticality: high
mission_alignment: mission_alpha
regulatory_classification: security_sensitive
```

## 52.4 Example Asset Event

```json
{
  "event_type": "asset.discovered",
  "asset_id": "ASSET-0001",
  "asset_type": "cloud_instance",
  "source_engine": "aqelyn_cyber_asset_discovery_inventory_intelligence_engine"
}
```
