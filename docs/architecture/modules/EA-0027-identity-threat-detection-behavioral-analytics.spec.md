# EA-0027 — Identity Threat Detection & Behavioral Analytics Engine — Implementation Specification

**Realizes:** EA-0027 / IS-027 (supersedes the placeholder `archive/EA-0027/EA-0027_Master.md` for implementation)
**Depends on:** ADR-0001, CONVENTIONS, EA-0001 (`AQService`), **EA-0017 (`BehaviorProfile`/`ProfileStore` — the one profiler)**, **EA-0011 (identity entitlements — cited)**, **EA-0006 (confidence)**, EA-0004 (evidence), EA-0013 (findings), EA-0008 (the only actor), EA-0020 (`Derivation` — replay), EA-0009 (Policy)
**Consumed by:** EA-0013 (detections arrive as findings), EA-0022 (executive summaries — account-scoped only)
**Status:** Accepted
**Build milestone:** C-024 (see `C-024_Task_Bundle.md`)
**Definition of Ready:** see §9

---

## 0. Scope reconciliation

Every prior engine analysed **systems**. This one analyses the behaviour of **named
human beings**, and it sits directly against a line the platform already drew —
**EA-0021 S8: "predictive suspicion of named people is out of scope, permanently."**
It is legitimate only because of a precise distinction, and it exists to *protect*
account owners (a stolen credential is something done *to* a person), never to
suspect them.

| The question | Owner | Realization |
|---|---|---|
| How does an identity normally behave? | **EA-0017** `BehaviorProfile`/`ProfileStore` | Profiles keyed by an **identity `subject_ref`** — no second profiler, no z-score maths here. |
| Does this identity have the *right* entitlements? | **EA-0011** | `access_paths`/`analyze_risk` — **cited, never merged**. This engine owns *how* they're used. |
| How confident are we? | **EA-0006** | The one confidence authority. |
| What becomes of a detection? | **EA-0013** finding + **EA-0008** gated action | A detection is a *question for a human*, never an auto-consequence. |

**Net-new:** credential intelligence and privilege-**use** analytics. Nothing else is
new — and one thing is deliberately **removed** (§S4).

Master overrides (**ECR-0016**): the archive demands an **"Identity risk score"**
(§429), **"insider threat identification"** (§107/261), and re-declares
`behavior.profile.updated` (§300) which **EA-0017 owns**. All three are rejected here.

## 1. The line this module turns on

| Legitimate | Forbidden |
|---|---|
| *"This credential authenticated from Oslo and São Paulo 40 minutes apart."* | *"This employee is likely to become an insider threat."* |
| A thing that **happened**, with evidence — and it usually **protects** the account's owner. | A **prediction about who someone is**. No evidence exists for it; the cost of being wrong is borne by a person. |

- **S1 — A detection is an observed event with evidence, never a prediction of who
  someone is.** Impossible travel, credential reuse, first-time privilege use are
  *events*. "Likely insider", "will exfiltrate", any forecast of an individual's
  future behaviour SHALL NOT exist (inherits EA-0021 S7/S8).
- **S2 — The account is the subject; the person is not the finding.** Output is
  *"this credential shows impossible travel,"* never *"this user is suspicious."* A
  `subject_ref` is an **account/credential/session**, and the detection is phrased as
  an observation, not a verdict about a colleague.
- **S3 — False positives here are people (the rule that shapes the design).**
  Individual behavioural anomalies are low-prevalence: even a strong detector produces
  mostly false positives, and each one is a colleague wrongly suspected. So an
  identity detection SHALL require **both** (a) **corroboration from ≥ 2 independent
  signals** and (b) a **confidence floor strictly above the platform default**. This
  is the one place in the platform a detector is deliberately made **less** sensitive.
  **§11 makes it non-negotiable** — a config lowering corroboration below 2, or
  dropping the floor to the default, is **rejected at construction**. The dignity
  guarantees are not knobs.
- **S4 — No per-person risk score. Ever.** UEBA-style per-user risk scores — a number
  attached to a colleague, rising and decaying invisibly — are precisely the artefact
  this boundary prevents. **No person-scoring type or method exists — absent, not
  disabled.** (Verified structurally: the review's first check is that no such type/
  method is present.)
- **S5 — Profiles are EA-0017's, keyed by an identity `subject_ref`.** No second
  profiler, no z-score/statistics in this package — behavioural baselining is
  EA-0017's `BehaviorProfile`/`ProfileStore`.
- **S6 — Entitlements are cited from EA-0011, never merged.** EA-0011 owns *whether*
  an identity has the right entitlements; this owns *how* they are used. The
  interesting conjunction — *"a rarely-used admin right, and EA-0011 already flags it
  as over-privileged"* — is a **citation of two owners**, not a computation here.
- **S7 — Right of reply by construction.** Every detection is evidence-backed,
  carries a replayable **EA-0020 `Derivation`** pinned to profile/rule versions, and
  is **human-reviewed before any consequence** — so an accused person can be shown
  *exactly what was observed and why*. Opaque suspicion is impossible structurally,
  not by policy.
- **S8 — Advisory; EA-0008 is the only actor.** A detection is raised as an EA-0013
  `Finding` (a question), non-actionable; consequence is a gated EA-0008 run after
  human review. The engine originates no action against a person.

Tenant-scoped, append-only, no network, no new authorization surface.

## 2. Purpose

Stolen credentials, misused privileges, and hijacked sessions are attacks **on**
people. This engine surfaces them as **observed, evidence-backed, account-scoped
events a human then judges** — never as a standing verdict about a colleague. Its
value is catching the attack *without* manufacturing suspicion of the person it
happened to.

## 3. Design decisions

- **D1 — `IdentityDetection` is account-scoped and evidence-backed.** `subject_ref`
  (account/credential/session), `detection_type`, `basis` (evidence),
  `corroboration` (≥ 2 signal refs), `confidence` (EA-0006), replayable `derivation`
  (EA-0020). Unrepresentable without basis + ≥ 2 corroboration + floor-passing
  confidence (S1/S3/S7).
- **D2 — The dignity gate is a constructor + config invariant, built first (C-024
  I2).** `raise_detection` cannot be reached without it; `IdThreatConfig` rejects
  `min_corroboration < 2` or `min_confidence ≤ platform_default` (§11/S3).
- **D3 — No `risk_score`/`user_score` field or method anywhere** (S4) — enforced
  structurally (review first-check + a no-person-scoring test).
- **D4 — Profiles delegate to EA-0017; entitlements cite EA-0011** (S5/S6) — spies
  prove the calls; no baselining or entitlement verdict is computed here.
- **D5 — `behavior.profile.updated` is consumed from EA-0017, never emitted here**
  (EA-0017 owns it, master §248/EA-0017). This engine emits only its own detection
  events (§11).
- **D6 — Registered as an `AQService`;** stores in-memory + Postgres; append-only.

## 4. Ubiquitous language

| Term | Meaning |
|---|---|
| **IdentityDetection** | An account-scoped, evidence-backed, ≥2-corroborated observed event (S1/S3/D1). |
| **subject_ref** | An **account/credential/session** — never "the person" (S2). |
| **Dignity gate** | The ≥2-corroboration + above-default-floor invariant, non-negotiable (S3/§11/D2). |
| **Corroboration** | ≥ 2 **independent** signal refs backing one detection (S3). Independence is keyed on the **signal** — distinct `ref`, and distinct `evidence_id` where present — never on `kind`: one occurrence relabelled twice is **one** corroboration (**ECR-0017**). |
| **Right of reply** | Evidence + replayable derivation + human review = the accused can see what was observed (S7). |

## 5. Types

```
DetectionType = "impossible_travel" | "credential_reuse" | "session_hijack"
              | "first_time_privilege_use" | "dormant_account_use" | "mfa_anomaly"

SignalRef = { kind: str, ref: str, as_of: datetime, evidence_id: str | null }   # independent signal (S3)
IdentityBasis = { kind: "profile"|"entitlement"|"event", ref: str,
                  as_of: datetime, evidence_id: str | null }                     # cited (S1/S7)

IdentityDetection = { id, tenant_id, subject_ref: str,          # account/credential/session (S2)
                      detection_type: DetectionType,
                      statement: str,                            # phrased as observation, never verdict (S2)
                      corroboration: list[SignalRef],            # >= 2 independent by ref/evidence_id (S3/ECR-0017)
                      confidence: float,                         # EA-0006, above floor (S3)
                      basis: list[IdentityBasis],                # evidence-backed (S1/S7)
                      derivation: "Derivation",                  # replayable, pinned versions (S7)
                      profile_ref: str | null,                   # EA-0017 profile (S5)
                      entitlement_refs: list[str],               # cited EA-0011 (S6)
                      status: "open"|"reviewed"|"closed",        # human-reviewed (S7)
                      detected_at: datetime }
# NOTE: there is deliberately NO risk_score / user_score / person field (S4).

IdThreatConfig = { min_corroboration: int,     # >= 2, rejected below (S3/§11)
                   min_confidence: float,      # strictly > platform_default, rejected at/below (S3/§11)
                   platform_default: float }   # the EA-0017/platform floor being exceeded
```

Reuses EA-0017 `BehaviorProfile`, EA-0011 entitlement refs, EA-0006 confidence,
EA-0020 `Derivation`, EA-0004 evidence, EA-0013 `Finding`.

## 6. Interfaces (Python 3.12)

```python
from typing import Protocol, Sequence
from datetime import datetime

class IdentityDetectionStore(Protocol):
    async def put(self, d: IdentityDetection) -> IdentityDetection: ...   # rejects: <2 corroboration / no basis
    async def get(self, detection_id: str, *, tenant_id: str | None) -> IdentityDetection | None: ...
    async def query(self, *, tenant_id: str | None, subject_ref: str | None = None,
                    detection_type: DetectionType | None = None, limit: int = 100) -> list[IdentityDetection]: ...

class IdentityThreatEngine(Protocol):
    async def detect(self, *, subject_ref: str, signals: Sequence[SignalRef],
                     tenant_id: str | None) -> IdentityDetection | None: ...   # dignity gate (S3); None if not met
    async def raise_detection(self, d: IdentityDetection, *, by: "ActorRef") -> "Finding": ...  # account-scoped question (S8)
    async def review(self, detection_id: str, *, by: "ActorRef", outcome: str,
                     tenant_id: str | None) -> IdentityDetection: ...          # human review before consequence (S7)
    # NOTE: no score_user()/risk_of()/predict() — those do not exist here (S1/S4).
```

`IdentityThreatService` wraps engine + store as an `AQService`
(name `"idthreat_engine"`, depends on detection/iag/trust/evidence; health reflects
owner-read availability + config validity + **dignity-gate validity**).

## 7. Computation (the reference model)

**Detect.** Gather ≥ 2 **independent** `SignalRef`s for an account `subject_ref`;
read its EA-0017 `BehaviorProfile` (S5) and cite EA-0011 entitlement context (S6).
**The dignity gate runs first:** if corroboration < `min_corroboration` (≥ 2) or
confidence ≤ `min_confidence` (> platform default), **no detection is produced**
(returns `None`) — the observation is dropped, not surfaced as suspicion (S3). Else
build the `IdentityDetection` with a replayable EA-0020 `Derivation` pinned to
profile/rule versions (S7), phrased as an observation (S2). The store rejects a
detection with < 2 corroboration or no basis.

**Raise.** A material detection is raised as an EA-0013-consumable, **non-actionable**
`Finding` (S8) — a question for a human. `review` records the human outcome before
any EA-0008 consequence (S7).

**Never.** No per-person score is computed, stored, or served (S4); no individual's
future behaviour is forecast (S1); no entitlement verdict or behavioural baseline is
recomputed (S5/S6).

## 8. Requirements

### Functional (testable)

- **FR-1** An `IdentityDetection` SHALL carry ≥ 2 independent `corroboration` signals and a non-empty `basis`; fewer/none SHALL be rejected at construction/`put` (S3/D1). Independence SHALL be keyed on the **signal** — signals sharing a `ref`, or sharing a non-null `evidence_id`, count as **one**; `kind` SHALL NOT distinguish them, and an undecidable pair counts as one (**ECR-0017**).
- **FR-2** `detect` SHALL apply the **dignity gate first**: corroboration < `min_corroboration` **or** confidence ≤ `min_confidence` SHALL yield **no detection** (S3). The gate SHALL de-duplicate corroboration **itself**; no caller SHALL pass a pre-computed corroboration count (**ECR-0017**).
- **FR-3** `IdThreatConfig` SHALL reject `min_corroboration < 2` and `min_confidence ≤ platform_default` at construction (`IdThreatConfigInvalid`) (S3/§11).
- **FR-4** `subject_ref` SHALL be an account/credential/session and `statement` SHALL be an observation; no field/type SHALL name or score a **person** (S2/S4).
- **FR-5** No `risk_score`/`user_score`/`predict`/`score_user` type or method SHALL exist in the package (S4) — verified structurally.
- **FR-6** A detection SHALL carry a replayable EA-0020 `Derivation` pinned to profile/rule versions; a non-replaying derivation SHALL be rejected (`IdentityNotReplayable`) (S7).
- **FR-7** Behavioural profiling SHALL delegate to EA-0017 (`BehaviorProfile`/`ProfileStore`); no second profiler / z-score maths SHALL be implemented (S5).
- **FR-8** Entitlement context SHALL cite EA-0011 (`access_paths`/`analyze_risk`); no entitlement verdict SHALL be computed here (S6).
- **FR-9** `behavior.profile.updated` SHALL be **consumed** from EA-0017, never emitted by this engine (D5).
- **FR-10** `confidence` SHALL come from EA-0006; no second confidence model (S3).
- **FR-11** A detection SHALL be raised as a **non-actionable** EA-0013 `Finding`; consequence SHALL be a gated EA-0008 run after `review` (S7/S8); no new `SignalRef` kind on EA-0013.
- **FR-12** No individual's future behaviour SHALL be forecast; no `project`/`predict` on a person (S1, EA-0021 S7/S8).
- **FR-13** `IdentityDetectionStore` in-memory and Postgres SHALL each pass one contract suite.
- **FR-14** `IdentityThreatService` SHALL register as an `AQService` with health reflecting dependency availability, config validity, **and dignity-gate validity** (EA-0001).

### Non-functional

- **NFR-1 (dignity gate — structural)** a detection with < 2 corroboration or below-floor confidence is **unrepresentable**, and a knob-lowering config is **unconstructable**; proven behaviourally (per **ECR-0007**), not by text.
- **NFR-2 (no person-scoring — structural)** no per-person score type/method exists; a spy/introspection test proves absence.
- **NFR-3 (right of reply)** every detection replays against pinned versions and is human-reviewable before consequence — proven by test.
- **NFR-4 (reuse, not rebuild)** profiles delegate to EA-0017, entitlements cite EA-0011 — spies prove the calls; no duplicate.

## 9. Acceptance Criteria ↔ Tests (Definition of Ready)

| # | Criterion | Test (pytest id) |
|---|---|---|
| AC-1 | Detection needs ≥ 2 corroboration + basis | `test_idt_corroboration_required` |
| AC-2 | Dignity gate: below corroboration/floor → no detection | `test_idt_dignity_gate_drops` |
| AC-3 | Config below floor/corroboration rejected (§11) | `test_idt_config_dignity_nonnegotiable` |
| AC-4 | subject_ref is account; statement is observation | `test_idt_account_not_person` |
| AC-5 | No person-scoring type/method exists (structural) | `test_idt_no_person_score_surface` |
| AC-6 | Detection carries replayable derivation (pinned) | `test_idt_detection_replayable` |
| AC-7 | Tampered derivation rejected | `test_idt_replay_mismatch` |
| AC-8 | Profiling delegates to EA-0017 | `test_idt_profile_delegates_detection` |
| AC-9 | Entitlements cite EA-0011, not merged | `test_idt_entitlements_cite_iag` |
| AC-10 | behavior.profile.updated consumed, not emitted | `test_idt_profile_event_not_emitted` |
| AC-11 | Confidence from EA-0006 | `test_idt_confidence_from_trust` |
| AC-12 | Detection → non-actionable Finding; review gate | `test_idt_finding_and_review` |
| AC-13 | No individual-behaviour forecast | `test_idt_no_precrime` |
| AC-14 | Right of reply: replay + human review before consequence | `test_idt_right_of_reply` |
| AC-15 | Store passes one suite each backend | `test_idt_store_contract[...]` |
| AC-16 | Registers as AQService with health (incl. dignity gate) | `test_idt_service_health` |
| AC-17 | No scan/network surface | `test_idt_no_scan_surface` |
| AC-18 | No `risk_score`/`user_score` field on any model | `test_idt_no_user_score_field` |
| AC-19 | Independence keyed on signal: one `ref`/`evidence_id` relabelled twice = one corroboration (ECR-0017) | `test_idt_corroboration_independence_key` |

## 10. Error taxonomy (contributions)

`IdThreatConfigInvalid`, `IdentityCorroborationMissing`, `IdentityBasisMissing`,
`IdentityNotFound`, `IdentityNotReplayable` (added to `conventions.errors` +
CONVENTIONS §9). Reuses EA-0020 `DerivationNotReplayable`, `StoreUnavailable`,
`TenantScopeRequired`.

## 11. Dignity gate & registered events (owned by EA-0027)

**Dignity gate (non-negotiable).** `IdThreatConfig` SHALL enforce
`min_corroboration ≥ 2` and `min_confidence > platform_default` **at construction** —
a config violating either is rejected (`IdThreatConfigInvalid`). These are not tunable
below their floors; the guarantee is structural.

**Events:** `aqelyn.idthreat.detected`, `aqelyn.idthreat.reviewed`,
`aqelyn.idthreat.credential_anomaly`, `aqelyn.idthreat.privilege_use` — via
`register_idthreat_events()`. **`behavior.profile.updated` is EA-0017's and is
consumed, never emitted here** (FR-9/D5).

## 12. Failure handling

- Invalid/knob-lowering config → `IdThreatConfigInvalid` at construction (§11).
- Corroboration < 2 or confidence ≤ floor → **no detection** (the observation is
  dropped, never surfaced as suspicion) (S3).
- Detection fails to replay → withheld, not served with a caveat (EA-0020).
- Profile/entitlement source unavailable → the detection is withheld (a partial
  identity signal is never raised against a person), recorded degraded — never faked.
- A request to score/predict a person → the method does not exist (S4/S1).

## 13. Dependencies & consumers

- **Depends on:** EA-0017 (`BehaviorProfile`/`ProfileStore`), EA-0011 (entitlements —
  cited), EA-0006 (confidence), EA-0020 (`Derivation`), EA-0004 (evidence), EA-0013
  (findings), EA-0008 (the only actor), EA-0009 (policy), EA-0001 `AQService`.
- **Consumed by:** EA-0013 (detections as findings), EA-0022 (account-scoped summaries).
- **Explicitly NOT:** a per-person risk scorer, a second profiler, an entitlement
  authority, a predictor of individual behaviour, or an actor.

## 14. Resolved / deferred decisions

- **A detection is an observed event, never a prediction of who someone is** (S1) —
  the line that lets this module exist against EA-0021 S8.
- **The account is the subject; the person is not the finding** (S2) and **right of
  reply is structural** (S7).
- **The dignity gate** (≥ 2 corroboration + above-default floor) and **no per-person
  score** are non-negotiable (S3/S4/§11) — see **ECR-0016**.
- **Profiles = EA-0017; entitlements cite EA-0011** (S5/S6) — no rebuild.
