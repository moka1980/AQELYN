# AQELYN Module Specifications (post-foundation)

Code-ready specifications for Engineering Archives **after** the C-001
foundation (EA-0005 onward). Same discipline as `../foundation/`: Codex
implements from these; Claude Code reviews against them. The `archive/EA-xxxx/`
masters remain the immutable published records; where a module spec here is more
detailed, the spec governs implementation.

## Where things go (file placement)

- **Specs, task bundles, and ECRs** (what you read) live here in
  `docs/architecture/modules/`.
- **A module's code** (what Codex writes) lives in `src/aqelyn/<module>/`, with
  tests in `tests/<module>/`. The exact package name and file list are given in
  that module's task bundle under "Target source layout". No new top-level
  folders are created — everything nests under the `src/aqelyn/` root already
  sanctioned by `START_HERE.md`.

Current mapping: EA-0005 → `src/aqelyn/graph/` + `tests/graph/`;
EA-0006 → `src/aqelyn/trust/` + `tests/trust/`;
EA-0007 → `src/aqelyn/mission/` + `tests/mission/`;
EA-0008 → `src/aqelyn/workflow/` + `tests/workflow/`;
EA-0009 → `src/aqelyn/policy/` + `tests/policy/`;
EA-0010 → `src/aqelyn/governance/` + `tests/governance/`;
EA-0011 → `src/aqelyn/iag/` + `tests/iag/`;
EA-0012 → `src/aqelyn/assetconfig/` + `tests/assetconfig/`;
EA-0013 → `src/aqelyn/risk/` + `tests/risk/`;
EA-0014 → `src/aqelyn/threat/` + `tests/threat/`;
EA-0015 → `src/aqelyn/soc/` + `tests/soc/`;
EA-0016 → `src/aqelyn/forensics/` + `tests/forensics/`;
EA-0017 → `src/aqelyn/detection/` + `tests/detection/`;
EA-0018 → `src/aqelyn/response/` + `tests/response/`;
EA-0019 → `src/aqelyn/lake/` + `tests/lake/`;
EA-0020 → `src/aqelyn/decision/` + `tests/decision/`;
EA-0021 → `src/aqelyn/forecast/` + `tests/forecast/`;
EA-0022 → `src/aqelyn/executive/` + `tests/executive/`;
EA-0023 → `src/aqelyn/exposure/` + `tests/exposure/`;
EA-0024 → `src/aqelyn/vuln/` + `tests/vuln/`;
EA-0025 → `src/aqelyn/inventory/` + `tests/inventory/`;
EA-0027 → `src/aqelyn/idthreat/` + `tests/idthreat/`;
EA-0028 → `src/aqelyn/cspm/` + `tests/cspm/`;
EA-0029 → `src/aqelyn/sspm/` + `tests/sspm/`;
EA-0030 → `src/aqelyn/supplychain/` + `tests/supplychain/`;
EA-0031 → `src/aqelyn/dspm/` + `tests/dspm/`;
EA-0032 → `src/aqelyn/secrets/` + `tests/secrets/`;
EA-0033 → `src/aqelyn/ispm/` + `tests/ispm/`;
IS-034 → no new package — distributed conformance over EA-0033, EA-0011,
EA-0025, EA-0032, EA-0002, and EA-0005; C-031 enhancements stay with those owners.

## Rules for AI agents and developers

1. Read the applicable **ADRs** (`../decisions/`) and **CONVENTIONS**
   (`../foundation/CONVENTIONS.spec.md`) before implementing any module.
2. A module is implementable only when its spec is **Accepted** and it passes
   its Definition of Ready (the spec's "Acceptance Criteria ↔ Tests").
3. Build one module at a time, in the order the owner releases specs. After each
   module merges, **report back to the owner** before starting the next.
4. Do not invent fields/types/events/behavior the spec doesn't define — raise an
   Engineering Change Request.

## Index

| Module | Realizes | Depends on | Build | Status |
|---|---|---|---|---|
| [EA-0005 Knowledge Graph](EA-0005-knowledge-graph.spec.md) | EA-0005 | EA-0002, EA-0001 | [C-002](C-002_Task_Bundle.md) | Accepted |
| [EA-0006 Trust Engine](EA-0006-trust-engine.spec.md) | EA-0006 | EA-0004, EA-0001 | [C-003](C-003_Task_Bundle.md) | Accepted |
| [EA-0007 Mission Engine](EA-0007-mission-engine.spec.md) | EA-0007 | EA-0005, EA-0006, EA-0002 | [C-004](C-004_Task_Bundle.md) | Accepted |
| [EA-0008 Workflow Engine](EA-0008-workflow-engine.spec.md) | EA-0008 | EA-0004, Finding, EA-0001 | [C-005](C-005_Task_Bundle.md) | Accepted |
| [EA-0009 Policy Engine](EA-0009-policy-engine.spec.md) | EA-0009 | EA-0002, EA-0008, EA-0001 | [C-006](C-006_Task_Bundle.md) | Accepted |
| [EA-0010 Compliance & Governance](EA-0010-compliance-governance-engine.spec.md) | EA-0010 | EA-0009, EA-0007, EA-0002, EA-0004 | [C-007](C-007_Task_Bundle.md) | Accepted |
| [EA-0011 Identity & Access Governance](EA-0011-identity-access-governance.spec.md) | EA-0011 | EA-0005, EA-0009, EA-0008, EA-0002 | [C-008](C-008_Task_Bundle.md) | Accepted |
| [EA-0012 Asset & Config Governance](EA-0012-asset-config-governance.spec.md) | EA-0012 | EA-0002, EA-0004, EA-0007, EA-0008 | [C-009](C-009_Task_Bundle.md) | Accepted |
| [EA-0013 Risk Intelligence](EA-0013-risk-intelligence.spec.md) | EA-0013 | Finding, EA-0007, EA-0008, EA-0010-0012 | [C-010](C-010_Task_Bundle.md) | Accepted |
| [EA-0014 Threat Intelligence Fusion](EA-0014-threat-intelligence-fusion.spec.md) | EA-0014 | EA-0002, EA-0005, EA-0006, EA-0013 | [C-011](C-011_Task_Bundle.md) | Accepted |
| [EA-0015 Security Operations (SOC)](EA-0015-security-operations.spec.md) | EA-0015 | Finding, EA-0008, EA-0013, EA-0014, EA-0005 | [C-012](C-012_Task_Bundle.md) | Accepted |
| [EA-0016 Digital Forensics](EA-0016-digital-forensics.spec.md) | EA-0016 | EA-0004, EA-0002, EA-0005, EA-0015 | [C-013](C-013_Task_Bundle.md) | Accepted |
| [EA-0017 Threat Detection & Analytics](EA-0017-threat-detection-analytics.spec.md) | EA-0017 | EA-0006, EA-0007, EA-0009, EA-0014 | [C-014](C-014_Task_Bundle.md) | Accepted |
| [EA-0018 Automated Response & Orchestration](EA-0018-automated-response-orchestration.spec.md) | EA-0018 | **EA-0008**, EA-0009, EA-0015 | [C-015](C-015_Task_Bundle.md) | Accepted (see ECR-0006) |
| [EA-0019 Security Data Lake & Telemetry](EA-0019-security-data-lake-telemetry.spec.md) | EA-0019 | EA-0004, EA-0008, EA-0009 | [C-016](C-016_Task_Bundle.md) | Accepted |
| [EA-0020 AI Decision Intelligence](EA-0020-ai-decision-intelligence.spec.md) | EA-0020 | **EA-0006**, EA-0008, EA-0013, EA-0015 | [C-017](C-017_Task_Bundle.md) | Accepted (see ECR-0007) |
| [EA-0021 Predictive Analytics & Forecasting](EA-0021-predictive-analytics-forecasting.spec.md) | EA-0021 | **EA-0020**, **EA-0006**, EA-0019 | [C-018](C-018_Task_Bundle.md) | Accepted (see ECR-0008) |
| [EA-0022 Executive Intelligence & Reporting](EA-0022-executive-intelligence-strategic-reporting.spec.md) | EA-0022 | EA-0007/0010/0013/0021, EA-0020, EA-0004 | [C-019](C-019_Task_Bundle.md) | Accepted |
| [EA-0023 Threat Exposure & Attack Surface Mgmt](EA-0023-threat-exposure-attack-surface-management.spec.md) | EA-0023 | EA-0012, EA-0019, EA-0005, EA-0011, EA-0007/0006, EA-0013 | [C-020](C-020_Task_Bundle.md) | Accepted (see ECR-0011, ECR-0041, ECR-0044) |
| [EA-0024 Vulnerability Intelligence & Prioritization](EA-0024-vulnerability-intelligence-prioritization.spec.md) | EA-0024 | EA-0014, EA-0023, EA-0007, EA-0012, EA-0006, EA-0020, EA-0018 | [C-021](C-021_Task_Bundle.md) | Accepted (see ECR-0012) |
| [EA-0025 Cyber Asset Discovery & Inventory Intelligence](EA-0025-cyber-asset-discovery-inventory-intelligence.spec.md) | EA-0025 | EA-0012, EA-0002, EA-0005, EA-0006, EA-0007, EA-0004 | [C-022](C-022_Task_Bundle.md) | Accepted (see ECR-0014) |
| IS-026 Configuration Compliance & Drift — **restates EA-0012, no new module** ([conformance](IS-026_Conformance_Analysis.md)) | (EA-0012) | — | [C-023](C-023_Task_Bundle.md) | ECR-0015: do not build |
| [EA-0027 Identity Threat Detection & Behavioral Analytics](EA-0027-identity-threat-detection-behavioral-analytics.spec.md) | EA-0027 | EA-0017, EA-0011, EA-0006, EA-0020, EA-0013, EA-0008 | [C-024](C-024_Task_Bundle.md) | Accepted (see ECR-0016, ECR-0017) |
| [EA-0028 Cloud Security Posture (CSPM)](EA-0028-cloud-security-posture.spec.md) | EA-0028 | EA-0025, EA-0012, EA-0010, EA-0023, EA-0011, EA-0013, EA-0006 | [C-025](C-025_Task_Bundle.md) | Accepted (see ECR-0020–0026) |
| [EA-0029 SaaS Security Posture (SSPM)](EA-0029-saas-security-posture.spec.md) | EA-0029 | EA-0025, EA-0012, EA-0010, EA-0011, EA-0013, EA-0005, EA-0023, EA-0006 | [C-026](C-026_Task_Bundle.md) | Accepted (ECR-0033; ECR-0032 Proposed) |
| [EA-0030 Software Supply Chain & SBOM](EA-0030-software-supply-chain-sbom.spec.md) | EA-0030 | EA-0005, EA-0024, EA-0025, EA-0004, EA-0010, EA-0013 | [C-027](C-027_Task_Bundle.md) | Accepted |
| [EA-0031 Data Security Posture Management](EA-0031-data-security-posture.spec.md) | EA-0031 | EA-0019, EA-0025, EA-0023, EA-0011, EA-0010, EA-0013, EA-0006, EA-0004, EA-0008 | [C-028](C-028_Task_Bundle.md) | Accepted (ECR-0041, ECR-0042; ECR-0032 Proposed) |
| [EA-0032 Secrets Security & Cryptographic Asset Intelligence](EA-0032-secrets-cryptographic-asset.spec.md) | EA-0032 | EA-0025, EA-0023, EA-0010, EA-0013, EA-0019, EA-0006, EA-0004, EA-0008 | [C-029](C-029_Task_Bundle.md) | Accepted (ECR-0043 through ECR-0048) |
| [EA-0033 Identity Security Posture Management](EA-0033-identity-security-posture.spec.md) | EA-0033 | **EA-0011**, EA-0013, EA-0007, EA-0006, EA-0020, EA-0012, EA-0025, EA-0023 | [C-030](C-030_Task_Bundle.md) | Accepted (ECR-0049–0052) |
| IS-034 Machine Identity & NHI Governance — **distributed conformance, no new module** ([conformance](IS-034_Conformance_Analysis.md)) | EA-0033 + EA-0011 + EA-0025 + EA-0032 | EA-0002, EA-0005, EA-0006, EA-0008, EA-0009 | [C-031](C-031_Task_Bundle.md) | ECR-0053 Proposed: do not build a second authority |
| [IS-035 — conformant via EA-0032](IS-035_Conformance_Analysis.md) | EA-0035 | *(no new module — see ECR-0054)* | [C-032](C-032_Task_Bundle.md) | Analysis |
| [IS-036 — conformant via EA-0018+EA-0008](IS-036_Conformance_Analysis.md) | EA-0036 | *(no new module; template archive — see ECR-0055)* | [C-033](C-033_Task_Bundle.md) | Analysis |

Spec authoring: [SPEC_AUTHOR_NOTES.md](SPEC_AUTHOR_NOTES.md) carries the reviewer's standing
rules and the current per-module handover for whoever drafts the next spec.

Change control: [ECR-LOG.md](ECR-LOG.md) records accepted and proposed
amendments to module specifications.

## Next

The four core engines (EA-0006-0009) plus the Knowledge Graph are specified.
IS-037 onward (check first whether the archive master is real content or a template): each gets a shipped-code reconciliation before Codex builds it;
the deliverable is either a code-ready spec for a genuinely new capability or a
conformance decision plus owner-scoped enhancements for a restatement. With the
Policy Engine, the safety spine is complete: EA-0008 enforces, EA-0009 decides,
and neither can loosen the other's floor (EA-0009 S3).
