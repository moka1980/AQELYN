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

### 20. A matching EA number transfers no scope
Raised during IS-037 and cited by C-034's review protocol before it was ever a standing rule — the
same number identifies incompatible artifacts across archive families. "037" names both the Cyber
Asset Exposure Management stub and Blueprint `Volume_037_AQELYN_Distributed_Scan_Engine.md`, and
importing the latter's active scanning would have reversed EA-0023's shipped no-scan boundary.
When an EA number appears in multiple archive families, verify the source family, title, and declared
source of truth before treating anything as in scope. A matching number is a collision, not a
mandate.

### 21. A guard mutation-verified only at the producer is verified for half the chain
C-034 fixed ECR-0034 by making `inventory()` report a truncated read honestly, and the analysis that
commissioned the fix warned in the same breath that an honest flag nobody acts on is the ECR-0013
unwired-default shape. The warning fired inside the fix written to address it: one consumer
(`ISPMEngine._inventory_note`) was wired to read `degraded` and a test docstring claimed coverage,
but no test exercised it. Neutering the producer flipped the expected controls; neutering that
consumer flipped nothing. The prose said the right thing and the code did not, and only mutation at
the consumer end could tell them apart.

Same family as rules 18 and 19 — the test infrastructure carrying the defect — but one level up:
here the mutation discipline itself was applied at only one end of the chain. **Mutating the producer
proves the signal is produced; only mutating each consumer proves the signal is acted on.** So:
enumerate every consumer of a safety signal and mutate each one independently. A spec-stage warning
does not prevent the defect it names; it only makes the defect findable, and only if the verification
is aimed at both ends.

Corollary (C-034, from the same round): proving a mechanism at a reduced scale establishes the logic,
not that the production constant is what reaches the call sites. Pin the constant and assert the
shipped call sites pass it, or the proof and the code can drift apart while both stay green.

### 22. Grep proposes, the type system disposes
Three instances of the same failure: the ECR-0015 capability check, the `llm` substring matching
`fullmatch(` in an ownership grep, and C-036's `AssetStore` double list -- wrong in **both**
directions, naming three files that implement other modules' protocols with similarly-named methods
while missing two real implementers. Grep is a **discovery heuristic** producing a candidate set; it
is never an enumeration, and treating its output as complete is what fails.
Enumerate Protocol implementers with `mypy --strict`. Where no signature change forces the issue,
break the Protocol signature temporarily and read what `mypy` names, then revert (C-037 used this to
establish that `FindingStore` has no test doubles at all).

### 23. When a return type widens to a tuple, every operation valid on both silently changes meaning
`len(result)` (row count -> always 2), **`if result:`** (empty was falsy -> a non-empty tuple is
always truthy), `for x in result:` (rows -> `[list, cursor]`), `result[0]` (first row -> the whole
list), `x in result` (membership over the wrong container). All are legal, so **`mypy` is
structurally unable to help**: C-036 shipped exactly this past a green `--strict` run --
`len(inventory)` where `inventory` had become a 2-tuple -- caught only because the expected value
happened not to be 2.
**`if result:` is the dangerous one**: it converts an empty read into a truthy one, so a guard
written as *"if we got nothing, refuse"* silently stops firing. That is the empty-means-safe family
(ECR-0013, ECR-0040) arriving through a **type change** rather than a logic error. Sweep call sites
for these five operations whenever a return type widens.

**Corollary - mutation testing modifies the working tree**, so restoration must not depend on `git`
when the tree is dirty. Restore from a scratchpad copy, or mutate a copy and point the test at it.
(`git checkout <file>` destroyed uncommitted work twice during C-036 before this was adopted.)

**Corollary - a fixture whose incidental structure mirrors the property under test cannot falsify a
wrong implementation.** Monotonic ids inserted in creation order is one instance; timestamps
correlated with insertion order is the same bug waiting for the next time-keyed cursor. The fixture
must be **adversarial with respect to the correlation the implementation might accidentally
exploit**: anti-correlate the sort key against the id, and insert out of id order.
Post-C-037 audit, measured: with fixtures inserted in id order, an `AssetStore` with **no ordering at
all** passed the entire cursor contract suite. With the fixtures inserted in reverse id order it
fails. The suites could not distinguish *"orders by id"* from *"returns insertion order"* - and the
one-contract-suite guarantee, which exists to catch backend divergence, would not have caught it,
because Postgres orders explicitly while an in-memory store need not.

**Corollary - a negative control is what distinguishes a real proof from a vacuous one.** C-037's
tie-spanning test was written specifically to fail against an `id`-only cursor, and on first run it
**passed** against that wrong implementation: `new_id` is monotonic, and creating fixtures in
descending severity order made id order coincide with sort order. A test asserting the right thing
about the right code can still prove nothing. Write the plausible wrong implementation, confirm the
test fails, then revert.

### 24. A contract suite that has never been run against a broken implementation is an untested test
Mutation verification was already the discipline for **guards** (rules 21, 23). Two consecutive
milestones then shipped an **inert control** in a *contract suite*, which is the same failure one
level over:
- C-037's tie-spanning test was written specifically to fail against an `id`-only cursor, and
  **passed** against it -- `new_id` is monotonic and the fixtures were created in descending severity
  order, so id order coincided with sort order.
- The `AssetStore` and `FindingStore` cursor suites **passed** against a store with its ordering
  removed entirely, because fixtures were inserted in id order and could not distinguish *"orders by
  id"* from *"returns insertion order"*.

Both were rigorous-looking and incapable of falsifying the wrong implementation. Two instances make
it a pattern, not an incident.

**For each property a contract suite claims to cover, break that property once and confirm the suite
goes red.** Specifying a negative control is not enough -- the control must be *executed* against the
defect, or nobody learns that it is inert. It costs one command; the alternative is silent and
unbounded.

### 25. A skipped test reports as success
Backend-parameterized suites **skip** when the backend is absent, and a skip is not a
failure - so a green local run can mean half the suite never executed. C-038 shipped a suite
that truncated `aq_vulnerability`, a table that does not exist (the real ones are
`aq_vuln_record` and `aq_vuln_history`); locally all three `postgres` params skipped, the run
was green, and only CI's matrix caught it.

Same family as rules 18, 19, 23 and 24 - **the test infrastructure reporting success while
not testing.** Read the skip count, or make an expected-but-absent backend fail rather than
skip. `docker compose up -d postgres` plus `AQELYN_DATABASE_URL` runs the real matrix
locally, which is one command and removes the blind spot entirely.

**Corollary - "needs a deployment" and "needs infrastructure" are different claims.**
ECR-0062's index-seek question was filed as settleable only by a first deployment. It needed
a *database*, which the repo's own `docker-compose.yml` supplies; running it took minutes and
returned an unfavourable answer that had been sitting unexamined. Before deferring a question
to production, check whether it merely needs something switched on.

### 26. A required field is an assertion that the field is always available
And **only real data can test it.** Fixtures cannot falsify an availability claim, because the
fixture author always has the value - they supplied it. `VulnerabilityRecord.cvss` was required
because every fixture carried a CVSS score; real grype output against a real Debian image withholds
it for **46%** of matches, and the model had no way to say *"I don't know"* - in an engine whose §0
discipline is *refuse, don't guess* (S-001, ECR-0064).

The same run found two more of the same shape: a severity vocabulary that did not include what real
scanners emit, and an SBOM parser requiring `purl` on every component when 7 220 of 7 367 were file
entries that correctly have none.

Same family as rules 18, 19, 23, 24 and 25 - **the apparatus reporting success while not testing** -
but from the other end: here the *fixtures* are what cannot fail. **Every required field on every
handed-in descriptor is an untested availability claim.** Treat the first real run of any new source
as the test, and expect it to fail on the fields nobody thought to omit.

**Corollary - a rejected record is invisible; an unknown record is a flagged gap.** Refusing what
cannot be represented is correct at the boundary, but it is not the resting state: the platform then
does not know those records exist. Making absence representable converts silent absences into
explicit unknowns, which is strictly more information and the only version consistent with
*absence != safe*.

### 27. A fixture's values encode assumptions about the SHAPE of real data
Rule 26's sibling. Where 26 covers **availability** - a required field asserts the field always
exists - this covers **shape**: precision, magnitude, cardinality, length. Every one is an assertion,
and every one is untested until real data arrives.

S-001: `_compose_score` returns `round(unit * 100, 6)` while the replay path does
`round(score / 100.0, 6)` - **scale-then-round versus round-then-scale, which are different
functions.** Fixture scores carried four decimals or fewer, so the round-trip was lossless *by
accident of fixture construction*. Real EPSS values (`0.01109`, `0.73327`) broke **162 of 200**
records on first contact (ECR-0065).

**Nobody chose four decimals as a claim about CVSS.** It was what a person types when writing an
example. The assertion was made invisibly, which is why no amount of mutation testing on the fixtures
could surface it - the fixtures agreed with themselves.

**Corollary - precision is usually the symptom, not the cause.** When a stored value and its
recomputation disagree, check whether the two paths perform the *same operations in the same order*
before adding digits. Adding digits makes today's values agree while leaving the paths computing
different functions, and the next value with more significant digits reopens it.

### 28. Before specifying that a condition be counted, check whether it is already refused
ECR-0064's amendment tabled `malformed` as a count category and illustrated it as
`{non_package: 7220, malformed: 0}` - which reads as *count it*. But EA-0030 already **quarantines** a
partial SBOM. Implementing the count as specified would have **downgraded a hard guarantee to a soft
signal while looking like added observability**, and it was caught only because a shipped test
(`test_sc_quarantine`) asserted the quarantine.

**Refusal is the strongest possible way of acting on a signal.** Replacing it with a counter is a
weakening dressed as instrumentation - and it is a particularly hard weakening to see in review,
because more reporting reads as more rigour.

## Part 2 - Current handover: IS-037 / EA-0037 (Cyber Asset Exposure Management)

**Repository state:** `main @dc6037e`, GC-001 merged and CI green (`mypy --strict src tests`
494 files; reviewer full-suite confirmation was still finishing when this handover was written).
**Next free ECR:** **0058** (log ends at ECR-0057; re-read `ECR-LOG.md` before assigning).
**Archive verified:** `archive/EA-0037/EA-0037_Master.md` declares itself the master Markdown and
IS-037 source of truth. Its copy inside `releases/EA-0037_FULL_COMPLETE.zip` is byte-identical
(SHA-256 `610c801a4c2d0485358f8de48916b866a56f9ffc2e3f520dd808cd8cec1c2be7`).

### Finding 1 - this is another generated TEMPLATE

EA-0037 has the same 424-line scaffold as template EA-0036. After normalizing the module number and
title, **401 of 424 lines are identical**. Twelve objectives are literal placeholders:

```
OBJ-0037-001: Provide a verifiable capability boundary for aqelyn cyber asset exposure
              management engine objective 1.
... (identical through objective 12)
```

The architecture, lifecycle, security, testing, and acceptance sections repeat generic prose. The
requirements matrix says only "Discovery and Intake", "Normalization", "Inventory", "Assessment",
and similarly generic capability labels. It supplies no concrete object schema, interface signature,
algorithm, lifecycle transition, failure rule, or acceptance case.

The only usable intent is the executive-summary sentence:

> discovers assets, measures exposure, maps attack surface relationships, and prioritizes reduction
> of exploitable exposure.

Do not manufacture requirements from the other headings. A reasonable-sounding CAEM specification
written from this template would be drafter-authored scope wearing archive authority.

### Finding 2 - "037" identifies three incompatible artifacts

Number alone is unsafe in this archive:

| Artifact | What it calls 037 |
|---|---|
| `archive/EA-0037/EA-0037_Master.md` + batch index | **Cyber Asset Exposure Management Engine / IS-037** |
| `docs/supporting_materials/.../Volume_037_AQELYN_Distributed_Scan_Engine.md` | **Distributed Scan Engine** |
| `docs/AQELYN_Master_Index_EA-0001_EA-0057.md` | **Pre-Coding Baseline Engine EA-0037** |

The first is authoritative for this turn: the master declares its own source-of-truth status, its
release ZIP matches it, and `archive/AQELYN_Master_Index_EA-0036_EA-0050.md` agrees. The broad index
needs a documentation correction. The Blueprint Volume 037 belongs to a different numbering family
and is **not an IS-037 requirement source**.

This distinction is safety-critical. Importing the Distributed Scan Engine's workers, credentials,
scheduler, or live collection into IS-037 would reverse EA-0023's shipped boundary. Active scanning
remains an EA-0008-gated connector action; this analytical turn opens no socket and holds no
credential.

**Promoted to Part 1 as rule 20** (landed by C-034): when an EA number appears in multiple archive
families, verify the source family, title, and declared source of truth. A matching number does not
transfer scope.

### Finding 3 - the named capability already ships across four owners

ECR-0015 event/type/capability check against shipped `src/`:

```
CyberDiscovered / CyberUpdated / CyberAssessmentCompleted / CyberRiskDetected : 0 each
CyberPolicyViolationDetected / CyberRecommendationGenerated                  : 0 each
CyberWorkflowRequested / CyberEvidenceLinked / CyberArchived                  : 0 each
Cyber Asset Exposure Management / cyber_asset_exposure / caem                 : 0 each

AttackSurfaceAsset 6 · ExposureRecord 81 · InventoryReport 11 · VulnPriority 22
derive_surface 3 · analyze_exposure 13 · prioritize 47 · paths 156
```

The zero-hit generic `Cyber*` events are template placeholders, not a net-new event namespace. The
capabilities behind them are already owned:

1. **Discovers assets / authoritative denominator:** EA-0025
   `InventoryIntelligenceEngine.ingest`, `reconcile`, `inventory`, and `infer_relationships`.
   Discovery reports are handed in; absence becomes `unreported`, never decommissioned.
2. **Measures exposure / attack surface:** EA-0023 `KnownDataExposureEngine.derive_surface`,
   `analyze_exposure`, `score_exposure`, and `raise_exposure_finding`. Unknown reachability stays
   `unknown` and flagged; no active probe occurs.
3. **Maps relationships:** EA-0002 owns relationship persistence and EA-0005 `KnowledgeGraph.paths`
   owns bounded traversal. EA-0023 delegates paths rather than walking a second graph.
4. **Prioritizes exploitable exposure:** EA-0024 `VulnerabilityIntelligenceEngine.prioritize` composes
   EA-0023 reachability through `ExposureStoreReachabilityProvider` into a replayable priority.

The runtime wiring already joins the owners in both factories:

- `InventoryKnownSurfaceSource(inventory_engine)` is the base of the composed EA-0023 source.
- `InventoryVulnerabilityCoverageProvider(inventory_engine, vuln_store)` supplies EA-0024's
  denominator.
- `ExposureStoreReachabilityProvider(exposure_store)` supplies EA-0024's exposure factor.
- `KnownDataExposureEngine(..., graph=knowledge_graph)` delegates attack paths to EA-0005.

Existing real-engine tests prove the joins, not only the calls:
`test_inv_seams_wired`, `test_exp_unknown_not_internal`,
`test_exp_paths_delegate_kg`, `test_exp_score_composes_trust_mission_risk_derivation`, and
`test_vuln_priority_replayable`. The targeted in-memory set was re-run for this handover: 8 passed.

### Resolution to propose - ECR-0059 (distributed conformance, no CAEM module)

> **Renumbered ECR-0058 → ECR-0059.** The owner sequenced GC-002 (event-namespace
> closure guard) ahead of C-034, so GC-002 takes ECR-0058 and IS-037/C-034
> conformance takes ECR-0059. See `ECR-LOG.md` (0058 = GC-002, 0059 = IS-037).

1. Mark IS-037 a **distributed restatement** realized by EA-0025 + EA-0023 + EA-0002/0005 + EA-0024.
   There SHALL be no `src/aqelyn/caem/`, `cyber_asset_exposure/`, second inventory/exposure store,
   second graph, second prioritizer, `caem_engine`, or generic `aqelyn.cyber.*` event namespace.
2. Deliver a conformance analysis and one real-runtime proof that drives the whole owner chain:
   handed-in inventory -> known surface -> exposure/path -> vulnerability priority, with replay,
   no-network, tenant isolation, and unknown-not-safe controls. A spy or event-name grep is
   insufficient.
3. Correct the broad master-index row so EA-0037 no longer points readers at "Pre-Coding Baseline".
   Preserve the Blueprint Volume 037 as supporting material, but state explicitly that it is not the
   IS-037 master.
4. Do not invent a feature gap from the template. The one genuine repair directly under this
   capability is already recorded as **ECR-0034** and should be closed in this turn if the owner
   approves (below).

### ECR-0034 is now on the critical path, not a distant follow-up

`InventoryIntelligenceEngine.inventory()` and `sweep_unreported()` still query
`AssetStore.query(limit=10_000)` once. `AssetStore.query` has no cursor, and `inventory()` hardcodes
`degraded=False`. The verified result for 10,050 assets is:

```
actual assets                         10050
InventoryReport.total                 10000
InventoryReport.degraded              False
EA-0023 known-surface records         10000
EA-0024 coverage denominator          10000
assets neither scanned nor unscanned     50
```

That is the exact failure IS-037's title makes load-bearing: a smaller world looks fully inventoried,
fully surfaced, and better covered. The fail-closed gates in `InventoryKnownSurfaceSource` and
`InventoryVulnerabilityCoverageProvider` key on `report.degraded`; the hardcoded `False` makes those
gates unreachable for store truncation.

Recommended C-034 shape:

- **L1 - conformance record and source-family correction:** docs + real-owner chain, zero production
  namespace.
- **L2 - implement existing ECR-0034 in EA-0025:** D8 cursor contract on both AssetStore backends;
  stable id order, filters before limit, `next_cursor` exactly when another matching row exists;
  bounded paging or refusal for `inventory()` and `sweep_unreported`; over-cap regression proving
  EA-0023/EA-0024 either see the full estate or refuse. Do not trade the silent cap for unbounded
  request work (ECR-0031).
- C-034 is not complete while the conformance record claims an exhaustive asset denominator and
  ECR-0034 remains reproducible. If the owner does not approve L2, record the residual
  non-conformance explicitly rather than calling the capability fully green.

### Delegation seams verified in shipped code

| Need | Shipped owner and exact seam |
|---|---|
| handed-in asset discovery and reconciliation | EA-0025 `InventoryIntelligenceEngine.ingest(*, reports, source, tenant_id)` / `reconcile(asset_id, *, tenant_id)` |
| authoritative inventory | EA-0025 `inventory(*, tenant_id) -> InventoryReport` |
| inventory -> exposure | `InventoryKnownSurfaceSource.list_known_surface(*, tenant_id)` |
| known-data surface and exposure | EA-0023 `derive_surface(*, tenant_id)` / `analyze_exposure(*, asset_ref, tenant_id)` |
| exposure scoring and finding | EA-0023 `score_exposure(exposure, *, impact_context=None)` / `raise_exposure_finding` |
| relationship persistence and traversal | EA-0002 `ObjectStore.relate`; EA-0005 `KnowledgeGraph.paths(..., max_depth, max_paths, max_work)` |
| vulnerability prioritization | EA-0024 `prioritize(vulnerability_id, *, tenant_id)` |
| exposure -> vulnerability factor | `ExposureStoreReachabilityProvider.reachability_factor(vulnerability)` |
| inventory -> vulnerability coverage | `InventoryVulnerabilityCoverageProvider.coverage(*, tenant_id)` |
| evidence / trust / mission / findings | EA-0004 / EA-0006 / EA-0007 / EA-0013 |
| any future active collection | EA-0008-gated `ActionSpec`; never an analytical-engine method |

### Review protocol for the drafted decision

1. **Template first:** no requirement may be attributed to a placeholder objective or generic section.
2. **Source family:** the draft must name Cyber Asset Exposure Management, not Distributed Scan or
   Pre-Coding Baseline. Trace every imported statement to the correct artifact.
3. **No second owner:** no CAEM package/service/store/graph/scorer/event namespace.
4. **Real chain, with a negative control:** removing the inventory->surface seam must change the real
   exposure result; removing the exposure record must change the real EA-0024 factor. Calls alone are
   insufficient.
5. **No scan surface:** socket spy plus callable-surface check. The only active path is an EA-0008
   action specification, never `scan`/`probe`/`connect` on the analytical engine.
6. **Unknown is not safe:** inventory reachability `None` becomes exposure `unknown`, never internal
   or unreachable; degraded inventory makes surface and coverage refuse.
7. **ECR-0034:** 10,050 assets either enumerate fully under a bounded contract or raise
   `InventoryUnavailable`; never return 10,000 with `degraded=False`. Prove both backends and both
   downstream adapters.
8. **D8 pagination:** adversarial ordering, filter before limit, exclusive cursor, no phantom page,
   both backends. `sweep_unreported` must reach assets beyond the former cap.
9. **Events stay with owners:** generic `Cyber*` placeholders remain absent; existing
   `aqelyn.inventory.*`, `aqelyn.exposure.*`, and `aqelyn.vuln.*` events are not re-emitted.
10. **Standing gates:** `ruff`, format, `mypy --strict src tests`, worktree pytest with
    `PYTHONPATH=$PWD/src`, live Postgres/Redis, both tenant modes, and `gh pr checks` confirmed green.

### Other tracked follow-ups this turn must not absorb

- EA-0018 `response/metrics.py` unclamped-duration flake.
- EA-0027 / EA-0018 enterprise health-probe gaps.
- EA-0013 equal-timestamp ordering tie-breaker.

They remain real, but they are not evidence for a CAEM module and do not belong in C-034.
