# C-015 Automated Response & Orchestration — Implementation Task Bundle

**Milestone:** C-015 (Automated Response & Orchestration, EA-0018)
**For:** Codex (implementer) · Claude Code (reviewer)
**Prerequisites:** EA-0017 merged & green; EA-0018 spec **Accepted**; **EA-0008 spec re-read (§2 S1–S9)**; CONVENTIONS + EA-0009/0015 read.
**Definition of Done:** every ticket's acceptance tests pass on in-memory **and** Postgres; `ruff` clean; `mypy --strict` clean; **no privileged execution path; destructive never auto-started; routing never grants**; nothing outside the spec; `make check` green; Claude Code sign-off per ticket.

**Read EA-0018 §0 + §1 first.** This module is the **conductor, not the hands**:
EA-0008 stays the single acting authority. Do **not** build a second playbook
model, a second approval authority, or any direct handler invocation. If a needed
behavior isn't in the spec, raise an ECR.

## Target source layout

```
src/aqelyn/response/
├── __init__.py       # exports the engine, service, types, register_response_events
├── models.py         # Phase, RunRef, ResponseCampaign, AutomationTrigger, ApprovalRequest,
│                     #   RecoveryVerification, ResponseMetrics, ResponseConfig (R1)
├── store.py          # CampaignStore + TriggerStore protocols (R2)
├── memory.py         # in-memory stores (R2)
├── postgres.py       # Postgres stores + DDL (R2)
├── campaign.py       # plan_campaign + advance + halt (all via EA-0008 public API) (R2/R3)
├── triggers.py       # evaluate_triggers — bounded by eligibility + Policy (R4)
├── approvals.py      # route_approval + escalate_overdue (routing only) (R4)
├── recovery.py       # verify_recovery (R5)
├── metrics.py        # MTTD/MTTR/containment (read-only) (R5)
└── service.py        # ResponseOrchestrationService(AQService) + register_response_events (R6)
tests/response/       # acceptance suite (in-memory + Postgres)
```

---

## R1 — Types & config

**Spec:** §5, FR-14; §10.
**Deliverables:** the models; `ResponseConfig`/trigger validation
(`ResponseConfigInvalid`; **`max_effect` limited to `read_only`/`reversible` at
`put`** — destructive is not expressible); new error codes in
`conventions.errors` + CONVENTIONS §9.
**Depends on:** EA-0008/0009 types, conventions.
**Acceptance:** `test_resp_tenant_version_config`, `test_resp_no_auto_destructive`
(config half).

## R2 — Campaign model + stores (over EA-0008 runs)

**Spec:** §6, §7, FR-1/8/15, D1/S1.
**Deliverables:** `CampaignStore` + `TriggerStore` (in-memory + Postgres + DDL,
optimistic version); `plan_campaign` (proposes an EA-0008 run per playbook,
groups into phases, **executes nothing**); campaign status **derived** from run
states.
**Depends on:** R1.
**Acceptance:** `test_resp_plan_no_execution`, `test_resp_status_derived`,
`test_resp_campaign_contract[inmemory]`, `test_resp_campaign_contract[postgres]`,
`test_resp_trigger_contract[inmemory]`, `test_resp_trigger_contract[postgres]`.

## R3 — Advance / halt through the single acting path

**Spec:** §1 (S1), §7, FR-2/3/9/10, NFR-1.
**Deliverables:** `advance` (starts phase runs **only via EA-0008 `execute`**;
refusal → phase `blocked`, surfaced, never bypassed, **no retry with weaker
gates**); phase ordering/`depends_on`; failed phase blocks dependents;
`halt_campaign` via EA-0008.
**Depends on:** R2.
**Acceptance:** `test_resp_advance_via_workflow`, `test_resp_refusal_blocks`,
`test_resp_no_privileged_path`, `test_resp_phase_ordering`, `test_resp_halt`.

## R4 — Automation triggers + approval routing (the bounded bits)

**Spec:** §1 (S2/S3), §7, FR-4/5/6/7, D2/D3/D4.
**Deliverables:** `evaluate_triggers` (EA-0009 structured conditions, **no
`eval`**; starts a run only if `max_effect ≤ reversible` **and** eligibility ==
`automatic` **and** `requires_approval == False` **and** Policy permits —
otherwise routes for approval); `route_approval` + `escalate_overdue` (SLA;
**never grants, never synthesizes an `Approval`**; expiry ≠ consent).
**Depends on:** R3.
**Acceptance:** `test_resp_no_auto_destructive`, `test_resp_trigger_bounded`,
`test_resp_trigger_no_eval`, `test_resp_routing_not_granting`.

## R5 — Recovery verification + metrics

**Spec:** §7, FR-11/12/13, D5/D6, S5.
**Deliverables:** `verify_recovery` (re-check via EA-0011/0012 assessment; if
unverified → finding + **proposed** follow-up run, never forced); evidence for
phases/triggers/routing/verification; `metrics` (read-only MTTD/MTTR/
containment).
**Depends on:** R4.
**Acceptance:** `test_resp_recovery_verify`, `test_resp_evidence_trail`,
`test_resp_metrics`.

## R6 — Service + events

**Spec:** FR-16, §11.
**Deliverables:** `ResponseOrchestrationService` (`AQService`, name
`"response_engine"`) + `register_response_events`; wired into the kernel factory.
**Depends on:** R5.
**Acceptance:** `test_resp_service_health`.

---

## Review protocol (Claude Code) — the hardest boundary review yet

Per ticket, confirm the normal DoD **and**, first and hardest:
1. **No privileged execution path.** The engine must never invoke an
   `ActionHandler` directly, construct/mutate an `Approval` or `Run` state, or
   reach around EA-0008's public API. Use a **handler spy**: assert zero direct
   handler invocations; every effect traces to an EA-0008 `execute` that
   re-validated its gates (S1/NFR-1).
2. **No second executor / playbook / approval authority.** Confirm the module
   reuses EA-0008's `Playbook`/`Approval`/`Run` rather than redefining them (§0).
3. **Destructive is never auto-started** — and `max_effect` cannot even express
   it. Try to configure it and assert rejection (S2).
4. **Triggers cannot widen a gate** — eligibility + Policy are honored; a refused
   run is routed for approval, never retried with weaker gates (S2).
5. **Routing ≠ granting** — no self-approval, no synthesized `Approval`, and SLA
   expiry does not imply consent (S3).
6. Campaign status derives from EA-0008 run states (no divergent truth); failed
   phase blocks dependents; everything evidenced and reconstructable.
7. No `eval`/`exec`; no network; tenant-scoped; `ruff` + `mypy --strict` clean.

Merge only on green review; then **report back to the owner** before the next
module.
