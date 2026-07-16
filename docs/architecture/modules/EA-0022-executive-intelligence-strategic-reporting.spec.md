# EA-0022 — Executive Intelligence & Strategic Reporting Engine — Implementation Specification

**Realizes:** EA-0022 / IS-022 (supersedes the placeholder `archive/EA-0022/EA-0022_Master.md` for implementation)
**Depends on:** ADR-0001, CONVENTIONS, EA-0001 (`AQService`), **EA-0004 (evidence + self-verifying `package()` — provenance & export)**, **EA-0006 (Trust — the confidence authority)**, **EA-0020 (`Derivation` + `replay` — the one explainability mechanism)**, EA-0007 (Mission), EA-0010 (Compliance/Governance), EA-0013 (Risk), EA-0021 (Forecast), EA-0008 (Workflow — approval), EA-0009 (Policy — publication governance)
**Consumed by:** the executive/board UI (the flagship **WCAG 2.2 AA** surface — deferred to a later UI turn; this spec delivers the *data model + assembly engine*, not screens)
**Status:** Accepted
**Build milestone:** C-019 (see `C-019_Task_Bundle.md`)
**Definition of Ready:** see §9

---

## 0. Scope reconciliation

IS-022 lists eight "engines". **Four originate nothing — they are views over an
existing owner.** This is the largest duplication surface in the project so far,
and the §0 boundary is the whole safety story of this module:

> **This engine reports. It never recomputes, and it originates no claim.**
> Every number it prints already exists in an owning engine's record, backed by
> that engine's evidence. The reporting engine reads, selects, arranges, freezes,
> and cites — it does not compute a posture, a risk, a forecast, or a compliance
> verdict of its own.

| IS-022 component | Realization |
|---|---|
| Dashboard Engine | **New here** — a *data model* (widgets = cited figures + refs). Screens are a later UI turn; this milestone ships the model, not a renderer. |
| Reporting Engine | **New here** — assembles/freezes/issues `ExecutiveReport`s from cited owner records (S1, S3). |
| KPI Engine | **New here (definitions only)** — a `KPIDefinition` is a *named, versioned recipe over owner reads*; it computes no primary metric, only arithmetic over already-owned figures, each carrying `source_refs` (S1, S4). |
| Executive Briefing Engine | **New here** — briefings **rendered from records via versioned templates** (S6), never authored prose (inherits EA-0020 S2). |
| Compliance Reporting Engine | **View over EA-0010** — `coverage()`, `control_result()`, `trend()`. No recomputation. |
| Risk Summary Engine | **View over EA-0013** — `assess()`, `trend()`, `mission_impact()`. No recomputation. |
| Forecast Summary Engine | **View over EA-0021** — `published_forecasts()`, `accuracy()`; **intervals + accuracy preserved** (S7). |
| Mission Summary Engine | **View over EA-0007** — `criticality_of()`, `mission_impact()`. No recomputation. |
| *(reuse)* Confidence | **EA-0006 Trust** — 4th request for a duplicate confidence model; reused, not rebuilt. |
| *(reuse)* Explainability | **EA-0020 `Derivation` + `replay`** — one mechanism platform-wide. |
| *(reuse)* Export | **EA-0004 `package()` / `verify_package()`** — reports export as self-verifying evidence packages, not fresh artifacts. |
| *(reuse)* Approval / publication | **EA-0008 Workflow** gates + **EA-0009 Policy** — no second approval path. |

Tenant-scoped, append-only, no network, no new authorization surface (roles are
EA-0009/EA-0011's).

## 1. The central problem: simplification is where evidence dies

Every prior module could satisfy *evidence before opinion* at the point of
computation. Executive reporting is where a platform usually **severs its own
evidence chain**: a board slide reading *"Posture: 73 — Amber"* is exactly the
un-evidenced verdict AQELYN exists **not** to be. The archive master is naïve
about this — it treats explainability as a checklist of fields (§22.3) and even
*permits the hazard* in failure handling (master §28.2 "Fallback metrics
displayed", §28.3 "Previous values retained"). Those two clauses are
**deliberately overridden** here (see **ECR-0009**). The chain is held to the
boardroom by seven rules:

- **S1 — No number without provenance.** Every figure a report or dashboard
  carries `source_refs` back to the owning engine's record(s) and their evidence;
  `drill_down()` returns them. A figure that cannot be traced **cannot be
  included** — rejected at *assembly*, not by convention. A KPI is not
  executive-grade without data-source lineage (master §22.4).
- **S2 — The engine reports; it never recomputes and originates no claim.** Every
  primary figure comes from an owning engine's read API (§0). The engine performs
  only *presentation arithmetic* (rollups/deltas over already-owned figures), and
  even that carries the `source_refs` of its inputs. It raises no finding, asserts
  no posture, and is never usable as evidence for another claim.
- **S3 — An issued report is immutable and reproducible.** Issuance **freezes its
  inputs** and **pins definition versions**. Later data changes SHALL NOT mutate
  an issued report; a re-run produces a **new** report. This is the difference
  between a report and a dashboard: a dashboard is live; a **board artifact must
  still mean what it meant when issued**. Report history is append-only.
- **S4 — KPI definitions are versioned and pinned.** "Posture" cannot be quietly
  redefined to look better between quarters. A definition change is a **new
  version**, explicitly promoted (EA-0020 S5 pattern); historical reports read
  against the **version in force at issuance**. No metric-gaming by redefinition.
- **S5 — Material exceptions cannot be omitted.** The engine assembles the
  exceptions section **itself** from the owners; report config **cannot suppress
  it**. If the exceptions query is **unavailable, issuance is refused** rather than
  emitting a clean-looking report. A green aggregate over an unreported fire is a
  lie.
- **S6 — Briefings are rendered, not authored.** Executive briefings and summaries
  are produced **from records via versioned templates**; the engine SHALL NOT
  author free narrative prose (inherits EA-0020 S2 — an executive summary is not a
  place to start inventing).
- **S7 — Uncertainty survives summarization.** A forecast summary SHALL carry the
  forecast's **interval and its method's accuracy**; a report SHALL NOT strip the
  uncertainty off a prediction to present a bare number (EA-0021 S4 preserved).

## 2. Purpose

Leadership asks: *what is our cyber posture, which missions are most at risk, is
security improving or degrading, which compliance objectives are slipping?* This
engine answers at board altitude **without severing provenance**: every figure is
a cited read from the engine that owns it, every issued report is frozen and
reproducible, every KPI has a versioned definition, and material exceptions can
never be summarized away. Its value is not the slide; it is **a board artifact you
can drill from a single number all the way down to the evidence**.

## 3. Design decisions

- **D1 — A `Figure` is the atom, and it is never bare.** Every value placed in a
  dashboard widget, KPI, or report section is a `Figure { value, unit,
  source_refs[], confidence?, as_of }`. A `Figure` without `source_refs` is
  **unrepresentable** (constructor + assembly gate) — this is S1 made structural
  per ECR-0007.
- **D2 — `KPIDefinition` is a versioned recipe, not a number.** It names inputs
  (owner read + selector), an arithmetic combinator, unit, and thresholds;
  `version` is pinned by every `KPIRecord` computed from it (S4). Promotion is
  explicit + attributed; the engine SHALL NOT self-promote.
- **D3 — Issuance freezes.** `issue(report)` snapshots every `Figure` and pins
  every `KPIDefinition.version` and owner `as_of`, producing an immutable
  `ExecutiveReport` with a content hash. Re-issuing over changed data mints a new
  report id (S3).
- **D4 — The exceptions section is engine-assembled and mandatory.** It is built
  from the owners (open criticals, overdue controls, breached-interval forecasts,
  degraded missions), is **not** part of caller-supplied config, and its
  unavailability **blocks issuance** (S5).
- **D5 — Summaries/briefings render from a versioned template over cited
  records** (S6); the rendered text embeds the same `source_refs`.
- **D6 — Explainability & confidence are reused, not rebuilt:** `drill_down()`
  returns the owner records + EA-0004 evidence (and, where a figure derives from an
  EA-0020 recommendation, its replayable `Derivation`); confidence is EA-0006
  Trust's. Export is EA-0004 `package()` (self-verifying).
- **D7 — Registered as an `AQService`;** stores in-memory + Postgres; append-only.

## 4. Ubiquitous language

| Term | Meaning |
|---|---|
| **Figure** | An atomic reported value with mandatory `source_refs` (D1/S1). |
| **KPIDefinition / KPIRecord** | A versioned recipe (D2/S4) and one computed, pinned instance of it. |
| **ExecutiveReport** | A frozen, hash-stamped, cited, immutable board artifact (D3/S3). |
| **Dashboard** | A *live* view of current figures — explicitly **not** frozen (contrast S3). |
| **ExecutiveBriefing** | Template-rendered narrative over cited records (D5/S6). |
| **Exceptions section** | Engine-assembled, unsuppressable material-exception list (D4/S5). |
| **drill_down** | The provenance walk from a figure to owner records + evidence (D6/S1). |

## 5. Types

```
Ref        = { kind: "risk"|"compliance"|"forecast"|"mission"|"finding"|"recommendation"|"evidence",
               ref_id: str, as_of: datetime, evidence_id: str | null }   # provenance atom (S1)

Figure     = { value: float | str, unit: str, source_refs: list[Ref],    # source_refs MANDATORY (D1/S1)
               confidence: float | null, as_of: datetime }               # confidence = EA-0006 Trust

KPIDefinition = { id, key: str, version: int, title: str,
                  inputs: list[dict], combinator: str, unit: str,
                  thresholds: dict,                                       # e.g. {amber: 60, red: 40}
                  promoted_by: ActorRef | null, promoted_at: datetime | null,
                  active: bool }                                          # versioned + pinned (S4/D2)
KPIRecord  = { id, tenant_id, kpi_key: str, definition_version: int,     # pins the version in force (S4)
               figure: Figure, reporting_period: str, band: str }        # band derived from thresholds

ReportSection = { key: str, title: str, figures: list[Figure],
                  narrative: str | null,                                 # rendered from template only (S6)
                  template_version: int | null }
ExecutiveReport = { id, tenant_id, title: str, version: int,
                    period: str, sections: list[ReportSection],
                    exceptions: list[Figure],                            # engine-assembled, mandatory (D4/S5)
                    approval_status: "draft"|"pending"|"approved"|"published",
                    issued_at: datetime | null, issued_by: ActorRef | null,
                    content_hash: str | null,                            # set at issuance (D3/S3)
                    frozen: bool = false }                               # true once issued (S3)

Dashboard  = { id, tenant_id, owner: ActorRef, widgets: list[Figure],   # LIVE, never frozen (S3 contrast)
               refresh_interval: int }
ExecutiveBriefing = { id, tenant_id, audience: str, template_version: int,
                      sections: list[ReportSection], recommendations: list[Ref],  # cited (S6)
                      generated_at: datetime }
ReportConfig = { sections: list[str], period: str, audience: str }       # CANNOT list/suppress exceptions (S5)
```

Reuses `ActorRef`, EA-0004 evidence refs + `package`, EA-0006 confidence,
EA-0020 `Derivation` (via `drill_down`).

## 6. Interfaces (Python 3.12)

```python
from typing import Protocol, Sequence
from datetime import datetime

class KPIRegistry(Protocol):
    async def propose(self, d: KPIDefinition, *, by: ActorRef) -> KPIDefinition: ...   # inactive (D2)
    async def promote(self, key: str, version: int, *, by: ActorRef,
                      reason: str) -> KPIDefinition: ...                 # explicit + attributed (S4)
    async def active(self, key: str) -> KPIDefinition: ...              # the version in force

class ReportStore(Protocol):
    async def put(self, r: ExecutiveReport) -> ExecutiveReport: ...     # rejects a frozen-report mutation (S3)
    async def get(self, report_id: str, *, tenant_id: str | None) -> ExecutiveReport | None: ...
    async def query(self, *, tenant_id: str | None, period: str | None = None,
                    limit: int = 100) -> list[ExecutiveReport]: ...

class ExecutiveEngine(Protocol):
    async def compute_kpi(self, *, key: str, period: str,
                          tenant_id: str | None) -> KPIRecord: ...        # reads owners; pins version (S1/S4)
    async def assemble(self, *, config: ReportConfig,
                       tenant_id: str | None) -> ExecutiveReport: ...     # draft; figures cited; +exceptions (S1/S5)
    async def issue(self, report_id: str, *, by: ActorRef,
                    tenant_id: str | None) -> ExecutiveReport: ...        # freezes + hashes (S3); refuses if exceptions unavailable (S5)
    async def drill_down(self, *, figure_ref: str,
                         tenant_id: str | None) -> list[Ref]: ...         # provenance walk (S1/D6)
    async def brief(self, *, audience: str, period: str,
                    tenant_id: str | None) -> ExecutiveBriefing: ...      # template-rendered (S6)
    async def dashboard(self, *, dashboard_id: str,
                        tenant_id: str | None) -> Dashboard: ...          # LIVE figures (not frozen)
    async def export(self, report_id: str, *, by: ActorRef,
                     tenant_id: str | None) -> str: ...                   # EA-0004 package id (D6)
```

`ExecutiveService` wraps engine + stores as an `AQService`
(name `"executive_engine"`, depends on mission/governance/risk/forecast/trust/
evidence; health reflects owner-read availability + config validity). Cross-owner
dependencies SHALL be typed as the owners' Protocols (not `object`) — see the
carried-forward note in §13.

## 7. Assembly (the reference model)

**KPI.** `compute_kpi` loads the **active** `KPIDefinition`, reads each input from
its **owning engine** (never recomputing it), applies the combinator, and emits a
`KPIRecord` whose `figure.source_refs` cite every owner record + evidence and
whose `definition_version` pins the recipe in force (S1/S4). A missing input →
the KPI is **omitted and recorded in `excludes`**, never silently zeroed (§12).

**Assemble.** For each requested section, gather `Figure`s from the owners (each
cited, S1). Then **the engine itself** appends the **exceptions** section from the
owners (open criticals, overdue controls, forecasts that breached their interval,
degraded missions) — this is not caller-controllable and cannot be suppressed
(S5). Result is a `draft` report; nothing is frozen yet.

**Issue.** `issue` snapshots every `Figure`, pins every `KPIDefinition.version`
and owner `as_of`, computes a `content_hash`, sets `frozen=True` and
`approval_status` via the **EA-0008** approval gate. If the **exceptions query is
unavailable at issuance, issuance is refused** (`ExceptionsUnavailable`) — no
clean-looking report is emitted (S5). A subsequent re-issue over changed data
mints a **new** report id (S3); the store rejects any write that would mutate a
frozen report.

**Brief / dashboard.** Briefings render section narratives from a **versioned
template** over the cited records (S6). Dashboards return **live** figures and are
explicitly **not** frozen — the S3 immutability applies to issued reports only.

**Drill down / export.** `drill_down` walks a figure's `source_refs` to the owner
records + EA-0004 evidence (and a `Derivation` where the figure came from an
EA-0020 recommendation). `export` produces an EA-0004 self-verifying `package`.

## 8. Requirements

### Functional (testable)

- **FR-1** Every `Figure` SHALL carry non-empty `source_refs`; a `Figure` without
  them SHALL be rejected at construction and at assembly (S1/D1).
- **FR-2** The engine SHALL NOT compute a primary metric; every primary figure
  SHALL originate from an owning engine's read API, and presentation arithmetic
  SHALL carry its inputs' `source_refs` (S2).
- **FR-3** `drill_down(figure_ref)` SHALL return the owner records + evidence refs
  backing that figure (S1/D6).
- **FR-4** An issued (`frozen`) `ExecutiveReport` SHALL be immutable: the store
  SHALL reject any write that mutates a frozen report; re-issuing over changed
  data SHALL mint a new report id (S3).
- **FR-5** `issue` SHALL pin `KPIDefinition.version` and owner `as_of` and set a
  `content_hash`; a later definition/data change SHALL NOT alter the issued
  report (S3/S4).
- **FR-6** A `KPIDefinition` SHALL be versioned; every `KPIRecord` SHALL pin the
  `definition_version` in force; promotion SHALL be explicit + attributed and the
  engine SHALL NOT self-promote (S4/D2).
- **FR-7** The exceptions section SHALL be engine-assembled from the owners and
  SHALL NOT be suppressible by `ReportConfig` (S5/D4).
- **FR-8** If the exceptions source is unavailable at issuance, `issue` SHALL raise
  `ExceptionsUnavailable` and issue nothing (S5).
- **FR-9** A missing KPI input SHALL cause the KPI to be **omitted and recorded in
  `excludes`**, never silently zeroed or backfilled with a prior value (§12,
  ECR-0009).
- **FR-10** Briefing/section narrative SHALL be rendered from a versioned template
  over cited records; the engine SHALL NOT author free prose (S6).
- **FR-11** A forecast summary figure SHALL carry the forecast interval and the
  method's accuracy; a report SHALL NOT reduce a forecast to a bare point (S7).
- **FR-12** The engine SHALL raise no finding and its outputs SHALL NOT be usable
  as evidence for another claim (S2).
- **FR-13** `confidence` on a `Figure` SHALL come from EA-0006 Trust; no second
  confidence model (§0).
- **FR-14** `export` SHALL produce an EA-0004 self-verifying package; report
  publication SHALL pass the EA-0008 approval gate + EA-0009 policy (§0).
- **FR-15** `ReportStore`/`KPIRegistry` in-memory and Postgres implementations
  SHALL each pass one contract suite.
- **FR-16** `ExecutiveService` SHALL register as an `AQService` with health
  reflecting owner-read availability + config validity (EA-0001).

### Non-functional

- **NFR-1 (provenance — structural)** a `Figure` without `source_refs`, and a
  mutation of a frozen report, are **unrepresentable** — not constructible/
  storable. Verified **behaviourally** (a spy proving every reported figure
  drills to a real owner record; a frozen-report write raises) per **ECR-0007**,
  not by textual check.
- **NFR-2 (no silent omission)** every excluded KPI/section appears in `excludes`;
  a missing number **looks missing** (ECR-0009), proven by a fail-closed test.
- **NFR-3 (reproducibility)** issuing twice over identical owner state yields an
  identical `content_hash`; over changed state yields a new id — proven by test.
- **NFR-4 (bounded & typed)** report/section sizes bounded; cross-owner deps typed
  as Protocols; `mypy --strict` + `ruff` clean.

## 9. Acceptance Criteria ↔ Tests (Definition of Ready)

| # | Criterion | Test (pytest id) |
|---|---|---|
| AC-1 | Figure without source_refs rejected (construct + assemble) | `test_ex_figure_requires_provenance` |
| AC-2 | Engine recomputes nothing; every primary figure cites an owner | `test_ex_no_recomputation` |
| AC-3 | drill_down walks figure → owner records + evidence | `test_ex_drill_down` |
| AC-4 | Frozen report is immutable; store rejects mutation | `test_ex_frozen_report_immutable` |
| AC-5 | Re-issue over changed data mints a new id; hash stable on identical state | `test_ex_issue_reproducible` |
| AC-6 | KPI definition versioned + pinned; explicit promote only | `test_ex_kpi_definition_versioned` |
| AC-7 | Exceptions section engine-assembled, not suppressible | `test_ex_exceptions_not_suppressible` |
| AC-8 | Exceptions unavailable at issuance → refuse, issue nothing | `test_ex_exceptions_unavailable_refuses` |
| AC-9 | Missing KPI input → omitted + in `excludes`, not zeroed | `test_ex_missing_kpi_excluded` |
| AC-10 | Narrative rendered from template only (no free prose) | `test_ex_narrative_from_template` |
| AC-11 | Forecast summary keeps interval + accuracy | `test_ex_forecast_uncertainty_preserved` |
| AC-12 | Engine raises no finding; output not usable as evidence | `test_ex_no_claim_originated` |
| AC-13 | Confidence from Trust (no 2nd model) | `test_ex_confidence_from_trust` |
| AC-14 | Export is an EA-0004 self-verifying package; publish gated by EA-0008/0009 | `test_ex_export_package` / `test_ex_publish_gated` |
| AC-15 | Report & KPI stores pass one suite each | `test_ex_store_contract[...]` / `test_ex_kpi_contract[...]` |
| AC-16 | Registers as AQService with health | `test_ex_service_health` |

## 10. Error taxonomy (contributions)

`ExecutiveConfigInvalid`, `FigureProvenanceMissing`, `FrozenReportMutation`,
`ExceptionsUnavailable`, `KPIDefinitionNotFound`, `ReportNotFound` (added to
`conventions.errors` + CONVENTIONS §9). Reuses EA-0020
`DerivationNotReplayable`, `StoreUnavailable`, `TenantScopeRequired`, and the
EA-0008 approval-gate errors.

## 11. Registered event types (owned by EA-0022)

`aqelyn.executive.report_issued`, `aqelyn.executive.kpi_calculated`,
`aqelyn.executive.briefing_completed`, `aqelyn.executive.dashboard_updated`,
`aqelyn.executive.summary_generated` — via `register_executive_events()`
(EA-0003 §7). (Archive uses `report.generated` etc.; kept in the platform
namespace.)

## 12. Failure handling

- Invalid config → `ExecutiveConfigInvalid` at construction.
- A missing KPI input / unavailable owner read → the KPI or section is **omitted
  and recorded in `excludes`**; it is **never silently zeroed** and **never
  backfilled with a prior value** (**ECR-0009** — overrides master §28.2/§28.3). A
  missing number must look missing.
- Exceptions source unavailable at issuance → `ExceptionsUnavailable`; **nothing
  is issued** (S5) — refusing beats a clean-looking report.
- Attempt to mutate a frozen report → `FrozenReportMutation` (S3).
- A figure that cannot be traced to an owner record → `FigureProvenanceMissing` at
  assembly; the figure is withheld, not printed with a caveat (EA-0020 precedent).
- Publication without EA-0008 approval / failing EA-0009 policy → blocked (master
  §28.4 preserved).

## 13. Dependencies & consumers

- **Depends on:** **EA-0020** (`Derivation`/`replay`), **EA-0006 Trust**
  (confidence), **EA-0004** (evidence + `package`), **EA-0007** (mission),
  **EA-0010** (compliance), **EA-0013** (risk), **EA-0021** (forecast — intervals
  + accuracy), **EA-0008** (approval), **EA-0009** (policy), EA-0001 `AQService`.
  All cross-owner deps SHALL be typed as the owners' Protocols — this module widens
  the dependency graph the most, so the standing type-tightening follow-up
  (forecast `lake_service`/`risk_engine`, lake `audit_store`) SHALL land **before**
  C-019 rather than after.
- **Consumed by:** the executive/board UI (**WCAG 2.2 AA** — the flagship
  "understandable by a non-expert" surface; deferred to a UI turn).
- **Explicitly NOT:** a claim authority. It originates nothing (S2).

## 14. Resolved / deferred decisions

- **This engine reports; it never recomputes and originates no claim** (S2) — the
  boundary that lets an executive layer exist without severing provenance.
- **Provenance is structural** (S1/D1) and **issued reports are frozen +
  reproducible** (S3/D3) — honesty is not editorial.
- **KPI definitions versioned + pinned** (S4) and **exceptions unsuppressible**
  (S5) — no metric-gaming, no summarizing away a fire.
- **Master §28.2/§28.3 overridden** — a missing number is omitted and marked, not
  backfilled/faked. See **ECR-0009**.
- **Dashboards/screens deferred** to a later UI turn; this milestone is the data
  model + assembly engine.
