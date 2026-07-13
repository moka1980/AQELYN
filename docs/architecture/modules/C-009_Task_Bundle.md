# C-009 Asset & Configuration Governance — Implementation Task Bundle

**Milestone:** C-009 (Asset & Configuration Governance, EA-0012)
**For:** Codex (implementer) · Claude Code (reviewer)
**Prerequisites:** EA-0011 merged & green; EA-0012 spec **Accepted**; CONVENTIONS + EA-0002/0004/0007/0008 + Finding model read.
**Definition of Done:** every ticket's acceptance tests pass on in-memory **and** Postgres; `ruff` clean; `mypy --strict` clean; **the engine never mutates an asset/config or applies a fix**; nothing outside the spec; `make check` green; Claude Code sign-off per ticket.

This engine **composes** the core (ObjectStore, Evidence, Finding, Mission,
Workflow). All change is delegated to EA-0008 (§0). If a needed behavior isn't in
the spec, raise an ECR.

## Target source layout

```
src/aqelyn/assetconfig/
├── __init__.py       # exports the engine, service, types, register_acg_events
├── models.py         # Check, Baseline, DriftItem, AssetDrift, DriftSnapshot, ACGConfig (A1)
├── comparators.py    # the comparator functions (eq/in/gte/regex/absent/...) (A1)
├── classify.py       # asset classification from declarative rules (A2)
├── drift.py          # assess_asset + assess (observed vs expected) (A2)
├── store.py          # BaselineStore + DriftSnapshotStore protocols (A3)
├── memory.py         # in-memory stores (A3)
├── postgres.py       # Postgres stores + DDL (A3)
├── engine.py         # trend + drift_to_findings (findings + proposed runs) (A4)
└── service.py        # AssetConfigGovernanceService(AQService) + register_acg_events (A5)
tests/assetconfig/    # acceptance suite (in-memory + Postgres)
```

---

## A1 — Types, comparators & config

**Spec:** §4, §6 (comparators), FR-11; §9.
**Deliverables:** the models; the comparator functions (safe, structured — no
`eval`); `ACGConfig`/`Baseline` validation (`BaselineConfigInvalid` on unknown
comparator, missing `key`/`expected`, `batch_size ≤ 0`); new error codes in
`conventions.errors` + CONVENTIONS §9.
**Depends on:** EA-0002 types, conventions.
**Acceptance:** `test_acg_comparators`, `test_acg_config_invalid`.

## A2 — Classification & drift detection

**Spec:** §6, FR-1/2/3/4/6/7/10, D1/D2/D3.
**Deliverables:** `classify` (declarative rules, unmatched flagged);
`assess_asset` + `assess` (paged tenant-scoped, class-matched baselines,
observed-vs-expected, unknown handling, deterministic, bounded batching);
`explain`.
**Depends on:** A1.
**Acceptance:** `test_acg_assess_estate`, `test_acg_deterministic`,
`test_acg_drift_item`, `test_acg_unknown_handling`, `test_acg_classification`,
`test_acg_baseline_scoping`, `test_acg_tenant_isolation`,
`test_acg_bounded_batches`.

## A3 — Baseline & snapshot persistence

**Spec:** §5, FR-5/12, D4.
**Deliverables:** `BaselineStore` + `DriftSnapshotStore` (in-memory + Postgres +
DDL, versioned/provenanced baselines); `latest`/`history`/`trend`; snapshot
written by `assess`.
**Depends on:** A2.
**Acceptance:** `test_acg_snapshot_history`,
`test_acg_baseline_contract[inmemory]`, `test_acg_baseline_contract[postgres]`,
`test_acg_snapshot_contract[inmemory]`, `test_acg_snapshot_contract[postgres]`.

## A4 — Drift → findings + proposed remediation (no direct change)

**Spec:** §0, §6, FR-8/9, D5, NFR-1; EA-0004 evidence; EA-0007 prioritize; EA-0008 propose.
**Deliverables:** evidence recorded for the snapshot; `drift_to_findings` (finding
per failing check/asset with severity + evidence + affected asset, optional
Mission prioritization, optional **proposed** Workflow run — never a direct fix).
**Depends on:** A3.
**Acceptance:** `test_acg_drift_to_findings`, `test_acg_no_direct_mutation`,
`test_acg_evidence_recorded`.

## A5 — Service + events

**Spec:** FR-13, §10.
**Deliverables:** `AssetConfigGovernanceService` (`AQService`, name
`"acg_engine"`) + `register_acg_events`
(`drift_detected`, `assessment_completed`); wired into the kernel factory.
**Depends on:** A4.
**Acceptance:** `test_acg_service_health`.

---

## Review protocol (Claude Code)

Per ticket, confirm the normal DoD **and**, with extra scrutiny:
1. **No code path mutates an asset/config object or applies a fix** — remediation
   is a *proposed* Workflow run (§0/D5). Trace `drift_to_findings`.
2. Comparators are safe/structured — no `eval`/`exec`.
3. Drift detection is deterministic, pure, tenant-scoped, bounded (batched).
4. Missing observed values are handled explicitly (never a silent pass).
5. Every snapshot is evidence-recorded; partial runs marked incomplete.
6. `ruff` + `mypy --strict` clean; interfaces match the spec exactly.

Merge only on green review; then **report back to the owner** before the next
module.
