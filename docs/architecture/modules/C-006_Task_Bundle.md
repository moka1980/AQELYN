# C-006 Policy Engine — Implementation Task Bundle

**Milestone:** C-006 (Policy Engine, EA-0009)
**For:** Codex (implementer) · Claude Code (reviewer)
**Prerequisites:** EA-0008 merged & green; EA-0009 spec **Accepted**; CONVENTIONS + EA-0002/0008 read.
**Definition of Done:** every ticket's acceptance tests pass on in-memory **and** Postgres; `ruff` clean; `mypy --strict` clean; nothing outside the spec; `make check` green; Claude Code sign-off per ticket.

**Order matters for safety:** the safe condition interpreter (P1) and the
deny-by-default decision core (P2) are proven **before** persistence and the
Workflow wiring. Never introduce `eval`/`exec`/dynamic import for conditions.

## Target source layout

```
src/aqelyn/policy/
├── __init__.py       # exports PolicyEngine, service, types, register_policy_events
├── models.py         # Condition, Target, Rule, Policy, DecisionRequest, Decision, ComplianceResult (P1)
├── interpreter.py    # safe structured condition evaluator (attr/op/value + all/any/not) (P1)
├── engine.py         # PolicyEngine: authorize (deny-overrides), evaluate_compliance, explain (P2)
├── store.py          # PolicyStore protocol (P3)
├── memory.py         # InMemoryPolicyStore (P3)
├── postgres.py       # PostgresPolicyStore + DDL (P3)
└── service.py        # PolicyEngineService(AQService) + register_policy_events (P4)
tests/policy/         # acceptance suite (in-memory + Postgres)
```

---

## P1 — Models + safe condition interpreter (build first)

**Spec:** §5, §7 (interpreter), S4, FR-5/FR-10; §10.
**Deliverables:** the types; the structured condition interpreter supporting
exactly the leaf `Op`s + `all`/`any`/`not`, with a nesting-depth cap; validation
that raises `PolicyConfigInvalid` on unknown `op`/`effect`/`kind`, malformed
condition, or over-deep nesting; the new error codes in `conventions.errors` +
CONVENTIONS §9. **No `eval`/`exec`/dynamic import anywhere.**
**Depends on:** conventions.
**Acceptance:** `test_policy_condition_interpreter`, `test_policy_no_code_eval`,
`test_policy_config_invalid`, `test_policy_depth_cap`.

## P2 — Decision core (deny-by-default, deny-overrides, compliance)

**Spec:** §7, FR-1/2/3/4/6/8/13, S1/S2/S3/S5.
**Deliverables:** `authorize` (deny-by-default, deny-overrides, obligation
aggregation, matched-rules + reason), the tighten-only guarantee, and
`evaluate_compliance`; `explain`. Pure — no writes.
**Depends on:** P1.
**Acceptance:** `test_policy_deny_by_default`, `test_policy_deny_overrides`,
`test_policy_require_approval`, `test_policy_explainable`,
`test_policy_tighten_only`, `test_policy_compliance_violations`,
`test_policy_no_side_effects`.

## P3 — PolicyStore (persistence + tenant scoping)

**Spec:** §5 (Policy), §6, FR-7/9/10/11, S6.
**Deliverables:** `PolicyStore` protocol; `InMemoryPolicyStore` +
`PostgresPolicyStore` (+ DDL), versioned/provenanced, tenant + global-baseline
`list`; one parametrized contract suite.
**Depends on:** P2.
**Acceptance:** `test_policy_tenant_scoping`, `test_policy_provenance`,
`test_policy_store_contract[inmemory]`, `test_policy_store_contract[postgres]`.

## P4 — Service + Workflow integration

**Spec:** FR-12, §11, §12.
**Deliverables:** `PolicyEngineService` (`AQService`, name `"policy_engine"`) +
`register_policy_events`; the adapter the Workflow Engine uses to replace its
static capability grant with `authorize`, mapping `permit`/`deny`/
`require_approval` and composing **most-restrictively** with EA-0008 floors (S3);
wired into the kernel factory.
**Depends on:** P3.
**Acceptance:** `test_policy_service_health`, `test_policy_workflow_adapter`.

---

## Review protocol (Claude Code) — safety gets the hard look

Per ticket, confirm the normal DoD **and**, with extra scrutiny:
1. **No `eval`, `exec`, `compile`, or dynamic import** anywhere in condition
   handling — grep and trace it; conditions are data, never code (S4).
2. Deny-by-default and deny-overrides hold; no permit path escapes them.
3. The **tighten-only** invariant (S3) holds: the Workflow adapter can only add
   gates/denials, never downgrade an EA-0008 floor. Trace the composition.
4. Evaluation is pure — `authorize`/`evaluate_compliance` write nothing.
5. Tenant + global-baseline scoping is correct; no cross-tenant leakage.
6. Invalid policies are rejected at `put`, before any decision uses them.
7. `ruff` + `mypy --strict` clean; interfaces match the spec exactly.

Merge only on green review; then **report back to the owner** before the next
module.
