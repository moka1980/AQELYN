# EA-0012 — Asset & Configuration Governance Engine — Implementation Specification

**Realizes:** EA-0012 / IS-012 (supersedes the placeholder `archive/EA-0012/EA-0012_Master.md` for implementation)
**Depends on:** ADR-0001, CONVENTIONS, EA-0001 (`AQService`), EA-0002 (assets/configurations as objects), EA-0004 (drift snapshots as evidence), the Finding model; EA-0007 (prioritization), EA-0008 (gated remediation), EA-0009 (optional baseline-as-policy)
**Consumed by:** asset & configuration UI (inventory, drift dashboards, baseline coverage — a WCAG 2.2 AA surface), the Finding pipeline (drift → findings), EA-0010 governance reporting, auditors (baseline-conformance evidence)
**Status:** Accepted
**Build milestone:** C-009 (see `C-009_Task_Bundle.md`)
**Definition of Ready:** see §11

---

## 0. Safety boundary (read first)

Like its governance siblings, this engine **detects and proposes; it does not
change assets.** It compares each asset's observed configuration to an expected
baseline, records drift, and produces findings + **proposed** remediation runs
for the Workflow Engine (EA-0008) — gated, approved, evidenced, reversible.
Applying a fix, re-imaging a host, or editing a config is never done here. The
engine is otherwise read/analysis over the estate: deterministic, explainable,
tenant-scoped, evidence-recorded. No new authorization surface.

## 1. Purpose

The Asset & Configuration Governance Engine answers *what do we have, is it
configured the way it should be, and where has it drifted?* It maintains the
authoritative view of assets and their configurations, expresses **desired
state as declarative baselines** (e.g. CIS-style hardening), detects **drift**
(observed ≠ expected), classifies assets and tracks ownership/lifecycle, and
turns misconfiguration into prioritized, provable findings.

## 2. Design decisions

- **D1 — Assets & configurations are EA-0002 objects.** `object_type ∈ {asset,
  configuration}`; an asset's observed configuration lives in its `attributes`
  (or a linked `configuration` object). Relationships express dependency/
  composition. No separate asset store.
- **D2 — Desired state is a declarative baseline.** A `Baseline` is data: a set
  of expected `(key, expected_value, comparator)` checks scoped to an asset
  class. Drift = the diff of observed vs expected. No imperative config logic.
- **D3 — Drift detection is deterministic, pure, explainable.** Each drift item
  names the check, the expected and observed values, and the asset. Same estate +
  baselines → same result. Charter "prove it."
- **D4 — Drift is snapshotted as evidence.** Each assessment writes a
  `DriftSnapshot` (persisted history) and may record an `EvidenceRecord`
  (EA-0004), so conformance-over-time and audit are real.
- **D5 — Remediation is delegated (§0).** Drift becomes findings + **proposed**
  Workflow runs; the engine never mutates an asset/config.
- **D6 — Baselines may be authored as Policy rules (EA-0009), optionally.** A
  baseline can reference Policy compliance rules for consistency with the
  governance engine; the native comparator model is the default.
- **D7 — Tenant-scoped, bounded** (paged over the estate). Registered as an
  `AQService` (D8).

## 3. Ubiquitous language

| Term | Meaning |
|---|---|
| **Asset** | A tracked thing with configuration (`object_type "asset"`): host, container, bucket, service. |
| **Configuration** | The asset's observed settings (`attributes.observed_state` or a linked `configuration` object). |
| **Baseline** | Declarative desired state: named checks `(key, expected, comparator)` scoped to an asset class. |
| **Check** | One expected-state assertion within a baseline. |
| **Drift** | An asset failing a baseline check (observed ≠ expected), with the diff. |
| **Drift snapshot** | The persisted result of a drift assessment: per-asset/per-check status + score + time. |
| **Classification** | An asset's assigned class/sensitivity (drives which baselines apply). |

## 4. Types

```
Comparator = "eq" | "ne" | "in" | "nin" | "gte" | "lte" | "exists" | "absent" | "regex"

Check      = { id, key: str, expected: Any, comparator: Comparator, severity: str,
               rationale: str, framework_refs: list[dict] }        # optional (feeds EA-0010)
Baseline   = { id, name, asset_class: str, version: int, checks: list[Check],
               tenant_id: str | null, set_by: ActorRef, set_at: datetime }

DriftItem  = { asset_id, check_id, key, expected: Any, observed: Any,
               status: "pass"|"fail"|"unknown", severity: str, reason: str }
AssetDrift = { asset_id, baseline_id, evaluated: int, passed: int, failed: int,
               score: float, items: list[DriftItem] }
DriftSnapshot = { id, tenant_id: str | null, run_at: datetime, scope: dict,
                  baseline_ids: list[str], overall_score: float,
                  asset_drifts: list[AssetDrift], evidence_id: str | null }

ACGConfig  = { batch_size: int, classification_rules: list[dict],
               unknown_is_fail: bool }                              # missing observed value handling
```

Reuses EA-0002 objects, `ActorRef`, the Finding model, EA-0007 prioritization,
and (optionally) EA-0009 rules.

## 5. Interfaces (Python 3.12)

```python
from typing import Protocol, Sequence
from datetime import datetime

class BaselineStore(Protocol):
    async def put(self, baseline: Baseline) -> Baseline: ...            # validates; versioned/provenanced
    async def get(self, baseline_id: str) -> Baseline | None: ...
    async def list(self, *, tenant_id: str | None,
                   asset_class: str | None = None) -> list[Baseline]: ...

class DriftSnapshotStore(Protocol):
    async def put(self, snapshot: DriftSnapshot) -> DriftSnapshot: ...
    async def get(self, snapshot_id: str) -> DriftSnapshot | None: ...
    async def latest(self, *, tenant_id: str | None) -> DriftSnapshot | None: ...
    async def history(self, *, tenant_id: str | None,
                      since: datetime | None = None, limit: int = 100) -> list[DriftSnapshot]: ...

class AssetConfigGovernanceEngine(Protocol):
    async def classify(self, asset_id: str) -> str: ...                # asset_class from rules (D1)
    async def assess_asset(self, asset_id: str, *, tenant_id: str | None) -> list[AssetDrift]: ...
    async def assess(self, *, tenant_id: str | None,
                     scope: "ObjectQuery | None" = None,
                     record_evidence: bool = True) -> DriftSnapshot: ...   # a run (D3/D4)
    async def trend(self, *, tenant_id: str | None, since: datetime) -> list[dict]: ...
    async def drift_to_findings(self, snapshot: DriftSnapshot, *, by: ActorRef,
                                propose_remediation: bool = True,
                                prioritize: bool = True) -> list[str]: ...  # findings + proposed runs (D5)
    def explain(self, item: DriftItem) -> dict: ...
```

`AssetConfigGovernanceService` wraps the engine + both stores as an `AQService`
(name `"acg_engine"`, depends on object store, evidence/finding stores, mission
+ workflow engines; health reflects their availability + config validity).

## 6. Computation (the reference model)

**Classification.** `classify(asset)` applies `classification_rules`
(structured, EA-0009-style matchers over `attributes`) to assign an
`asset_class`; unmatched → `"unclassified"`, flagged.

**Drift (`assess`).** Enumerate in-scope assets via `ObjectStore.query` (paged,
tenant-scoped). For each asset, select baselines matching its class; for each
`Check`, read the observed value from `attributes.observed_state[key]` and
compare with the `comparator`. Missing observed → `unknown` (counts as `fail` if
`unknown_is_fail`). `AssetDrift.score = passed / evaluated` (1.0 if none).
`overall_score` = mean over assets. Persist a `DriftSnapshot` (D4); if
`record_evidence`, write an `EvidenceRecord`. Deterministic (D3).

**Drift → findings.** For each failing check (or grouped per asset), raise a
finding: severity from the `Check`, evidence = snapshot evidence + the diff,
affected object = the asset, remediation summary from the check's `rationale`;
if `propose_remediation`, create a **proposed** Workflow run (§0/D5); if
`prioritize`, order via `MissionEngine.prioritize`.

## 7. Requirements

### Functional (testable)

- **FR-1** `assess` SHALL enumerate in-scope assets via `ObjectStore.query`, paged and tenant-scoped, and evaluate each matching baseline's checks against the asset's observed state (D1/D2).
- **FR-2** Drift detection SHALL be deterministic and pure; identical estate + baselines + config → identical snapshot (excluding ids/timestamps) (D3).
- **FR-3** Each `DriftItem` SHALL report `key`, `expected`, `observed`, `status`, `severity`, and a `reason` (D3).
- **FR-4** A missing observed value SHALL yield `unknown`, counted as `fail` iff `unknown_is_fail`; never a crash or silent pass.
- **FR-5** `assess` SHALL persist a `DriftSnapshot`; `latest`/`history`/`trend` SHALL return persisted snapshots (D4).
- **FR-6** `classify` SHALL assign an `asset_class` from declarative rules; unmatched → `"unclassified"`, flagged.
- **FR-7** Only baselines matching an asset's class (and its tenant/global) SHALL apply to that asset.
- **FR-8** `drift_to_findings` SHALL raise a finding per failing check/asset with the check severity, snapshot evidence, and the asset as affected object; optional Mission prioritization; and, when requested, a **proposed** Workflow run — never a direct asset/config change (§0/D5).
- **FR-9** When `record_evidence`, `assess` SHALL write an `EvidenceRecord`; the engine SHALL NOT mutate assets/configs/baselines during assessment.
- **FR-10** Runs SHALL be tenant-scoped; no cross-tenant asset appears (D7).
- **FR-11** Invalid config/baseline (unknown comparator, `batch_size ≤ 0`, check missing `key`/`expected`) SHALL raise `BaselineConfigInvalid` at `put`/construction.
- **FR-12** `BaselineStore` and `DriftSnapshotStore` in-memory and Postgres implementations SHALL each pass one contract suite.
- **FR-13** `AssetConfigGovernanceService` SHALL register as an `AQService` with health reflecting dependency availability + config validity (EA-0001).

### Non-functional

- **NFR-1 (no direct mutation)** no code path edits an asset/config or applies a fix; remediation is delegated to Workflow (enforced by test).
- **NFR-2 (determinism)** identical inputs → identical snapshot (excluding id/timestamp).
- **NFR-3 (bounded)** estate processed in bounded batches; memory independent of estate size.
- **NFR-4 (portability & typing)** in-memory + Postgres stores pass their suites; `mypy --strict` + `ruff` clean.

## 8. Acceptance Criteria ↔ Tests (Definition of Ready)

| # | Criterion | Test (pytest id) |
|---|---|---|
| AC-1 | Assess evaluates baselines across assets | `test_acg_assess_estate` |
| AC-2 | Deterministic drift snapshot | `test_acg_deterministic` |
| AC-3 | Drift item reports expected/observed/reason | `test_acg_drift_item` |
| AC-4 | Missing observed → unknown/fail per config | `test_acg_unknown_handling` |
| AC-5 | Comparators (eq/in/gte/regex/absent…) correct | `test_acg_comparators` |
| AC-6 | Classification assigns class, unmatched flagged | `test_acg_classification` |
| AC-7 | Only class-matching baselines apply | `test_acg_baseline_scoping` |
| AC-8 | Snapshot persisted; latest/history/trend | `test_acg_snapshot_history` |
| AC-9 | Drift → prioritized findings + proposed runs | `test_acg_drift_to_findings` |
| AC-10 | No direct asset/config mutation | `test_acg_no_direct_mutation` |
| AC-11 | Evidence recorded for snapshot | `test_acg_evidence_recorded` |
| AC-12 | Tenant isolation | `test_acg_tenant_isolation` |
| AC-13 | Invalid baseline/config rejected | `test_acg_config_invalid` |
| AC-14 | Bounded batching over large estate | `test_acg_bounded_batches` |
| AC-15 | Baseline & snapshot stores pass one suite each | `test_acg_baseline_contract[...]` / `test_acg_snapshot_contract[...]` |
| AC-16 | Registers as AQService with health | `test_acg_service_health` |

## 9. Error taxonomy (contributions)

`BaselineConfigInvalid`, `BaselineNotFound`, `DriftSnapshotNotFound` (added to
`conventions.errors` + CONVENTIONS §9). Reuses `StoreUnavailable`,
`TenantScopeRequired`.

## 10. Registered event types (owned by EA-0012)

`aqelyn.config.drift_detected` (payload: `asset_id`, `baseline_id`, failed
count), `aqelyn.config.assessment_completed` (payload: `overall_score`) — via
`register_acg_events()` (EA-0003 §7). (Archive uses
`configuration.drift.detected`; mapped into the platform namespace as
`aqelyn.config.drift_detected`.)

## 11. Failure handling

- Invalid baseline/config → `BaselineConfigInvalid` at `put`/construction;
  service `unavailable` until fixed.
- Dependency unavailable → `StoreUnavailable`; service `degraded`; a partial run
  is marked incomplete in the snapshot, never presented as a clean pass.
- A single check error is recorded on that `DriftItem` (`unknown`, flagged) and
  does not abort the run.
- A failed remediation proposal leaves the finding raised and surfaces the
  delegation failure; it SHALL NOT attempt a direct asset change as a fallback.

## 12. Dependencies & consumers

- **Depends on:** EA-0002 `ObjectStore.query` + `attributes`; EA-0004
  `EvidenceStore.add`; the Finding model + pipeline; EA-0007 `prioritize`;
  **EA-0008 Workflow (remediation proposed + gated there)**; EA-0009 (optional
  baseline-as-policy); EA-0001 `AQService`.
- **Consumed by:** asset & configuration UI (inventory, drift dashboards,
  baseline coverage — **WCAG 2.2 AA** applies); EA-0010 governance reporting
  (config controls feed framework scores); auditors (baseline-conformance
  evidence packages).

## 13. Resolved / deferred decisions

- **Detect-and-propose, delegate all change** (§0) — binding; the engine never
  applies a fix.
- **Native declarative comparator baselines** are the default; **baseline-as-
  Policy (EA-0009)** is an optional authoring path for shops standardizing on
  Policy rules — same detection semantics either way.
- **Asset discovery / ingestion** (populating observed state) is out of scope —
  that arrives with connectors (later EA); this engine governs whatever observed
  state exists on the objects.
- **Auto-remediation of drift without approval** is explicitly *not* offered;
  all fixes go through the Workflow gates.
