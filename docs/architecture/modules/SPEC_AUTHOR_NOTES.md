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

## Part 2 - Current handover: the EA-0052 - EA-0063 batch (proposed ECR-0086)

**From:** Claude Code (reviewer; the only actor that reads shipped code)
**To:** claude.ai (spec author)
**Date:** 2026-08-01
**Verified against:** `main @0152432`, working tree clean, **no open PRs**

Everything below was run against shipped `src/` at that SHA. Where I give a count or a
file:line, I ran it. Nothing here is inferred from titles.

---

## 0. State

- **`main @0152432`**, clean, no open PRs.
- **Shipped since the last brief:** PR #281 (GC-004 persisted-field consumer guard),
  PR #282 (inventory coverage page-budget control), PR #283 (retroactive re-review closure —
  C-034/C-035/C-038 controls).
- **Next free ECR: `0086`.** Read from `ECR-LOG.md` at `0152432`; highest allocated is
  **ECR-0085**. **Rule 1 discharged — but re-check before merging.**
- **Next free GC: `005`** (GC-001…GC-004 exist).
- **SPEC_AUTHOR_NOTES rules 1–33 are current.** Rule 33 = *a test that a field holds the right
  value proves maintenance, not use.*
- The retroactive self-verification debt (`SELF_VERIFICATION_DISCLOSURES.md`) is **fully closed**,
  including the judgment half. No milestone is queued with Codex.

---

## 1. The headline — **the archive is NOT exhausted, and the record says it is**

ECR-0060 recorded:

> **Archive status: exhausted as a requirements source.** With EA-0036 – EA-0050 resolved,
> the remaining backlog is the tracked follow-ups plus whatever is chosen deliberately.

**That claim is false.** `archive/` contains **EA-0001 … EA-0063**. Its own index says so on
line 1 of `archive/EA_MASTER_INDEX.md`:

> This index covers EA-0001 through EA-0063 after final AQELYN rebranding and normalization.

EA-0050 and EA-0051 were classified non-capability by ECR-0060. That leaves
**EA-0052 … EA-0063 — twelve masters that have never been assessed at all.**

### 1.1 A second recorded claim is also false, and this one is load-bearing

Two ECR number allocations discharge rule 20 with this premise (`ECR-LOG.md`, the ECR-0071 and
one later allocation):

> **Number:** verified free; rule 20 checked (**archive stops at EA-0051**).

The archive does not stop at EA-0051; it stops at EA-0063. **Both conclusions still happen to
hold** — they were checking for an `EA-0071`, and 0063 < 0071 — **but they hold by luck, not by
the check.** The premise gives the *wrong* answer anywhere in the **0052–0063 band**, and
ECR-0052 … ECR-0063 are all already allocated.

This is the same family as the `>= 30` registry floor I found in C-038: **a bound that was true
on the day it was written and does not track what it measures.** Worth correcting in the same
ECR, because the next person to run a rule-20 check will reuse the sentence, not re-derive it.

---

## 2. The twelve, mapped

Per-item capability map — the step ECR-0060 proved you cannot skip, because it is the step that
found EA-0048.

### Finding A — same-generator templates, but a **different generator** from EA-0038–0050

| family | lines | heading shape |
|---|---|---|
| EA-0038 … EA-0050 (assessed by ECR-0060) | 424 | 40 × `## Section NNN` |
| **EA-0052 … EA-0057 (unassessed)** | **485 each** | 30 × `# Section NNN`, each with `## Engineering Notes` + `## Acceptance Implications` |

Normalising identifiers and capability names, **EA-0052 vs EA-0055 differ in 54 lines total**,
and those 54 lines are: **five FR one-liners**, ten event names mechanically derived from the
engine name, and an API verb table with the name substituted.

> **The five FRs are the only module-specific text in each master.** Treat these as stubs of the
> same class as EA-0038–0050 — a *different* template, the *same* problem.

### Finding B — the twelve carry **three** dispositions, not one

**Disposition A — already shipped (3).** Verified by importing the package at `0152432`:

| archive master | shipped owner | evidence |
|---|---|---|
| EA-0055 Attack Surface Discovery | `src/aqelyn/exposure/` — EA-0023 | docstring *"Threat Exposure & Attack Surface Management Engine (EA-0023)"*; exports `ExposureManagementService`, `KnownDataExposureEngine`; id prefix **`asa` = `attack_surface_asset` already allocated** |
| EA-0056 Vulnerability Intelligence | `src/aqelyn/vuln/` — EA-0024 | docstring *"Vulnerability Intelligence & Prioritization Engine (EA-0024)"*; **the master's proposed engine name IS the shipped class** — `VulnerabilityIntelligenceEngine`, **14 occurrences** in `src/` |
| EA-0057 Asset Discovery & Inventory | `src/aqelyn/inventory/` — EA-0025 | docstring *"Cyber Asset Discovery & Inventory Intelligence package (EA-0025)"*; prefix `ast` = `asset_record` |

**Disposition B — genuine capability gaps (3): EA-0052, EA-0053, EA-0054.**

| master | capability | absence verified how |
|---|---|---|
| EA-0052 Endpoint Intelligence | endpoint telemetry inventory; process/service/software/browser/firewall visibility; cross-platform agent | no `endpoint` package; `grep -rlE "process_list\|running_process\|agent_enrolment\|endpoint_telemetry" src/` ⇒ **0 files** |
| EA-0053 Endpoint Security Assessment | endpoint posture scoring, misconfiguration detection, remediation instructions | no owner; depends entirely on EA-0052's absent telemetry |
| EA-0054 Web Intelligence | website/domain scanning; TLS, DNS, HTTP headers, CSP, HSTS, SPF, DKIM, DMARC, redirects | no `web` package; `grep -rlicE "\b(hsts\|dkim\|dmarc\|csp header\|tls handshake)\b" src/` ⇒ **0 files** |

> **This is three times the EA-0048 result** — and unlike EA-0048, **the roadmap schedules them.**
> `docs/AQELYN_Updated_Implementation_Roadmap.md`: *C-005 Endpoint Platform: Endpoint Intelligence
> (EA-0052) followed by Endpoint Security Assessment (EA-0053)*; *C-006 Exposure Platform: Web
> Intelligence (EA-0054), Attack Surface Discovery (EA-0055), Vulnerability Intelligence (EA-0056).*
> **Two of C-006's three are already shipped under different EA numbers.** The roadmap's coding
> order was written against archive numbers that the platform has since realised under EA-0023/24/25.

**Disposition C — non-capability (6): EA-0058 … EA-0063.** Same family as EA-0050/EA-0051.

`EA-0058 Development & Coding Standards` · `EA-0059 AQELYN Design System` ·
`EA-0060 AI Engineering & Prompt Handbook` · `EA-0061 Developer Handbook & Implementation Guide` ·
`EA-0062 Engineering Portal & Mission Control` · `EA-0063 Final Readiness and Market Leadership
Blueprint`.

⚠️ **"Non-capability" must not collapse into "ignore."** EA-0058, EA-0060 and EA-0061 are
**normative standards documents** (703 lines each for 0058/0060 — real content, not the 485-line
stub shape). They plausibly contain coding and AI-engineering standards this platform is supposed
to conform to. EA-0063 does carry FRs, but they are *process* FRs (*"architecture baseline
freeze"*, *"brand normalization to aqelyn"*), not platform capabilities.
**Recommendation: classify all six non-capability for BUILD purposes, and record EA-0058 /
EA-0060 / EA-0061 as owing a separate conformance read.** Do not let one word close three
documents nobody has opened.

**Status update (ECR-0087, 2026-08-02): CLOSED.** The read found a third generator template,
not standards. The 703-line count measured the generator rather than normative content.

---

## 3. The boundary the three gaps would cross — **the most important item here**

**All three Disposition-B gaps are active scanners. The shipped platform opens no socket.**

Verified at `0152432`: the only `urllib` imports in `src/aqelyn` are `urlsplit` / `parse_qsl` in
`dspm/models.py:8` and `secrets/models.py:10` — **string parsing**. There is no `socket`,
`http.client`, `requests`, `httpx`, `aiohttp`, `ssl` or `dns` client anywhere in `src/`.

The boundary is recorded and called safety-critical (IS-037 analysis in `ECR-LOG.md`):

> Active scanning remains an **EA-0008-gated connector action**; this analytical turn **opens no
> socket and holds no credential.**

…and the C-032 bundle records the same shape as *"the EA-0031/EA-0034 trap — handed-in
descriptors only"*. The roadmap's own Safety Requirements section:

> All endpoint, web and attack surface functions must enforce explicit scope. No unauthorized
> scanning, credential extraction, exploit execution, destructive checks or personal-content
> collection is permitted.

⇒ **EA-0052/0053/0054 would be the first modules to make AQELYN touch a customer system
directly.** Every capability shipped so far assesses descriptors the customer hands in.

**Whether to schedule them is the owner's decision, not the spec author's and not mine.**
ECR-0060 set the precedent for exactly this situation with EA-0048: *"an open capability gap,
**not scheduled**."* ECR-0086 should record the disposition and **surface** the scheduling
question — it must not presume either answer.

---

## 4. False friends — names already taken

**Id prefixes** (`conventions/ids.py::PREFIXES`, **61 allocated**):

- **`tlm` = `telemetry_record`** — EA-0052's FR-001 is *"endpoint telemetry inventory"*. The
  obvious prefix is **already taken.**
- `asa` = `attack_surface_asset` · `ast` = `asset_record` · `vln`/`vas`/`vpr` (vulnerability) ·
  `sct` = `secret_asset` · `x509`, `cky` (certs/keys) · `svc`, `src`, `evd`, `evt`.
- **No prefix exists for endpoint or web.** A Disposition-B module would need new ones.

**ECR-0015 event/type restatement check, run by me at `0152432`** (claude.ai cannot grep the repo):

```
EndpointIntelligenceEngine          : 0
EndpointSecurityAssessmentEngine    : 0
WebIntelligenceEngine               : 0
AttackSurfaceDiscoveryEngine        : 0
AssetDiscoveryInventoryEngine       : 0
VulnerabilityIntelligenceEngine     : 14   <-- the SHIPPED EA-0024 class. Do not restate it.
```

**Rule 20 has a live case here — an IS-number collision.**
`archive/EA-0052/EA-0052_Master.md` declares **"Implementation Specification: IS-035"**.
**IS-035 is already assessed and closed**: `docs/architecture/modules/IS-035_Conformance_Analysis.md`
subject is *"Secrets, Keys & Certificate Lifecycle Governance Engine"*, realized by **EA-0032**
under **ECR-0054**. Same number, incompatible artifact — exactly the pattern already recorded as
*"037 identifies three incompatible artifacts."*
EA-0055 declares IS-038 and EA-0057 declares IS-040, from the same declared series.
**Verify each against its source family and title; do not assume they map to the IS-0xx
conformance analyses already on file.**

**Event naming — do not carry the masters' names literally.** They propose PascalCase:
`EndpointIntelligenceEngineDiscovered`, `…Updated`, `…Assessed`, ten per master. The shipped
convention is **dotted lowercase `aqelyn.<domain>.<verb>`** — `aqelyn.object.created`,
`aqelyn.kernel.runtime_started`, `aqelyn.relationship.created` — and **GC-002 closes the event
namespace**. The masters' event block is generator output, not a contract.

---

## 5. Carry-forward — what ECR-0086 must not weaken

Cumulative list, unchanged and still binding: tri-state status audit · columnar-vs-jsonb
persistence · tenant-scoped health probes exercised in **both** tenant modes · **EA-0002 D8
pagination under a work budget** · `propose(..., source_finding=)` mandatory · **EA-0004 integrity
≠ authenticity** · **ECR-0034's inventory cap / budget-refusal** · **rule 33** (maintenance ≠ use)
· **GC-004's persisted-field census** (670 fields: 520 consumed, 149 exempt, 1 dormant, 0
unconsumed — a new module's persisted fields join this census and must be consumed or reasoned).

### 5.1 **New, and it applies directly to this decision**

PR #283 closed the EA-0048 absence guard. The lesson generalises to every Disposition-B row:

> **A control that certifies an ABSENCE is only as good as its detection net, and a "cleaner"
> net can be a smaller one.** The first fix replaced the EA-0048 keyword net with a
> docstring-declaration check; it passed CI, `mypy --strict` and ruff, and it had **lost** the
> ability to detect the very probe that proved the old net live. Only a mutation found it.

The shipped EA-0048 net now has **three branches, each with a unique witness test**: exact
`EA-0048` declaration discovery · the raw keyword net (uniquely witnessed by a string-literal
case) · token-normalised identifier matching (uniquely witnessed by a CamelCase case).

🔴 **Consequence for ECR-0086: the existing net does NOT cover the new gaps.**
`EA0048_OWNERSHIP_TERMS` is AI vocabulary only — `model_governance`, `ai_security`, `model_card`,
`model_risk`, `model_inventory`, `model_bias`, `prompt_injection`, `training_data`, `ml_model`,
`ai_system`. **Nothing in it would notice an endpoint or web module arriving.**
**If ECR-0086 records EA-0052/0053/0054 as open gaps, each needs its own absence guard built to
the same three-branch standard** — otherwise the batch certifies three absences with no control
behind them, which is the EA-0048 defect reintroduced at triple scale.

Also carry forward the honest limit already named on the EA-0048 net: it catches
**anticipated-or-conventional vocabulary, or an explicit declaration** — not *any* capability. A
determined novel vocabulary evades it. State the guarantee that way; don't overclaim it.

---

## 6. What I recommend ECR-0086 record

1. **Correct ECR-0060's "archive exhausted" status.** The archive runs to EA-0063; twelve masters
   were unassessed. Correcting a superseded status line is the point of the log.
2. **Correct the "archive stops at EA-0051" rule-20 premise**, noting both prior conclusions
   survive but were not established by the check.
3. **One batch decision, three dispositions** — the ECR-0060 shape, which is proven:
   - **A (conformant via shipped owners):** EA-0055 → EA-0023, EA-0056 → EA-0024, EA-0057 → EA-0025.
   - **B (open capability gaps):** EA-0052, EA-0053, EA-0054 — **disposition recorded, scheduling
     reserved to the owner.**
   - **C (non-capability):** EA-0058 … EA-0063. The EA-0058/0060/0061 standards-conformance read
     is **discharged by ECR-0087**: all three are generator-template class 3 with no topic-specific
     normative content.
4. **Absence guards for the three new Disposition-B rows**, built to the three-branch standard,
   each branch with a unique witness. This is the test-side deliverable of the ECR.
5. **Record the no-socket boundary explicitly** as the thing EA-0052/0053/0054 would cross, with
   the evidence in §3, so the scheduling decision is made with it in view rather than discovered
   during implementation.

**Do not** write module specs for EA-0052/0053/0054 in this pass. The batch decision is required
first either way, and it is required before any scheduling question can be answered.

---

## 7. Ball

**Next: claude.ai authors ECR-0086** (the EA-0051 … EA-0063 batch conformance analysis) from this
brief. Then Codex implements, and I review and merge.

**Reserved to the owner, and only the owner:** whether the three genuine gaps
(EA-0052 Endpoint Intelligence, EA-0053 Endpoint Security Assessment, EA-0054 Web Intelligence)
get scheduled at all, given that building any of them opens AQELYN's first socket.
