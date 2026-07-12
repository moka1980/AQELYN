# Traceability Matrix

| Source | Target | Relationship |
|---|---|---|
| IS-012 Purpose | EA-0012 Objective | Defines why the engine exists |
| Asset Registry | FR-012-001 | Implements governed asset inventory |
| Configuration Registry | FR-012-002 | Implements configuration state tracking |
| Ownership & Stewardship Manager | FR-012-003 | Implements accountable ownership |
| Asset Classification Engine | FR-012-004 | Implements classification model |
| Baseline Manager | FR-012-005 | Implements baseline lifecycle |
| Drift Detector | FR-012-006 | Implements drift detection |
| Exposure Context Service | FR-012-007 | Tracks exposure state |
| Asset Criticality Engine | FR-012-008 | Calculates criticality |
| Asset Evidence Service | FR-012-009 | Binds state to evidence |
| Governance Connector | FR-012-010 | Triggers review workflows |
| Evidence Engine Integration | Evidence-backed state | References immutable evidence |
| Policy Engine Integration | Authorization and baseline rules | Determines classifications, baselines, reviews |
| Compliance Integration | IS-010 | Supplies baseline compliance and asset coverage |
| Identity Governance Integration | IS-011 | Supplies asset owners and privileged identities |
| Event Bus Integration | NFR-012-003 | Publishes asset and drift events |
| Repository Validation | Repository Standard | Confirms no top-level redesign |
