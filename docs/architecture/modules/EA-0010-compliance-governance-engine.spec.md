# EA-0010 — Compliance & Governance Engine — Implementation Specification

**Realizes:** EA-0010 / IS-010 (supersedes the placeholder `archive/EA-0010/EA-0010_Master.md` for implementation)
**Depends on:** ADR-0001, CONVENTIONS, EA-0001 (`AQService`), EA-0002 (object estate), EA-0004 (evidence — assessments recorded), EA-0009 (Policy compliance evaluation), EA-0007 (Mission prioritization), the Finding model
**Consumed by:** governance/reporting UI (posture dashboards, framework coverage), the Finding pipeline (violations become findings), executive reporting, auditors (evidence-backed compliance packages)
**Status:** Accepted
**Change control:** ECR-0030 (object-estate pagination made effective and verified)
**Build milestone:** C-007 (see `C-007_Task_Bundle.md`)
**Definition of Ready:** see §11

---

## 0. Scope note (sequence correction)

EA-0010 is the **Compliance & Governance Engine** (Phase 3), *not* the
collection/connectors turn — per the archive, connectors and the first UI come
later in the sequence. This engine is pure analysis/orchestration over the core
already built; it introduces **no new safety or authorization surface** (all
"can I act?" decisions remain with EA-0008/EA-0009). The UI/WCAG and server
decisions attach to the *reporting surfaces that consume* this engine, not to the
engine itself.

## 1. Purpose

EA-0009 can decide whether one resource meets one compliance rule. The
Compliance & Governance Engine runs that evaluation **across the whole estate,
over time, and against named frameworks** — answering: *how compliant are we
right now, where are the gaps, which gaps matter most, is posture improving, and
can we prove it to an auditor?* It turns scattered rule results into a coherent,
explainable, evidence-backed governance picture.

## 2. Design decisions

- **D1 — Composes, does not reimplement.** Rule evaluation is `EA-0009
  evaluate_compliance`; target enumeration is `ObjectStore.query`; gap
  prioritization is `EA-0007 Mission`; gaps become findings via the Finding
  pipeline. This engine orchestrates and aggregates. Single source of truth.
- **D2 — Deterministic & pure over its inputs.** A run against a fixed estate +
  policy set + config yields identical results. No randomness. Reproducible for
  audit.
- **D3 — Posture is snapshotted, not just computed.** Each assessment run writes
  a `ComplianceSnapshot` (per-control pass/fail counts, score, timestamp) so
  posture-over-time and trend are real, queryable history — not recomputed guesses.
- **D4 — Framework mapping is declarative data.** Controls map to framework
  requirements (e.g. a control → "ISO 27001 A.9.2") via configuration; coverage
  and per-framework scores derive from that mapping. No framework logic in code.
- **D5 — Explainable end to end.** Every control result carries which
  policy/rule produced it and which objects failed; every framework score shows
  its contributing controls. Charter "explain + prove."
- **D6 — Evidence-recorded.** Each run records a `ComplianceSnapshot` and may
  emit an evidence record (EA-0004) so a posture claim is provable and
  tamper-evident. The engine itself does not mutate objects/policies.
- **D7 — Bounded & tenant-scoped.** Runs are tenant-scoped and exhaust the
  object query's cursor pages in bounded `batch_size` batches. A repeated cursor
  is a store failure, never permission to persist a partial clean snapshot
  (ECR-0030).
- **D8 — Registered as an `AQService`.**

## 3. Ubiquitous language

| Term | Meaning |
|---|---|
| **Control** | A named governance requirement, backed by one or more EA-0009 compliance rules. |
| **Assessment run** | One evaluation of controls across a scoped set of objects at a point in time. |
| **Control result** | For a control: objects evaluated, passed, failed, and the failing subjects (explainable). |
| **Compliance snapshot** | The persisted result of a run: per-control counts + score + timestamp (history, D3). |
| **Framework** | A named standard (ISO 27001, SOC 2, …); controls map to its requirements (D4). |
| **Coverage** | The fraction of a framework's requirements that have at least one mapped control. |
| **Posture score** | A `[0,1]` compliance score for a control / framework / overall, derived from pass ratios. |

## 4. Types

```
Control      = { id, name, description, policy_ids: list[str],
                 framework_refs: list[{framework: str, requirement: str}],
                 severity: str }                         # severity when failing (feeds findings)
ControlResult= { control_id, evaluated: int, passed: int, failed: int,
                 failing_subject_ids: list[str], score: float, reason: str }
ComplianceSnapshot = { id, tenant_id: str | null, run_at: datetime,
                       scope: dict, overall_score: float,
                       control_results: list[ControlResult],
                       framework_scores: dict[str, float],
                       evidence_id: str | null }
FrameworkCoverage = { framework: str, requirements: int, covered: int,
                      coverage: float, score: float }
GovernanceConfig = { controls: list[Control], frameworks: dict[str, list[str]],  # framework -> requirement ids
                     batch_size: int, min_confidence: float }
```

Reuses EA-0009 `ComplianceResult`/`ComplianceViolation`, EA-0002 `ObjectQuery`,
and the Finding model.

## 5. Interfaces (Python 3.12)

```python
from typing import Protocol, Sequence
from datetime import datetime

class SnapshotStore(Protocol):
    async def put(self, snapshot: ComplianceSnapshot) -> ComplianceSnapshot: ...
    async def get(self, snapshot_id: str) -> ComplianceSnapshot | None: ...
    async def latest(self, *, tenant_id: str | None) -> ComplianceSnapshot | None: ...
    async def history(self, *, tenant_id: str | None,
                      since: datetime | None = None, limit: int = 100) -> list[ComplianceSnapshot]: ...

class ComplianceEngine(Protocol):
    async def assess(self, *, tenant_id: str | None,
                     scope: "ObjectQuery | None" = None,
                     record_evidence: bool = True) -> ComplianceSnapshot: ...     # a run (D1-D3,D6)
    async def control_result(self, control_id: str, *, tenant_id: str | None) -> ControlResult: ...
    async def coverage(self, *, tenant_id: str | None) -> list[FrameworkCoverage]: ...   # D4
    async def trend(self, *, tenant_id: str | None, since: datetime) -> list[dict]: ...   # posture over time (D3)
    async def gaps_to_findings(self, snapshot: ComplianceSnapshot, *,
                               by, prioritize: bool = True) -> list[str]: ...     # returns finding ids
    def explain(self, result: ControlResult) -> dict: ...
```

`ComplianceGovernanceService` wraps the engine + `SnapshotStore` as an
`AQService` (name `"compliance_engine"`, depends on object store, policy engine,
mission engine, evidence/finding stores; health reflects their availability +
config validity).

## 6. Computation (the reference model)

**A run (`assess`).** Enumerate in-scope objects via `ObjectStore.query`
(paged, `batch_size`, tenant-scoped). For each `Control`, evaluate its
`policy_ids`' compliance rules against each object via
`PolicyEngine.evaluate_compliance`; tally passed/failed; `score = passed /
evaluated` (or `1.0` when `evaluated == 0`, flagged "no targets"). Aggregate
`framework_scores` from control→framework mapping (mean of contributing control
scores). `overall_score` = mean of control scores. Persist a
`ComplianceSnapshot` (D3) and, if `record_evidence`, write an evidence record
(D6). Deterministic (D2).

**Coverage.** For each framework, `covered = requirements with ≥1 mapped
control`; `coverage = covered / requirements`.

**Gaps → findings.** For each failing control, build a finding (severity from
the control, evidence = the snapshot's evidence + failing subjects, affected
objects = `failing_subject_ids`), raise it via the Finding pipeline; if
`prioritize`, order via `MissionEngine.prioritize`. The finding's mandatory
explanation fields are populated from the control (what/why/how/remediation).

## 7. Requirements

### Functional (testable)

- **FR-1** `assess` SHALL enumerate every in-scope object via `ObjectStore.query`, following `next_cursor` to exhaustion in bounded, tenant-scoped pages, and evaluate each control's rules via `PolicyEngine.evaluate_compliance` (D1/ECR-0030).
- **FR-2** `assess` SHALL be deterministic: identical estate + config + scope → identical snapshot (excluding `run_at`/ids) (D2).
- **FR-3** Each `ControlResult` SHALL report evaluated/passed/failed counts, the `failing_subject_ids`, a `score`, and an explanation (D5).
- **FR-4** A control with no in-scope targets SHALL score `1.0` flagged "no targets", never divide-by-zero.
- **FR-5** `assess` SHALL persist a `ComplianceSnapshot`; `history`/`trend`/`latest` SHALL return persisted snapshots (D3).
- **FR-6** `coverage` SHALL compute per-framework requirement coverage from the declarative control→framework mapping (D4).
- **FR-7** `framework_scores` SHALL derive from contributing control scores; every score reports its contributing controls (D5).
- **FR-8** `gaps_to_findings` SHALL raise a finding per failing control with the control's severity, the snapshot evidence, and `failing_subject_ids` as affected objects; optional Mission prioritization (D1).
- **FR-9** When `record_evidence`, `assess` SHALL write an `EvidenceRecord` for the snapshot (D6); the engine SHALL NOT mutate objects or policies.
- **FR-10** Runs SHALL be tenant-scoped; a run SHALL NOT evaluate or reference another tenant's objects (D7).
- **FR-11** Invalid config (control referencing an unknown policy, framework ref to an undefined framework requirement, `batch_size ≤ 0`) SHALL raise `GovernanceConfigInvalid`.
- **FR-12** `SnapshotStore` in-memory and Postgres implementations SHALL pass one contract suite.
- **FR-13** `ComplianceGovernanceService` SHALL register as an `AQService` with health reflecting dependency availability + config validity (EA-0001).

### Non-functional

- **NFR-1 (determinism)** identical inputs serialize to identical snapshots (excluding run id/timestamp).
- **NFR-2 (bounded)** estate processed in bounded batches (`batch_size`); memory does not scale with estate size.
- **NFR-3 (purity)** no mutation of objects/policies; only snapshot/evidence/finding writes via their stores.
- **NFR-4 (portability & typing)** in-memory + Postgres `SnapshotStore` pass one suite; `mypy --strict` + `ruff` clean.

## 8. Acceptance Criteria ↔ Tests (Definition of Ready)

| # | Criterion | Test (pytest id) |
|---|---|---|
| AC-1 | Run evaluates controls across queried objects | `test_gov_assess_estate` |
| AC-2 | Deterministic snapshot | `test_gov_deterministic` |
| AC-3 | Control result reports counts + failing subjects | `test_gov_control_result` |
| AC-4 | No-targets control scores 1.0 flagged | `test_gov_no_targets` |
| AC-5 | Snapshot persisted; history/latest/trend work | `test_gov_snapshot_history` |
| AC-6 | Framework coverage computed | `test_gov_coverage` |
| AC-7 | Framework scores derive from controls | `test_gov_framework_scores` |
| AC-8 | Gaps become prioritized findings | `test_gov_gaps_to_findings` |
| AC-9 | Evidence recorded for snapshot | `test_gov_evidence_recorded` |
| AC-10 | Engine mutates nothing (objects/policies) | `test_gov_no_side_effects` |
| AC-11 | Tenant isolation | `test_gov_tenant_isolation` |
| AC-12 | Invalid config rejected | `test_gov_config_invalid` |
| AC-13 | Bounded batching over large estate | `test_gov_bounded_batches` |
| AC-14 | In-memory & Postgres SnapshotStore pass one suite | `test_gov_snapshot_contract[inmemory]` / `[postgres]` |
| AC-15 | Registers as AQService with health | `test_gov_service_health` |
| AC-16 | Real ObjectStore pagination evaluates later estate pages | `test_gov_pages_full_estate[inmemory]` / `[postgres]` |

## 9. Error taxonomy (contributions)

`GovernanceConfigInvalid`, `SnapshotNotFound` (added to `conventions.errors` +
CONVENTIONS §9). Reuses `StoreUnavailable`, `TenantScopeRequired`.

## 10. Registered event types (owned by EA-0010)

`aqelyn.compliance.assessment_completed` (payload: `overall_score`, counts),
`aqelyn.compliance.posture_changed` (emitted when overall score crosses a
configured band vs the previous snapshot) — via `register_compliance_events()`
(EA-0003 §7).

## 11. Failure handling

- Invalid config → `GovernanceConfigInvalid` at construction; service
  `unavailable` until fixed.
- A dependency (policy/object/mission/store) unavailable → `StoreUnavailable`;
  service `degraded`; a partial run SHALL be marked incomplete in the snapshot,
  never presented as a clean pass.
- A single control evaluation error SHALL be recorded on that `ControlResult`
  (score withheld, flagged) and SHALL NOT abort the whole run.

## 12. Dependencies & consumers

- **Depends on:** EA-0009 `evaluate_compliance`; EA-0002 `ObjectStore.query`;
  EA-0007 `MissionEngine.prioritize`; EA-0004 `EvidenceStore.add`; the Finding
  pipeline; EA-0001 `AQService`.
- **Consumed by:** governance/reporting UI (posture dashboards, framework
  coverage, trend — the first surfaces where the **UI/WCAG 2.2 AA** gate
  applies); executive reporting; auditors (evidence-backed compliance packages
  built from snapshots + EA-0004 packages).

## 13. Resolved / deferred decisions

- **Compose EA-0009 rather than a second rule engine** — one evaluation
  semantics, one source of truth.
- **Snapshots as first-class history** (not recomputed) so trend/audit are real.
- **Declarative framework mapping**; named-framework *content* (the actual ISO/
  SOC requirement catalogs) is configuration/data shipped separately, not code.
- **Reporting UI is a separate surface** (later EA); this spec provides the data
  + explanations it renders, and is where the accessibility gate first binds.
