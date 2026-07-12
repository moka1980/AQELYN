# Traceability Matrix

| Source | Target | Relationship |
|---|---|---|
| IS-015 Purpose | EA-0015 Objective | Defines why the engine exists |
| Alert Manager | FR-015-001 | Implements alert lifecycle |
| Alert Correlation Engine | FR-015-002 | Supports incident creation |
| Incident Manager | FR-015-002 | Implements incident lifecycle |
| Case Manager | FR-015-003 | Implements case management |
| Investigation Engine | FR-015-004 | Implements structured investigations |
| Threat Hunting Engine | FR-015-005 | Implements proactive hunting |
| Analyst Workspace | FR-015-006 | Implements analyst operational view |
| Playbook Engine | FR-015-007 | Implements response playbooks |
| Response Coordinator | FR-015-008 | Coordinates operational response |
| Executive Dashboard | FR-015-009 | Implements SOC reporting |
| Event Publisher | FR-015-010 | Publishes SOC events |
| Evidence Engine Integration | Evidence-backed investigations | References immutable evidence |
| Policy Engine Integration | Severity and authorization rules | Determines escalation and closure behavior |
| Mission Engine Integration | Mission-aware prioritization | Supplies mission impact context |
| Risk Intelligence Integration | Risk-aware investigations | Supplies risk context |
| Threat Intelligence Integration | Threat context | Supplies indicators, actors, campaigns |
| Event Bus Integration | Event-driven synchronization | Publishes operational events |
| Repository Validation | Repository Standard | Confirms no top-level redesign |
