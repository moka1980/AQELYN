# EA-0008 — Workflow Engine — Implementation Specification

**Realizes:** EA-0008 (supersedes the placeholder `archive/EA-0008/EA-0008_Master.md` for implementation)
**Depends on:** ADR-0001, CONVENTIONS, EA-0001 (`AQService`), EA-0002 (objects), EA-0003 (events), EA-0004 (evidence — every action is recorded), the Finding model (`automation` eligibility gate), EA-0007 (priority ordering, optional)
**Consumed by:** the remediation/triage surface, EA-0009 Policy (which actions are permitted), UI (approval inbox, run history)
**Status:** Accepted
**Build milestone:** C-005 (see `C-005_Task_Bundle.md`)
**Definition of Ready:** see §12

---

## 1. Purpose

The Workflow Engine is the first AQELYN module that **acts** rather than
analyzes: it runs remediation playbooks — ordered steps that change something
(open a ticket, disable an account, apply a firewall rule) — with a
human-in-the-loop where it matters. Because it acts, this spec treats **safety
and authorization as the primary design surface, not an add-on**: nothing runs
that wasn't explicitly permitted, nothing destructive runs without approval,
every action can be simulated first, everything it does is recorded as evidence,
and everything it does can be traced and (where possible) undone.

## 2. Safety & authorization model (read first — this governs everything else)

- **S1 — Deny by default.** No action executes unless (a) its action type is
  registered with an explicit **capability**, (b) the caller/run is authorized
  for that capability, and (c) any required approval has been granted. Absence of
  a rule means *no*, never *yes*.
- **S2 — Actions are typed by blast radius.** Every action declares an
  `effect ∈ {read_only, reversible, destructive}` and the `capability` it needs.
  `read_only` may run without approval; **`reversible` and `destructive` require
  an approval gate**; `destructive` additionally requires an explicit
  `confirm_token` and is never auto-approved.
- **S3 — Honor the finding's automation eligibility.** When a run is derived from
  a finding, the engine SHALL NOT exceed `finding.automation.eligibility`
  (`none` → propose only, no execution; `assisted` → execute only with approval;
  `automatic` → may execute without per-run human approval **only** for
  non-destructive actions, and only if `requires_approval` is false).
- **S4 — Approvals are explicit, attributed, and recorded.** An approval names
  the approver (`ActorRef`), the exact step(s) approved, a reason, and a time.
  Approval of a run does not implicitly approve later-added steps.
- **S5 — Dry-run first.** Every playbook supports `simulate()` that produces the
  planned actions and predicted effects **without executing**. Callers can
  require a successful simulation before an execution is allowed.
- **S6 — Idempotency.** Every action carries an `idempotency_key`; re-running a
  step that already succeeded is a no-op, not a double-apply.
- **S7 — Everything is evidence.** Each executed (or simulated) action writes an
  `EvidenceRecord` (EA-0004) — inputs, outcome, actor, time — so a run is fully
  auditable and tamper-evident. A workflow event is emitted per state change
  (EA-0003).
- **S8 — Rollback & halt.** A run can be halted at any step; reversible actions
  record a `rollback_ref`; on failure the engine stops (does not blindly
  continue) and surfaces the partial state. Destructive actions that cannot be
  rolled back are flagged as such **before** approval.
- **S9 — Bounded & tenant-scoped.** Runs are tenant-scoped; a run never touches
  objects in another tenant; step counts and durations are bounded.

The remaining sections implement this model.

## 3. Scope

**In scope:** declarative playbook definition, the action/capability registry,
run lifecycle (propose → simulate → await-approval → execute → complete/failed/
halted), approval gates, idempotent execution, per-action evidence + events,
rollback, and the `WorkflowEngine` interface + `WorkflowEngineService`
(`AQService`).

**Out of scope:** the concrete action *implementations* that touch external
systems (each is a registered `ActionHandler` delivered by its own connector/EA
— this engine orchestrates and gates them, it does not embed integrations),
*policy authorship* (EA-0009 decides what is allowed; this engine enforces the
decision), and scheduling/cron (a later EA).

## 4. Ubiquitous language

| Term | Meaning |
|---|---|
| **Playbook** | A declarative, versioned template: ordered steps + inputs. Data, not code. |
| **Step** | One action invocation within a playbook, with its inputs and guards. |
| **Action / ActionHandler** | A registered, capability-typed operation (`read_only`/`reversible`/`destructive`) that a step invokes. |
| **Capability** | The named permission an action requires (deny-by-default, S1). |
| **Run** | A single execution instance of a playbook, tenant-scoped, with a lifecycle + audit. |
| **Approval gate** | A required, attributed human authorization before gated steps run (S4). |
| **Simulation / dry-run** | Planned actions + predicted effects with no execution (S5). |

## 5. Types

```
ActionEffect = "read_only" | "reversible" | "destructive"

ActionSpec = { action_type: str, capability: str, effect: ActionEffect,
               reversible: bool, description: str }

Step = { id: str, action_type: str, inputs: dict, idempotency_key: str,
         requires_approval: bool }          # derived from effect + policy; never lowered by inputs

Playbook = { id: str, version: int, name: str, description: str,
             steps: list[Step], tenant_id: str | null }

RunStatus = "proposed" | "simulated" | "awaiting_approval" | "approved"
          | "running" | "completed" | "failed" | "halted"

Approval = { step_ids: list[str], approver: ActorRef, reason: str,
             confirm_token: str | null, at: datetime }   # confirm_token required for destructive (S2)

StepResult = { step_id: str, status: str, outcome: dict, evidence_id: str,
               rollback_ref: str | null, error: str | null }

Run = { id: str, playbook_id: str, playbook_version: int, tenant_id: str | null,
        status: RunStatus, source_finding_id: str | null,
        results: list[StepResult], approvals: list[Approval],
        created_by: ActorRef, created_at: datetime, updated_at: datetime,
        version: int }

SimulationResult = { run_id: str, planned: list[{step_id, action_type, effect,
                     requires_approval, predicted: dict}], safe_to_execute: bool }
```

## 6. Interfaces (Python 3.12)

```python
from typing import Protocol, Sequence

class ActionHandler(Protocol):
    spec: ActionSpec
    async def simulate(self, inputs: dict, *, tenant_id: str | None) -> dict: ...   # no effect (S5)
    async def execute(self, inputs: dict, *, tenant_id: str | None,
                      idempotency_key: str) -> dict: ...                            # returns outcome (+rollback_ref)
    async def rollback(self, rollback_ref: str, *, tenant_id: str | None) -> None: ...

class ActionRegistry(Protocol):
    def register(self, handler: ActionHandler) -> None: ...
    def get(self, action_type: str) -> ActionHandler: ...        # raises UnknownAction if absent (S1)

class WorkflowEngine(Protocol):
    async def propose(self, playbook: Playbook, *, by: ActorRef,
                      source_finding: "Finding | None" = None) -> Run: ...          # honors S3
    async def simulate(self, run_id: str) -> SimulationResult: ...                  # S5
    async def approve(self, run_id: str, approval: Approval) -> Run: ...            # S4
    async def execute(self, run_id: str, *, by: ActorRef) -> Run: ...              # S1/S2/S6/S7/S8
    async def halt(self, run_id: str, *, by: ActorRef, reason: str) -> Run: ...    # S8
    async def rollback(self, run_id: str, *, by: ActorRef) -> Run: ...             # reverse reversible steps
    async def get(self, run_id: str) -> Run | None: ...
```

`WorkflowEngineService` wraps the engine + registries as an `AQService`
(name `"workflow_engine"`, depends on object/evidence/event infra; health
reflects their availability). Runs persist via an in-memory + Postgres
`RunStore` (same two-implementation/one-contract pattern as the foundation).

## 7. Run lifecycle & gating

```
propose ─► simulated ─►(gated steps?)─► awaiting_approval ─► approved ─► running ─► completed
   │            │             │no                                   │            └─► failed  (stop, S8)
   │            └─────────────┴───────────────────────────────────► running        └─► halted  (S8)
```

- On `propose`, each step's `requires_approval` is set from its action `effect`
  **and** policy (S2/S3) and can only be raised, never lowered, by inputs.
- `execute` refuses (`ApprovalRequired`) if any gated step lacks a matching
  `Approval`; refuses (`UnauthorizedAction`) if a capability isn't granted;
  refuses (`ConfirmationRequired`) if a destructive step lacks a `confirm_token`.
- Each step: check idempotency (S6) → `execute` handler → write evidence (S7) →
  emit event → record `StepResult`/`rollback_ref`. On error: stop, mark `failed`,
  surface partial results (S8).

## 8. Requirements

### Functional (testable)

- **FR-1** No step SHALL execute unless its action is registered, its capability granted, and (if gated) approved — deny by default (S1). Unknown action → `UnknownAction`.
- **FR-2** Action `effect` SHALL determine gating: `read_only` may run ungated; `reversible`/`destructive` SHALL require approval; `destructive` SHALL additionally require a `confirm_token` and SHALL never be auto-approved (S2).
- **FR-3** A run derived from a finding SHALL NOT exceed `finding.automation.eligibility`; `none` → no execution (propose/simulate only); `assisted` → execution only with approval; `automatic` → ungated execution only for non-destructive actions with `requires_approval == False` (S3).
- **FR-4** `approve` SHALL record approver, exact `step_ids`, reason, and time; approval SHALL NOT cover steps added after it (S4).
- **FR-5** `simulate` SHALL produce planned actions + predicted effects and SHALL execute nothing; `safe_to_execute` reflects gating readiness (S5).
- **FR-6** Re-execution of an already-succeeded step (same `idempotency_key`) SHALL be a no-op, not a re-apply (S6).
- **FR-7** Every executed **and** simulated action SHALL write an `EvidenceRecord` (EA-0004) and every run state change SHALL emit a workflow event (EA-0003) (S7).
- **FR-8** On step failure the run SHALL stop (`failed`), never silently continue, and SHALL surface partial `results` (S8).
- **FR-9** `rollback` SHALL reverse reversible steps via their `rollback_ref`; steps flagged non-reversible SHALL be reported as such and left untouched (S8).
- **FR-10** Runs SHALL be tenant-scoped; a run SHALL NOT reference or affect another tenant's objects (S9).
- **FR-11** Run state changes SHALL use optimistic `version` (conflict → `OptimisticConcurrencyConflict`), consistent with the foundation stores.
- **FR-12** Playbooks SHALL be declarative data (versioned); the engine SHALL reject a run whose playbook references an unregistered `action_type` at `propose`.
- **FR-13** `WorkflowEngineService` SHALL register as an `AQService` with health reflecting registry + store availability (EA-0001).

### Non-functional

- **NFR-1 (safety-first)** there is no code path from `propose` to a destructive external effect that bypasses S1–S3; enforced by tests that assert refusal.
- **NFR-2 (auditability)** every run reconstructs fully from its evidence + events; no action lacks an evidence record.
- **NFR-3 (bounded)** step count per run and per-step timeout are capped; a stuck handler is timed out, the run marked `failed`, never hung.
- **NFR-4 (portability & typing)** in-memory and Postgres `RunStore` pass one contract suite; `mypy --strict` + `ruff` clean.

## 9. Acceptance Criteria ↔ Tests (Definition of Ready)

| # | Criterion | Test (pytest id) |
|---|---|---|
| AC-1 | Unregistered/ungranted action refused | `test_wf_deny_by_default` |
| AC-2 | reversible/destructive require approval | `test_wf_gating_by_effect` |
| AC-3 | destructive requires confirm_token, never auto | `test_wf_destructive_confirm` |
| AC-4 | eligibility=none blocks execution | `test_wf_eligibility_none_no_exec` |
| AC-5 | eligibility=assisted needs approval | `test_wf_eligibility_assisted` |
| AC-6 | eligibility=automatic ungated only if non-destructive | `test_wf_eligibility_automatic_scope` |
| AC-7 | approval records approver/steps/reason | `test_wf_approval_recorded` |
| AC-8 | approval doesn't cover later-added steps | `test_wf_approval_scope` |
| AC-9 | simulate executes nothing | `test_wf_simulate_no_effect` |
| AC-10 | idempotent step re-run is no-op | `test_wf_idempotent_step` |
| AC-11 | every action writes evidence + emits event | `test_wf_action_evidenced` |
| AC-12 | failure stops run, surfaces partial | `test_wf_failure_stops` |
| AC-13 | rollback reverses reversible steps | `test_wf_rollback` |
| AC-14 | tenant isolation on runs | `test_wf_tenant_isolation` |
| AC-15 | optimistic concurrency on run updates | `test_wf_optimistic_conflict` |
| AC-16 | unregistered action_type rejected at propose | `test_wf_unknown_action_at_propose` |
| AC-17 | step timeout → failed, not hung | `test_wf_step_timeout` |
| AC-18 | in-memory & Postgres RunStore pass one suite | `test_wf_runstore_contract[inmemory]` / `[postgres]` |
| AC-19 | registers as AQService with health | `test_wf_service_health` |

## 10. Error taxonomy (contributions)

`UnknownAction`, `UnauthorizedAction`, `ApprovalRequired`, `ConfirmationRequired`,
`ActionFailed`, `RunNotFound` (added to `conventions.errors` + CONVENTIONS §9).
Reuses `OptimisticConcurrencyConflict`, `CrossTenantReference`, `StoreUnavailable`.

## 11. Registered event types (owned by EA-0008)

`aqelyn.workflow.run_proposed`, `aqelyn.workflow.run_simulated`,
`aqelyn.workflow.approval_granted`, `aqelyn.workflow.step_executed`,
`aqelyn.workflow.run_completed`, `aqelyn.workflow.run_failed`,
`aqelyn.workflow.run_halted` — registered via a `register_workflow_events()`
helper (EA-0003 §7 extensibility).

## 12. Dependencies & consumers

- **Depends on:** EA-0001 `AQService`; EA-0002 objects (targets); EA-0003 events;
  EA-0004 `EvidenceStore.add` (every action recorded); the Finding model
  (`automation` gate); `ActorRef` (CONVENTIONS). Action *implementations* arrive
  as registered `ActionHandler`s from their own connectors/EAs.
- **Consumed by:** the remediation UI (approval inbox, run history); **EA-0009
  Policy decides which capabilities/actions are permitted — this engine enforces
  that decision** (the policy hook is the capability grant check in S1/FR-1);
  reporting.

## 13. Resolved / deferred decisions

- **Deny-by-default with typed effects + mandatory approval for anything beyond
  read-only** is the binding safety posture; it cannot be weakened by playbook
  inputs.
- **Action implementations are out of scope** here — the engine ships with a
  registry and a couple of built-in `read_only` handlers for tests; real
  destructive handlers arrive with their connectors, each carrying its own
  `ActionSpec`.
- **Policy integration point is the capability check** (S1). Until EA-0009 lands,
  capability grants come from static config; EA-0009 replaces that source without
  changing this interface.
- **Scheduling/recurring runs** are deferred to a later EA; this spec covers
  on-demand runs only.
