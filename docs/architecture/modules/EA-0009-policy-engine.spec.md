# EA-0009 — Policy Engine — Implementation Specification

**Realizes:** EA-0009 (supersedes the placeholder `archive/EA-0009/EA-0009_Master.md` for implementation)
**Depends on:** ADR-0001, CONVENTIONS, EA-0001 (`AQService`), EA-0002 (objects — compliance targets), EA-0003 (events), EA-0004 (evidence — decisions are recordable)
**Consumed by:** **EA-0008 Workflow Engine** (its S1 capability check calls `authorize`), the Finding pipeline (turn compliance violations into findings), UI (policy management, decision explanations)
**Status:** Accepted
**Build milestone:** C-006 (see `C-006_Task_Bundle.md`)
**Definition of Ready:** see §12

---

## 1. Purpose

The Policy Engine is AQELYN's **authority on what is allowed and what is
required**. It plays two roles: a **decision point** — given "may this actor
perform this capability on this target?", it returns an explainable
permit/deny/require-approval decision (this is the authority the Workflow Engine
enforces); and a **compliance evaluator** — given required-state rules (e.g.
"tier-1 assets must have MFA"), it reports what complies and what doesn't. Both
roles are declarative, deterministic, and explainable, so every decision can be
audited and defended.

## 2. Safety & authorization posture (read first — this governs everything else)

- **S1 — Deny by default.** `authorize` returns `deny` unless an applicable rule
  explicitly permits. No rule = no permission.
- **S2 — Deny overrides.** If any applicable rule denies, the decision is `deny`,
  regardless of any permits. Safety beats convenience.
- **S3 — The engine can only *tighten*, never *loosen*, another engine's safety
  floor.** The Workflow Engine's deny-by-default, effect-based gating, and
  destructive-`confirm_token` rules (EA-0008 §2) are **hard floors**. A Policy
  decision composes with them by taking the **more restrictive** outcome: Policy
  may add an approval requirement or deny, but a Policy `permit` can never
  downgrade an EA-0008 gate. This invariant is the reason the two engines are
  separate.
- **S4 — No arbitrary code execution.** Rule conditions are a **bounded,
  structured predicate model** (attribute/operator/value + `all`/`any`/`not`),
  evaluated by a fixed interpreter. The engine SHALL NOT `eval`/`exec` strings or
  load executable rule code. Untrusted policy text can configure *data*, never
  *code*.
- **S5 — Deterministic, pure, explainable.** Identical `(request, policies)` →
  identical decision. Evaluation has no side effects. Every decision carries the
  rule(s) that fired and a plain-language reason.
- **S6 — Tenant-scoped with a global baseline.** Only policies for the resource's
  tenant plus global (`tenant_id = NULL`) baseline policies apply; a tenant's
  policies never affect another tenant.

## 3. Scope

**In scope:** declarative versioned policies + rules, the safe condition
interpreter, the authorization decision (`authorize`), compliance evaluation, the
`PolicyStore` (in-memory + Postgres), decision/violation explanation, and the
`PolicyEngine` interface + `PolicyEngineService` (`AQService`).

**Out of scope:** *enforcing* decisions (the Workflow Engine and other callers
enforce; this engine decides), authoring UI, turning violations into findings
(the Finding pipeline does that from the returned results), and learned/ML policy
inference (out — policies are explicit and declarative).

## 4. Ubiquitous language

| Term | Meaning |
|---|---|
| **Policy** | A declarative, versioned, provenanced set of rules, tenant-scoped (or global baseline). |
| **Rule** | `kind ∈ {authorization, compliance}` with a target, a condition, an effect, and obligations. |
| **Condition** | A structured predicate (attr/op/value + `all`/`any`/`not`) — never code (S4). |
| **Effect** | Authorization: `permit`/`deny`/`require_approval`. Compliance: `require` (a state that must hold). |
| **Obligation** | An extra requirement attached to a decision (e.g. `require_approval`, `require_confirm`, `notify`). |
| **Decision** | The authorization outcome + matched rules + obligations + reason. |
| **Violation** | A compliance rule whose required condition does not hold for a resource. |

## 5. Types

```
Op = "eq" | "ne" | "in" | "nin" | "gt" | "gte" | "lt" | "lte" | "exists" | "contains"

Condition = { op: Op, attr: str, value: Any }        # leaf: dotted path into request/resource attrs
          | { all: list[Condition] }                  # AND
          | { any: list[Condition] }                  # OR
          | { not: Condition }                        # NOT
# The interpreter supports exactly these forms. Nothing else. (S4)

Target = { actions: list[str] | null,                 # capabilities this rule applies to (null = any)
           resource_types: list[str] | null }         # object_types this rule applies to (null = any)

Obligation = { type: str, params: dict }              # e.g. {"require_approval"}, {"require_confirm"}

Rule = { id: str, kind: "authorization" | "compliance", description: str,
         target: Target, condition: Condition | null,
         effect: "permit" | "deny" | "require_approval" | "require",
         obligations: list[Obligation], priority: int }

Policy = { id: str, version: int, name: str, description: str,
           tenant_id: str | null,                     # null = global baseline (S6)
           rules: list[Rule], standard: str | null,   # optional compliance-framework tag
           set_by: ActorRef, set_at: datetime }

DecisionRequest = { subject: ActorRef, action: str,   # the capability being requested
                    resource: { id: str | null, type: str | null,
                                attributes: dict, tenant_id: str | null },
                    context: dict }

Decision = { effect: "permit" | "deny" | "require_approval",
             matched_rules: list[str], obligations: list[Obligation],
             reason: str }

ComplianceViolation = { policy_id: str, rule_id: str, subject_ref: str,
                        requirement: str, reason: str }
ComplianceResult = { compliant: bool, violations: list[ComplianceViolation],
                     evaluated: int }
```

## 6. Interfaces (Python 3.12)

```python
from typing import Protocol, Sequence

class PolicyStore(Protocol):
    async def put(self, policy: Policy) -> Policy: ...          # validates (S4/FR-10); versioned/provenanced
    async def get(self, policy_id: str) -> Policy | None: ...
    async def list(self, *, tenant_id: str | None) -> list[Policy]: ...   # tenant + global baseline (S6)

class PolicyEngine(Protocol):
    async def authorize(self, request: DecisionRequest) -> Decision: ...  # PDP; deny-by-default (S1/S2)
    async def evaluate_compliance(
        self, resource: dict, *, tenant_id: str | None
    ) -> ComplianceResult: ...
    def explain(self, decision: Decision) -> dict: ...                    # matched rules + reason detail
```

`PolicyEngineService` wraps the engine + store as an `AQService`
(name `"policy_engine"`, health reflects store availability + policy validity).
The condition interpreter is an internal, side-effect-free evaluator (S4).

## 7. Evaluation (the reference model)

**Authorization (`authorize`)** — deny-overrides, deny-by-default:

1. Load applicable policies (tenant + global baseline, S6).
2. Select rules with `kind == "authorization"` whose `target` matches `action`/
   `resource.type` and whose `condition` evaluates true against the request.
3. Combine: if **any** matched rule `deny` → `deny` (S2). Else if any
   `require_approval` (or a permit carrying a `require_approval` obligation) →
   `require_approval`. Else if any `permit` → `permit`. Else → `deny` (S1).
4. Aggregate obligations from all matched non-deny rules. Attach `matched_rules`
   + a plain-language `reason`.

**Compliance (`evaluate_compliance`)** — for each applicable `kind ==
"compliance"` rule whose `target` matches the resource, the rule's `condition`
is the **required** state; if it does not hold, emit a `ComplianceViolation`.
`compliant = (violations == [])`.

**Composition floor (S3).** Callers combine a Policy `Decision` with their own
floor by most-restrictive: `deny` > `require_approval` > `permit`. The engine
guarantees it never emits a decision that *removes* an obligation or downgrades a
deny — it can only add restrictions.

## 8. Requirements

### Functional (testable)

- **FR-1** `authorize` SHALL return `deny` when no authorization rule permits the request (deny-by-default, S1).
- **FR-2** Any applicable `deny` rule SHALL force a `deny` decision regardless of permits (deny-overrides, S2).
- **FR-3** `require_approval` SHALL result when an applicable rule requires approval (or a permit carries that obligation) and no rule denies; obligations SHALL be aggregated.
- **FR-4** Decisions SHALL be deterministic and pure, carrying `matched_rules` and a plain-language `reason` (S5).
- **FR-5** Conditions SHALL be evaluated only via the structured interpreter (leaf ops + `all`/`any`/`not`); the engine SHALL NOT `eval`/`exec` any string or load rule code (S4). An unsupported op/form SHALL raise `PolicyConfigInvalid` at `put`.
- **FR-6** The engine SHALL NOT emit a decision that downgrades a deny or drops an obligation — it can only tighten (S3); verified by the composition tests.
- **FR-7** Only the resource-tenant's policies plus global (`NULL`) baseline policies SHALL apply; other tenants' policies SHALL NOT affect the decision (S6).
- **FR-8** `evaluate_compliance` SHALL return each unmet `require` rule as a `ComplianceViolation` with an explanation; it SHALL mutate nothing.
- **FR-9** Policies SHALL be versioned and provenanced (`set_by`, `set_at`); `PolicyStore` SHALL preserve this (FR-10 covers validation).
- **FR-10** Invalid policies (unknown `effect`/`kind`/`op`, malformed `condition`, non-int `priority`) SHALL raise `PolicyConfigInvalid` at `put`, before any evaluation uses them.
- **FR-11** `PolicyStore` in-memory and Postgres implementations SHALL pass one contract suite.
- **FR-12** `PolicyEngineService` SHALL register as an `AQService` with health reflecting store availability + policy validity (EA-0001).
- **FR-13** Evaluation SHALL be side-effect free; no object/evidence/finding is written by `authorize`/`evaluate_compliance` (S5).

### Non-functional

- **NFR-1 (safety)** no code path evaluates rule conditions via `eval`/`exec` or dynamic import; enforced by a test that greps the module and by behavior tests.
- **NFR-2 (determinism)** identical `(request, policy set)` serialize to identical decisions.
- **NFR-3 (bounded)** evaluation is `O(rules)`; condition nesting depth is capped (default 32) → deeper nesting rejected at `put`.
- **NFR-4 (portability & typing)** in-memory + Postgres `PolicyStore` pass one suite; `mypy --strict` + `ruff` clean.

## 9. Acceptance Criteria ↔ Tests (Definition of Ready)

| # | Criterion | Test (pytest id) |
|---|---|---|
| AC-1 | No permit → deny | `test_policy_deny_by_default` |
| AC-2 | Any deny overrides permits | `test_policy_deny_overrides` |
| AC-3 | require_approval aggregates obligations | `test_policy_require_approval` |
| AC-4 | Decision carries matched rules + reason | `test_policy_explainable` |
| AC-5 | Structured condition eval (eq/in/gt/exists/all/any/not) | `test_policy_condition_interpreter` |
| AC-6 | No eval/exec of strings | `test_policy_no_code_eval` |
| AC-7 | Cannot downgrade a deny / drop obligation (tighten-only) | `test_policy_tighten_only` |
| AC-8 | Tenant + global baseline scoping | `test_policy_tenant_scoping` |
| AC-9 | Compliance returns violations w/ reasons | `test_policy_compliance_violations` |
| AC-10 | Invalid policy rejected at put | `test_policy_config_invalid` |
| AC-11 | Policy versioned + provenanced | `test_policy_provenance` |
| AC-12 | Evaluation mutates nothing | `test_policy_no_side_effects` |
| AC-13 | Nesting depth cap enforced | `test_policy_depth_cap` |
| AC-14 | In-memory & Postgres store pass one suite | `test_policy_store_contract[inmemory]` / `[postgres]` |
| AC-15 | Registers as AQService with health | `test_policy_service_health` |
| AC-16 | Workflow authorize adapter maps permit/deny/approval | `test_policy_workflow_adapter` |

## 10. Error taxonomy (contributions)

`PolicyConfigInvalid`, `PolicyNotFound` (added to `conventions.errors` +
CONVENTIONS §9). Reuses `StoreUnavailable`, `TenantScopeRequired`.

## 11. Registered event types (owned by EA-0009)

`aqelyn.policy.updated`, `aqelyn.policy.decision_denied` (optional audit signal
for denied authorizations) — registered via `register_policy_events()`
(EA-0003 §7). `decision_denied` is emitted by callers that choose to audit
denials, not by the pure `authorize` path.

## 12. Dependencies & consumers

- **Depends on:** EA-0001 `AQService`; EA-0002 (compliance targets are objects);
  `ActorRef` (CONVENTIONS); EA-0003 events; EA-0004 for callers that record
  decisions as evidence.
- **Consumed by — the key integration:** the **Workflow Engine** replaces its
  static capability-grant source (EA-0008 S1/FR-1) with a call to
  `PolicyEngine.authorize(DecisionRequest(subject, action=capability,
  resource=target, context))`. Mapping: `permit` → capability granted; `deny` →
  `UnauthorizedAction`; `require_approval` (or an approval obligation) → the step
  is gated. Per S3 this composes **most-restrictively** with EA-0008's own floors
  — Policy can add gates, never remove them. Also consumed by the Finding
  pipeline (violations → findings) and policy-management UI.

## 13. Resolved / deferred decisions

- **Deny-overrides + deny-by-default** is the binding combining algorithm; a
  configurable algorithm is not offered (a single, safe, well-understood rule is
  preferred for auditability).
- **Structured predicate model over an expression language.** No embedded DSL
  that could execute; if richer conditions are ever needed they extend the
  structured `Op` set under review, never via arbitrary code (S4 is permanent).
- **Policy authorship UI and framework mappings** (e.g. mapping rules to named
  compliance standards) are deferred; the `standard` tag reserves the seam.
- **Tighten-only composition (S3)** is a permanent invariant shared with EA-0008;
  neither engine may be changed to let policy loosen a safety floor without a new
  ADR.
