# C-012 Security Operations (SOC) — Implementation Task Bundle

**Milestone:** C-012 (Security Operations Engine, EA-0015)
**For:** Codex (implementer) · Claude Code (reviewer)
**Prerequisites:** EA-0014 merged & green; EA-0015 spec **Accepted**; CONVENTIONS + Finding model + EA-0005/0007/0008/0013/0014 read.
**Definition of Done:** every ticket's acceptance tests pass on in-memory **and** Postgres; `ruff` clean; `mypy --strict` clean; **response is proposed via Workflow, never executed**; nothing outside the spec; `make check` green; Claude Code sign-off per ticket.

This engine is the **operational layer** — it composes findings/risk/threat into
alerts→incidents→cases and **coordinates** response as gated Workflow runs (§0).
If a needed behavior isn't in the spec, raise an ECR.

## Target source layout

```
src/aqelyn/soc/
├── __init__.py       # exports the engine, service, types, register_soc_events
├── models.py         # Alert, Incident, TimelineEntry, ResponseAction, Hunt, SOCConfig (S1)
├── store.py          # SOCStore protocol (S2)
├── memory.py         # InMemorySOCStore (S2)
├── postgres.py       # PostgresSOCStore + DDL (S2)
├── intake.py         # findings/threat/risk -> alerts (S1/S3)
├── correlate.py      # alerts -> incidents, priority via Mission+Risk (S3)
├── engine.py         # assign/transition/investigate/propose_response/hunt (S3/S4)
└── service.py        # SecurityOperationsService(AQService) + register_soc_events (S5)
tests/soc/            # acceptance suite (in-memory + Postgres)
```

---

## S1 — Types, config & alert intake

**Spec:** §4, §6 (intake), FR-1/11, D1; §9.
**Deliverables:** the models; `SOCConfig` validation (`SOCConfigInvalid`); new
error codes in `conventions.errors` + CONVENTIONS §9; `intake` (findings/threat/
risk → alerts, deduped by `source_ref`, evidence carried, no signal duplication).
**Depends on:** Finding model, EA-0013/0014 outputs, conventions.
**Acceptance:** `test_soc_intake_alerts`, `test_soc_config_invalid`.

## S2 — SOCStore (alerts + incidents/cases)

**Spec:** §5, FR-4/12, D3.
**Deliverables:** `SOCStore` (in-memory + Postgres + DDL) with optimistic
`version` on incidents; one parametrized contract suite.
**Depends on:** S1.
**Acceptance:** `test_soc_tenant_isolation`,
`test_soc_store_contract[inmemory]`, `test_soc_store_contract[postgres]`.

## S3 — Correlation, case work & investigation

**Spec:** §6, FR-2/3/4/5/7/9, D2/D3/D4/D5.
**Deliverables:** `correlate` (alerts→incidents, priority via Mission+Risk,
deterministic); `assign`/`transition` (versioned, timeline + evidence);
`investigate` (KG pivot attached as evidence); `explain`.
**Depends on:** S2.
**Acceptance:** `test_soc_correlate_incidents`, `test_soc_priority`,
`test_soc_transition_evidence`, `test_soc_assign`, `test_soc_investigate_pivot`,
`test_soc_case_auditable`.

## S4 — Response coordination (delegate-only) & hunting

**Spec:** §0, §6, FR-6/8/10, D6/D7, NFR-1; EA-0008 propose.
**Deliverables:** `propose_response` (per action → **proposed** EA-0008 Workflow
run + `ResponseAction` status tracking; never direct); `hunt` (bounded,
read-only).
**Depends on:** S3.
**Acceptance:** `test_soc_response_delegates`, `test_soc_response_status`,
`test_soc_hunt_readonly`, `test_soc_no_side_effects`.

## S5 — Service + events

**Spec:** FR-13, §10.
**Deliverables:** `SecurityOperationsService` (`AQService`, name `"soc_engine"`)
+ `register_soc_events`; wired into the kernel factory.
**Depends on:** S4.
**Acceptance:** `test_soc_service_health`.

---

## Review protocol (Claude Code) — the response boundary gets the hard look

Per ticket, confirm the normal DoD **and**, with extra scrutiny:
1. **No code path executes a response** — `propose_response` creates *proposed*
   Workflow runs only; trace it and the `ResponseAction` status tracking (§0/D6).
2. The engine mutates only its own alert/incident/case records (+ evidence +
   proposed runs) — never findings/objects/risks.
3. Correlation is deterministic; priority reuses Mission+Risk (no new scorer).
4. Every material case step is evidence-bound; a case reconstructs from timeline
   + evidence.
5. `hunt` is bounded and read-only; everything tenant-scoped.
6. `ruff` + `mypy --strict` clean; interfaces match the spec exactly.

Merge only on green review; then **report back to the owner** before the next
module.
