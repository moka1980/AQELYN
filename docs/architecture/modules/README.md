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
EA-0013 → `src/aqelyn/risk/` + `tests/risk/`.

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

Change control: [ECR-LOG.md](ECR-LOG.md) records approved amendments to Accepted
specs (currently ECR-0001 against EA-0005).

## Next

The four core engines (EA-0006-0009) plus the Knowledge Graph are specified.
EA-0014 onward: each gets a code-ready spec pass (owner + planning) before Codex
builds it, because the archive masters are still placeholders. With the Policy
Engine, the safety spine is complete: EA-0008 enforces, EA-0009 decides, and
neither can loosen the other's floor (EA-0009 S3).
