# Examples

## 57.1 Example Control Mapping

```yaml
control_id: ACCESS-001
framework: Internal Security Baseline
title: Privileged Access Review
mapped_policy: POL-IDENTITY-004
evidence_required:
  - privileged_user_inventory
  - access_review_approval_log
  - identity_provider_audit_log
status: PARTIAL
reason: Policy exists, but current review evidence is incomplete.
```

## 57.2 Example Governance Decision

```yaml
decision_id: GOV-DEC-0001
decision_type: waiver_approved
actor: governance_board
authority_level: governance
affected_controls:
  - ACCESS-001
reason: Temporary operational constraint with compensating controls.
evidence_links:
  - evidence://access-review-2026-q1
valid_until: 2026-09-30
```

## 57.3 Example Compliance Event

```json
{
  "event_type": "compliance.status.changed",
  "control_id": "ACCESS-001",
  "previous_status": "UNKNOWN",
  "new_status": "PARTIAL",
  "reason": "Required evidence incomplete",
  "source_engine": "aqelyn_compliance_governance_engine"
}
```
