# EA-0018 — Automated Response & Orchestration — Implementation Specification

**Realizes:** EA-0018 / IS-018 (supersedes the placeholder `archive/EA-0018/EA-0018_Master.md` for implementation)
**Depends on:** ADR-0001, CONVENTIONS, EA-0001 (`AQService`), **EA-0008 (Workflow — the single acting authority)**, EA-0009 (Policy — authorization), EA-0015 (SOC incidents/cases), EA-0004 (evidence), the Finding model
**Consumed by:** the SOC analyst workspace + response dashboard (campaigns, approval inbox, MTTR — a WCAG 2.2 AA surface), reporting, auditors
**Status:** Accepted
**Build milestone:** C-015 (see `C-015_Task_Bundle.md`)
**Definition of Ready:** see §12

---

## 0. Scope reconciliation (read first — this module is *not* a second executor)

IS-018's component list overlaps substantially with **EA-0008 Workflow**, which
is already implemented and is the platform's **single acting authority**.
Implementing IS-018 literally would create a parallel executor with its own
playbooks and its own approvals — which would break the §0 discipline every prior
module upholds. This spec therefore realizes IS-018 as the **orchestration layer
above EA-0008**. Nothing from the archive is dropped; each component is mapped:

| IS-018 component | Realization |
|---|---|
| Playbook Engine | **Already EA-0008** (`Playbook`: declarative, versioned, steps). Reused, not rebuilt. |
| Approval Engine | **Split.** *Granting* stays EA-0008 (`Approval`, S4). **New here:** approval **routing + escalation + SLA** (getting the request to the right human). Routing ≠ granting. |
| Response Engine / Automation Engine | **New here:** *when* to start a run — triggers bounded by `finding.automation.eligibility` + Policy. Execution stays EA-0008. |
| Orchestration Engine | **New here:** multi-run, multi-phase **response campaigns** (contain → remediate → recover) with ordering/dependencies across gated runs. |
| Containment / Remediation / Recovery Engines | **New here as `ActionSpec` families + capabilities** registered into EA-0008's registry. The system-touching `ActionHandler` implementations arrive with **connectors** (EA-0008 §13) — still deferred. |
| Recovery Engine (verification) | **New here:** verify restoration, reopen if unverified (read/verify + propose). |
| Metrics Engine | **New here:** MTTD / MTTR / containment-time analytics over runs + incidents (read-only). |
| Dashboard Service | A UI surface (UX turn, later EA); this spec supplies its data. |

## 1. Safety boundary

- **S1 — One acting path, unchanged.** Every effect goes through EA-0008
  `execute`. This engine **has no privileged path**: it calls the same public
  `execute()` any caller does, and EA-0008 re-validates deny-by-default,
  capability, approval, `confirm_token`, and eligibility **at run time**. The
  orchestrator therefore *cannot* cause an effect EA-0008 would refuse.
- **S2 — Tighten-only, never widen.** Automation triggers may **narrow** what
  runs (fewer, safer, more conditions) but SHALL NOT relax any EA-0008 gate.
  Specifically: **destructive actions are never auto-started**, and a trigger
  SHALL NOT exceed `finding.automation.eligibility` or a Policy `deny`/
  `require_approval`. (Mirrors EA-0009 S3.)
- **S3 — Routing is not granting.** `route_approval` creates and escalates an
  approval **request**; only a human's EA-0008 `approve` grants it. This engine
  SHALL NOT self-approve, auto-approve, or synthesize an `Approval`.
- **S4 — No network surface.** Campaign orchestration touches no external system
  directly; system-touching handlers arrive with connectors (§0 table).
- **S5 — Everything evidenced.** Campaign phases, trigger firings, approval
  routing, and recovery verification each write an `EvidenceRecord` (EA-0004) —
  a response reconstructs fully from its audit trail.
- Tenant-scoped and bounded throughout.

## 2. Purpose

SOC can propose a response; Workflow can execute one gated run. Nothing yet
**coordinates a whole response**: contain the host *now*, then remediate the root
cause once approved, then verify recovery — as one tracked campaign, with the
right humans pulled in at the right moment, and MTTR measured at the end. That is
this engine: **the conductor, never the hands.**

## 3. Design decisions

- **D1 — A campaign composes EA-0008 runs.** `ResponseCampaign` holds ordered
  **phases**, each holding proposed/executing Workflow runs with dependencies.
  Campaign state derives from its runs' states (source of truth stays EA-0008).
- **D2 — Triggers are declarative, structured predicates** — reuse the EA-0009
  safe condition model. **No `eval`/`exec`.**
- **D3 — Automation is bounded by the finding's eligibility + Policy** (S2);
  the trigger evaluates *whether to start*, never *whether it's allowed*.
- **D4 — Approval routing is a queue concern:** route to a role/actor, SLA, then
  escalate. The grant is EA-0008's (S3).
- **D5 — Recovery verification re-checks the world** (via the relevant governance
  engine's assessment) and, if not restored, raises a finding + proposes a new
  run — never forces a fix.
- **D6 — Metrics are read-only analytics** over runs/incidents/campaigns; no new
  scoring model.
- **D7 — Registered as an `AQService`;** campaigns persist (in-memory + Postgres).

## 4. Ubiquitous language

| Term | Meaning |
|---|---|
| **Response campaign** | An ordered, multi-phase coordination of gated Workflow runs for one incident. |
| **Phase** | `contain` / `remediate` / `recover` — a stage holding runs, gated on prior phases. |
| **Trigger** | A declarative condition that may **start** an already-permitted run (S2). |
| **Approval request** | A routed, SLA-tracked ask for a human EA-0008 approval (S3). |
| **Recovery verification** | A re-check that the fix actually restored the desired state (D5). |
| **MTTD / MTTR** | Mean time to detect / respond — measured over incidents + runs. |

## 5. Types

```
Phase       = { name: "contain"|"remediate"|"recover", order: int,
                run_refs: list[RunRef], depends_on: list[str],
                status: "pending"|"running"|"completed"|"failed"|"blocked" }
RunRef      = { workflow_run_id: str, action_type: str, effect: str,
                status: str }                       # mirrors the EA-0008 run (D1)
ResponseCampaign = { id, tenant_id, incident_id: str | null,
                     source_finding_id: str | null, phases: list[Phase],
                     status: "planned"|"awaiting_approval"|"running"
                             |"completed"|"failed"|"halted",
                     created_by: ActorRef, created_at, updated_at,
                     evidence_ids: list[str], version: int }

AutomationTrigger = { id, tenant_id, name, condition: "Condition",   # EA-0009 model (D2)
                      playbook_id: str, max_effect: "read_only"|"reversible",
                      enabled: bool, version: int }                  # destructive NEVER auto (S2)

ApprovalRequest = { id, tenant_id, workflow_run_id: str, step_ids: list[str],
                    routed_to: ActorRef | str, sla_seconds: int,
                    escalate_to: ActorRef | str | null,
                    status: "open"|"granted"|"expired"|"escalated",
                    requested_at: datetime }                          # routing only (S3)

RecoveryVerification = { campaign_id: str, checks: list[dict], verified: bool,
                         reopened_finding_id: str | null, reason: str }
ResponseMetrics = { window: dict, mttd_seconds: float | null,
                    mttr_seconds: float | null, containment_seconds: float | null,
                    campaigns: int, automated_pct: float }
ResponseConfig = { phase_order: tuple[str, ...], default_sla_seconds: int,
                   batch_size: int }
```

Reuses EA-0008 `Run`/`Approval`/`ActionSpec`, EA-0009 `Condition`, EA-0015
incidents, the Finding model, `ActorRef`.

## 6. Interfaces (Python 3.12)

```python
from typing import Protocol, Sequence
from datetime import datetime

class CampaignStore(Protocol):
    async def upsert(self, campaign: ResponseCampaign) -> ResponseCampaign: ...   # optimistic version
    async def get(self, campaign_id: str) -> ResponseCampaign | None: ...
    async def query(self, *, tenant_id: str | None,
                    status: Sequence[str] | None = None, limit: int = 100) -> list[ResponseCampaign]: ...

class TriggerStore(Protocol):
    async def put(self, trigger: AutomationTrigger) -> AutomationTrigger: ...     # validates condition + max_effect (S2/D2)
    async def list(self, *, tenant_id: str | None, enabled_only: bool = True) -> list[AutomationTrigger]: ...

class ResponseOrchestrationEngine(Protocol):
    async def plan_campaign(self, *, incident_id: str | None, tenant_id: str | None,
                            playbooks: Sequence[dict], by: ActorRef) -> ResponseCampaign: ...
    # proposes an EA-0008 run per playbook, grouped into phases; nothing executes (D1/S1)

    async def advance(self, campaign_id: str, *, by: ActorRef,
                      expected_version: int) -> ResponseCampaign: ...
    # starts the next phase's runs via EA-0008 execute() — EA-0008 re-validates every gate (S1)

    async def evaluate_triggers(self, *, tenant_id: str | None) -> list[str]: ...
    # returns campaigns/runs started by automation; bounded by eligibility + Policy (S2/D3)

    async def route_approval(self, workflow_run_id: str, *, step_ids: Sequence[str],
                             to: ActorRef | str, sla_seconds: int | None = None) -> ApprovalRequest: ...
    async def escalate_overdue(self, *, tenant_id: str | None) -> list[ApprovalRequest]: ...
    # routing/escalation only — never grants (S3)

    async def halt_campaign(self, campaign_id: str, *, by: ActorRef, reason: str,
                            expected_version: int) -> ResponseCampaign: ...   # halts pending runs via EA-0008
    async def verify_recovery(self, campaign_id: str, *, by: ActorRef) -> RecoveryVerification: ...  # D5
    async def metrics(self, *, tenant_id: str | None, since: datetime) -> ResponseMetrics: ...       # D6
    def explain(self, campaign: ResponseCampaign) -> dict: ...
```

`ResponseOrchestrationService` wraps the engine + stores as an `AQService`
(name `"response_engine"`, depends on workflow, policy, SOC, finding, evidence;
health reflects availability + config validity).

## 7. Computation (the reference model)

**Plan.** `plan_campaign` proposes an EA-0008 run per playbook
(`WorkflowEngine.propose`, honoring the source finding's eligibility) and groups
them into ordered phases per `phase_order`. Nothing executes; campaign status
`planned`/`awaiting_approval` derives from the runs' states (D1/S1).

**Advance.** `advance` starts the next phase's runs by calling **EA-0008
`execute`** — which re-checks capability, approval, `confirm_token`, and
eligibility at run time. A refused run marks its phase `blocked` and the campaign
surfaces why; the orchestrator never bypasses the refusal (S1).

**Triggers.** `evaluate_triggers` evaluates each enabled trigger's structured
condition; on match it may start a run **only if** `max_effect ≤ reversible`,
`finding.automation.eligibility == automatic`, `requires_approval == False`, and
Policy `authorize` permits. Destructive → never auto-started; anything else →
routed for approval instead (S2/D3).

**Approvals.** `route_approval` creates an `ApprovalRequest` (SLA tracked);
`escalate_overdue` escalates past SLA. A human then calls **EA-0008 `approve`**;
this engine reflects the outcome (S3).

**Recovery.** `verify_recovery` re-runs the relevant assessment (e.g. config
baseline via EA-0012, access state via EA-0011); if the desired state isn't
restored, it raises a finding and proposes a follow-up run — it never forces
(D5).

**Metrics.** `metrics` aggregates detection→containment→resolution timestamps
over incidents/campaigns (read-only, D6).

## 8. Requirements

### Functional (testable)

- **FR-1** `plan_campaign` SHALL propose an EA-0008 run per playbook and group them into ordered phases; it SHALL NOT execute anything (S1/D1).
- **FR-2** `advance` SHALL start phase runs **only via EA-0008 `execute`**; when EA-0008 refuses (unauthorized/unapproved/unconfirmed), the phase SHALL be marked `blocked` and the refusal surfaced — never bypassed (S1).
- **FR-3** The engine SHALL have **no privileged execution path**: it SHALL NOT invoke `ActionHandler`s directly, construct `Approval`s, or set run state — only EA-0008's public API (S1/S3).
- **FR-4** A trigger SHALL NOT auto-start a destructive action under any configuration; `max_effect` SHALL be limited to `read_only`/`reversible` at `put` (S2).
- **FR-5** A trigger SHALL start a run only if `finding.automation.eligibility == automatic`, `requires_approval == False`, and Policy `authorize` permits; otherwise it SHALL route for approval instead (S2/D3).
- **FR-6** Triggers SHALL evaluate declarative structured conditions (EA-0009 model); no `eval`/`exec` (D2).
- **FR-7** `route_approval` SHALL create an SLA-tracked request and `escalate_overdue` SHALL escalate past SLA; neither SHALL grant an approval (S3).
- **FR-8** Campaign status SHALL derive from its runs' EA-0008 states; the engine SHALL NOT hold a divergent source of truth (D1).
- **FR-9** Phases SHALL respect `depends_on`/order: a phase SHALL NOT start until its prerequisites complete; a failed phase SHALL block dependents (never blind-continue).
- **FR-10** `halt_campaign` SHALL halt pending runs via EA-0008 and mark the campaign `halted`.
- **FR-11** `verify_recovery` SHALL re-check the desired state and, if unverified, raise a finding + propose a follow-up run; it SHALL NOT force a fix (D5).
- **FR-12** Campaign phases, trigger firings, approval routing, and recovery verification SHALL each write an `EvidenceRecord` (S5); a campaign SHALL reconstruct from its trail.
- **FR-13** `metrics` SHALL compute MTTD/MTTR/containment time read-only over incidents/campaigns (D6).
- **FR-14** All operations SHALL be tenant-scoped and versioned (optimistic `version`); invalid config/trigger SHALL raise `ResponseConfigInvalid`.
- **FR-15** `CampaignStore` and `TriggerStore` in-memory and Postgres implementations SHALL each pass one contract suite.
- **FR-16** `ResponseOrchestrationService` SHALL register as an `AQService` with health reflecting dependency availability + config validity (EA-0001).

### Non-functional

- **NFR-1 (single acting path)** no code path produces an external effect except through EA-0008 `execute`; enforced by tests (handler-spy: zero direct handler invocations) and grep.
- **NFR-2 (tighten-only)** no configuration can make this engine widen an EA-0008/Policy gate; proven by refusal tests.
- **NFR-3 (auditability)** every campaign reconstructs fully from evidence + run history.
- **NFR-4 (bounded & typed)** batched; in-memory + Postgres stores pass their suites; `mypy --strict` + `ruff` clean.

## 9. Acceptance Criteria ↔ Tests (Definition of Ready)

| # | Criterion | Test (pytest id) |
|---|---|---|
| AC-1 | plan proposes runs, executes nothing | `test_resp_plan_no_execution` |
| AC-2 | advance starts runs only via EA-0008 execute | `test_resp_advance_via_workflow` |
| AC-3 | EA-0008 refusal blocks phase, never bypassed | `test_resp_refusal_blocks` |
| AC-4 | No direct handler calls / no synthesized Approval | `test_resp_no_privileged_path` |
| AC-5 | Destructive never auto-started | `test_resp_no_auto_destructive` |
| AC-6 | Trigger honors eligibility + Policy, else routes | `test_resp_trigger_bounded` |
| AC-7 | Triggers use structured conditions; no eval | `test_resp_trigger_no_eval` |
| AC-8 | route_approval never grants; SLA + escalation | `test_resp_routing_not_granting` |
| AC-9 | Campaign status derives from run states | `test_resp_status_derived` |
| AC-10 | Phase ordering/dependencies + fail blocks dependents | `test_resp_phase_ordering` |
| AC-11 | halt halts pending runs | `test_resp_halt` |
| AC-12 | Recovery verify → finding + proposed run, no force | `test_resp_recovery_verify` |
| AC-13 | Campaign fully evidenced/reconstructable | `test_resp_evidence_trail` |
| AC-14 | Metrics read-only MTTD/MTTR | `test_resp_metrics` |
| AC-15 | Tenant isolation + optimistic version + invalid config | `test_resp_tenant_version_config` |
| AC-16 | Campaign & trigger stores pass one suite each | `test_resp_campaign_contract[...]` / `test_resp_trigger_contract[...]` |
| AC-17 | Registers as AQService with health | `test_resp_service_health` |

## 10. Error taxonomy (contributions)

`ResponseConfigInvalid`, `CampaignNotFound`, `TriggerNotFound`,
`PhaseBlocked` (added to `conventions.errors` + CONVENTIONS §9). Reuses EA-0008
`UnauthorizedAction`/`ApprovalRequired`/`ConfirmationRequired`,
`OptimisticConcurrencyConflict`, `StoreUnavailable`, `TenantScopeRequired`.

## 11. Registered event types (owned by EA-0018)

`aqelyn.response.campaign_planned`, `aqelyn.response.started`,
`aqelyn.response.phase_completed`, `aqelyn.response.approval_routed`,
`aqelyn.response.campaign_completed` — via `register_response_events()`
(EA-0003 §7). (Archive uses `response.started`; mapped into the platform
namespace as `aqelyn.response.started`.)

## 12. Failure handling

- Invalid config/trigger → `ResponseConfigInvalid` at `put`/construction.
- EA-0008 refuses a run → phase `blocked`, reason surfaced, campaign continues to
  reflect reality; **no retry-with-weaker-gates, ever** (S2).
- A phase fails → dependents blocked, campaign `failed`, partial state surfaced
  (never blind-continue).
- Workflow/Policy/store unavailable → `StoreUnavailable`; service `degraded`; the
  campaign is not advanced on a guess.
- Approval SLA expiry → escalate; if no approver, the request expires and the
  phase stays blocked — **expiry never implies consent**.

## 13. Dependencies & consumers

- **Depends on:** **EA-0008 Workflow** (`propose`/`simulate`/`approve`/`execute`/
  `halt` — the only acting path); EA-0009 Policy (`authorize`); EA-0015 SOC
  (incidents); EA-0004 evidence; the Finding model; EA-0011/0012 (recovery
  re-checks); EA-0001 `AQService`.
- **Consumed by:** the SOC workspace + response dashboard (campaigns, approval
  inbox, MTTR — **WCAG 2.2 AA** applies); reporting; auditors.

## 14. Resolved / deferred decisions

- **EA-0018 orchestrates; EA-0008 executes** (§0/S1) — binding. No second
  executor, no second playbook model, no second approval authority.
- **Automation may narrow, never widen** (S2); destructive is never auto-started.
- **Routing ≠ granting** (S3).
- **Containment/remediation/recovery `ActionHandler` implementations arrive with
  connectors** (EA-0008 §13) — this spec defines their `ActionSpec` families and
  capabilities only; the network surface stays deferred.
