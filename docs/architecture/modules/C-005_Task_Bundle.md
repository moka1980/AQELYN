# C-005 Workflow Engine — Implementation Task Bundle

**Milestone:** C-005 (Workflow Engine, EA-0008)
**For:** Codex (implementer) · Claude Code (reviewer)
**Prerequisites:** EA-0007 merged & green; EA-0008 spec **Accepted**; CONVENTIONS + EA-0002/0003/0004 + Finding model read.
**Definition of Done:** every ticket's acceptance tests pass on in-memory **and** Postgres; `ruff` clean; `mypy --strict` clean; nothing outside the spec; `make check` green; Claude Code sign-off per ticket.

**Order matters here for safety:** the authorization/gating core (W1) is built and
proven **before** any execution path (W3). Do not implement `execute` until W1's
refusal tests are green.

## Target source layout

```
src/aqelyn/workflow/
├── __init__.py       # exports WorkflowEngine, service, types, register_workflow_events
├── models.py         # ActionSpec, Step, Playbook, Run, Approval, StepResult, SimulationResult (W1)
├── registry.py       # ActionRegistry + ActionHandler protocol + built-in read_only test handlers (W1)
├── gating.py         # deny-by-default authorization, effect->gate, eligibility check (S1-S3) (W1)
├── store.py          # RunStore protocol (W2)
├── memory.py         # InMemoryRunStore (W2)
├── postgres.py       # PostgresRunStore + DDL (W2)
├── engine.py         # WorkflowEngine: propose, simulate, approve, execute, halt, rollback (W3/W4)
└── service.py        # WorkflowEngineService(AQService) (W5)
tests/workflow/       # acceptance suite (in-memory + Postgres)
```

---

## W1 — Safety & authorization core (build first)

**Spec:** §2 (S1–S3), §5, §6 (ActionRegistry/ActionHandler), FR-1/2/3/12; §10.
**Deliverables:** the types; `ActionRegistry` + `ActionHandler` protocol +
built-in `read_only` test handlers; the gating module implementing deny-by-default,
effect→approval mapping, destructive `confirm_token` rule, and the
`finding.automation.eligibility` ceiling; the new error codes added to
`conventions.errors` + CONVENTIONS §9.
**Depends on:** Finding model, conventions.
**Acceptance:** `test_wf_deny_by_default`, `test_wf_gating_by_effect`,
`test_wf_destructive_confirm`, `test_wf_eligibility_none_no_exec`,
`test_wf_eligibility_assisted`, `test_wf_eligibility_automatic_scope`,
`test_wf_unknown_action_at_propose`.

## W2 — Run persistence

**Spec:** §5 (Run), FR-11, NFR-4.
**Deliverables:** `RunStore` protocol; `InMemoryRunStore` + `PostgresRunStore`
(+ DDL) with optimistic `version`; one parametrized contract suite.
**Depends on:** W1.
**Acceptance:** `test_wf_optimistic_conflict`, `test_wf_tenant_isolation`,
`test_wf_runstore_contract[inmemory]`, `test_wf_runstore_contract[postgres]`.

## W3 — Propose, simulate, approve (no external effects yet)

**Spec:** §7, FR-4/5, S4/S5; §11 (events).
**Deliverables:** `propose` (sets per-step gating from effect+eligibility),
`simulate` (executes nothing), `approve` (attributed, step-scoped);
`register_workflow_events` + emission on state changes.
**Depends on:** W2.
**Acceptance:** `test_wf_simulate_no_effect`, `test_wf_approval_recorded`,
`test_wf_approval_scope`.

## W4 — Execute, evidence, failure & rollback

**Spec:** §7, FR-6/7/8/9, S6/S7/S8, NFR-2/NFR-3.
**Deliverables:** `execute` (re-checks S1–S3 at run time, idempotent steps,
per-step evidence via `EvidenceStore.add`, event per step, stop-on-failure,
step timeout); `halt`; `rollback` of reversible steps.
**Depends on:** W3.
**Acceptance:** `test_wf_idempotent_step`, `test_wf_action_evidenced`,
`test_wf_failure_stops`, `test_wf_rollback`, `test_wf_step_timeout`.

## W5 — WorkflowEngineService (AQService)

**Spec:** FR-13, §12.
**Deliverables:** `WorkflowEngineService` registering as an `AQService`
(name `"workflow_engine"`); health reflects registry + store availability; wired
into the kernel factory.
**Depends on:** W4.
**Acceptance:** `test_wf_service_health`.

---

## Review protocol (Claude Code) — safety gets the hard look

Per ticket, confirm the normal DoD **and**, with extra scrutiny:
1. **No path from `propose` to a destructive external effect bypasses S1–S3.**
   Trace it; the refusal tests must actually exercise the deny path.
2. Destructive actions cannot be auto-approved and require a `confirm_token`.
3. `finding.automation.eligibility` is a hard ceiling, never widened by inputs.
4. Every executed **and** simulated action wrote an `EvidenceRecord`; every state
   change emitted an event — a run reconstructs fully from the audit trail.
5. `simulate` provably performs no external effect.
6. Failure stops the run and surfaces partial state; nothing "continues anyway".
7. Tenant isolation on runs; optimistic concurrency on updates.
8. `ruff` + `mypy --strict` clean; interfaces match the spec exactly.

Merge only on green review; then **report back to the owner** before the next
module.
