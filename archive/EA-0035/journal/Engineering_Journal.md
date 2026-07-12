# Engineering Journal - EA-0035

Major decisions:
- AQELYN shall govern credential metadata and lifecycle without becoming a plaintext secret store.
- Provider-specific behavior is isolated in connectors.
- Findings must be evidence-backed.
- Credential assets are first-class graph nodes linked to identities, workloads, providers, policies, and missions.
- Certificate governance is included because certificate failure is both a security and availability risk.

Assumptions:
- External systems remain authoritative for storing secrets and issuing certificates.
- Connectors can obtain safe metadata under least-privilege configurations.
- Some providers may expose incomplete metadata; confidence scores and evidence quality must reflect this.

Future work:
- Confidential computing attestation integration.
- Post-quantum cryptography lifecycle policy.
- Automated emergency credential revocation playbooks.
- Expanded signing key provenance tracking.