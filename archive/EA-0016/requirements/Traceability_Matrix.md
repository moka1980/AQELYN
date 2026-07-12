# Traceability Matrix

| Source | Target | Relationship |
|---|---|---|
| IS-016 Purpose | EA-0016 Objective | Defines why the engine exists |
| Acquisition Manager | FR-016-001 | Implements forensic acquisition |
| Chain of Custody Manager | FR-016-002 | Implements custody tracking |
| Evidence Verification Service | FR-016-003 | Implements hash validation |
| Timeline Engine | FR-016-004 | Implements timeline reconstruction |
| Artifact Analysis Engines | FR-016-005 | Implements artifact analysis |
| Report Generator | FR-016-006 | Implements forensic reporting |
| Event Publisher | FR-016-007 | Publishes forensic events |
| Evidence Engine Integration | Evidence source of truth | References immutable evidence |
| Knowledge Graph Integration | Evidence relationships | Links artifacts, timelines, investigations, incidents |
| SOC Integration | IS-015 | Supports incident investigation |
| Risk Integration | IS-013 | Provides evidence supporting risk |
| Compliance Integration | IS-010 | Supports audit and regulatory reporting |
| Policy Integration | Security rules | Controls retention, access, custody, export |
| Repository Validation | Repository Standard | Confirms no top-level redesign |
