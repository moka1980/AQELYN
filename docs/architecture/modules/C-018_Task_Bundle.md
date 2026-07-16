# C-018 Predictive Analytics & Forecasting — Implementation Task Bundle

**Milestone:** C-018 (Predictive Analytics & Forecasting, EA-0021)
**For:** Codex (implementer) · Claude Code (reviewer)
**Prerequisites:** EA-0020 merged & green (its `Derivation`/`replay` is a hard dependency); EA-0021 spec **Accepted**; **EA-0021 §1 read**; CONVENTIONS + EA-0006/0018/0019 read.
**Definition of Done:** every ticket's acceptance tests pass on in-memory **and** Postgres; `ruff` clean; `mypy --strict` clean; **every forecast has an interval and replays; every elapsed forecast is scored; no forecast can fire automation**; nothing outside the spec; `make check` green; Claude Code sign-off per ticket.

**Read EA-0021 §1 first.** There is **no evidence for the future** — this module
only works because a forecast is reframed as a claim about *a method's output
given data*, never about the world. Three properties carry that: **mandatory
intervals**, **replayable derivations**, and **outcome scoring**. Build the gates
(P1–P2) before anything can issue a forecast, and build scoring (P4) as a
first-class ticket, not an afterthought.

**Verification standard (ECR-0007):** invariants here are **structural** (an
interval-less/unreplayable forecast is unrepresentable) and **behavioural**
(`replay == {point, interval}`; a forecast offered to a trigger is refused). Do
not lean on textual checks.

## Target source layout

```
src/aqelyn/forecast/
├── __init__.py       # exports the engine, service, types, register_forecast_events
├── models.py         # Interval, BasisRef, TrendRecord, Forecast, Outcome,
│                     #   AccuracyRecord, PredictionModel, Scenario, ForecastConfig (P1)
├── methods.py        # the registered PURE methods (point + interval) + MethodRegistry (P1)
├── store.py          # ForecastStore + model store protocols (P2)
├── memory.py         # in-memory stores (P2)
├── postgres.py       # Postgres stores + DDL (P2)
├── trend.py          # analyze_trend (slope/r_squared/basis) (P3)
├── engine.py         # forecast() + explain(); derivation via EA-0020 (P3)
├── scoring.py        # score_due + accuracy (P4)
├── scenario.py       # simulate() — sandboxed (P5)
└── service.py        # ForecastingService(AQService) + register_forecast_events (P6)
tests/forecast/       # acceptance suite (in-memory + Postgres)
```

---

## P1 — Types, methods & config (intervals from the start)

**Spec:** §5, §6, D1, FR-1/6/15; §10.
**Deliverables:** the models; the **registered pure methods**, each returning
**point _and_ interval** (`moving_average`, `linear_trend`, `seasonal_naive`,
`holt_winters`, `rate_extrapolation`); `MethodRegistry` (`UnknownMethod`
otherwise); config validation (`ForecastConfigInvalid`); new error codes in
`conventions.errors` + CONVENTIONS §9.
**Depends on:** EA-0020 types, conventions.
**Acceptance:** `test_fc_method_registry`, `test_fc_config_invalid`.

## P2 — Stores + the two gates (unrepresentable, not merely forbidden)

**Spec:** §1 (S4/S9), FR-1/2/16, NFR-1.
**Deliverables:** `ForecastStore` + model store (in-memory + Postgres + DDL);
the **gates**: `put`/construction rejects a forecast with **no `Interval`** or
whose **EA-0020 `Derivation` does not replay** to `{point, interval}`.
**Depends on:** P1.
**Acceptance:** `test_fc_interval_required`, `test_fc_replay_equals_result`,
`test_fc_replay_mismatch_rejected`,
`test_fc_store_contract[inmemory]`, `test_fc_store_contract[postgres]`,
`test_fc_model_contract[inmemory]`, `test_fc_model_contract[postgres]`.

## P3 — Trend + forecast (cited basis, no invented evidence)

**Spec:** §7, FR-3/4/5/7/12/13/14, D3/D5, S1/S2/S3/S8.
**Deliverables:** `analyze_trend` (slope + `r_squared` + basis + reason);
`forecast` (basis from EA-0019/EA-0013 as `BasisRef`s, active `PredictionModel`
**pinned**, confidence from **EA-0006 Trust**, derivation built via EA-0020,
`statement` rendered **from** it, `advisory=True`); **`InsufficientHistory`
refusal**; **aggregate/system `subject_ref` only — no individual-intent
forecasting**; `explain`.
**Depends on:** P2.
**Acceptance:** `test_fc_statement_from_derivation`, `test_fc_advisory_only`,
`test_fc_basis_not_outcome_evidence`, `test_fc_insufficient_history`,
`test_fc_no_individual_prediction`, `test_fc_confidence_from_trust`,
`test_fc_model_version_pinned`.

## P4 — Outcome scoring & published accuracy (the accountability ticket)

**Spec:** §1 (S5), §7, FR-8/9, NFR-2.
**Deliverables:** `score_due` (scores **every** forecast past `resolves_at` — not
a selected subset; writes `Outcome` + evidence; `unscoreable` flagged and
**excluded** from accuracy); rolling `AccuracyRecord` per (method, metric);
**every served forecast is accompanied by its method's accuracy**.
**Depends on:** P3.
**Acceptance:** `test_fc_score_all_due`, `test_fc_accuracy_published`.

## P5 — Scenarios + the no-precrime refusal

**Spec:** §1 (S6/S7), §7, FR-10/11, NFR-3.
**Deliverables:** `simulate` (read-only copy, mutates nothing,
`hypothetical=True`); the **refusal path**: a `Forecast` offered as an EA-0018
`AutomationTrigger` input is **rejected**.
**Depends on:** P4.
**Acceptance:** `test_fc_scenario_sandboxed`, `test_fc_no_automation_trigger`.

## P6 — Service + events

**Spec:** FR-17, §11.
**Deliverables:** `ForecastingService` (`AQService`, name `"forecast_engine"`) +
`register_forecast_events`; wired into the kernel factory.
**Depends on:** P5.
**Acceptance:** `test_fc_service_health`.

---

## Review protocol (Claude Code) — honesty is the invariant here

Per ticket, confirm the normal DoD **and**, with extra scrutiny:
1. **No bare point estimates.** Try to construct/store a forecast without an
   `Interval`; assert it fails at the gate, not at a lint rule (S4).
2. **Replay is the gate.** `replay(derivation) == {point, interval}` for every
   forecast in the suite; tamper with one and assert it is **withheld**, not
   served with a caveat (S9). Behavioural — not a grep (ECR-0007).
3. **Accuracy cannot be cherry-picked.** `score_due` must score **all** elapsed
   forecasts; `unscoreable` outcomes are flagged and excluded — never dropped in
   a way that flatters the record. Accuracy must be *derived from* stored
   outcomes, never asserted (S5).
4. **No precrime.** Assert a forecast offered to an EA-0018 trigger is refused —
   there must be no path from a prediction to an automated action (S7).
5. **No individual-intent forecasting** (S8); **scenarios mutate nothing** (S6).
6. **Basis ≠ outcome evidence** — the forecast cites history; it never carries or
   implies evidence for what will happen (S2). It is never usable as evidence.
7. **No second confidence model** (EA-0006) and **no second explainer**
   (EA-0020 `Derivation`).
8. `ruff` + `mypy --strict` clean; interfaces match the spec exactly.

Merge only on green review; then **report back to the owner** before the next
module.
