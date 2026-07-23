# Spec-author notes — reviewer → spec author

**Audience:** the actor drafting the next implementation spec and task bundle (claude.ai).
**Author:** the reviewer (Claude Code), who works against the running repository.
**Why this file exists:** the spec author has the archive and `CONVENTIONS.spec.md` but **not the
repository**. The reviewer has the shipped code, the test suites, and a live Postgres. That
asymmetry is the reason the review step exists — and it means a spec can only be checked against
shipped reality by someone holding the repo.

Every spec-stage defect so far came from the same shape: the draft asserted something about shipped
code that it had no way to verify.

| Round | Draft asserted | Shipped reality |
|---|---|---|
| EA-0029 | FR-7 delegated to a `SurfaceFacet` + `api_endpoint`/`federated_identity` | none of those types exist; the real seam is `KnownSurfaceSource → KnownSurfaceRecord` |
| EA-0030 | §0 asserted the module was net-new | true, but only confirmed by re-running the check against `src/` |
| EA-0031 | the DSPM surface row "replaces the same-object inventory placeholder" | it keyed on `obj_` while the placeholder keys on `ast_`; the replacement could never fire |

These are cheapest to kill before implementation. This file is where the reviewer hands over what
only the repo can answer. **It is cumulative** — each round appends; nothing is dropped.

---

## Part 1 — Standing rules for every spec

Each rule names the round that earned it, so the cost is visible.

### 1. Read the next free ECR number from `ECR-LOG.md`, never from context
A stale counter silently overwrites an accepted decision. Hit 2026-07-19: a proposed ECR was
numbered "0017", which was already an accepted corroboration-independence decision. Also check any
"what's built so far" claim against `git log` — the same stale message listed two merged milestones
as still to build.

### 2. Run the ECR-0015 event/type restatement check against shipped `src/`, not against the master
Do not accept the archive master's own §0 claim that a module is new. The reviewer runs the grep and
publishes the counts in Part 2. A module that restates an existing capability must route to the
owner instead of re-implementing.

### 3. Grep every named type and API of a delegation target before writing FR text
If an FR says "delegate to X", `X` must exist in shipped code with that exact name and signature.
This is the ECR-0027 class and it is the single most expensive thing to catch late (EA-0029).

### 4. Tri-state status audit: `bool` + absence is always the bug
Every status field must distinguish *computed and negative* from *never computed*. Absence must never
resolve toward "safe".
- `reachable_object_ids=[] , truncated=False` conflated "reaches nothing" with "never ran" → ECR-0035
  `reach_status: computed|truncated|pending`.
- `SupplyChainAssessment.truncated: bool` could not say "didn't assess" → `AssessmentStatus`.
- `PriorityFactor` had no `unknown`, so an unassessable vulnerability scored exactly as safe as a
  proved-unreachable one → ECR-0040.
- Use semantic tokens, **not** `"true"/"false"/"unknown"` strings — those are all truthy, so
  `if x.over_scoped:` misfires (ECR-0033).

### 5. Absence of a modifier must not reduce a score
Related to rule 4 but distinct: when an optional factor is missing, the result must not improve.
EA-0023's `ExposureImpactContext` gets this right — no context behaves as factor `1.0` (maximum
impact), so not knowing a store's sensitivity never buys it a lower score.
Denominator exclusion alone is not sufficient: C-030 G4 showed that dropping an unknown MFA factor
would otherwise make the unknown case score exactly like MFA-present. Test the same subject with the
factor known-good, known-bad, and unknown; the unknown result must not become the favourable result.

### 6. Losing or corrupting evidence must never improve an answer
EA-0031 P2 discarded a detector signal whose evidence was missing *or failed integrity
verification*, then classified the field from the weaker surviving candidate: `public / known /
flagged=False`, while the same input with readable evidence produced `unknown / conflict / flagged`.
Specify that unusable evidence is refused (`EvidenceNotFound` vs `EvidenceTampered`), never silently
skipped, and keep *absent* distinguishable from *tampered*.

### 7. `Workflow.propose(..., source_finding=finding)` is mandatory for finding-driven proposals
A finding carrying `Automation(eligibility="none")` only blocks execution if the run is bound to it —
`gating.py` checks `if source_finding is not None`. EA-0031 P4 omitted the argument; the proposed run
executed against the real engine after one ordinary approval. EA-0011/0012/0013/0014/0018 all pass it.

### 8. Evidence integrity is not authenticity
EA-0004 `verify()` proves AQELYN's own hash chain was not altered. It does **not** prove a publisher
signature is authentic — EA-0004 D4 reserves signing for a later ADR. Wiring `verify().ok` into a
trust claim would be the platform forging a claim from its own hash chain (ECR-0039). Two stages:
EA-0004 integrity first, then a typed kind-specific verifier supplied by a trusted adapter
(`supplychain/provenance.py::ProvenanceVerifier` is the shipped pattern).

### 9. Persistence shape decides whether an "additive" field is free
Check the target table before calling a new field additive. `asset_ref` is `jsonb`, so
`AssetRef.object_id` round-tripped for free; `aq_exposure_record` is **columnar**, so
`impact_context` needed a DDL column, `ALTER TABLE … ADD COLUMN IF NOT EXISTS` for existing
deployments, and all write/read mapping sites — otherwise it passes in-memory and silently returns
`None` on Postgres.

### 10. Pagination: EA-0002 D8 semantics from the first persistence ticket, under a work budget
Stable id order, exclusive cursor, `next_cursor` non-null exactly when another matching row exists,
filters applied **before** `LIMIT`. Do not trade a silent cap for unbounded per-request scanning
(ECR-0031) — page under a budget and report `truncated`.

### 11. Health probes must be tenant-scoped, and both tenant modes must be exercised
`create_inmemory_runtime()` defaults to `tenant_mode="local"`, so driving "the factory-built runtime"
proves nothing about enterprise. Acceptance criteria must parametrize `(backend, tenant_mode)`.
Only a minority of services define a `_health_tenant()` helper; the ones whose probes issue
tenant-scoped queries need it. Known open instances: EA-0027 `idthreat_engine`, EA-0018
`response_engine` — both currently fail enterprise startup.

### 12. Confirm module ownership from `README.md` before naming an EA in a finding or dependency
`README.md` maps EA number → `src/` path. A wrong EA number sends the reader to the wrong spec and
the wrong task bundle. (Reviewer mislabelled `src/aqelyn/response/` as EA-0016 three times; it is
EA-0018. EA-0016 is Digital Forensics, `src/aqelyn/forensics/`.)

### 13. Handed-in descriptors, not collection
Analytical engines accept already-produced records. They open no socket, hold no credential, poll
nothing. Live collection is a later connector delivered as an EA-0008 gated action, and the
descriptor is the seam that keeps the engine unchanged when connectors land. Enforce it with a
grep/no-network test in the suite (`test_tif_ingest_no_fetch`,
`test_dspm_no_collection_or_bulk_read`).

### 14. Minimal retention is structural, not a prose promise
If a module handles sensitive material, the typed shapes must make raw content unconstructible
(`extra="forbid"`, no `value`/`sample`/`content`/`blob` field), and the acceptance test must attempt
construction rather than grep for the words.

### 15. Sequence a type with the ticket its dependency lands in
A type pulled into an earlier ticket than the change it depends on can have an interim where its only
constructible form violates a rule that arrives later — it will pass its own ticket's tests and fail
the system. (C-029 W1 shipped `CryptographicExposure` while the `credential_sensitivity` widening it
needs was scheduled for W4, so on-branch it could *only* be built with the ECR-0044-forbidden
`data_sensitivity` kind.) At spec/bundle stage, if ticket N defines a type whose valid construction
depends on a change in ticket N+k, either move the additive dependency forward to N or defer the type
to N+k. Review a type against the ticket its dependency lands in, never in isolation.

### 16. Prove the no-action boundary against the owning finding's automation contract
`source_finding` binding is mandatory (rule 7), but not every owner finding has
`eligibility="none"`. EA-0033 correctly preserves EA-0011's `assisted` access-remediation contract:
the module only proposes, `requires_approval=True`, and the real workflow refuses execution before
approval. Do not rewrite an owner's automation semantics merely to make a stronger-looking test.
Drive the real workflow and prove the exact applicable boundary: permanent refusal for `none`, or
approval-gated execution for `assisted`.

### 17. Historical handoffs pin exact owner records; they never recompute
C-030 G5 exposed this at the assessment-to-finding boundary. A method accepting only an assessment
id cannot later reproduce the records it used unless the assessment durably stores their exact ids.
Persist the owner refs at computation time, validate them on read, and route those records forward.
Re-running the owner engine against today's estate is silent historical drift, not reconstruction.

### 18. A test double that stops conforming to its Protocol stops testing that contract
ECR-0052 additively made `IdentityGovernanceOwner.risks_to_findings` tenant-scoped, but the C-030 G3
spy retained the old signature. The implementation was correct and `mypy --strict src` was green;
`mypy --strict src tests` failed because the test double no longer represented the owner interface.
A stale spy can leave assertions green while silently testing a different call shape. Whenever a
Protocol changes, sweep every implementation and test double, statically check the full `src tests`
surface, and assert forwarding of the new argument or result. A spy proves delegation only while it
continues to satisfy the Protocol it doubles.

### 19. A fixture that performs a forbidden action to reach its assertion has normalized that action
C-033 K1 / ECR-0056 exposed the same shape as rule 18 (a stale spy passing while testing the wrong
call): the test infrastructure, not the assertion, carried the defect — some workflow/policy
fixtures approved as system and passed.
Audit what fixtures DO to reach a state, not only what tests ASSERT. Corollary: a §0 guarantee tested
only on happy paths where it holds is untested; each needs a test that fails on the refusal.

## Part 2 — Current handover: IS-036 / EA-0036 (Autonomous Remediation Orchestration)

**Repository state:** `main @c051b1f`, green (ruff, format, `mypy --strict src tests` 484 files,
1292 passed / 3 skipped live PG16+Redis7).
**Next free ECR:** **0055** (log ends at ECR-0054; re-read `ECR-LOG.md` before assigning).
**Archive verified:** `archive/EA-0036/EA-0036_Master.md` is IS-036. **Two findings up front, both load-bearing.**

### Finding 1 — the archive is a near-empty TEMPLATE, not a specification

Unlike EA-0032/0033/0035, this master has **no real content**. Its objectives are literal placeholders:

```
OBJ-0036-001: Provide a verifiable capability boundary for aqelyn autonomous remediation
              orchestration engine objective 1.
... (identical through objective 12)
```

The purpose is grammatically broken ("The engine is to coordinates safe... remediation"), and every
section — Vision, Context, Architecture, Internal/External Interface Contracts — repeats the same
boilerplate ("defines implementation guidance required for coding, validation, operations, and
maintenance"). There are **no concrete components (ARC-036-*), no interfaces, no requirements (REQ-*),
no lifecycle, no acceptance criteria.** The only substantive sentence is one paragraph: *"coordinates
safe, policy-bound remediation actions across AQELYN engines, workflows, evidence, and trust context …
without redesigning the fixed repository or previously approved architecture."*

**Consequence for the spec pass:** there is nothing here to reconcile a real capability against. The
drafter cannot extract requirements that were never written. **Do not invent a spec from the template
headings** — that manufactures scope. IS-036 must be grounded in shipped code, not in placeholder
objectives. (EA-0036 also opens a new archive batch, index `EA-0036_EA-0050`; the rest may be similarly
templated — treat "is this archive real content?" as the first check for each.)

### Finding 2 — the capability already ships, and "Autonomous" is a §0 landmine

ECR-0015 run against shipped `src/`:

```
Playbook 202 · propose 179 · requires_approval 47 · eligibility 32 · WorkflowEngine 23   (EA-0008)
response.*campaign 109 · aqelyn.response 40                                              (EA-0018)
autonomous 0
```

**Remediation orchestration already ships:** **EA-0008** `WorkflowEngine` (`propose`/`approve`/`execute`
— the platform's ONLY actor, capability-gated, eligibility-gated, approval-gated) and **EA-0018**
`ResponseOrchestrationEngine` (`plan_campaign`/`advance`/`propose` — multi-step, multi-phase remediation
campaigns). Decisioning is **EA-0020**, policy **EA-0009**, evidence **EA-0004**, trust **EA-0006**,
mission **EA-0007**. Fourth distributed-conformance case (IS-026, IS-034, IS-035, IS-036).

**`autonomous` = 0 hits, and that is by design.** Every module in this platform is detect-and-propose:
EA-0031/0032/0033 remediation is `propose(playbook, by=, source_finding=finding)` with
`requires_approval=True`, and eligibility-`none` findings are *structurally* unexecutable
(`gating.py`). **The archive's title word "Autonomous" must NOT become autonomous action.** The only
legitimate reading is *the orchestration/evidence/decision/sequencing flow is automated* — never
*execution without a human*. **If the drafted spec introduces any un-gated execution, any bypass of
`WorkflowEngine.approve`, or any finding-driven run that isn't `source_finding`-bound with
`requires_approval=True`, that is THE defect to catch (rules 7, 16).**

### Resolution to propose — ECR-0055 (conformance, gated)

1. **Mark IS-036 conformant** — remediation orchestration is realized by **EA-0018 + EA-0008**, evidenced
   by a conformance analysis and **real-engine** exercises (drive `plan_campaign`→`advance` and
   `propose`→`approve`→`execute`, prove an eligibility-`none` step is refused execution), not spies/grep.
2. **Forbid** a second orchestration engine, workflow actor, or response campaign model. There SHALL be
   no `src/aqelyn/autonomous_remediation/` (or `remediation_orchestration/`), no second `*_engine`
   service, no `aqelyn.autonomy.*` namespace, and — non-negotiable — **no execution path that is not
   EA-0008-gated and human-approved.**
3. **The archive specifies no genuine gap.** Because it is a template, the burden is on the drafter to
   justify *any* net-new capability against shipped EA-0018/EA-0008 — and it must stay inside the
   propose→gate→approve boundary. A plausible *narrow* candidate, if the owner wants one: a
   **read-only remediation-orchestration VIEW/plan** that composes proposed (never executed) EA-0008 runs
   and EA-0018 campaigns across engines into one evidence-backed, replayable plan record — additive, and
   still emitting only `requires_approval=True` proposals. Owner-gated; do not assume it.

### Boundaries (unchanged, but sharper here than anywhere)

- **No autonomous action, ever** — the whole platform's §0. Orchestration proposes; EA-0008 gates; a
  human approves; only then does anything execute. Prove it behaviourally against the **real**
  `WorkflowEngine` (rule 16: the guarantee's shape is EA-0008's `approve` + eligibility, verified).
- **`source_finding` binding mandatory** on any finding-driven proposal (rule 7).
- **Handed-in / composed, not a new actor** — orchestration composes existing owners; it holds no new
  execution capability.

### Delegation seams, verified present in shipped code

| Need | Shipped seam |
|---|---|
| gated remediation action (the only actor) | EA-0008 `WorkflowEngine.propose` / `approve` / `execute` (capability + eligibility + approval gates) |
| multi-step remediation campaigns | EA-0018 `ResponseOrchestrationEngine.plan_campaign` / `advance` / `propose` |
| decision / recommendation | EA-0020 decision engine (`recommend`), replayable `Derivation` |
| policy authorization | EA-0009 `PolicyEngine` |
| findings that drive remediation | EA-0013 finding path; owner `risks_to_findings` / `*_to_findings` |
| evidence · trust · mission | EA-0004 · EA-0006 · EA-0007 |
| relationships / traversal | EA-0002 `ObjectStore.relate` · EA-0005 bounded paths |

### False friends

- `aqelyn.workflow.*` (run_proposed etc.) and `aqelyn.response.*` events belong to EA-0008/EA-0018; any
  new event must be net-new and re-emit nothing. `WorkflowEngine`/`ResponseOrchestrationEngine` are the
  service names — do not shadow them.
- "Orchestration" already names EA-0018 (`ResponseOrchestrationEngine`). A second orchestrator is the
  duplication ECR-0053/0054 rejected for identity and crypto.

### Open follow-up this must not weaken

**ECR-0034** (inventory `limit=10_000` reports complete) remains unimplemented — keep coverage honest if
any orchestration reads EA-0025 inventory.
