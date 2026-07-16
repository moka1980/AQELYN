# EA-0020 — AI Decision Intelligence Engine — Implementation Specification

**Realizes:** EA-0020 / IS-020 (supersedes the placeholder `archive/EA-0020/EA-0020_Master.md` for implementation)
**Depends on:** ADR-0001, CONVENTIONS, EA-0001 (`AQService`), **EA-0006 (Trust — the confidence authority)**, EA-0007 (Mission), EA-0013 (Risk), EA-0015 (SOC cases), EA-0004 (evidence), **EA-0008 (the only acting path)**
**Consumed by:** the SOC analyst workspace (recommendations shown beside their derivation — a WCAG 2.2 AA surface), EA-0018 (recommendations may seed a *proposed* campaign), reporting
**Status:** Accepted
**Build milestone:** C-017 (see `C-017_Task_Bundle.md`)
**Definition of Ready:** see §12

---

## 0. Scope reconciliation (what IS-020 asks for vs what exists)

| IS-020 component | Realization |
|---|---|
| Confidence Engine | **Already EA-0006 Trust.** Reused as the confidence authority — **no second confidence model**. |
| Explainability Engine | **Not a bolt-on explainer.** Every engine already explains itself, and a post-hoc explainer would produce *rationalizations*, not explanations (§1 S2). Realized here as **explanation-by-construction**: the derivation *is* the explanation. |
| Recommendation Engine | **New here:** advisory recommendations derived from existing, cited claims. |
| Reasoning Engine | **New here:** the explicit, replayable `Derivation` that produces a recommendation. |
| Similarity Engine | **New here:** an explicit, deterministic similarity metric over cases/incidents. |
| Learning Engine | **New here, tightly bounded:** feedback → versioned proposals that are **never auto-applied** (§1 S5). |
| Analytics Engine | **New here:** read-only decision analytics (acceptance rate, accuracy over time). |

## 1. The central problem, and the boundary (read first)

For fifteen modules AQELYN has held: **evidence before opinion**, deterministic,
reproducible, explainable — *"how AQELYN knows"* answerable for every claim. An
"AI decision" engine is precisely where a platform quietly abandons that and
starts emitting conclusions the rest of the system trusts because they sound
right. This spec refuses that trade:

- **S1 — Explanation-by-construction (the load-bearing rule).** A
  `Recommendation` is **invalid without a complete `Derivation`** — an ordered
  list of explicit steps, each naming its input refs, operation, parameters, and
  output. `replay(derivation)` re-executes those steps against the pinned inputs
  and **MUST equal** the recommendation. **A recommendation that cannot be
  replayed cannot be emitted** — enforced by the constructor and a validation
  gate, not by convention.
  *This is why it is structural, not textual:* an opaque model cannot produce a
  replayable derivation of explicit steps, so the invariant excludes black boxes
  **by construction** rather than by grepping for library imports (which the
  C-016 review proved is gameable).
- **S2 — The explanation is the derivation, never a narrative about it.** The
  engine SHALL NOT generate prose that *describes* a conclusion reached some
  other way. A plausible story is not knowing. Human-readable text is **rendered
  from** the derivation, never authored independently of it.
- **S3 — Recommendations are advisory. They are not findings, not evidence, not
  actions.** A recommendation SHALL NOT be raised as a finding asserting fact,
  SHALL NOT be cited as evidence for another claim, and SHALL NOT execute
  anything. It may **propose** a gated EA-0008 run — the same path as everything
  else. (Extends the EA-0017 S4 stance on projections.)
- **S4 — Derived from cited claims, never invented.** Every derivation input is a
  **reference to an existing platform claim** (finding, risk, detection, trust
  assessment, mission impact, case) with its evidence. The engine adds reasoning
  over claims; it never originates a claim about the world.
- **S5 — Learning never auto-applies.** Feedback produces a **versioned proposal**
  (`ModelVersion`), which takes effect only via an **explicit, attributed,
  evidenced promotion**. Behavior SHALL NOT drift silently. Every recommendation
  pins the `model_version` in force, so a decision from six months ago is still
  explainable and replayable against *that* version (the EA-0017 S2 pattern,
  strengthened: promotion is an explicit act).
- **S6 — No opaque model in this EA.** Any future learned component needs its own
  ADR **and** must still satisfy S1 (replayable derivation) — S1 is not waivable
  by an ADR that only argues accuracy.
- **S7 — Confidence is EA-0006's.** No second confidence model (§0).

Tenant-scoped, bounded, no network. No new authorization surface.

## 2. Purpose

Fifteen engines produce claims: findings, risks, detections, mission impacts,
threat matches. An analyst still has to answer *"given all this — what should I
do?"* This engine makes that step **explicit and inspectable**: it derives
**advisory recommendations** from cited claims via a replayable derivation, finds
**similar prior cases**, and learns from analyst feedback — **without ever
becoming an oracle.** Its value is not that it decides; it is that it *shows its
work* well enough for a human to decide faster and defend the decision later.

## 3. Design decisions

- **D1 — Derivation is a first-class, persisted, replayable structure** (S1).
  Operations come from a **fixed, registered vocabulary** (e.g. `select_claims`,
  `filter`, `weigh` (Trust), `mission_weight`, `rank`, `threshold`,
  `similarity`) — each a pure function. New operations are added to the registry
  under review, never as free-form code in a rule.
- **D2 — Recommendations are objects** (`object_type "recommendation"`),
  evidence-*referencing* (not evidence-*creating* for their conclusion, S3).
- **D3 — Similarity is an explicit, deterministic metric** (e.g. weighted Jaccard
  over shared signal kinds/assets/techniques) — reported as *"similar because it
  shares 3 of 4 indicators and the same asset class"*, never an opaque embedding
  distance.
- **D4 — Feedback is recorded, learning is proposed, promotion is explicit**
  (S5). `LearningRecord` captures accept/reject + reason; a proposal adjusts
  weights/thresholds **only** in a new `ModelVersion`.
- **D5 — Decision analytics are read-only** (acceptance rate, precision against
  later outcomes). No new scorer.
- **D6 — Registered as an `AQService`;** stores in-memory + Postgres.

## 4. Ubiquitous language

| Term | Meaning |
|---|---|
| **Claim ref** | A reference to an existing platform claim (finding/risk/detection/…) + its evidence (S4). |
| **Derivation** | The ordered explicit steps producing a recommendation; replayable (S1). |
| **Operation** | A pure, registered function usable in a derivation step (D1). |
| **Recommendation** | An advisory suggestion + its derivation + confidence. Never a finding/evidence/action (S3). |
| **Decision record** | What a human actually decided about a recommendation (accept/reject/modify). |
| **Model version** | The pinned, versioned parameter set in force for a derivation (S5). |
| **Learning record** | Feedback captured for a proposed (not applied) parameter change (S5). |

## 5. Types

```
ClaimRef      = { kind: "finding"|"risk"|"detection"|"trust"|"mission"|"case",
                  ref_id: str, evidence_id: str | null }        # S4

DerivationStep = { seq: int, op: str,                            # from the registered vocabulary (D1)
                   input_refs: list[str], params: dict,
                   output: dict, note: str }                     # human-readable, rendered from data (S2)
Derivation    = { inputs: list[ClaimRef], steps: list[DerivationStep],
                  result: dict, model_version: int,
                  engine_version: str }                          # replayable (S1)

Recommendation = { id, tenant_id, subject_ref: str,
                   statement: str,                               # rendered FROM the derivation (S2)
                   action_hint: dict | null,                     # what a proposed run would do (S3)
                   confidence: float,                            # from EA-0006 Trust (S7)
                   derivation: Derivation,                       # MANDATORY (S1)
                   advisory: bool = True,                        # always (S3)
                   created_at: datetime }

DecisionRecord = { id, recommendation_id: str, decision: "accepted"|"rejected"|"modified",
                   decided_by: ActorRef, reason: str, at: datetime,
                   workflow_run_id: str | null,                  # if it led to a proposed run (S3)
                   evidence_id: str }
LearningRecord = { id, recommendation_id: str, feedback: str,
                   proposed_change: dict, applied: bool = False, # NEVER auto-true (S5)
                   recorded_at: datetime }
ModelVersion  = { version: int, params: dict, promoted_by: ActorRef | null,
                  promoted_at: datetime | null, active: bool,
                  evidence_id: str | null }                      # promotion is explicit + evidenced (S5)
SimilarityHit = { case_id: str, score: float, shared: dict, reason: str }   # D3
DecisionConfig = { operations_allowed: list[str], max_steps: int,
                   min_confidence: float, batch_size: int }
```

Reuses EA-0006 confidence, `ActorRef`, EA-0004 evidence refs, EA-0015 cases.

## 6. Interfaces (Python 3.12)

```python
from typing import Protocol, Sequence

class OperationRegistry(Protocol):
    def register(self, name: str, fn: "PureOp") -> None: ...      # pure, deterministic (D1)
    def get(self, name: str) -> "PureOp": ...                     # UnknownOperation if absent

class ModelVersionStore(Protocol):
    async def put(self, mv: ModelVersion) -> ModelVersion: ...     # new version; never mutate active
    async def active(self, *, tenant_id: str | None) -> ModelVersion: ...
    async def get(self, version: int) -> ModelVersion | None: ...
    async def promote(self, version: int, *, by: ActorRef, reason: str) -> ModelVersion: ...  # explicit (S5)

class RecommendationStore(Protocol):
    async def put(self, rec: Recommendation) -> Recommendation: ...   # rejects if derivation invalid (S1)
    async def get(self, rec_id: str) -> Recommendation | None: ...
    async def query(self, *, tenant_id: str | None, limit: int = 100) -> list[Recommendation]: ...

class DecisionIntelligenceEngine(Protocol):
    async def recommend(self, *, subject_ref: str, tenant_id: str | None
                        ) -> list[Recommendation]: ...             # derives from cited claims (S1/S4)
    async def replay(self, derivation: Derivation) -> dict: ...     # MUST equal recommendation.result (S1)
    async def similar_cases(self, case_id: str, *, limit: int = 5) -> list[SimilarityHit]: ...  # D3
    async def record_decision(self, rec_id: str, *, decision: str, by: ActorRef,
                              reason: str, propose_run: bool = False) -> DecisionRecord: ...  # S3
    async def record_feedback(self, rec_id: str, *, feedback: str,
                              by: ActorRef) -> LearningRecord: ...   # proposes only (S5)
    async def propose_model_version(self, *, from_learning: Sequence[str],
                                    by: ActorRef) -> ModelVersion: ...  # inactive until promoted (S5)
    async def analytics(self, *, tenant_id: str | None) -> dict: ...    # read-only (D5)
    def explain(self, rec: Recommendation) -> dict: ...              # renders the derivation (S2)
```

`DecisionIntelligenceService` wraps engine + stores as an `AQService`
(name `"decision_engine"`, depends on trust/mission/risk/soc/finding/evidence/
workflow; health reflects availability + config validity).

## 7. Computation (the reference model)

**Recommend.** Gather `ClaimRef`s for the subject (findings, risks, detections,
mission impact — each with evidence, S4). Execute a derivation using only
**registered pure operations** (D1) under the **active `ModelVersion`**: select →
filter → weigh (EA-0006 Trust) → mission-weight (EA-0007) → rank → threshold.
Each step records `input_refs`, `params`, and `output`. `confidence` comes from
Trust (S7). `statement` is **rendered from** the final steps (S2). The
`Recommendation` is constructed **with** its `Derivation`; the store **rejects**
any recommendation whose `replay(derivation) != result` (S1).

**Replay.** Re-execute the derivation's steps against the pinned inputs +
`model_version`. Any divergence ⇒ `DerivationNotReplayable` — the recommendation
is invalid, surfaced, not shown as trustworthy.

**Similarity.** Explicit metric over shared features (signal kinds, assets,
techniques); `shared` + `reason` name exactly what matched (D3).

**Decide.** `record_decision` stores what the human chose + an `EvidenceRecord`;
if `propose_run`, it creates a **proposed** EA-0008 run (never executes, S3).

**Learn.** `record_feedback` stores a `LearningRecord` (`applied=False`).
`propose_model_version` derives a new **inactive** `ModelVersion`; only
`promote` (explicit, attributed, evidenced) activates it. Existing
recommendations keep their pinned version and stay replayable (S5).

## 8. Requirements

### Functional (testable)

- **FR-1** A `Recommendation` SHALL be invalid without a complete `Derivation`; construction/`put` SHALL reject one lacking it (S1).
- **FR-2** `replay(derivation)` SHALL re-execute the pinned steps and equal `recommendation.result`; a mismatch SHALL raise `DerivationNotReplayable` and the recommendation SHALL NOT be served as valid (S1).
- **FR-3** Derivation steps SHALL use only operations in the registered vocabulary; an unknown/unregistered op SHALL raise `UnknownOperation`. Operations SHALL be pure and deterministic (D1).
- **FR-4** `statement`/`explain` output SHALL be rendered from the derivation; the engine SHALL NOT produce an explanation not derived from the recorded steps (S2).
- **FR-5** Every derivation input SHALL be a `ClaimRef` to an existing platform claim; the engine SHALL NOT originate a claim about the world (S4).
- **FR-6** A recommendation SHALL be `advisory=True`, SHALL NOT be raised as a finding, SHALL NOT be usable as evidence for another claim, and SHALL NOT execute anything (S3).
- **FR-7** `record_decision(propose_run=True)` SHALL create a **proposed** EA-0008 run only; no direct action (S3).
- **FR-8** `confidence` SHALL come from EA-0006 Trust; the module SHALL NOT implement a second confidence model (S7).
- **FR-9** `record_feedback` SHALL store `applied=False`; feedback SHALL NOT change active behavior (S5).
- **FR-10** `propose_model_version` SHALL create an **inactive** version; only `promote` (attributed + evidenced) SHALL activate it; the engine SHALL NOT self-promote (S5).
- **FR-11** Every recommendation SHALL pin its `model_version`; replaying an old recommendation SHALL use the pinned version, not the active one (S5).
- **FR-12** `similar_cases` SHALL use an explicit deterministic metric and report `shared` + `reason`; no opaque distance (D3).
- **FR-13** Derivations SHALL be bounded (`max_steps`); operations SHALL be side-effect free; the engine SHALL open no network connection.
- **FR-14** All operations SHALL be tenant-scoped; invalid config (unknown op in `operations_allowed`, `max_steps ≤ 0`) SHALL raise `DecisionConfigInvalid`.
- **FR-15** `RecommendationStore`, `ModelVersionStore` in-memory and Postgres implementations SHALL each pass one contract suite.
- **FR-16** `DecisionIntelligenceService` SHALL register as an `AQService` with health reflecting dependency availability + config validity (EA-0001).

### Non-functional

- **NFR-1 (no unexplainable output — structural)** the type + store gate make an unreplayable recommendation unrepresentable: it cannot be constructed, stored, or served. Verified behaviorally (`replay == result` on every recommendation in the suite), **not** by grepping for model libraries.
- **NFR-2 (no silent drift)** no code path activates a `ModelVersion` without an explicit attributed `promote`; proven by refusal tests.
- **NFR-3 (advisory-only)** no code path turns a recommendation into a finding, evidence, or an executed action; proven by tests.
- **NFR-4 (bounded & typed)** derivations step-capped, batched; `mypy --strict` + `ruff` clean.

## 9. Acceptance Criteria ↔ Tests (Definition of Ready)

| # | Criterion | Test (pytest id) |
|---|---|---|
| AC-1 | Recommendation without derivation rejected | `test_dec_derivation_required` |
| AC-2 | replay(derivation) == result for every recommendation | `test_dec_replay_equals_result` |
| AC-3 | Tampered derivation → DerivationNotReplayable, not served | `test_dec_replay_mismatch_rejected` |
| AC-4 | Only registered pure ops; unknown op rejected | `test_dec_operation_registry` |
| AC-5 | Explanation rendered from derivation only | `test_dec_explanation_from_derivation` |
| AC-6 | Inputs are ClaimRefs; no invented claims | `test_dec_inputs_are_claims` |
| AC-7 | Advisory: not a finding, not evidence, no action | `test_dec_advisory_only` |
| AC-8 | Decision may propose gated run only | `test_dec_decision_proposes` |
| AC-9 | Confidence from Trust (no 2nd model) | `test_dec_confidence_from_trust` |
| AC-10 | Feedback recorded, never applied | `test_dec_feedback_not_applied` |
| AC-11 | Model version inactive until explicit promote | `test_dec_promotion_explicit` |
| AC-12 | Old recommendation replays against pinned version | `test_dec_pinned_version_replay` |
| AC-13 | Similarity explicit + explains shared features | `test_dec_similarity_explicit` |
| AC-14 | Derivation bounded; no network; tenant-scoped | `test_dec_bounds_and_scope` |
| AC-15 | Invalid config rejected | `test_dec_config_invalid` |
| AC-16 | Rec & model-version stores pass one suite each | `test_dec_rec_contract[...]` / `test_dec_model_contract[...]` |
| AC-17 | Registers as AQService with health | `test_dec_service_health` |

## 10. Error taxonomy (contributions)

`DecisionConfigInvalid`, `DerivationNotReplayable`, `UnknownOperation`,
`RecommendationNotFound`, `ModelVersionNotFound` (added to `conventions.errors` +
CONVENTIONS §9). Reuses `StoreUnavailable`, `TenantScopeRequired`.

## 11. Registered event types (owned by EA-0020)

`aqelyn.decision.recommendation_generated`, `aqelyn.decision.decision_recorded`,
`aqelyn.decision.model_promoted` — via `register_decision_events()` (EA-0003 §7).
(Archive uses `recommendation.generated`; mapped into the platform namespace.)

## 12. Failure handling

- Invalid config → `DecisionConfigInvalid` at construction.
- A derivation that fails to replay → the recommendation is **withheld**, not
  served with a caveat. An unexplainable recommendation is worse than none.
- A required claim/dependency unavailable → `StoreUnavailable`; service
  `degraded`; recommendations are **not** generated from partial inputs and
  silently presented as complete — the derivation would misrepresent its basis.
- Promotion with no `promoted_by` → refused (`applied`/`active` cannot be set
  without an attributed act, S5).
- Feedback on a withheld/invalid recommendation → recorded, but never proposed
  into a model change.

## 13. Dependencies & consumers

- **Depends on:** **EA-0006 Trust** (confidence, S7); EA-0007 Mission; EA-0013
  Risk; EA-0017 Detection; EA-0015 SOC (cases); EA-0004 evidence refs;
  **EA-0008 Workflow** (proposed runs only, S3); EA-0001 `AQService`.
- **Consumed by:** the SOC workspace — recommendations SHALL be rendered **beside
  their derivation**, never as a bare verdict (**WCAG 2.2 AA** applies); EA-0018
  (a recommendation may seed a *proposed* campaign); reporting.

## 14. Resolved / deferred decisions

- **Explanation-by-construction (S1)** is the binding mechanism and the reason
  this module does not weaken the platform: unreplayable output is
  unrepresentable. It is enforced structurally + behaviorally — **not** by grep
  (the C-016 review demonstrated textual checks are gameable).
- **No post-hoc narrative explanations (S2)** — a rationalization is not a
  reason.
- **Advisory only (S3)** — recommendations never become findings, evidence, or
  actions.
- **Learning proposes; humans promote (S5)** — no silent drift; old decisions
  stay replayable against their pinned version.
- **No opaque model here (S6);** any future learned component needs its own ADR
  **and** must still satisfy S1 — accuracy alone never buys a waiver.
