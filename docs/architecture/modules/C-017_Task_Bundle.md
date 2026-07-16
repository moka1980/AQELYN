# C-017 AI Decision Intelligence — Implementation Task Bundle

**Milestone:** C-017 (AI Decision Intelligence, EA-0020)
**For:** Codex (implementer) · Claude Code (reviewer)
**Prerequisites:** EA-0019 merged & green; EA-0020 spec **Accepted**; **EA-0020 §1 and EA-0017 §2 re-read**; CONVENTIONS + EA-0006/0008 read.
**Definition of Done:** every ticket's acceptance tests pass on in-memory **and** Postgres; `ruff` clean; `mypy --strict` clean; **every recommendation replays to its result; advisory-only; no silent learning drift**; nothing outside the spec; `make check` green; Claude Code sign-off per ticket.

**Read EA-0020 §1 first.** This is the module where a platform usually abandons
its principles. It doesn't here, because of one mechanism: **a recommendation
that cannot be replayed cannot exist.** Build the derivation machinery (E1–E2)
**before** anything can emit a recommendation.

**A note on verification (the C-016 lesson).** The L4 review found code
obfuscated to slip past an over-broad grep. Do **not** rely on textual checks in
this module. The invariant here is **behavioural**: for every recommendation the
suite produces, `replay(derivation) == result`. An opaque model cannot satisfy
that, which is the point — the check cannot be argued around.

## Target source layout

```
src/aqelyn/decision/
├── __init__.py       # exports the engine, service, types, register_decision_events
├── models.py         # ClaimRef, DerivationStep, Derivation, Recommendation,
│                     #   DecisionRecord, LearningRecord, ModelVersion, SimilarityHit, DecisionConfig (E1)
├── operations.py     # the registered vocabulary of PURE ops + OperationRegistry (E1)
├── derive.py         # build + replay a Derivation; the validity gate (E2)
├── store.py          # RecommendationStore + ModelVersionStore protocols (E2)
├── memory.py         # in-memory stores (E2)
├── postgres.py       # Postgres stores + DDL (E2)
├── recommend.py      # recommend() over ClaimRefs; confidence via EA-0006 Trust (E3)
├── similarity.py     # explicit deterministic metric (E3)
├── learning.py       # feedback -> proposal -> explicit promote (E4)
└── service.py        # DecisionIntelligenceService(AQService) + register_decision_events (E5)
tests/decision/       # acceptance suite (in-memory + Postgres)
```

---

## E1 — Types, operation registry & config

**Spec:** §5, §6, D1, FR-3/13/14; §10.
**Deliverables:** the models; the **registered vocabulary of pure operations**
(`select_claims`, `filter`, `weigh`, `mission_weight`, `rank`, `threshold`,
`similarity`) + `OperationRegistry` (`UnknownOperation` for anything else);
config validation (`DecisionConfigInvalid`); new error codes in
`conventions.errors` + CONVENTIONS §9. Operations must be **pure** — no I/O, no
state.
**Depends on:** EA-0006 types, conventions.
**Acceptance:** `test_dec_operation_registry`, `test_dec_config_invalid`.

## E2 — Derivation: build, replay & the validity gate (build before anything else)

**Spec:** §1 (S1/S2), §7, FR-1/2/4/15, NFR-1.
**Deliverables:** `Derivation` construction; **`replay()`**; the gate that makes
a recommendation **unrepresentable without a replayable derivation** (constructor
+ store `put` both reject); `explain()` rendering **from the derivation only**;
`RecommendationStore` + `ModelVersionStore` (in-memory + Postgres + DDL).
**Depends on:** E1.
**Acceptance:** `test_dec_derivation_required`, `test_dec_replay_equals_result`,
`test_dec_replay_mismatch_rejected`, `test_dec_explanation_from_derivation`,
`test_dec_rec_contract[inmemory]`, `test_dec_rec_contract[postgres]`,
`test_dec_model_contract[inmemory]`, `test_dec_model_contract[postgres]`.

## E3 — Recommend + similarity (derived from cited claims only)

**Spec:** §1 (S3/S4/S7), §7, FR-5/6/7/8/12, D3.
**Deliverables:** `recommend` (inputs are `ClaimRef`s to existing claims;
**confidence from EA-0006 Trust** — no second model; `advisory=True` always;
never a finding/evidence); `record_decision` (+ optional **proposed** EA-0008
run); `similar_cases` (explicit metric reporting `shared` + `reason`).
**Depends on:** E2.
**Acceptance:** `test_dec_inputs_are_claims`, `test_dec_advisory_only`,
`test_dec_decision_proposes`, `test_dec_confidence_from_trust`,
`test_dec_similarity_explicit`, `test_dec_bounds_and_scope`.

## E4 — Learning: propose, never apply

**Spec:** §1 (S5), §7, FR-9/10/11, NFR-2.
**Deliverables:** `record_feedback` (`applied=False`, always);
`propose_model_version` (**inactive**); `promote` (explicit, attributed,
evidenced — refuse without `promoted_by`); **every recommendation pins its
`model_version`** and old recommendations replay against the **pinned** version,
not the active one.
**Depends on:** E3.
**Acceptance:** `test_dec_feedback_not_applied`, `test_dec_promotion_explicit`,
`test_dec_pinned_version_replay`.

## E5 — Service + events

**Spec:** FR-16, §11.
**Deliverables:** `DecisionIntelligenceService` (`AQService`, name
`"decision_engine"`) + `register_decision_events`; wired into the kernel factory.
**Depends on:** E4.
**Acceptance:** `test_dec_service_health`.

---

## Review protocol (Claude Code) — behavioural proof, not textual

Per ticket, confirm the normal DoD **and**, with extra scrutiny:
1. **Replay is the gate.** For every recommendation the suite produces, assert
   `replay(derivation) == result`. Then **tamper** with a derivation and assert
   the recommendation is rejected/withheld — not served with a caveat (S1/FR-2).
   *Do not substitute a grep for model libraries; the invariant is behavioural.*
2. **Unrepresentable, not merely forbidden.** Try to construct/store a
   recommendation without a derivation and assert it fails at the type/gate — not
   at a lint rule.
3. **Explanation comes from the derivation only** — no prose path that could
   describe a conclusion reached elsewhere (S2). Trace `explain`/`statement`.
4. **Advisory-only** — no path makes a recommendation a finding, evidence, or an
   executed action; `record_decision` can only *propose* a gated run (S3).
5. **No second confidence model** — confidence traces to EA-0006 Trust (S7).
6. **No silent drift** — feedback never sets `applied=True`; a `ModelVersion`
   never activates without an attributed `promote`; old recommendations replay
   against their **pinned** version (S5).
7. Inputs are `ClaimRef`s — the engine never originates a world-claim (S4).
8. Bounded steps, no network, tenant-scoped; `ruff` + `mypy --strict` clean.

Merge only on green review; then **report back to the owner** before the next
module.
