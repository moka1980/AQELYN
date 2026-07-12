# Traceability Matrix

| Source | Target | Relationship |
|---|---|---|
| IS-014 Purpose | EA-0014 Objective | Defines why the engine exists |
| Threat Source Registry | FR-014-001 | Implements source lifecycle |
| Feed Ingestion Service | FR-014-002 | Implements feed import |
| Indicator Catalog | FR-014-003 | Implements normalized indicators |
| Threat Actor Registry | FR-014-004 | Implements adversary profiles |
| Campaign Manager | FR-014-005 | Implements campaign tracking |
| TTP Mapping Service | FR-014-006 | Implements TTP mapping |
| Confidence Scoring Engine | FR-014-007 | Implements confidence model |
| Threat Correlation Engine | FR-014-008 | Correlates threat context |
| Risk Intelligence Connector | FR-014-009 | Supplies IS-013 threat context |
| Threat Reporting Service | FR-014-010 | Produces threat reports |
| Evidence Engine Integration | Evidence-backed intelligence | References immutable evidence |
| Policy Engine Integration | Publishing and confidence rules | Determines source acceptance and thresholds |
| Mission Engine Integration | Mission threat relevance | Supplies mission impact context |
| Asset Governance Integration | Asset threat context | Supplies asset exposure and criticality |
| Identity Governance Integration | Identity threat context | Supplies privileged and compromised identity context |
| Event Bus Integration | NFR-014 event-driven sync | Publishes threat events |
| Repository Validation | Repository Standard | Confirms no top-level redesign |
