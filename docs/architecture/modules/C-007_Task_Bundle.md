# C-007 Compliance & Governance Engine — Implementation Task Bundle

**Milestone:** C-007 (Compliance & Governance Engine, EA-0010)
**For:** Codex (implementer) · Claude Code (reviewer)
**Prerequisites:** EA-0009 merged & green; EA-0010 spec **Accepted**; CONVENTIONS + EA-0002/0004/0007/0009 + Finding model read.
**Definition of Done:** every ticket's acceptance tests pass on in-memory **and** Postgres; `ruff` clean; `mypy --strict` clean; the engine mutates nothing beyond snapshot/evidence/finding writes; nothing outside the spec; `make check` green; Claude Code sign-off per ticket.

This engine **composes** the core (EA-0009 evaluate_compliance, EA-0002 query,
EA-0007 prioritize, EA-0004 evidence, Finding pipeline) — it does not
reimplement rule evaluation. If a needed behavior isn't in the spec, raise an ECR.

## Target source layout

```
src/aqelyn/governance/
├── __init__.py       # exports ComplianceEngine, service, types, register_compliance_events
├── models.py         # Control, ControlResult, ComplianceSnapshot, FrameworkCoverage, GovernanceConfig (G1)
├── engine.py         # ComplianceEngine: assess, control_result, coverage, trend, gaps_to_findings (G2/G3/G4)
├── store.py          # SnapshotStore protocol (G3)
├── memory.py         # InMemorySnapshotStore (G3)
├── postgres.py       # PostgresSnapshotStore + DDL (G3)
└── service.py        # ComplianceGovernanceService(AQService) + register_compliance_events (G5)
tests/governance/     # acceptance suite (in-memory + Postgres)
```

---

## G1 — Types, config & control model

**Spec:** §4, §6, D4, FR-11; §9.
**Deliverables:** the models; `GovernanceConfig` validation
(`GovernanceConfigInvalid` on unknown policy ref, undefined framework
requirement, `batch_size ≤ 0`); the new error codes in `conventions.errors` +
CONVENTIONS §9.
**Depends on:** EA-0009 types, conventions.
**Acceptance:** `test_gov_config_invalid`.

## G2 — Assessment run (compose Policy + ObjectStore)

**Spec:** §6, FR-1/2/3/4/9/10, D1/D2, NFR-2.
**Deliverables:** `assess` (paged tenant-scoped enumeration via
`ObjectStore.query`, per-control evaluation via
`PolicyEngine.evaluate_compliance`, deterministic, bounded batching, no-targets
handling) and `control_result`; `explain`.
**Depends on:** G1.
**Acceptance:** `test_gov_assess_estate`, `test_gov_deterministic`,
`test_gov_control_result`, `test_gov_no_targets`, `test_gov_bounded_batches`,
`test_gov_tenant_isolation`, `test_gov_no_side_effects`.

## G3 — Snapshot persistence, history & trend

**Spec:** §4 (ComplianceSnapshot), FR-5/12, D3.
**Deliverables:** `SnapshotStore` protocol; `InMemorySnapshotStore` +
`PostgresSnapshotStore` (+ DDL); `latest`/`history`/`trend`; snapshot written by
`assess`.
**Depends on:** G2.
**Acceptance:** `test_gov_snapshot_history`,
`test_gov_snapshot_contract[inmemory]`, `test_gov_snapshot_contract[postgres]`.

## G4 — Coverage, framework scores & gaps→findings

**Spec:** §6, FR-6/7/8, D1/D5; EA-0004 evidence; EA-0007 prioritize.
**Deliverables:** `coverage`, framework score aggregation, and
`gaps_to_findings` (raise a finding per failing control with severity + snapshot
evidence + failing subjects, optional Mission prioritization); evidence recorded
for the snapshot.
**Depends on:** G3.
**Acceptance:** `test_gov_coverage`, `test_gov_framework_scores`,
`test_gov_gaps_to_findings`, `test_gov_evidence_recorded`.

## G5 — Service + events

**Spec:** FR-13, §10.
**Deliverables:** `ComplianceGovernanceService` (`AQService`, name
`"compliance_engine"`) + `register_compliance_events`
(`assessment_completed`, `posture_changed`); wired into the kernel factory.
**Depends on:** G4.
**Acceptance:** `test_gov_service_health`.

---

## Review protocol (Claude Code)

Per ticket, confirm: (1) each named acceptance test passes on in-memory **and**
Postgres; (2) the engine **composes** EA-0009/EA-0002/EA-0007/EA-0004 — no
reimplemented rule evaluation, no second rule engine; (3) runs are deterministic,
bounded (batched), and tenant-scoped; (4) the engine mutates nothing beyond
snapshot/evidence/finding writes; (5) partial/failed runs are marked incomplete,
never presented as a clean pass; (6) every control result and framework score is
explainable; (7) `ruff` + `mypy --strict` clean; interfaces match the spec.
Merge only on green review; then **report back to the owner** before the next
module.
