# Example Predictive Forecast Records

## 52.1 Example Forecast

```yaml
forecast_id: FCST-0001
prediction: increased phishing campaign activity against mission-critical users
confidence: 0.82
horizon: 14_days
evidence:
  - evidence://trend-phishing-30d
  - evidence://threat-campaign-2001
```

## 52.2 Example Prediction Model

```yaml
model_id: PM-1001
version: v1.0
accuracy: 0.78
updated_at: 2026-07-07T12:00:00Z
scope: threat_campaign_forecasting
```

## 52.3 Example Scenario

```yaml
scenario_id: SCN-2001
likelihood: moderate
impact: high
description: If privileged credential exposure continues, mission disruption likelihood increases within 7 days.
```

## 52.4 Example Forecast Event

```json
{
  "event_type": "forecast.generated",
  "forecast_id": "FCST-0001",
  "confidence": 0.82,
  "horizon": "14_days",
  "source_engine": "aqelyn_predictive_analytics_forecasting_engine"
}
```
