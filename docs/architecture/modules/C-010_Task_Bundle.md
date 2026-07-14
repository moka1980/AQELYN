# C-010 Risk Intelligence — Implementation Task Bundle

**Milestone:** C-010 (Risk Intelligence, EA-0013)
**For:** Codex (implementer) · Claude Code (reviewer)
**Prerequisites:** EA-0012 merged & green; EA-0013 spec **Accepted**; CONVENTIONS + Finding model + EA-0007/0008 read.
**Definition of Done:** every ticket's acceptance tests pass on in-memory **and** Postgres; `ruff` clean; `mypy --strict` clean; **the engine never executes a treatment/mitigation**; nothing outside the spec; `make check` green; Claude Code sign-off per ticket.

This engine **composes** shipped contracts (findings + governance signals,
Mission weighting, Evidence, Workflow). All action is delegated to EA-0008 (§0).
If a needed behavior isn't in the spec, raise an ECR.

## Target source layout

```
src/aqelyn/risk/
├── __init__.py       # exports the engine, service, types, register_risk_events
├── models.py         # SignalRef, Risk, RiskSnapshot, RiskConfig (R1)
├── scoring.py        # likelihood x impact, mission-weighted combiner (R1/R2)
├── correlate.py      # signals -> risks by correlation_key (R2)
├── store.py          # RiskStore + RiskSnapshotStore protocols (R3)
├── memory.py         # in-memory stores (R3)
├── postgres.py       # Postgres stores + DDL (R3)
├── engine.py         # assess + treat (records evidence; mitigate -> Workflow) + trend (R3/R4)
└── service.py        # RiskIntelligenceService(AQService) + register_risk_events (R5)
tests/risk/           # acceptance suite (in-memory + Postgres)
```

---

## R1 — Types, config & scoring

**Spec:** §4, §6 (score), FR-2/3/5/11, D2/D4; §9.
**Deliverables:** the models; the deterministic bounded scorer (likelihood x
impact, mission-weighted, band from appetite); `RiskConfig` validation
(`RiskConfigInvalid` on weights ≠ 1, unordered/out-of-range thresholds, unknown
combiner); new error codes in `conventions.errors` + CONVENTIONS §9.
**Depends on:** Finding model, EA-0007 types, conventions.
**Acceptance:** `test_risk_score_bounded`, `test_risk_mission_weighted`,
`test_risk_appetite_band`, `test_risk_config_invalid`.

## R2 — Correlation

**Spec:** §6, FR-1/4/8/9, D1/D3.
**Deliverables:** `correlate` (gather findings via `FindingStore.query` +
governance signal refs, group by `correlation_key`, threat-intel as evidence
signal), `explain`, tenant-scoped, bounded.
**Depends on:** R1.
**Acceptance:** `test_risk_correlate`, `test_risk_explainable`,
`test_risk_threat_intel_signal`, `test_risk_tenant_isolation`.

## R3 — Register, snapshots & assess

**Spec:** §5, §6, FR-6/10/12, D1/D7.
**Deliverables:** `RiskStore` + `RiskSnapshotStore` (in-memory + Postgres + DDL,
correlation-key dedupe + optimistic version); `assess` (correlate + score +
upsert + snapshot); `trend`; no mutation of signal sources.
**Depends on:** R2.
**Acceptance:** `test_risk_assess_upsert_snapshot`, `test_risk_trend`,
`test_risk_no_side_effects`,
`test_risk_store_contract[inmemory]`, `test_risk_store_contract[postgres]`,
`test_risk_snapshot_contract[inmemory]`, `test_risk_snapshot_contract[postgres]`.

## R4 — Treatment (delegate-only) + evidence

**Spec:** §0, §6, FR-7, D5, NFR-1; EA-0004 evidence; EA-0008 propose.
**Deliverables:** `treat` (optimistic version, records `EvidenceRecord`, advances
lifecycle; `mitigate` → finding + **proposed** Workflow run; `accept`/`transfer`
= recorded decisions only; never direct action).
**Depends on:** R3.
**Acceptance:** `test_risk_treat_evidence`, `test_risk_mitigate_delegates`,
`test_risk_accept_transfer`.

## R5 — Service + events

**Spec:** FR-13, §10.
**Deliverables:** `RiskIntelligenceService` (`AQService`, name `"risk_engine"`) +
`register_risk_events` (`identified`, `score_changed`, `treated`); wired into the
kernel factory.
**Depends on:** R4.
**Acceptance:** `test_risk_service_health`.

---

## Review protocol (Claude Code)

Per ticket, confirm the normal DoD **and**, with extra scrutiny:
1. **No code path executes a treatment/mitigation or edits a signal source** —
   `mitigate` is a *proposed* Workflow run (§0/D5); `accept`/`transfer` are
   records. Trace `treat`.
2. Scoring is deterministic, bounded `[0,100]`, mission-weighted, monotonic.
3. Correlation + assessment are tenant-scoped and bounded.
4. Every treatment writes an `EvidenceRecord`; risks use optimistic version.
5. Threat-intel is an evidence signal, not a live fetch here.
6. `ruff` + `mypy --strict` clean; interfaces match the spec exactly.

Merge only on green review; then **report back to the owner** before the next
module.
