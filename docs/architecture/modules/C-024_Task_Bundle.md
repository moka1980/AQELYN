# C-024 Identity Threat Detection & Behavioral Analytics — Implementation Task Bundle

**Milestone:** C-024 (Identity Threat Detection & Behavioral Analytics, EA-0027)
**For:** Codex (implementer) / Claude Code (reviewer)
**Prerequisites:** EA-0025 merged & green; EA-0027 spec **Accepted**; **EA-0027 §0 and §1 read first**; CONVENTIONS + EA-0004/0006/0008/0009/0011/0013/0017/0020 read.
**Definition of Done:** acceptance tests pass on in-memory **and** Postgres where a store is touched; `ruff` clean; `mypy --strict` clean; **no per-person risk score type or method; the dignity gate (≥2 corroboration + floor > platform default) is non-negotiable; detections are account-scoped observations**; nothing outside the spec; `make check` green; Claude Code sign-off per ticket.

**Read EA-0027 §1 first.** This is the module that watches **people**, legitimate only
because it surfaces **observed, evidence-backed, account-scoped events** — never a
prediction of who someone is, and never a standing score attached to a colleague.
**False positives here are people.** If a needed behavior isn't in the spec, raise an ECR.

**Verification standard (ECR-0007) — the review's FIRST check:** **no person-scoring
type or method exists** (`risk_score`/`user_score`/`score_user`/`predict` — absent, not
disabled), and a sub-threshold detection / knob-lowering config is **unrepresentable**.
Do not substitute a grep for the proof; introspect the public surface and construct the
forbidden states behaviourally.

## Target source layout

```
src/aqelyn/idthreat/
|-- __init__.py       # exports engine, service, stores, types, register_idthreat_events
|-- models.py         # SignalRef, IdentityBasis, IdentityDetection, IdThreatConfig (I1)
|-- dignity.py        # the dignity gate — config floors + gate() (I2)
|-- engine.py         # detect (gate-first) / raise / review (I3-I4)
|-- store.py          # IdentityDetectionStore protocol + validators (I3)
|-- memory.py         # in-memory store (I3)
|-- postgres.py       # Postgres store + DDL (I3)
`-- service.py        # IdentityThreatService(AQService) + register_idthreat_events (I5)
tests/idthreat/       # acceptance suite (in-memory + Postgres)
```

Suggested id prefixes (register in CONVENTIONS §9): `idt` (identity_detection).

---

## I1 — Types, taxonomy & the absent person-scoring surface

**Spec:** §1 (S1/S2/S4), §5, §8 FR-1/4/5, §10.
**Deliverables:** the models; `IdentityDetection` (account-scoped `subject_ref`,
`statement` as observation, ≥2 `corroboration`, `basis`, `confidence`, `derivation`);
**no `risk_score`/`user_score`/`person` field on any model**; error codes
(`IdThreatConfigInvalid`, `IdentityCorroborationMissing`, `IdentityBasisMissing`,
`IdentityNotFound`, `IdentityNotReplayable`) in `conventions.errors` + CONVENTIONS §9.
No `scan`/`probe`/`connect`/network surface.
**Acceptance:** `test_idt_no_person_score_surface`, `test_idt_no_user_score_field`,
`test_idt_account_not_person`, `test_idt_no_scan_surface`.

## I2 — The dignity gate (built before any detection can be raised)

**Spec:** §1 (S3), §11, FR-1/2/3, NFR-1.
**Deliverables (in `dignity.py`):** `IdThreatConfig` **rejects** `min_corroboration < 2`
and `min_confidence <= platform_default` **at construction** (`IdThreatConfigInvalid`);
a `dignity_gate(corroboration, confidence, config)` that returns **pass only when** both
`len(corroboration) >= min_corroboration (>=2)` **and** `confidence > min_confidence`.
This gate is a standalone, tested unit — **nothing downstream may raise a detection
without passing it.** The floors are not tunable below their minimums.
**Depends on:** I1.
**Acceptance:** `test_idt_config_dignity_nonnegotiable` (config below 2 / at-or-below
default rejected), `test_idt_dignity_gate_drops` (sub-threshold → gate fails → no
detection).

## I3 — IdentityDetectionStore + detect (gate-first, replayable)

**Spec:** §6, §7 detect, FR-1/6/10/13, NFR-1/3.
**Deliverables:** `IdentityDetectionStore` (in-memory + Postgres + DDL, contract,
tenant, append-only). `detect` **runs the I2 dignity gate first** — if it fails, returns
**`None`** (the observation is dropped, never surfaced); else builds an
`IdentityDetection` with ≥2 corroboration, EA-0006 `confidence`, and a replayable EA-0020
`Derivation` pinned to profile/rule versions (rejected if `replay != result`). The store
rejects <2 corroboration / no basis.
**Depends on:** I2.
**Independence (ECR-0017):** the gate de-duplicates corroboration itself, keyed on the
**signal** (`ref`, and `evidence_id` where present) — never on `kind`. One occurrence
relabelled twice is **one** corroboration; undecidable pairs count as one. I2's
`(kind, ref)` key is superseded.
**Acceptance:** `test_idt_corroboration_required`, `test_idt_corroboration_independence_key`,
`test_idt_detection_replayable`,
`test_idt_replay_mismatch`, `test_idt_confidence_from_trust`,
`test_idt_store_contract[inmemory]`, `test_idt_store_contract[postgres]`.

## I4 — Reuse delegations, right of reply & findings path

**Spec:** §1 (S5/S6/S7/S8), §7 raise/review, FR-7/8/9/11/12, NFR-4.
**Deliverables:** behavioural profiling **delegates to EA-0017** (`BehaviorProfile`/
`ProfileStore`, keyed by identity `subject_ref` — no second profiler, no z-score maths);
entitlement context **cites EA-0011** (`access_paths`/`analyze_risk`) — no entitlement
verdict computed here; **`behavior.profile.updated` is consumed from EA-0017, never
emitted**; `raise_detection` raises a **non-actionable** EA-0013 `Finding` (no new
`SignalRef` kind); `review` records the human outcome **before** any EA-0008 consequence
(right of reply); no individual-behaviour forecast (`no predict`/`no project`).
**Depends on:** I3.
**Acceptance:** `test_idt_profile_delegates_detection`, `test_idt_entitlements_cite_iag`,
`test_idt_profile_event_not_emitted`, `test_idt_finding_and_review`,
`test_idt_right_of_reply`, `test_idt_no_precrime`.

## I5 — Service + events

**Spec:** FR-14, §11.
**Deliverables:** `IdentityThreatService` (`AQService`, name `"idthreat_engine"`) +
`register_idthreat_events` (detection events only — **not** `behavior.profile.updated`);
in-memory and Postgres kernel-factory wiring using the established `TYPE_CHECKING` +
in-function import pattern; health reflects owner-read availability, config validity,
**and dignity-gate validity**.
**Depends on:** I4.
**Acceptance:** `test_idt_service_health`.

---

## Review protocol (Claude Code) — false positives here are people

Per ticket, confirm the normal DoD **and**, with extra scrutiny (in this order):
1. **No person-scoring surface exists (FIRST check).** No `risk_score`/`user_score`/
   `score_user`/`predict` type or method — absent, not disabled. Introspect the public
   API; construct the forbidden field and assert it can't exist.
2. **The dignity gate is non-negotiable.** A config with `min_corroboration < 2` or
   `min_confidence <= platform_default` is **unconstructable**; a sub-threshold
   observation yields **no detection**. Nothing raises a detection without passing the
   gate (I2 built first).
3. **The account is the subject.** `subject_ref` is an account/credential/session;
   `statement` is an observation, never a verdict about a person.
4. **Right of reply by construction.** Every detection replays against pinned versions
   and is human-reviewed (`review`) before any EA-0008 consequence.
5. **Reuse, not rebuild.** Profiles delegate to EA-0017 (spy); entitlements cite EA-0011
   (spy); `behavior.profile.updated` consumed, never emitted; confidence is EA-0006's.
6. **No precrime.** No forecast/prediction of an individual's future behaviour.
7. **Findings path.** Detections flow through the existing `FindingStore`, non-actionable;
   consequence is a gated EA-0008 run after review.
8. **Service import discipline.** Final ticket avoids the R5/T5 trap (`TYPE_CHECKING` +
   in-function imports).

Merge only on green review; then **report back to the owner** before the next module.
