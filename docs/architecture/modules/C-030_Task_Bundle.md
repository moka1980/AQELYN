# C-030 Identity Security Posture Management — Implementation Task Bundle

**Milestone:** C-030 (Identity Security Posture Management, EA-0033)
**For:** Codex (implementer) · Claude Code (reviewer)
**Prerequisites:** C-029 (EA-0032) merged & green; EA-0033 spec **Accepted**; **EA-0033 §0 + §0.3 read**; `SPEC_AUTHOR_NOTES.md` Part 1 rules 1–15 read; CONVENTIONS + **`src/aqelyn/iag/` (EA-0011)** read before writing any code.
**Definition of Done:** every ticket's acceptance tests pass on in-memory **and** Postgres **and in both tenant modes**; `ruff` clean; `mypy --strict` clean; **no reimplementation of EA-0011; no person-level score; unknown never favourable**; nothing outside the spec; `make check` green; Claude Code sign-off per ticket.

**Read EA-0033 §0 first.** The identity-governance half of ISPM **already ships**
as EA-0011 (entitlement 107 · certification 154 · privilege 34 · dormant 19 ·
orphaned 12 · access_path 23 hits in `src/`). The master's five component names —
Posture Assessment, Risk Scoring, Drift, Recommendation, Classification — **must
not become five new engines.** ISPM is a `normalize → score → route` posture layer
(the fourth, after CSPM/SSPM/DSPM) that earns its existence on exactly three
net-new pieces:

1. a **deterministic, replayable 0–100 posture score** (composing EA-0013/0007/0006);
2. **identity posture drift** on the **EA-0012** baseline/snapshot shape;
3. **wider-scope identity normalization** into **EA-0011's shipped EA-0002
   identity/account objects and relationship vocabulary**.

**Everything else routes to `IdentityAccessGovernanceEngine`.** If you are about to compute orphaned,
dormant, over-privileged, SoD, privileged-unreviewed, an access path, or a
certification — stop; call EA-0011.

**And the rule the archive doesn't state (§0.3):** this is the first module to
attach a **number to an identity**. The score measures **an account's control
state**, never its holder. There must be **no person-level rollup type** — as with
EA-0027's person-score and EA-0032's secret value, the judgement is
*unrepresentable*, not merely unwritten.

**Verification standard (ECR-0007):** structural (no person-score type; no local
re-derivation; unreplayable score unrepresentable) + behavioural (delegation
spies prove dispatch, while a full normalization → **real**
`IdentityAccessGovernanceEngine` → score round trip proves the seam is actionable;
scoring driven through the **real** scoring function, not a spy — the ECR-0040
method; socket spy). Not textual checks. **A spy proves that a call was made; it
does not prove that EA-0011 can act on what ISPM wrote.**
**Run gates under `python -O` too** (the #147 habit).

## Target source layout

```
src/aqelyn/ispm/
├── __init__.py       # exports engine, service, types, register_ispm_events
├── models.py         # ControlFact, identity/account/access-edge descriptors, NormalizedIdentity,
│                     #   PostureFactor, IdentityPostureScore, IdentityBaseline*,
│                     #   IdentityDrift*, ISPMAssessment, ISPMConfig (G1)
├── normalize.py      # descriptor -> EA-0011 EA-0002 graph intake; EA-0025 registration (G2)
├── governance.py     # thin delegation to EA-0011 analyze_risk/access_paths/certification (G3)
├── scoring.py        # PostureFactor -> EA-0020 Derivation -> 0-100 (G4)
├── drift.py          # EA-0012 baseline/comparator shape, append-only snapshots (G4)
├── surface.py        # KnownSurfaceSource + ExposureImpactContext (G5, with ECR-0049)
├── store.py          # ISPMStore protocol (D8 pagination) (G2)
├── memory.py / postgres.py  # stores + DDL (G2)
├── engine.py         # ingest + assess + posture_to_findings (G2/G4/G5)
└── service.py        # ISPMService(AQService) + register_ispm_events (G6)
tests/ispm/           # acceptance suite (in-memory + Postgres, both tenant modes)
```

**No `certification.py`, no `risk.py`, no `accesspath.py`** — EA-0011 owns all
three. If they appear, the milestone has gone wrong.

---

## G1 — Types, tri-state controls & config

**Spec:** §4, FR-5/18/19; §9.
**Deliverables:** the models; `ControlFact` tri-state (`present|absent|unknown`,
**default `unknown`**, carrying the reason); `ISPMAssessment.status` as **semantic
tokens** `computed|truncated|pending` (not truthy strings — ECR-0033); config
validation (`ISPMConfigInvalid`); reuse EA-0027's existing `IdentityNotFound`
per ECR-0050 and register only the three net-new errors;
**`ips`/`ibl`/`idr`/`ipa` prefixes registered
in BOTH `conventions/ids.py::PREFIXES` and CONVENTIONS §1**, errors in `errors.py` +
CONVENTIONS §9. **Do not reuse the `cert` prefix** (`iag_certification`).
**Rule 15 check:** no type defined here may require a widening scheduled later —
identity `ExposureImpactContext` is **deferred to G5**, not defined now.
**Acceptance:** `test_ispm_controls_tristate`, `test_ispm_assessment_status`,
`test_ispm_config_invalid`, `test_ispm_prefixes_and_events`.

## G2 — Normalization + store (EA-0011's shape, EA-0025 registration)

**Spec:** §2.3, §6, FR-1/2/16/20, D1, NFR-4.
**Deliverables:** `ingest_identities` (**handed-in descriptors only — no socket,
no credential, no poll, no connector method**) producing `NormalizedIdentity` in
**EA-0011's shipped EA-0002 graph intake**: `object_type="identity"` and
`object_type="account"` objects, an evidence-backed identity → account
`has_account` relationship for every supplied account, and optional
`has_role`/`grants_entitlement`/`member_of` relationships only from explicit
evidence-backed descriptor claims. Use `ObjectStore.relate`; do not invent a
parallel graph or relation vocabulary. `NormalizedIdentity` carries the account
object and relationship ids. `identity_kind` classification (unmatched →
`"unknown"`, with `flagged=true` required on the normalized record per
**ECR-0051**); conflicts resolved by **EA-0006** and
**recorded**; registration via **EA-0025
`InventoryIntelligenceEngine.ingest(reports=, source=DiscoverySource, tenant_id=)`**;
`ISPMStore` (in-memory + Postgres + DDL) with **EA-0002 D8 pagination** under
`page_budget` (rule 10). **Rule 9:** check the target table's shape before
treating any field as additive.
**Depends on:** G1.
**Acceptance:** `test_ispm_no_collection`, `test_ispm_normalize_to_iag_shape`,
`test_ispm_pagination`,
`test_ispm_store_contract[inmemory]`, `test_ispm_store_contract[postgres]`.

## G3 — Governance delegation (prove it before scoring uses it)

**Spec:** §0.1, §6, FR-3/4/11, NFR-3.
**Deliverables:** `governance_context` delegating to
**`IdentityAccessGovernanceEngine.analyze_risk(*, tenant_id, scope)`** and
**`IdentityAccessGovernanceEngine.access_paths(identity_id, *, tenant_id)`**;
certification routed to **`open_certification`/`decide_item`/
`complete_certification`**; findings via
**`risks_to_findings(report, *, by, prioritize=True)`** — **no new
`SignalKind`**. **Reuse** `AccessPath`/`AccessRisk`/`AccessRiskReport`/
`ReviewItem`/`Certification`; redefine none.
**This ticket exists before G4 deliberately:** the score depends on these risks,
and rule 3 says the seam must be proven present with its exact signature before
FR text leans on it. Add `test_ispm_real_iag_round_trip`: ingest
a descriptor with a linked account whose `last_used_at` is older than the real
EA-0011 dormant threshold, then call the real analyzer. Assert the expected
`dormant` risk is present and that the account is **not** falsely `orphaned` —
proving both the account object and `has_account` relation are actionable. A spy
or `analyze_risk` call assertion is not this proof.
**Depends on:** G2.
**Acceptance:** `test_ispm_real_iag_round_trip`,
`test_ispm_iag_not_reimplemented`, `test_ispm_certification_delegates`,
`test_ispm_findings_path`.

## G4 — Posture score (replayable) + drift (EA-0012 shape)

**Spec:** §2.1/§2.2, §0.3, §6, FR-6/7/8/9/10/15, NFR-1/2/5.
**Deliverables:** `score_identity` — `PostureFactor`s from EA-0011 risks (cited),
control facts, **EA-0007** mission weight, **EA-0006** confidence; an `unknown`
fact ⇒ `status="unknown"` and **excluded from the denominator, never favourable**;
combine to 0–100 under `factor_weights`; **EA-0020 `Derivation`** built and the
store **rejects an unreplayable score**; `statement` in **control language**;
**no person-level rollup type exists**. `detect_drift` on the **EA-0012**
baseline/comparator shape with **append-only** snapshots; unestablishable fact ⇒
`status="unknown"`, **never `pass`**.
Add `test_ispm_score_cites_real_iag_risk`: the resulting posture score must
pin the exact real-owner `AccessRisk` returned in G3 (the shipped `AccessRisk`
type has no id) and the derivation must cite that pinned owner input. Do not mint
a local "risk id" or replace the owner record with a locally re-derived summary.
**Depends on:** G3.
**Acceptance:** `test_ispm_score_cites_real_iag_risk`,
`test_ispm_unknown_not_favourable`, `test_ispm_score_replay`,
`test_ispm_score_composed`, `test_ispm_no_person_score`, `test_ispm_drift_shape`.

## G5 — Exposure, findings, service & wiring **(final ticket)**

**Spec:** §6, FR-11/12/13/14/17/21, D6, §10, §12a, §13.
**Deliverables:** a `KnownSurfaceSource` yielding `KnownSurfaceRecord`s for
identities, reusing the existing **`AssetRef.kind="identity"`**; an
`ExposureImpactContext` carrying identity sensitivity.
**The `identity_sensitivity` `ExposureImpactKind` widening (ECR-0049) lands in
THIS ticket** — additive, `data_sensitivity` default preserved, replay-pinned.
**Rule 15 is the reason:** the context type's only valid construction depends on
this widening, so defining it earlier would leave an interim where it could only
be built with a forbidden kind (the C-029 W1 failure, exactly).
Also deliver `posture_to_findings` over the assessment's exact persisted
`score_ids` (ECR-0052; evidence-backed via tenant-scoped EA-0011/EA-0013) and
**EA-0008 `propose(playbook, by=, source_finding=finding)`** with
`requires_approval=True` — **`source_finding` binding mandatory** (rule 7);
**no identity provider is modified**; `ISPMAssessment` carries `inventory_complete`
+ `inventory_note` honestly (**ECR-0034 inherited, not deepened**); `ISPMService`
(`AQService`, name `"ispm_engine"`) with a **tenant-scoped health probe** (add
`_health_tenant()` — rule 11) + `register_ispm_events` (`aqelyn.ispm.*` only,
**never `aqelyn.iag.*`**); wired into the kernel factory.
**Depends on:** G4.
**Acceptance:** `test_ispm_exposure_seam`,
`test_ispm_identity_sensitivity_kind`, `test_ispm_propose_binds_finding`,
`test_ispm_inventory_not_exhaustive`,
`test_ispm_service_health[local]`, `test_ispm_service_health[enterprise]`.

---

## Review protocol (Claude Code) — no reimplementation of EA-0011, first and hardest

Per ticket, confirm the normal DoD **and**:

1. **EA-0011 is connected and not restated.** Drive a handed-in descriptor
   through ISPM into the real EA-0002 store, then the real
   `IdentityAccessGovernanceEngine.analyze_risk`, then the posture score. Assert
   an expected non-empty owner risk, no false orphaning when `has_account` was
   supplied, and that the score pins the exact `AccessRisk`. A delegation spy
   proves intent only; it cannot discharge this connectivity check. Every
   access-path, orphaned/dormant/
   over-privileged/SoD/privileged-unreviewed, and certification concern must
   **route to the shipped `IdentityAccessGovernanceEngine`**. Delegation spies
   against the real engine;
   confirm **no local re-derivation** and **no redefined** `AccessPath`/
   `AccessRisk`/`AccessRiskReport`/`Certification` (§0.1/NFR-3).
2. **No person-level score.** Search types/fields/methods for any aggregation of
   an individual's accounts into a single rating. It must be **absent**, not
   disabled. `subject_ref` is an account; `statement` is control language (§0.3).
3. **Unknown is never favourable.** Drive the **real** scoring function (not a
   spy) with one factor `unknown`; assert it is **excluded from the denominator**
   and the score does **not** improve — and that unknown-MFA does not match
   proven-present-MFA (the ECR-0040 method, rules 4/5).
4. **Score replays.** `replay(derivation) == score`; tamper and assert the score
   is **withheld**, not served with a caveat. Under `python -O` too.
5. **Drift is EA-0012's shape**, append-only; unestablishable ⇒ `unknown`, never
   `pass`.
6. **No collection.** Socket spy; no connector/poll/enumerate method (§0.2).
7. **Proposal binds its finding.** `propose(..., source_finding=finding)` present
   — without it, `Automation(eligibility="none")` does not gate and the run
   executes after one ordinary approval (rule 7). Nothing on any IdP is modified.
8. **Rule 15 sequencing.** Confirm the `identity_sensitivity` widening lands in
   **G5**, the same ticket that first constructs the identity
   `ExposureImpactContext` — and that no earlier ticket defines a type whose only
   valid construction depends on it.
9. **ECR-0034 not deepened.** `inventory_complete` is honest; nothing presents the
   bounded inventory as exhaustive (§12a).
10. **Both tenant modes.** `(backend, tenant_mode)` parametrized; **enterprise
    startup asserted**, not just `local` (rule 11).
11. `ips`/`ibl`/`idr`/`ipa` prefixes and errors registered at **both** sites;
    EA-0002/EA-0025 records retain `obj`/`rel`/`ast`; no `cert` prefix; no
    `aqelyn.iag.*` emission. `ruff` + `mypy --strict` clean.

Merge only on green review; then **report back to the owner** before the next
module. **ECR-0032** (shared posture-normalization base, now **four** instances)
is a *separate* decision after C-030 is green — do **not** fold a refactor into
this milestone.
