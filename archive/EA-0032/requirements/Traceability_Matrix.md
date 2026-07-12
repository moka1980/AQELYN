# Traceability Matrix

| Source | Target | Relationship |
|---|---|---|
| IS-032 Purpose | EA-0032 Objective | Defines why the engine exists |
| Secret Discovery Engine | FR-032-001 | Discovers secrets and credentials |
| Cryptographic Asset Inventory Engine | FR-032-002 | Inventories keys, certificates, and cryptographic assets |
| Certificate Lifecycle Engine | FR-032-003 | Tracks certificate expiration and renewal |
| Key Management Intelligence Engine | FR-032-003 | Evaluates rotation, age, ownership, and algorithm policy |
| Secret Exposure Analysis Engine | FR-032-003 | Detects exposed or hardcoded secrets |
| Cryptographic Compliance Engine | Governance and compliance | Maps cryptographic assets to policy |
| Cryptographic Risk Engine | Risk scoring | Calculates cryptographic security risk |
| Event Publisher | FR-032-006 | Publishes secret, certificate, key, exposure, and risk events |
| Security Data Lake Integration | Cryptographic telemetry | Supplies secret inventories, certificate metadata, key metadata |
| AI Decision Integration | Remediation recommendations | Supplies confidence and recommendations |
| Risk & Threat Integration | Threat context | Supplies threat, identity, supply chain, and DSPM context |
| Compliance Integration | Governance and audit | Supports certificate, key, and secret governance |
| Repository Validation | Repository Standard | Confirms no top-level redesign |
