# Traceability Matrix

| Source | Target | Relationship |
|---|---|---|
| IS-017 Purpose | EA-0017 Objective | Defines why the engine exists |
| Detection Engine | FR-017-001 | Implements threat detection |
| Behavioral Analysis Engine | FR-017-002 | Implements behavioral analytics |
| Anomaly Detection Engine | FR-017-003 | Implements anomaly detection |
| Correlation Engine | FR-017-004 | Implements contextual correlation |
| Threat Scoring Engine | FR-017-005 | Implements threat scoring |
| MITRE ATT&CK Mapper | FR-017-006 | Implements technique mapping |
| Predictive Analytics Engine | FR-017-007 | Implements prediction lifecycle |
| Detection Dashboard | FR-017-008 | Implements reporting and metrics |
| Event Publisher | FR-017-009 | Publishes detection events |
| Evidence Engine Integration | Evidence-backed detections | References immutable evidence |
| Digital Forensics Integration | Forensic context | Consumes reports, timelines, artifact verification |
| SOC Integration | IS-015 | Supports incident creation and hunting |
| Risk Integration | IS-013 | Supplies risk correlation and forecasting |
| Threat Intelligence Integration | IS-014 | Supplies indicators, actors, campaigns |
| Policy Integration | Analytical rules | Controls thresholds, escalation, publication, retention |
| Repository Validation | Repository Standard | Confirms no top-level redesign |
