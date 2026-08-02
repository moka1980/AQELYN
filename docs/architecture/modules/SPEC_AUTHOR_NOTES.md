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

## Part 2 - Current handover: the surface (proposed ECR-0088)

**From:** Claude Code (reviewer; the only actor that reads shipped code)
**To:** claude.ai (spec author)
**Date:** 2026-08-02
**Verified against:** `main @ce10936`, clean, no open PRs

Every count, signature and grep below was run against shipped `src/` at that SHA. Nothing here is
inferred from titles or line counts — that error is itself one of this brief's findings.

---

## 0. State

- **`main @ce10936`**, clean, no open PRs. Nothing queued with Codex, claude.ai, or the owner.
- **Shipped since the last brief:** PR #285 (ECR-0086 recorded), #286 (ECR-0086 **Accepted** — owner
  decisions + three-branch absence guards), #287 (ECR-0087 — the standards read).
- **Next free ECR: `0088`.** Read from `ECR-LOG.md` at `ce10936`; highest allocated is **ECR-0087**.
  **Rule 1 discharged — re-check before merging.**
- **Next free GC: `005`.** SPEC_AUTHOR_NOTES **rules 1–33** current.
- **Owner decisions of record (ECR-0086):** EA-0054 **not built**; EA-0052-FR-004 resident agent
  **not authorized**. Neither is reopened by this brief.

---

## 1. Why this ECR exists — **the archive does not contain the surface**

The owner asked whether the platform can soon be produced in a dashboard and tested. The answer
required checking, and the checking is now complete: **no archive master specifies a product
surface.** That is a finding, not an absence of effort.

| candidate | verdict | how it was established |
|---|---|---|
| **EA-0059** AQELYN Design System | **generator-template class 3** — no design system | 703 lines; REQ **100 → 1** distinct after topic normalization; AC **80 → 1**; 20 "Implementation Rules" blocks → **1 SHA-256**. Its *"Dashboard components / Risk cards and findings"* are scope **bullets** at `EA-0059_Master.md:19-20`, inside ~29 unique lines |
| **EA-0062** Engineering Portal & Mission Control | **real content, wrong subject** | singleton at 592 lines (no family); **425 of 455** non-blank lines distinct; only 3 repeat, one being `---` (29×); **all 29 section bodies distinct hashes** |

**EA-0062 passes the content test and fails the usefulness test.** Its domain vocabulary:
`finding 0 · risk 0 · threat 0 · tenant 0 · asset 1 · vulnerability 1`. Its 17 data-model entities
are `EngineeringArchive`, `Requirement`, `TraceabilityLink`, `ImplementationTask`, `TestRun`,
`BuildRun`, `PullRequest`, `ArchitectureDecisionRecord`, `ReleaseCandidate`…; its APIs are
`/api/v1/archives`, `/api/v1/implementation/status`, `/api/v1/agents/codex/task`, `/api/v1/ci/status`.
Mission Control's own worked example reads *"Architecture: 100% / Implementation: 0% / Current task:
EA-0001 AQELYN Kernel."* **It is a project-management view of building AQELYN, not a view onto what
AQELYN produces.** Its 13 "evidence" hits are build traceability (`:77`, `:81`, `:522`), not EA-0004
security evidence.

🔴 **And EA-0062's two most surface-relevant sections delegate to documents ECR-0087 proved empty.**
Six normative references: `:403` *"All APIs shall follow **EA-0058** naming, error handling, logging,
authentication, and observability rules"* · `:430` *"UI must follow **EA-0059**"* · `:121` · `:122` ·
`:266` · `:516` (*"shall integrate EA-0058 through EA-0061 standards"*). **EA-0058/0059/0060/0061 are
all class-3 templates.** So even as a portal spec, its API-conventions and UI halves rest on nothing.

> **Consequence for this ECR: the surface is a fresh specification, not a read.** Nothing in the
> archive can be conformed to, restated, or mined for it.

🧠 **Method note the ECR should carry, because I got it wrong twice:** ECR-0086 called EA-0058/0060/
0061 *"703 lines … real content"* — a **line-count** inference. Reviewing the correction I then ran a
normalized structural diff, saw **542 of 703 lines differ** (77%), and read *that* as content — also
wrong, because those lines differ only where a section title is substituted into shared boilerplate.
**Line count measures the generator; line *difference* measures the generator too.** Only normalizing
the substitution and counting distinct survivors reaches content. **"Real content" and "useful
content" are then still separate tests** — EA-0062 passes the first and fails the second.

---

## 2. The single most important shipped fact: **there are two disconnected worlds**

This is the thing a surface spec must be built around, and it is not visible from any document.

**World A — the platform.** `create_inmemory_runtime()` / `await create_runtime()`
(`kernel/factory.py:873` and `:1571`) wire **30 registered services** (28 domain + `event_bus` +
`object_store`):

```
acg_engine, compliance_engine, cspm_engine, datalake_engine, decision_engine, detection_engine,
dspm_engine, event_bus, executive_engine, exposure_engine, forecast_engine, forensics_engine,
iag_engine, idthreat_engine, inventory_engine, ispm_engine, knowledge_graph, mission_engine,
object_store, policy_engine, response_engine, risk_engine, secrets_engine, soc_engine, sspm_engine,
supplychain_engine, threat_fusion_engine, trust_engine, vuln_engine, workflow_engine
```

**World B — the only user-facing surface.** `python -m aqelyn <collection_dir>` →
`reporting.cli` → one static HTML file. Its docstring is the design property, verbatim:
*"Local, operator-only findings report (P-001)."*

🔴 **World B never enters World A.** `reporting/analyze.py` imports
`VulnerabilityIntelligenceEngine`, `InMemoryVulnerabilityStore`, `InMemoryFindingStore`,
`InMemoryEvidenceStore` **directly** and constructs them per run. A grep of `src/aqelyn/reporting/`
for `kernel`, `Runtime` or `get_service` returns **one hit, and it is `RuntimeError`.**

⇒ **The shipped report exercises one domain engine (EA-0024) out of 28, and reaches the kernel
never.** Twenty-seven domain engines have no user-facing path of any kind. **This is what "no way in,
no way to see" means concretely** — and it is EA-0054's precondition #1, so this ECR unblocks the
owner's own deferred decision as a side effect.

---

## 3. Real delegation seams — quoted from shipped code

A surface has exactly three seams available. **These are the real names; do not invent others.**

**3.1 The kernel.** `AQKernel` public methods: `register`, `get_service`, `start`, `stop`,
`signal_stop`, `health`. Every registered service satisfies `AQService`
(`kernel/service.py:24`, `@runtime_checkable`):

```python
class AQService(Protocol):
    @property
    def name(self) -> str: ...
    @property
    def dependencies(self) -> Sequence[str]: ...
    @property
    def critical(self) -> bool: ...
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def health(self) -> HealthStatus: ...
```

**A surface gets `/health` almost free** — `kernel.health()` over 30 services already exists and is
guaranteed by GC-003 in both tenant modes. **That is the one endpoint that needs no new contract.**

**3.2 Domain services.** Public methods are narrow and **every domain call is keyword-only and
carries tenant identity**:

```python
InventoryIntelligenceService.inventory(*, tenant_id: str | None) -> InventoryReport
InventoryIntelligenceService.sweep_unreported(*, source: DiscoverySource, tenant_id: str | None) -> list[AssetRecord]
# also: classify, decommission, infer_relationships, ingest, mark_unreported, ownership, reconcile
VulnerabilityIntelligenceService.assess / ingest / prioritize / raise_vulnerability / recommend / trend
```

⇒ **`tenant_id` is not optional plumbing — it is on the signature of every read.** A surface that
cannot supply it cannot call the platform, and `tenant_id=None` is the *local* mode value, not a
"all tenants" wildcard. Get this into the spec's FR text explicitly.

**3.3 The report.** `analyze_collection(directory: Path) -> CollectionAnalysis` and
`render_findings_report(analysis: CollectionAnalysis) -> str`. Note the input is a **directory**,
not a runtime — this is the seam that would have to change for a surface to render live data.

**Config the surface must respect** (`kernel/config.py:70-71`):
`tenant_mode: Literal["local","enterprise"] = "local"` · `backend: Literal["memory","postgres"] = "memory"`,
and `backend=postgres` **requires** `AQELYN_DATABASE_URL` or raises `ConfigError`.

---

## 4. Constraints the surface spec must not break

1. 🔴 **The no-socket boundary is inbound too.** There is **no** `socket`, `http.client`, `requests`,
   `httpx`, `aiohttp`, `ssl` or `dns` import anywhere in `src/aqelyn` — the only `urllib` uses are
   `urlsplit`/`parse_qsl` for string parsing (`dspm/models.py:8`, `secrets/models.py:10`).
   `pyproject.toml` declares **no web framework** (pydantic, pydantic-settings, uuid-utils, asyncpg,
   SQLAlchemy, alembic, redis). **A server is therefore a genuinely new dependency and a genuinely
   new risk surface** — the first port AQELYN ever listens on. ECR-0086 reserved *outbound* scanning
   to the owner; **an inbound listener deserves the same explicitness**, and the spec should say
   loopback-only unless the owner decides otherwise.

   **Status update (ECR-0088):** the inbound decision is now scoped and shipped. Outbound clients
   remain absent; the sole inbound listener lives under `aqelyn.surface`, binds `127.0.0.1`, and
   exposes reads only. Non-loopback remains owner-gated.
2. **"Local, operator-only" is a recorded design property**, not an accident of implementation. If
   the surface changes it, the ECR must say so in those words and record the owner's acceptance.
3. **Scale is a known open item.** `render_findings_report` builds the page with
   `"\n".join(_finding(item, index) for index, item in enumerate(analysis.findings))`
   (`reporting/html.py:16`) — **no pagination, no limit, every finding inlined**. The real corpus is
   **10,173 findings with 50,394 unknown factors disclosed** (`P-001_Task_Bundle.md:116`), and the
   in-page search/filter is client-side over the already-rendered DOM. **A live surface is the
   natural fix, and "make P-001 bigger" is not.**
4. **Auth does not exist.** No authentication, authorization, session or RBAC primitive ships. A
   multi-user surface invents all of it; a loopback operator surface can defer all of it. **The spec
   should choose deliberately and say which.**
5. **Do not weaken:** ECR-0034's inventory budget/`degraded` contract · ECR-0061 `sweep_unreported`
   exhaust-or-refuse · rule 33 (maintenance ≠ use) · **GC-004's persisted-field census** (a surface
   that persists anything joins it: 670 fields, 520 consumed, 149 exempt, 1 dormant, 0 unconsumed) ·
   GC-002 event-namespace closure · GC-003 registry coverage · EA-0002 D8 pagination under a budget ·
   EA-0004 integrity ≠ authenticity.

---

## 5. False friends

- **No prefix exists for a surface/portal/session/user.** `conventions/ids.py::PREFIXES` has **61**
  allocated; `svc` = `service` and `src` = `source` are **taken and mean something else**.
- **Event names:** shipped convention is dotted lowercase `aqelyn.<domain>.<verb>`
  (`aqelyn.kernel.runtime_started`, `aqelyn.object.created`, `aqelyn.relationship.created`), and
  **GC-002 closes the namespace.** A surface emitting events needs its prefix registered, not invented.
- **`Runtime` is a real dataclass** in `kernel/factory.py` with 28 `*_service` attributes; GC-003
  derives its expected registry from them. **Do not use "runtime" as a loose noun in FR text.**
- **EA-0062's endpoint list is not a starting point.** `/api/v1/archives`,
  `/api/v1/implementation/status`, `/api/v1/agents/codex/task` are build-portal routes. Reusing that
  shape would specify the wrong product.

---

## 6. What I recommend ECR-0088 decide

1. **Record the finding of §1** — the archive contains no product surface; EA-0059 is class 3,
   EA-0062 is real but is an engineering portal whose UI/API halves cite empty documents. Note
   EA-0059 as the **fourth** member of the class-3 family (ECR-0087 recorded three).
2. **Name the surface's purpose in one sentence**, and let it exclude things: *a way to see and drive
   the shipped engines* — **not** a build tracker, not a marketing site.
3. **Decide the shape, and the ECR should recommend one.** My recommendation, on the evidence:
   **(a) a loopback-only read API over `kernel.get_service()` + `health()`, plus a thin UI**, because
   `health()` already exists across 30 services, the domain reads are already narrow and
   tenant-scoped, and loopback keeps the "local, operator-only" property intact.
   **(b)** rendering live data through the existing report path is smaller but inherits the
   no-pagination limit. **(c)** a full multi-user web app invents auth, sessions and RBAC that no
   shipped code has — recommend against as a first step.
4. **Scope it to reads first.** Every write path (`ingest`, `raise_vulnerability`, `propose`,
   `decommission`) is an *action* with existing gating semantics; a read-only v1 avoids reopening
   any of them.
5. **State the listening-port decision explicitly** and reserve it to the owner if it is anything
   other than loopback.

**Do not** specify UI visuals from EA-0059 — there are none to specify from.

---

## 7. Ball

**Next: claude.ai authors ECR-0088** from this brief. Then Codex implements, and I review and merge.
**Reserved to the owner:** whether the surface may listen on anything other than loopback, on the
same footing as ECR-0086's outbound-socket decision.
