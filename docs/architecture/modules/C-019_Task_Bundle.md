# C-019 Executive Intelligence & Strategic Reporting — Implementation Task Bundle

**Milestone:** C-019 (Executive Intelligence & Strategic Reporting, EA-0022)
**For:** Codex (implementer) · Claude Code (reviewer)
**Prerequisites:** EA-0021 merged & green; EA-0022 spec **Accepted**; **EA-0022 §1 read**; CONVENTIONS + EA-0004/0007/0010/0013/0020/0021 read.
**Definition of Done:** every ticket's acceptance tests pass on in-memory **and** Postgres; `ruff` clean; `mypy --strict` clean; **no figure without provenance; issued reports immutable; exceptions unsuppressable**; nothing outside the spec; `make check` green; Claude Code sign-off per ticket.

**Read EA-0022 §1 first.** This module is where a security platform usually
severs the evidence chain: a board slide reading *"Posture: 73 — Amber"* with
nothing behind it. It doesn't here, because **a figure without `source_refs`
cannot be included in a report**. This engine **reports**; it never recomputes
and never originates a claim (§0). If a needed behavior isn't in the spec, raise
an ECR.

**Verification standard (ECR-0007):** invariants are **structural** (no-provenance
figures unrepresentable; issued reports immutable) and **behavioural** (every KPI
in the suite drills down to real owner records; configuring away the exceptions
section fails). Not textual checks.

## Target source layout

```
src/aqelyn/executive/
├── __init__.py       # exports the engine, service, types, register_executive_events
├── models.py         # SourceRef, KPIDefinition, KPIRecord, ExceptionItem,
│                     #   ExecutiveReport, ExecutiveBriefing, Dashboard, ReportConfig (X1)
├── definitions.py    # KPIDefinitionStore + versioned promote (X1)
├── kpi.py            # compute_kpi — reads owners, builds provenance + derivation (X2)
├── exceptions.py     # engine-assembled material exceptions (X3)
├── report.py         # assemble_report + issue_report (freeze/pin/evidence) + drill_down (X3)
├── briefing.py       # render_briefing — template + data only (X4)
├── store.py          # ReportStore protocol (X2)
├── memory.py         # in-memory stores (X2)
├── postgres.py       # Postgres stores + DDL (X2)
└── service.py        # ExecutiveIntelligenceService(AQService) + register_executive_events (X5)
tests/executive/      # acceptance suite (in-memory + Postgres)
```

---

## X1 — Types + versioned KPI definitions

**Spec:** §5, §6, D1, S4, FR-8/15; §10.
**Deliverables:** the models; `KPIDefinitionStore` (new version per change,
**inactive until an explicit attributed `promote`**; never mutate active);
config/definition validation (`ReportConfigInvalid` on unknown source engine/
metric, unordered thresholds, `max_kpis ≤ 0`); new error codes in
`conventions.errors` + CONVENTIONS §9.
**Depends on:** EA-0020/0006 types, conventions.
**Acceptance:** `test_exec_definition_promote`, `test_exec_config_invalid`.

## X2 — KPI computation + the provenance gate + stores

**Spec:** §1 (S1/S6), §7, FR-1/2/3/14/16, NFR-1.
**Deliverables:** `compute_kpi` — **read the value from the owning engine's
record** (EA-0010/EA-0013/EA-0021/EA-0007), **never recompute**; collect
`source_refs` (+ evidence); EA-0020 `Derivation` where composed; confidence from
EA-0006. **The gate:** a `KPIRecord` with empty `source_refs` is rejected.
`ReportStore` + definition store (in-memory + Postgres + DDL). `drill_down`.
**Depends on:** X1.
**Acceptance:** `test_exec_provenance_required`, `test_exec_drill_down`,
`test_exec_no_recomputation`, `test_exec_composed_not_reinvented`,
`test_exec_def_contract[inmemory]`, `test_exec_def_contract[postgres]`,
`test_exec_report_contract[inmemory]`, `test_exec_report_contract[postgres]`.

## X3 — Assembly, unsuppressable exceptions & immutable issuance

**Spec:** §1 (S3/S5/S8), §7, FR-5/6/7/9/10/11, NFR-2/NFR-3.
**Deliverables:** `assemble_report` (draft; declares `scope` + `excludes`;
**engine adds the exceptions section itself** — config cannot remove it; forecast
figures keep `Interval` + accuracy); `issue_report` (freeze
`input_snapshot_ids`, pin `pinned_definitions`, `issued_by/at`, `EvidenceRecord`);
**issued reports immutable** (`FrozenReportMutation`); historical reads use **pinned**
versions; **issuance refused if the exceptions query is unavailable** (fail-closed).
**Depends on:** X2.
**Acceptance:** `test_exec_issue_freezes`, `test_exec_report_immutable`,
`test_exec_pinned_definitions`, `test_exec_exceptions_unsuppressable`,
`test_exec_forecast_interval_kept`, `test_exec_scope_declared`.

## X4 — Briefings + export (rendered, self-verifying)

**Spec:** §1 (S2/S7), §7, FR-4/12/13, D5.
**Deliverables:** `render_briefing` (versioned template applied to report
records; **no figure or claim absent from the report**); `export` → a
**self-verifying EA-0004 `package`**; read-only throughout (no findings, no
actions, no source mutation).
**Depends on:** X3.
**Acceptance:** `test_exec_briefing_from_records`, `test_exec_export_package`,
`test_exec_read_only`.

## X5 — Service + events

**Spec:** FR-17, §11.
**Deliverables:** `ExecutiveIntelligenceService` (`AQService`, name
`"executive_engine"`) + `register_executive_events`; wired into the kernel
factory.
**Depends on:** X4.
**Acceptance:** `test_exec_service_health`.

---

## Review protocol (Claude Code) — keep the boardroom attached to the evidence

Per ticket, confirm the normal DoD **and**, with extra scrutiny:
1. **No number without provenance.** Try to assemble a report containing a KPI
   with empty `source_refs`; assert it fails at the gate. Then assert **every**
   KPI in the suite drills down to real owner records + evidence (S1/NFR-1).
2. **No recomputation.** Values must be **read from** EA-0010/0013/0021/0007
   records — trace it. This engine originates no claim (S6).
3. **Issued reports are immutable.** Mutate one; assert `FrozenReportMutation`.
   Change the underlying data; assert the issued report does **not** change and a
   re-run yields a **new** report (S3).
4. **Definitions pinned.** Promote a new KPI definition version; assert a
   historical report still reads its **pinned** version (S4) — no metric-gaming
   by redefinition.
5. **Exceptions cannot be suppressed.** Configure them away; assert the section
   is still assembled. Make the exceptions query unavailable; assert issuance is
   **refused** rather than issuing a clean-looking report (S5, fail-closed).
6. **Briefings render from records only** — no prose path that could introduce a
   figure or claim absent from the report (S2, EA-0020 precedent).
7. **Forecasts keep their intervals + accuracy** — a report may not strip
   uncertainty off a prediction (D6).
8. Missing owner data → the KPI is **omitted and recorded in `excludes`**, never
   silently zeroed or staled. A missing number must look missing.
9. Export is an EA-0004 package (no bespoke integrity); tenant-scoped; `ruff` +
   `mypy --strict` clean.

Merge only on green review; then **report back to the owner** before the next
module.
