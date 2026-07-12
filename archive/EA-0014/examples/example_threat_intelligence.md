# Example Threat Intelligence Records

## 56.1 Example Threat Source

```yaml
source_id: THSRC-0001
name: Internal SOC Detections
type: internal
trust_score: 0.94
confidence: high
update_frequency: continuous
status: active
```

## 56.2 Example Threat Indicator

```yaml
indicator_id: IOC-1001
indicator_type: domain
value: malicious-example.test
confidence: high
first_seen: 2026-07-07T12:00:00Z
last_seen: 2026-07-07T12:30:00Z
source: THSRC-0001
```

## 56.3 Example Threat Campaign

```yaml
campaign_id: CAMP-2001
actors:
  - ACTOR-3001
indicators:
  - IOC-1001
ttps:
  - TTP-PHISHING
timeframe:
  first_seen: 2026-07-01
  last_seen: 2026-07-07
status: active
```

## 56.4 Example Threat Event

```json
{
  "event_type": "risk.threat.updated",
  "risk_id": "RISK-0001",
  "indicator_id": "IOC-1001",
  "confidence": "high",
  "reason": "Indicator matched mission-critical asset exposure",
  "source_engine": "aqelyn_threat_intelligence_fusion_engine"
}
```
