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

### 29. A correction applied at one call site when it was a property of all of them
**ECR-0040** established that an unknown factor is excluded from the denominator rather than scored
favourably. It was applied to `exposure`. Three lines away in the same function, `threat`, `baseline`
and `mission` kept defaulting to `known` when their providers are unwired - so every real priority
score was computed with **three phantom favourable inputs**, and S-001's density report found it by
showing `known=200` for providers that do not exist (ECR-0066).

**This is a distinct failure mode from the rest of this series.** Rules 18/19/23/24/25 are the
apparatus reporting success while not testing; 26/27 are fixtures unable to express the failure.
This one is neither: **nothing failed to test, and the decision was correct.** The fix was scoped to
the symptom, and the siblings inherited nothing.

> **When an ECR corrects a defect at a call site, the closing question is not *"is this site fixed"*
> but *"is this site the only one that could have had it?"*** - answered by **enumeration**, not by
> inspection of the diff.

**Corollary - the guard can carry the same error.** GC-001 AC-3 asserted that each composition scorer
ships *a case* proving unknown is not favourable: **per scorer, one case**. A seven-factor scorer with
one correct factor passes, so the guarantee written to catch this family was **capable of passing the
exact defect**. A per-instance guard against a per-pattern property is the same mistake one level up.
Widen the guard **with** the fix, or it certifies the repair while still admitting the disease.

### 30. Real data is not adversarial either
Rules 26 and 27 say fixtures cannot falsify assumptions about **availability** and **shape**, because
the fixture author supplies the value. The S-track was the remedy - and it has the mirror-image limit.

**Real data supplies what it supplies.** It falsifies a *different* set of assumptions than fixtures
do, and the ones it leaves untouched are **invisible precisely because the run succeeded against
them**. S-001's density report - the instrument built to find unwired factors - could not see `epss`
defaulting to `known`, because every grype match carried EPSS, so its missing branch never fired
(ECR-0066).

> **A `known = N/N` row is not evidence that a factor is wired. It is evidence that the corpus never
> asked.**

**The camouflage improves with scale.** A larger corpus in which every record carries EPSS hides the
defect *exactly as well* as a small one, and makes the row look **better evidenced** - `known =
20,000/20,000` reads as stronger confirmation than `200/200`. More data does not eventually expose a
defaulting factor; it deepens the impression that there is nothing to expose.

**So the S-track does not supersede enumeration - it relocates what enumeration is for.** Measurement
covers what the corpus exercised; **enumeration covers the rest**, and only enumeration separates
*always known* from *always known by default*. That is the concrete vindication of auditing all seven
factors rather than the three the report revealed: the measurement could not have found the fourth.

### 31. For a guarantee of the form "A must equal B", mutate A or B - never the comparator
ECR-0067: `validate_replayable_exposure` called `replay()` and **discarded the return value**. That
is not a check asserting a weaker property - it is **no check at all, wearing the name of one**. The
three things it did verify were incidental: that `replay` does not raise, that the derivation is
traversable, that steps exist. The comparison never happened.

**Eight controls passed, and no mutation of the tests would have found it - the tests were fine.**
The defect was in the code they exercised, which called the checker and threw the answer away.

> **A correct comparator whose result is discarded passes every mutation of itself.** Perturbing
> `replay()` would have changed nothing. Perturbing the **stored score** turned all eight red.

**The revealing mutation targets the subject of the guarantee, not its implementation.** Adjacent to
rule 21 - mutate consumers, not only producers - but distinct: rule 21 is about whether a signal is
*acted on*; this is about whether the comparison is **wired at all**.

**Corollary:** a guarantee that holds *in fact* while being absent *in principle* cannot be noticed
by reading, because every output is correct. Only mutating its subject distinguishes "verified" from
"happens to be true".

### 32. A synthesized fixture can manufacture a defect as easily as it can hide one
S-003 U5 / PR #251 review: the product correctly required an externally bound listener's PID to
match a collected unit before calling the listener attributable. A synthesized test used `pid=1`.
That value satisfied the field's type while referring to no unit in the fixture, so the test accused
correct code of leaving the listener unknown.

Rules 26, 27, and 30 cover fixtures and corpora that are too generous and hide defects. This is the
opposite failure: a plausible value satisfies the field's **shape** while violating what the field
**refers to**, manufacturing a false defect report and inviting a fix to correct code.

> **For every synthesized reference, construct the referent and verify the join before judging the
> product.** A typed id, PID, cursor, evidence id, or object key is not valid merely because its
> syntax is valid.

**The tell:** if a result is surprising, test the fixture's referential claim independently before
changing the implementation. The product remains strict: a PID matching no collected unit is
unattributable, because resolving it would turn a plausible-looking reference into a false answer.

### 33. A test that a field holds the right value proves maintenance, not use
ECR-0084 / P-002: selected by the owner on 2026-07-31, with both clauses required.
`current_severity_score` was written correctly, updated on re-emission, and covered by a
passing conformance test, while no user-facing path read it.

> **A test that a field holds the right value proves maintenance, not use.** *Is it read?* is
> the question that decides whether the feature exists, and no assertion about the field can
> answer it.

The mechanical form is `grep -rn <field> src/ | grep -v <owning package>`: a persisted field
with no reader outside its owner is maintained internal state, not a delivered feature.

**Second clause:** a consumer **no shipped path can reach with the data it reads** is a
consumer **for the checker and not for the user**. A grep hit is necessary, not sufficient.
P-002 demonstrates the distinction: its renderer branch is reachable from `__main__`, but a
fresh per-run store cannot produce the re-emission state that makes the branch fire.

**Review consequence:** when a persisted field gains its first reader, determine whether a
shipped path can supply the state that reader consumes. If not, record the consumer as dormant
rather than claiming the feature exists.

**Fixture symmetry (ECR-0099).** Every component of a sort tuple must decide at least one
comparison in the same fixture. A fixture tuned to expose one component is presumed to blind
another until leading-key and tail mutations both turn red against it.

### 34. Carried mutation matrices are sampled by recorded policy, not convenience

ECR-0099 closes the ordering-witness arc with one final full carried run and records the policy
for later reviews:

- run the full carried matrix when a carried-control file changes, an ECR amends carried
  fixtures or claims family closure, and at every tenth ECR;
- otherwise name the rotating sample in the review record, cover the full matrix within five
  reviews, and add every carried mutation touching the current ECR's scope;
- any changed verdict in the sample or scope escalates to the full matrix before merge.

Sampling is a recorded allocation of review attention, not an implicit relaxation. Its
composition and rotation must remain auditable, and the rule can be reversed only by another
recorded decision.

## Part 2 - Current handover: widening the surface (proposed ECR-0089)

**From:** Claude Code (reviewer; the only actor that reads shipped code)
**To:** claude.ai (spec author)
**Date:** 2026-08-02
**Verified against:** `main @f601c69`, clean, no open PRs

Every count and signature below was produced by importing the shipped runtime and inspecting it at
that SHA. Nothing is inferred from titles.

---

## 0. State

- **`main @f601c69`**, clean, **no open PRs**, nothing queued with Codex or the owner.
- **Shipped since the last brief:** PR #288 (this brief's predecessor), #289 (ECR-0088 — the
  loopback operator surface), #290 (fixed a fatal `app.js` parse error and a broken `[hidden]` rule
  that I had merged; **the owner confirmed the UI responds in a real browser**).
- **Next free ECR: `0089`.** Highest allocated is **ECR-0088**. **Rule 1 discharged — re-check
  before merging.**
- **Next free GC: `005`.** Rules 1–33 current.
- **Owner decisions unchanged:** EA-0054 not built; EA-0052-FR-004 resident agent not authorized;
  non-loopback binding remains owner-gated.

---

## 1. What ECR-0088 actually shipped, and what it did not

**Shipped:** a loopback-only, read-only surface — `python -m aqelyn surface --port 8765` — with
`/`, `/health`, `/api/v1/meta`, `/api/v1/inventory`, `/api/v1/findings`, `/api/v1/vulnerabilities`,
and two assets. Stdlib `asyncio` only; **no new dependency**. Verified live: binds `127.0.0.1`,
rejects writes with 405, rejects bodies with 400, rejects `tenant_id` in local mode with 400.

**Not shipped:** everything else. **The surface exposes 3 domain reads out of 30 registered
services.** That is the gap this ECR addresses.

---

## 2. 🔴 The finding that governs this spec: **there is no uniform read seam**

I inspected all 30 registered services. They split into **two incompatible shapes**, and a spec that
assumes either one will be wrong for roughly half the platform.

| shape | count | services |
|---|---|---|
| **Methods on the service** | **15** | `cspm_engine`, `detection_engine`, `dspm_engine`, `executive_engine`, `exposure_engine`, `finding_read`, `forensics_engine`, `idthreat_engine`, `inventory_engine`, `ispm_engine`, `policy_engine`, `secrets_engine`, `sspm_engine`, `supplychain_engine`, `vuln_engine` |
| **Engine-only** — service exposes *nothing* public; the API is on a `.engine` (or `.graph`) attribute | **13** | `acg_engine`, `compliance_engine`, `decision_engine`, `forecast_engine`, `iag_engine`, `knowledge_graph`, `mission_engine`, `response_engine`, `risk_engine`, `soc_engine`, `threat_fusion_engine`, `trust_engine`, `workflow_engine` |
| **Neither** (infrastructure / no read API) | **3** | `datalake_engine`, `event_bus`, `object_store` |

Concretely — `kernel.get_service("risk_engine")` returns a `RiskIntelligenceService` whose only
public methods are `start`/`stop`/`health`. Its real API lives at `.engine`:

```
RiskIntelligenceEngine   -> assess, correlate, explain, score, treat, trend
SecurityOperationsEngine -> assign, correlate, explain, hunt, investigate, propose_response, transition
ThreatFusionEngine       -> correlate, explain, ingest, matches_to_findings, score_confidence
```

> **The surface cannot widen uniformly until this is settled.** Reaching through `service.engine`
> from the surface would make the surface depend on engine internals — precisely the coupling
> ECR-0088 avoided by importing only models plus `Runtime`.

**This is a genuine architectural decision and it belongs in this ECR, not in an implementation.**

---

## 3. The precedent ECR-0088 already set — and my recommendation

ECR-0088 did not reach into `FindingStore`. It added a **dedicated read service**:

```python
class FindingReadService:
    """Expose the owner's existing keyset query without adding a write path."""
    def query(self, *, tenant_id: str | None, ...) -> ...
```

registered as `finding_read`. **That is the shape to generalise**, and I recommend it:

- it puts the read contract in the domain package that owns the data, not in the surface;
- it is **read-only by construction** — the type has no write method to call by accident;
- it keeps the surface importing only models and `Runtime`, which is what makes the
  no-engine-import guarantee testable (`test_surface_imports_no_domain_engine_or_store`);
- it needs no change to the 13 engine-only services — a read service can wrap `.engine` inside the
  owning package, where that coupling is legitimate.

**Recommendation: widen by adding `*ReadService` classes in the owning packages, one per exposed
capability, and register them.** Do **not** teach the surface to traverse `.engine`.

---

## 4. Delegation seams, quoted from shipped code

**Tenant scope is on the signature of every domain read** — 9 of `inventory`'s methods, 11 of
`secrets`', 9 of `ispm`'s take `tenant_id`:

```python
InventoryIntelligenceService.inventory(*, tenant_id: str | None) -> InventoryReport
VulnerabilityIntelligenceService.assess(*, tenant_id: str | None) -> VulnerabilityAssessment
FindingReadService.query(*, tenant_id: str | None, ...)
```

`tenant_id=None` means **this local estate**, not "all tenants" — the surface already enforces that
in both directions (`400` if supplied in local mode, `400` if omitted in enterprise mode). **Any new
route inherits that rule; state it in the FR text rather than leaving it to the implementer.**

**Kernel:** `AQKernel.{register, get_service, start, stop, signal_stop, health}`; every service
satisfies `AQService` (`kernel/service.py:24`). `kernel.health()` already covers all 30 and is
GC-003-guaranteed in both tenant modes.

**Pagination:** only `findings` currently pages (composite keyset on `(severity_score, id)` per
ECR-0062). `inventory` returns a whole `InventoryReport` under `page_budget` with a `degraded` flag
(ECR-0034/0061). **A widened surface must not paper over `degraded`** — ECR-0034's flag is the
honest-truncation contract and three consumers are guarded against ignoring it.

---

## 5. The second gap this ECR should decide: `reporting/` still bypasses the kernel

`grep -c "kernel\|get_service" src/aqelyn/reporting/*.py` → **0, 0, 0, 0.** The P-001 report still
imports `VulnerabilityIntelligenceEngine` and the in-memory stores directly and builds them per run.
So the platform now has **two** user-facing paths that do not share a data path:

- `python -m aqelyn <dir>` → static HTML, one engine, no kernel;
- `python -m aqelyn surface` → live read API, real kernel, three engines.

Left alone this becomes two products. **Options, with my recommendation:**

- **(a) Leave both, record the split as deliberate.** Cheapest, honest, but the divergence compounds.
- **(b) ⭐ Point the report at the kernel** — `analyze_collection` keeps its handed-in-document input
  but publishes through the same read services the surface uses. One data path, two renderers.
- **(c) Serve the report from the surface.** Tempting and wrong as a first step: it inherits P-001's
  no-pagination limit (`html.py:16` inlines all 10,173 findings) into a live server.

**Recommend (b), scoped to reads only.**

---

## 6. Constraints the widening must not break

1. **Loopback stays.** `LOOPBACK_HOST = "127.0.0.1"` with no bind seam; the network guard now catches
   `http.server`/`socketserver`/`asyncio.start_server`/`start_unix_server`/`create_server`/
   `create_unix_server`/`socket.socket` **outside `surface/`**, in both import forms, plus dynamic
   module strings. **Non-loopback binding remains an owner decision.**
2. **Reads only.** `READ_METHODS = frozenset(("GET","HEAD"))` and a fixed route allowlist. Every write
   path (`ingest`, `raise_*`, `propose_*`, `decommission`, `transition`) is an *action* with existing
   gating; **a read-only v2 avoids reopening any of it.**
3. **No new dependency.** The surface is stdlib `asyncio`. Adding a framework would be a new supply
   chain surface and should be its own decision.
4. **Client assets are generated Python strings** — `APP_JS` must stay `r"""` and the served-asset
   quote guard plus `[hidden] { display: none !important; }` must survive. **PR #290 exists because
   a non-raw literal ate a `\n` and killed the entire UI while every gate stayed green.**
5. **Do not weaken:** ECR-0034 `degraded` · ECR-0061 exhaust-or-refuse · ECR-0062 keyset ·
   rule 33 · GC-002 event namespace · GC-003 registry coverage · GC-004 persisted-field census (any
   new persisted field joins it) · EA-0004 integrity ≠ authenticity.
6. **No auth exists.** Widening the read surface widens what an operator with loopback access sees.
   That is acceptable *because* it is loopback and read-only — **and it is the reason both properties
   must hold together.** If either is relaxed, authentication becomes a prerequisite, not a nicety.

---

## 7. False friends

- **No prefix for a surface/session/user** — `conventions/ids.py::PREFIXES` has 61 allocated; `svc`
  and `src` are taken and mean `service`/`source`.
- **Event names** are dotted lowercase `aqelyn.<domain>.<verb>` and **GC-002 closes the namespace**.
  A read surface should emit **no** events; if it must, the prefix needs registering.
- **`finding_read` is a service name, not a package.** The registry key and the package differ
  across the platform (`vuln_engine` → `src/aqelyn/vuln/`), which is what broke my first GC-003
  analysis. **Diff by class identity, never by name similarity.**
- **`/api/v1/` is already claimed** by the surface's own routes; EA-0062's `/api/v1/archives`,
  `/api/v1/agents/codex/task` are **build-portal** routes from an unrelated document — not a
  starting point (ECR-0086/0087).

---

## 8. What I recommend ECR-0089 decide

1. **The seam question (§2)** — read services in owning packages, generalising `FindingReadService`.
   This is the decision; everything else follows from it.
2. **Which capabilities go first.** Recommend the four with the clearest operator value and existing
   tenant-scoped reads: **ISPM posture**, **exposure**, **secrets/crypto**, **supply chain** — each
   already has `assess`/`explain` and 7–11 tenant-scoped methods.
3. **`explain` is the platform's differentiator and it is nearly universal** — 11 services expose it.
   A surface that shows a score without its derivation contradicts the product principle
   (*"Explain Before You Recommend"*). **Recommend every widened route carry its `explain` payload.**
4. **The `reporting/` split (§5)** — recommend (b).
5. **Pagination for any collection route**, on ECR-0062's keyset precedent, never offset.

**Do not** add writes, auth, a framework, or a non-loopback bind in this pass.

---

## 9. Ball

**Next: claude.ai authors ECR-0089** from this brief. Then Codex implements, and I review and merge.
**Reserved to the owner:** nothing new. The existing reservations (non-loopback bind, EA-0054,
EA-0052-FR-004) are untouched by this work.
