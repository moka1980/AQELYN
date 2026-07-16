# EA-0021 — Predictive Analytics & Forecasting Engine — Implementation Specification

**Realizes:** EA-0021 / IS-021 (supersedes the placeholder `archive/EA-0021/EA-0021_Master.md` for implementation)
**Depends on:** ADR-0001, CONVENTIONS, EA-0001 (`AQService`), **EA-0020 (`Derivation` + `replay` — the explainability mechanism)**, **EA-0006 (Trust — the confidence authority)**, EA-0019 (telemetry/history), EA-0013 (risk metrics), EA-0004 (evidence for *basis*)
**Consumed by:** the executive/planning UI (forecasts shown with intervals + accuracy history — a WCAG 2.2 AA surface), EA-0020 (a forecast may be a cited input to an advisory recommendation), EA-0022 (executive reporting)
**Status:** Accepted
**Build milestone:** C-018 (see `C-018_Task_Bundle.md`)
**Definition of Ready:** see §12

---

## 0. Scope reconciliation

| IS-021 component | Realization |
|---|---|
| Forecast / Prediction / Trend Analysis Engine | **New here** — owns forecasting platform-wide. |
| Simulation / Scenario Engine | **New here** — hypothetical, sandboxed "what-if" (§1 S6). |
| Confidence Engine | **Already EA-0006 Trust** (3rd request for a duplicate confidence model — reused, not rebuilt). |
| Explainability Engine | **Already EA-0020** — reuse `Derivation` + `replay()`. **One explainability mechanism platform-wide**, not a per-engine explainer. |
| *(collision)* EA-0017 `project()` | **Superseded — see ECR-0008.** EA-0017's narrow `project()` delegates here; EA-0017 keeps its S4 *stance*, which this spec inherits and generalizes. |

## 1. The central problem: there is no evidence for the future

Every module so far has been able to satisfy *evidence before opinion*. **This one
structurally cannot** — no evidence exists for an event that hasn't happened. A
platform whose whole value is "how AQELYN knows" must therefore be exact about
what a forecast *is*:

- **S1 — A forecast is not a claim about the world. It is a claim about a
  method's output given data.** *"There will be 40 phishing attempts"* is not
  provable and SHALL NOT be asserted. *"Given the last 30 days of observed
  volume and a stated seasonal-naive method, the projected 14-day volume is 40
  ± 12"* **is** provable — and that is the only shape a forecast takes here.
- **S2 — Evidence backs the basis and the method, never the outcome.** A
  `Forecast` cites the historical data and names the method; it SHALL NOT carry
  or imply evidence for what will happen. It is never usable as evidence for
  another claim.
- **S3 — Advisory only, always.** A forecast is never a finding, never evidence,
  never an action. (Inherits EA-0017 S4, generalized.)
- **S4 — No bare point estimates.** Every forecast SHALL carry an uncertainty
  **interval**; a lone number masquerades as certainty. This is a
  plain-language-honesty requirement, not a statistical nicety — a
  non-expert reading "40" believes something different from "40 ± 12".
- **S5 — Forecasts are scored against reality (the accountability rule).** When a
  horizon elapses, the forecast is **retro-scored** against what actually
  happened, and the method's **published accuracy** is derived from that history.
  A forecast that is never checked is astrology. Every forecast is therefore
  served **with its method's track record**.
- **S6 — Scenarios are sandboxed.** Simulation applies hypothetical assumptions
  over a **read-only copy**; it SHALL NOT mutate any real record, and its output
  is labeled hypothetical.
- **S7 — A forecast SHALL NOT trigger automated response.** A forecast SHALL NOT
  be usable as an input to an EA-0018 `AutomationTrigger`. Acting automatically
  on something that has not happened is precisely the harm this platform exists
  to avoid; a forecast may inform a **human**, who decides. *(EA-0018 triggers
  accept a generic `Condition` — this closes that path deliberately.)*
- **S8 — No individual-intent prediction.** Forecasts SHALL be about aggregate or
  system metrics (volumes, rates, capacity, risk trend). The engine SHALL NOT
  forecast an identified person's future behaviour or attribute intent to an
  individual. Predictive suspicion of named people is out of scope, permanently.
- **S9 — Explainability is EA-0020's `Derivation`** (replayable) and **confidence
  is EA-0006 Trust's**. No new mechanisms. **No opaque model** (EA-0020 S6): the
  method must be named, parameterized, and replayable.

Tenant-scoped, bounded, no network. No new authorization surface.

## 2. Purpose

Leaders and defenders both ask *"where is this heading?"* — is phishing volume
climbing, will patch backlog exceed capacity, is our risk trend improving. This
engine answers with **honest, bounded, checkable projections**: named methods over
cited history, uncertainty always shown, every forecast later graded against what
actually happened, and the method's real accuracy on display. Its value is not
prophecy; it is **calibrated foresight you can audit**.

## 3. Design decisions

- **D1 — Methods are explicit, named, and registered** (`moving_average`,
  `linear_trend`, `seasonal_naive`, `holt_winters`, `rate_extrapolation`) — pure
  and deterministic; each computes a point **and** an interval (S4). New methods
  are added to the registry under review, never as free-form code.
- **D2 — A `Forecast` carries an EA-0020 `Derivation`** and is invalid without a
  replayable one (S9, inheriting EA-0020 S1's structural gate).
- **D3 — `PredictionModel` is versioned; forecasts pin `model_version`**;
  promotion is explicit and attributed (EA-0020 S5 pattern). Old forecasts stay
  replayable against the version in force.
- **D4 — Outcome scoring is first-class** (S5): `resolves_at`, then an `outcome`
  (`actual`, `error`, `within_interval`), then a rolling `AccuracyRecord` per
  (method, metric).
- **D5 — Trends are measured, not asserted**: a `TrendRecord` reports slope, fit
  quality (`r_squared`), window, and basis refs — "improving/worsening" is
  derived from the number, with the number shown.
- **D6 — Registered as an `AQService`;** stores in-memory + Postgres.

## 4. Ubiquitous language

| Term | Meaning |
|---|---|
| **Method** | A named, pure forecasting function producing a point **and** interval (D1). |
| **Forecast** | A method's projection over a horizon, with interval, derivation, basis, and (later) an outcome. |
| **Basis** | The cited historical data + method the forecast derives from (S2). |
| **Interval** | The uncertainty band; mandatory (S4). |
| **Outcome / accuracy** | What actually happened vs the forecast, and the method's track record (S5). |
| **Scenario** | A sandboxed hypothetical over a read-only copy (S6). |
| **Trend** | A measured slope + fit over a window (D5). |

## 5. Types

```
Method = "moving_average" | "linear_trend" | "seasonal_naive" | "holt_winters"
       | "rate_extrapolation"

Interval  = { low: float, high: float, level: float }        # e.g. level=0.80; MANDATORY (S4)
BasisRef  = { kind: "telemetry"|"finding"|"risk"|"metric", ref: str,
              window: dict, evidence_id: str | null }         # evidence backs the BASIS (S2)

TrendRecord = { id, tenant_id, metric: str, window_days: int,
                slope: float, r_squared: float, direction: "up"|"down"|"flat",
                basis: list[BasisRef], reason: str }           # D5

Forecast  = { id, tenant_id, metric: str, subject_ref: str,    # aggregate/system only (S8)
              method: Method, model_version: int,
              horizon_days: int, issued_at: datetime, resolves_at: datetime,
              point: float, interval: Interval,                # S4
              confidence: float,                               # EA-0006 Trust (S9)
              basis: list[BasisRef],                           # S2
              derivation: "Derivation",                        # EA-0020, MANDATORY (D2/S9)
              advisory: bool = True,                           # always (S3)
              statement: str,                                  # rendered FROM the derivation
              outcome: Outcome | null }                        # filled at resolution (S5)

Outcome   = { actual: float, error: float, within_interval: bool,
              scored_at: datetime, evidence_id: str }
AccuracyRecord = { method: Method, metric: str, n: int, mae: float,
                   within_interval_pct: float, updated_at: datetime }   # published (S5)

PredictionModel = { id, method: Method, params: dict, version: int,
                    promoted_by: ActorRef | null, promoted_at: datetime | null,
                    active: bool, evidence_id: str | null }     # D3
Scenario  = { id, tenant_id, name: str, assumptions: dict, base_metric: str,
              result: dict, hypothetical: bool = True,          # S6
              derivation: "Derivation", created_by: ActorRef }
ForecastConfig = { methods_allowed: list[Method], max_horizon_days: int,
                   min_history_points: int, default_level: float, batch_size: int }
```

Reuses EA-0020 `Derivation`, EA-0006 confidence, `ActorRef`, EA-0004 evidence
refs.

## 6. Interfaces (Python 3.12)

```python
from typing import Protocol, Sequence
from datetime import datetime

class MethodRegistry(Protocol):
    def register(self, name: Method, fn: "PureForecastFn") -> None: ...   # pure; returns point+interval (D1)
    def get(self, name: Method) -> "PureForecastFn": ...                  # UnknownMethod if absent

class ForecastStore(Protocol):
    async def put(self, f: Forecast) -> Forecast: ...       # rejects: no interval, no replayable derivation
    async def get(self, forecast_id: str) -> Forecast | None: ...
    async def due_for_scoring(self, *, tenant_id: str | None,
                              now: datetime) -> list[Forecast]: ...       # S5
    async def query(self, *, tenant_id: str | None, metric: str | None = None,
                    limit: int = 100) -> list[Forecast]: ...

class ForecastingEngine(Protocol):
    async def analyze_trend(self, *, metric: str, window_days: int,
                            tenant_id: str | None) -> TrendRecord: ...     # D5
    async def forecast(self, *, metric: str, horizon_days: int, method: Method,
                       tenant_id: str | None) -> Forecast: ...             # S1-S4, S9
    async def score_due(self, *, tenant_id: str | None) -> list[Outcome]: ...  # retro-score (S5)
    async def accuracy(self, *, method: Method | None = None,
                       metric: str | None = None) -> list[AccuracyRecord]: ...  # published (S5)
    async def simulate(self, *, scenario: Scenario) -> Scenario: ...       # sandboxed (S6)
    async def propose_model_version(self, *, method: Method, params: dict,
                                    by: ActorRef) -> PredictionModel: ...  # inactive (D3)
    async def promote_model(self, version: int, *, by: ActorRef,
                            reason: str) -> PredictionModel: ...           # explicit (D3)
    def explain(self, f: Forecast) -> dict: ...                            # renders the Derivation (S9)
```

`ForecastingService` wraps engine + stores as an `AQService`
(name `"forecast_engine"`, depends on lake/trust/risk/evidence; health reflects
availability + config validity).

## 7. Computation (the reference model)

**Trend.** Fit over the window; report `slope`, `r_squared`, `direction`, basis
refs, and a reason naming the numbers (D5). Insufficient history
(`< min_history_points`) → refuse with `InsufficientHistory` — **not** a
confident-looking line through three points.

**Forecast.** Gather history (EA-0019 telemetry / risk metrics) as `BasisRef`s
with evidence; run the **registered pure method** under the **active
`PredictionModel`**; produce `point` **and** `interval` (S4); confidence from
Trust (S9); build the EA-0020 `Derivation`; render `statement` **from** it. The
store **rejects** a forecast lacking an interval or a replayable derivation.
Emits `aqelyn.forecast.generated`.

**Score.** `score_due` finds forecasts past `resolves_at`, reads the **actual**
value from the same basis metric, computes `error` + `within_interval`, writes an
`Outcome` + `EvidenceRecord`, and updates the rolling `AccuracyRecord` (S5). This
runs regardless of whether the forecast looked good — **no cherry-picking**.

**Serve.** Every forecast returned SHALL be accompanied by its method's
`AccuracyRecord` (S5) — the reader sees the track record beside the prediction.

**Simulate.** Apply `assumptions` over a **read-only** copy of the basis; produce
a labeled hypothetical `result` + derivation; mutate nothing (S6).

## 8. Requirements

### Functional (testable)

- **FR-1** A `Forecast` SHALL carry an `Interval`; a forecast without one SHALL be rejected at construction/`put` (S4).
- **FR-2** A `Forecast` SHALL carry an EA-0020 `Derivation` and SHALL be rejected if `replay(derivation) != {point, interval}` (S9/D2).
- **FR-3** `statement` and `explain` SHALL be rendered from the derivation; the engine SHALL NOT author a narrative independent of it (S9, EA-0020 S2).
- **FR-4** A forecast SHALL be `advisory=True`, SHALL NOT be raised as a finding, and SHALL NOT be usable as evidence for another claim (S2/S3).
- **FR-5** Forecast `basis` SHALL cite historical data (with evidence where available); the engine SHALL NOT imply evidence for the outcome (S2).
- **FR-6** Methods SHALL come from the registry and be pure/deterministic; an unregistered method SHALL raise `UnknownMethod` (D1).
- **FR-7** `horizon_days` SHALL be ≤ `max_horizon_days`; history below `min_history_points` SHALL raise `InsufficientHistory` rather than forecast (D5).
- **FR-8** `score_due` SHALL retro-score every forecast past `resolves_at` (not a selected subset), write an `Outcome` + evidence, and update the rolling `AccuracyRecord` (S5).
- **FR-9** `accuracy` SHALL be derived from recorded outcomes; every served forecast SHALL be accompanied by its method's `AccuracyRecord` (S5).
- **FR-10** A `Forecast` SHALL NOT be accepted as an input to an EA-0018 `AutomationTrigger`; the forecast/trigger integration SHALL refuse it (S7).
- **FR-11** `simulate` SHALL operate on a read-only copy, mutate no real record, and return `hypothetical=True` (S6).
- **FR-12** The engine SHALL NOT forecast an identified individual's future behaviour or attribute intent; `subject_ref` SHALL be an aggregate/system metric scope (S8).
- **FR-13** `confidence` SHALL come from EA-0006 Trust; no second confidence model (S9).
- **FR-14** `PredictionModel` SHALL be versioned; forecasts SHALL pin `model_version`; promotion SHALL be explicit + attributed; the engine SHALL NOT self-promote (D3).
- **FR-15** Invalid config (method not in `methods_allowed`, `max_horizon_days ≤ 0`, `min_history_points < 2`, `default_level` outside (0,1)) SHALL raise `ForecastConfigInvalid`.
- **FR-16** `ForecastStore` and the model store in-memory and Postgres implementations SHALL each pass one contract suite.
- **FR-17** `ForecastingService` SHALL register as an `AQService` with health reflecting dependency availability + config validity (EA-0001).

### Non-functional

- **NFR-1 (honest uncertainty — structural)** an interval-less or unreplayable forecast is **unrepresentable**: it cannot be constructed, stored, or served. Verified behaviourally (`replay == {point, interval}` on every forecast in the suite), per **ECR-0007** — not by textual check.
- **NFR-2 (accountability)** every elapsed forecast is scored; published accuracy is derived only from recorded outcomes, never asserted.
- **NFR-3 (no precrime)** no code path lets a forecast fire an automated action; proven by refusal tests (S7).
- **NFR-4 (bounded & typed)** horizons/history capped, batched; `mypy --strict` + `ruff` clean.

## 9. Acceptance Criteria ↔ Tests (Definition of Ready)

| # | Criterion | Test (pytest id) |
|---|---|---|
| AC-1 | Forecast without interval rejected | `test_fc_interval_required` |
| AC-2 | replay(derivation) == {point, interval} | `test_fc_replay_equals_result` |
| AC-3 | Tampered derivation → rejected, not served | `test_fc_replay_mismatch_rejected` |
| AC-4 | Statement rendered from derivation only | `test_fc_statement_from_derivation` |
| AC-5 | Advisory: not a finding, not evidence | `test_fc_advisory_only` |
| AC-6 | Basis cited; no evidence implied for outcome | `test_fc_basis_not_outcome_evidence` |
| AC-7 | Only registered pure methods | `test_fc_method_registry` |
| AC-8 | Insufficient history refuses (no 3-point line) | `test_fc_insufficient_history` |
| AC-9 | score_due scores ALL elapsed forecasts | `test_fc_score_all_due` |
| AC-10 | Accuracy derived from outcomes; served with forecast | `test_fc_accuracy_published` |
| AC-11 | Forecast cannot fire an EA-0018 trigger | `test_fc_no_automation_trigger` |
| AC-12 | Scenario sandboxed; mutates nothing | `test_fc_scenario_sandboxed` |
| AC-13 | No individual-intent forecasting | `test_fc_no_individual_prediction` |
| AC-14 | Confidence from Trust (no 2nd model) | `test_fc_confidence_from_trust` |
| AC-15 | Model versioned + pinned + explicit promote | `test_fc_model_version_pinned` |
| AC-16 | Invalid config rejected | `test_fc_config_invalid` |
| AC-17 | Forecast & model stores pass one suite each | `test_fc_store_contract[...]` / `test_fc_model_contract[...]` |
| AC-18 | Registers as AQService with health | `test_fc_service_health` |

## 10. Error taxonomy (contributions)

`ForecastConfigInvalid`, `UnknownMethod`, `InsufficientHistory`,
`ForecastNotFound`, `ForecastNotReplayable` (added to `conventions.errors` +
CONVENTIONS §9). Reuses EA-0020 `DerivationNotReplayable`, `StoreUnavailable`,
`TenantScopeRequired`.

## 11. Registered event types (owned by EA-0021)

`aqelyn.forecast.generated`, `aqelyn.forecast.scored`,
`aqelyn.forecast.trend_detected` — via `register_forecast_events()` (EA-0003 §7).
(Archive uses `forecast.generated`; kept in the platform namespace.)

## 12. Failure handling

- Invalid config → `ForecastConfigInvalid` at construction.
- Insufficient history → `InsufficientHistory`; **no forecast is issued** —
  refusing beats a confident-looking guess.
- Basis/telemetry unavailable → `StoreUnavailable`; service `degraded`; forecasts
  are **not** issued from partial history presented as complete.
- A forecast that fails to replay → **withheld**, not served with a caveat
  (EA-0020 precedent).
- Actual value unavailable at `resolves_at` → the outcome is recorded as
  `unscoreable` (flagged) and **excluded from accuracy**, never silently dropped
  in a way that flatters the track record.
- Promotion without `promoted_by` → refused (D3).

## 13. Dependencies & consumers

- **Depends on:** **EA-0020** (`Derivation` + `replay`); **EA-0006 Trust**
  (confidence); EA-0019 (history/telemetry); EA-0013 (risk metrics); EA-0004
  (evidence for basis); EA-0001 `AQService`.
- **Consumed by:** the executive/planning UI (forecast + interval + **accuracy
  history** shown together — **WCAG 2.2 AA** applies); EA-0020 (a forecast may be
  a **cited input** to an advisory recommendation); EA-0022 executive reporting.
- **Explicitly NOT consumed by:** EA-0018 automation triggers (S7).

## 14. Resolved / deferred decisions

- **A forecast is a claim about a method's output, not about the world** (S1) —
  the reframing that lets this module exist without breaking "evidence before
  opinion".
- **Intervals mandatory** (S4) and **outcomes scored** (S5) — honesty and
  accountability are structural, not editorial.
- **No automated action on a forecast** (S7) and **no individual-intent
  prediction** (S8) — both permanent.
- **Reuse EA-0020 `Derivation` + EA-0006 Trust** (S9) — one explainability
  mechanism, one confidence authority, platform-wide.
- **EA-0017 `project()` superseded** — see **ECR-0008**.
