# EA-0013 — Risk Intelligence Engine — Implementation Specification

**Realizes:** EA-0013 / IS-013 (supersedes the placeholder `archive/EA-0013/EA-0013_Master.md` for implementation)
**Depends on:** ADR-0001, CONVENTIONS, EA-0001 (`AQService`), the Finding model (risk signals), EA-0007 (mission-weighted impact), EA-0004 (risk & treatment evidence); reads posture/risk signals from EA-0010/0011/0012; EA-0008 (mitigation actions proposed + gated)
**Consumed by:** the risk UI (risk register, heat map, trend, treatment plans — a WCAG 2.2 AA surface), executive/board reporting, EA-0010 governance reporting, auditors (risk & treatment evidence)
**Status:** Accepted
**Build milestone:** C-010 (see `C-010_Task_Bundle.md`)
**Definition of Ready:** see §11

---

## 0. Safety boundary (read first)

This is the aggregation capstone of the governance phase: it **turns signals into
scored, treatable risks** and records treatment decisions. It does **not** take
action. A treatment decision of "mitigate" produces a finding and a **proposed,
gated Workflow run (EA-0008)** — accepting or transferring a risk is a *recorded
decision*, not an execution. Otherwise the engine is read/analysis:
deterministic, explainable, tenant-scoped, evidence-recorded. No new
authorization surface.

## 1. Purpose

Findings, compliance gaps, identity risks, and config drift each tell part of the
story. The Risk Intelligence Engine assembles them into **one register of scored
risks** — each with a likelihood, an impact, a mission-weighted score, its
contributing signals, a lifecycle, and a treatment decision — so an organization
can see *what its top risks are, why, whether they're inside appetite, whether
they're getting better or worse, and what's being done about each.* It is the
layer that answers "so, how much risk are we carrying?"

## 2. Design decisions

- **D1 — A risk is a first-class registered record, correlated from signals.**
  Signals (findings, compliance/identity/config results) are aggregated into
  `Risk` records via correlation keys; the register persists (in-memory +
  Postgres). Risks are not re-derived on every read.
- **D2 — Scoring is deterministic, bounded, explainable.** `score = f(likelihood,
  impact)` with `likelihood, impact ∈ [0,1]` and a documented combiner; impact is
  **mission-weighted** via EA-0007. Every score lists its contributing signals
  and factor values. Charter "prove it."
- **D3 — Signals compose, they are not reimplemented.** Likelihood/impact inputs
  come from Finding `severity_score`/`confidence` and from the upstream engines'
  results; threat-intel is an **evidence input** (EA-0004), correlated, never a
  live external fetch here.
- **D4 — Appetite/tolerance is declarative config.** Score → band
  (`within_appetite` / `elevated` / `over_tolerance`) via configured thresholds;
  deterministic and readable.
- **D5 — Risk lifecycle + treatment are stateful, evidenced records.**
  `identified → assessed → treated → (accepted|mitigating|transferred|closed)`;
  each transition writes an `EvidenceRecord` (EA-0004). Mitigation delegates to
  Workflow (§0/D6).
- **D6 — No direct action** (§0). Registered as an `AQService` (D7). Tenant-
  scoped and bounded (D8).
- **D7 — Trend is snapshotted.** Periodic `RiskSnapshot`s persist so score
  history / heat-map trend are real, not recomputed.

## 3. Ubiquitous language

| Term | Meaning |
|---|---|
| **Signal** | An input contributing to risk: a finding, a compliance gap, an identity risk, a config drift, a threat-intel item. |
| **Risk** | A registered record aggregating signals under a correlation key, with likelihood, impact, score, lifecycle, treatment. |
| **Likelihood / Impact** | `[0,1]` factors; impact is mission-weighted (EA-0007). |
| **Risk score** | The bounded `[0,100]` combined score (heat-map value). |
| **Appetite / tolerance** | Configured bands mapping score → within/elevated/over. |
| **Treatment** | The decision on a risk: accept / mitigate / transfer / (close). |
| **Risk snapshot** | Persisted register state at a time, for trend. |

## 4. Types

```
SignalRef   = { kind: "finding"|"compliance"|"identity"|"config"|"threat_intel",
                ref_id: str, weight: float, evidence_id: str | null }

Risk        = { id, tenant_id: str | null, correlation_key: str, title: str,
                category: str, likelihood: float, impact: float, score: float,   # score in [0,100]
                band: "within_appetite"|"elevated"|"over_tolerance",
                signals: list[SignalRef], affected_object_ids: list[str],
                top_mission_id: str | null,
                lifecycle: "identified"|"assessed"|"treated"|"closed",
                treatment: "none"|"accept"|"mitigate"|"transfer",
                treatment_note: str | null, treated_by: ActorRef | null,
                reason: str, first_seen_at: datetime, last_scored_at: datetime,
                version: int }

RiskSnapshot = { id, tenant_id: str | null, run_at: datetime,
                 total: int, band_counts: dict[str, int],
                 top_risks: list[str], overall_exposure: float }

RiskConfig  = { likelihood_weights: dict[str, float],      # per signal kind
                appetite: { elevated: float, over: float }, # score thresholds
                correlation: dict, combiner: str,           # e.g. "mission_weighted/v1"
                w_likelihood: float, w_impact: float }
```

Reuses the Finding model, EA-0007 mission impact, `ActorRef`, and EA-0004
evidence.

## 5. Interfaces (Python 3.12)

```python
from typing import Protocol, Sequence
from datetime import datetime

class RiskStore(Protocol):
    async def upsert(self, risk: Risk) -> Risk: ...                    # correlation-key dedupe, version
    async def get(self, risk_id: str) -> Risk | None: ...
    async def query(self, *, tenant_id: str | None, band: Sequence[str] | None = None,
                    lifecycle: Sequence[str] | None = None, limit: int = 100) -> list[Risk]: ...

class RiskSnapshotStore(Protocol):
    async def put(self, snapshot: RiskSnapshot) -> RiskSnapshot: ...
    async def latest(self, *, tenant_id: str | None) -> RiskSnapshot | None: ...
    async def history(self, *, tenant_id: str | None, since: datetime | None = None,
                      limit: int = 100) -> list[RiskSnapshot]: ...

class RiskIntelligenceEngine(Protocol):
    async def correlate(self, *, tenant_id: str | None,
                        scope: dict | None = None) -> list[Risk]: ...   # signals -> risks (D1/D3)
    async def score(self, risk: Risk) -> Risk: ...                      # likelihood x impact, mission-weighted (D2)
    async def assess(self, *, tenant_id: str | None) -> RiskSnapshot: ...  # correlate+score+persist+snapshot
    async def treat(self, risk_id: str, *, decision: str, by: ActorRef,
                    note: str | None, expected_version: int,
                    propose_remediation: bool = True) -> Risk: ...      # records evidence; mitigate -> Workflow (D5/§0)
    async def trend(self, *, tenant_id: str | None, since: datetime) -> list[dict]: ...
    def explain(self, risk: Risk) -> dict: ...
```

`RiskIntelligenceService` wraps the engine + both stores as an `AQService`
(name `"risk_engine"`, depends on finding/mission/evidence stores + governance
engines' outputs; health reflects their availability + config validity).

## 6. Computation (the reference model)

**Correlate.** Gather signals (open findings via `FindingStore.query`; posture
gaps, identity risks, config drift as signal refs) and group by
`correlation_key` (configurable: e.g. finding_type + affected object, or a
mapped risk category). Each group → a `Risk` with its `SignalRef`s and
`affected_object_ids`.

**Score.** `likelihood = clamp(Σ weightₖ·signalₖ_likelihood)` (per-kind weights;
findings use `confidence`); `impact = mission_weighted(max severity across
signals, EA-0007 mission factor of affected objects)`; `score = round(100 ·
(w_likelihood·likelihood + w_impact·impact))`, bounded `[0,100]`, monotonic.
`band` from appetite thresholds (D4). Deterministic (D2).

**Assess.** `correlate` → `score` each → `upsert` into the register (dedupe by
`correlation_key`, bump version) → persist a `RiskSnapshot` (D7). Emits
`aqelyn.risk.score_changed` when a risk's score crosses a band.

**Treat.** `treat` records the decision + an `EvidenceRecord`; `mitigate` also
raises a finding + a **proposed** Workflow run (§0); `accept`/`transfer` are
recorded decisions only; lifecycle advances accordingly.

## 7. Requirements

### Functional (testable)

- **FR-1** `correlate` SHALL aggregate signals (findings + governance results) into `Risk` records by `correlation_key`, each listing its `SignalRef`s and affected objects (D1/D3).
- **FR-2** `score` SHALL compute bounded `[0,100]`, mission-weighted, deterministic scores; identical signals + config → identical score (D2).
- **FR-3** Impact SHALL be mission-weighted via EA-0007; a risk on a tier-1 mission SHALL score no lower than the same risk on a lower-criticality mission (monotonic).
- **FR-4** Each `Risk` SHALL carry its contributing signals, factor values, `band`, and a plain-language `reason` (D2).
- **FR-5** `band` SHALL derive from configured appetite thresholds; deterministic (D4).
- **FR-6** `assess` SHALL upsert risks by `correlation_key` (dedupe, optimistic version) and persist a `RiskSnapshot` (D1/D7).
- **FR-7** `treat` SHALL enforce optimistic `version`, record decider/decision/time + an `EvidenceRecord`, and advance lifecycle; `mitigate` SHALL raise a finding + a **proposed** Workflow run and SHALL NOT execute mitigation directly (§0/D5).
- **FR-8** Threat-intel SHALL be consumed as an evidence-referenced signal, not a live external fetch in this engine.
- **FR-9** Runs SHALL be tenant-scoped; no cross-tenant signal or risk appears (D8).
- **FR-10** The engine SHALL NOT mutate findings/objects/governance records; it writes only risks, snapshots, evidence, and (via pipeline) findings for mitigation.
- **FR-11** Invalid config (`w_likelihood + w_impact ≠ 1 ± 1e-6`, thresholds unordered/out of range, unknown combiner) SHALL raise `RiskConfigInvalid`.
- **FR-12** `RiskStore` and `RiskSnapshotStore` in-memory and Postgres implementations SHALL each pass one contract suite.
- **FR-13** `RiskIntelligenceService` SHALL register as an `AQService` with health reflecting dependency availability + config validity (EA-0001).

### Non-functional

- **NFR-1 (no direct action)** no code path executes a mitigation or edits a signal source; mitigation delegates to Workflow (enforced by test).
- **NFR-2 (determinism)** identical signals + config → identical scores/bands.
- **NFR-3 (bounded)** correlation/scoring processes signals in bounded batches.
- **NFR-4 (portability & typing)** in-memory + Postgres stores pass their suites; `mypy --strict` + `ruff` clean.

## 8. Acceptance Criteria ↔ Tests (Definition of Ready)

| # | Criterion | Test (pytest id) |
|---|---|---|
| AC-1 | Signals correlated into risks | `test_risk_correlate` |
| AC-2 | Score bounded [0,100], deterministic | `test_risk_score_bounded` |
| AC-3 | Impact mission-weighted + monotonic | `test_risk_mission_weighted` |
| AC-4 | Risk carries signals + reason | `test_risk_explainable` |
| AC-5 | Band from appetite thresholds | `test_risk_appetite_band` |
| AC-6 | Assess upserts by correlation key + snapshot | `test_risk_assess_upsert_snapshot` |
| AC-7 | treat records evidence + version | `test_risk_treat_evidence` |
| AC-8 | mitigate → finding + proposed run, no direct action | `test_risk_mitigate_delegates` |
| AC-9 | accept/transfer are recorded decisions only | `test_risk_accept_transfer` |
| AC-10 | Threat-intel consumed as evidence signal | `test_risk_threat_intel_signal` |
| AC-11 | Engine mutates no signal source | `test_risk_no_side_effects` |
| AC-12 | Tenant isolation | `test_risk_tenant_isolation` |
| AC-13 | Trend from snapshots | `test_risk_trend` |
| AC-14 | Invalid config rejected | `test_risk_config_invalid` |
| AC-15 | Risk & snapshot stores pass one suite each | `test_risk_store_contract[...]` / `test_risk_snapshot_contract[...]` |
| AC-16 | Registers as AQService with health | `test_risk_service_health` |

## 9. Error taxonomy (contributions)

`RiskConfigInvalid`, `RiskNotFound`, `RiskSnapshotNotFound` (added to
`conventions.errors` + CONVENTIONS §9). Reuses `OptimisticConcurrencyConflict`,
`StoreUnavailable`, `TenantScopeRequired`.

## 10. Registered event types (owned by EA-0013)

`aqelyn.risk.identified`, `aqelyn.risk.score_changed` (payload: `previous_score`,
`new_score`, `band`), `aqelyn.risk.treated` — via `register_risk_events()`
(EA-0003 §7). (Archive uses `risk.score.changed`; mapped into the platform
namespace as `aqelyn.risk.score_changed`.)

## 11. Failure handling

- Invalid config → `RiskConfigInvalid` at construction; service `unavailable`.
- Dependency unavailable → `StoreUnavailable`; service `degraded`; a partial
  assessment is marked incomplete in the snapshot, never presented as clean.
- A single signal that fails to score is recorded on the risk (flagged) and does
  not abort the run.
- `treat(mitigate)` failing to propose a Workflow run leaves the decision +
  finding recorded and surfaces the delegation failure; it SHALL NOT attempt a
  direct mitigation as a fallback.

## 12. Dependencies & consumers

- **Depends on:** the Finding model + `FindingStore.query`; EA-0007
  `MissionEngine` (impact weighting); EA-0004 `EvidenceStore.add`; signal inputs
  from EA-0010/0011/0012 results; **EA-0008 Workflow (mitigation proposed +
  gated)**; EA-0001 `AQService`.
- **Consumed by:** the risk UI (register, heat map, trend, treatment — **WCAG 2.2
  AA** applies); executive/board reporting; EA-0010 governance reporting;
  auditors (risk & treatment evidence packages).

## 13. Resolved / deferred decisions

- **Risks are correlated records, not per-read derivations** — one register,
  snapshotted for trend.
- **Mission-weighted, transparent scoring** over a learned risk model, for
  auditability — consistent with Trust/Mission.
- **Threat-intel as an evidence signal**, not a live feed in this engine — live
  ingestion arrives with connectors (later EA); the correlation seam is ready.
- **Detect/score/record + delegate mitigation** (§0) is binding; the engine never
  executes treatment.
