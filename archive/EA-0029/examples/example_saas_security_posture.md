# Example SaaS Security Posture Records

## 52.1 Example SaaS Application

```yaml
application_id: SAAS-0001
vendor: Microsoft 365
tenant: enterprise-primary
status: active
owner: collaboration_security_team
```

## 52.2 Example SaaS Assessment

```yaml
assessment_id: SAAS-ASSESS-2001
compliance_score: 84
risk_score: 72
generated_at: 2026-07-07T12:00:00Z
```

## 52.3 Example SaaS Integration

```yaml
integration_id: INT-3001
provider: third_party_oauth_app
permission_scope: read_write_mailbox
confidence: 0.89
risk_state: high
```

## 52.4 Example SaaS Event

```json
{
  "event_type": "saas.policy.violation",
  "application_id": "SAAS-0001",
  "risk_score": 72,
  "source_engine": "aqelyn_saas_security_posture_management_engine"
}
```
