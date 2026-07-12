# Example Identity Governance Records

## 55.1 Example Identity

```yaml
identity_id: ID-0001
identity_type: employee
display_name: Jane Doe
owner: HR
status: active
trust_score: 0.92
risk_score: low
```

## 55.2 Example Account Mapping

```yaml
account_id: ACC-1001
identity_id: ID-0001
platform: Azure AD
username: jane.doe@example.com
status: active
last_seen: 2026-07-07T10:00:00Z
```

## 55.3 Example Access Grant

```yaml
grant_id: GRANT-2001
identity: ID-0001
account: ACC-1001
role: ROLE-FINANCE-APPROVER
entitlement: ENT-FINANCE-PAYMENT-APPROVE
approval: GOV-DEC-3001
expires_at: 2026-12-31
```

## 55.4 Example SoD Violation Event

```json
{
  "event_type": "governance.sod.violation.detected",
  "identity_id": "ID-0001",
  "conflict": ["create_vendor", "approve_vendor_payment"],
  "severity": "high",
  "source_engine": "aqelyn_identity_access_governance_engine"
}
```
