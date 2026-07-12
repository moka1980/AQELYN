# Traceability Matrix

| Source | Target | Relationship |
|---|---|---|
| IS-018 Purpose | EA-0018 Objective | Defines why the engine exists |
| Response Engine | FR-018 response coordination | Coordinates response execution |
| Orchestration Engine | FR-018-005 | Coordinates cross-engine tasks |
| Playbook Engine | FR-018-001 | Executes governed playbooks |
| Automation Engine | FR-018-002, FR-018-003 | Executes containment and remediation actions |
| Approval Engine | FR-018-004 | Manages approvals |
| Containment Engine | FR-018-002 | Implements containment |
| Remediation Engine | FR-018-003 | Implements remediation |
| Recovery Engine | Recovery lifecycle | Restores services and assets |
| Metrics Engine | FR-018-006 | Calculates response metrics |
| Event Publisher | FR-018-007 | Publishes response events |
| Workflow Engine Integration | Orchestration | Supplies workflow definitions and history |
| Policy Engine Integration | Authorization and rules | Supplies response and approval policies |
| SOC Integration | IS-015 | Supplies incident response context |
| Threat Detection Integration | IS-017 | Supplies detections and scores |
| Digital Forensics Integration | IS-016 | Supplies evidence and timelines |
| Repository Validation | Repository Standard | Confirms no top-level redesign |
