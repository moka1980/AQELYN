# S-003 U5 — Run, KEV Re-check, Density Report — Task Bundle

**Milestone:** S-003 U5 (assemble the milestone's actual output)
**For:** Codex (implementer) · Claude Code (reviewer + **the real-estate run**)
**Prerequisites:** U1–U4 merged (`main @588a3d1`); working tree clean; no open PRs.
**Data handling (ECR-0069):** **counts and classes only.** No service name, port, address or path appears in this bundle, in any test, in any fixture, or in the report itself.
**Definition of Done:** the join is **reported**, not merely computed; the baseline observations are **derived, not asserted**; the dependents count is **falsifiable**; the density report is structurally incapable of per-asset detail; both backends, both tenant modes, `python -O`; `mypy --strict src tests`; `gh pr checks` PASS; **real-estate run by the reviewer before merge**.

---

## 1. The KEV join is measured, and the bundle's hypothesis is falsified

| quantity | value |
|---|---|
| grype matches | **10,784** |
| distinct CVE ids on the estate | **2,319** |
| KEV catalogue size | 1,653 |
| **KEV ∩ estate** | **1** |
| join rate | **0.04%** |

The S-003 bundle predicted this might differ from S-002's near-disjoint finding
because the estate carries vendor-class products. **It does not differ.** S-002's
near-disjointness **holds on a real multi-service host**, not only on a container
image.

**And the prediction was wrong twice.** The single hit is **not** from the predicted
vendor-product class — it is a **vendored binary component**, not a declared or
tiered service. That is the same `binary`-classifier family that produced ECR-0071's
purl-less identity problem. *(Kept at class level here per ECR-0069; the class is the
finding, not the product.)*

**Say this plainly in the report. Do not soften it.** A hypothesis stated before a
run and then quietly restated afterwards is worth less than no hypothesis, and
S-002's lesson was precisely that writing it down first is what makes being wrong
visible.

## 2. Why **1** matters more than the 2,319 — and the general form

> **The single hit is the join's own positive control.**

Had the result been **0**, nothing would distinguish *"the join works and the estate
is genuinely clean of KEV entries"* from *"the join is broken."* Getting **1** proves
the mechanism functions, which makes the near-zero **a finding about the estate
rather than a defect in the code.**

**Put differently, and this is what the report must carry:** the single hit is the
only reason the other **2,318 non-matches are information** rather than absence of
evidence. A reader seeing *"1"* will read it as noise. **It is the opposite of
noise — it is the control that makes everything else interpretable.**

**And if a future run returns 0, that zero is trustworthy only because this one
returned 1.**

> **The general form, worth carrying beyond this join:** *a measurement that has only
> ever returned zero is not a measurement — it is a hypothesis.* A join, a filter, a
> counter, a query: until it has produced a non-zero, nothing distinguishes an empty
> result from a broken one. This is rule 24's shape (*a control that has never failed
> is untested*) applied to **measurements** rather than **guards**.

## 3. Reuse — U5 is mostly wiring

Nothing here needs inventing:

- **`check_cve_join(catalog, vulns)`** — the S-002 checker, whose docstring already
  carries the silent-zero warning. **Reuse it. Do not write a second join.**
- **`RunReport`** already carries every field U5 needs, including U4's
  `roadmap_dependencies`.
- **`density_report(report)`** is the count-only emitter.
- **All four factors already emit readings** — coverage (C-040), surface (U3),
  baseline (U4), mission (U2).

> **U5 aggregates. It must not add a fifth vocabulary.** Four factors reporting in
> four idioms would make the convergence in §6 unreadable, which is the one thing
> this unit exists to show.

## 4. The gap U4 left, and U5 is the caller

`assess_s003_baseline` **takes its C1–C5 observations from its caller** — it does not
derive them from the U1 documents. **U5 is that caller.**

So *"do not invent a baseline"* is enforced (owner-confirmed, tool accepts handles),
while ***"do not invent the observations" is not.*** Hand-coding them would reproduce
the declared-estate failure **inside the one unit whose purpose is to report
honestly.**

**Decision: derive, do not disclose.** The brief offers "derive mechanically **or**
state in the report that the caller asserted them." Disclosure is the weaker option
and it erodes — the entire S-track exists because author-supplied data can only
falsify what its author thought to withhold (rules 26/27/30). An asserted observation
makes the reviewer's judgement the platform's output.

**And the machinery already exists.** U4 shipped a resolution gate: attempt to
resolve the observed value; unresolved ⇒ `unknown` with a reason; `compare()` never
called. **U5's job is to feed that gate the U1 documents — not to bypass it with
pre-resolved values.**

> **Stronger form, worth considering rather than dismissing:** have
> `assess_s003_baseline` accept **the documents** rather than the observations. While
> it accepts observations, a caller *can* hand-code them, and *"remember to derive
> them"* is the class of rule this project has repeatedly found erodes. If that is
> judged too large for U5, deriving here plus a test that the values trace to the
> documents is the minimum — **record which was chosen.**

**Acceptance:** `test_u5_baseline_observations_derived_from_documents`,
`test_u5_unresolvable_claim_still_unknown_via_gate`.

## 5. The number the report publishes that nothing pins

`density_report` renders `dependents=<n>` from `PRIVILEGED_READ_DEPENDENTS`, and
U4's test asserts **the constant against itself** — so the published figure is
**unfalsifiable**. It is correct today, and **U5 is where it leaves the box.**

**Decision: derive it from the dependents themselves**, not from a literal pin.

A literal pin catches drift between **constant and test**. It does **not** catch
drift between **constant and reality**: if a fifth dependent appears and nobody
updates the constant, a literal pin stays green while the published number is wrong.

> **This is GC-001 §2.1's own principle** — *discovery, never declaration.* A
> hand-maintained count is a declaration; a count derived from the enumerated
> dependents is discovery, and a new dependent updates it on the day it lands.

**If derivation proves impractical**, GC-001's own fallback applies: pin the literal
**and** add a completeness scan asserting the enumerated dependents number exactly
that — never a bare pin.

**Acceptance:** `test_u5_dependents_derived_not_declared`,
`test_u5_adding_a_dependent_changes_the_count`.

---

## Z1 — Assemble the run

**Deliverable:** the full chain end to end, reusing `check_cve_join`, `RunReport` and
`density_report`. **The join must be *reported*, not merely computed** — a test
checking only `hits >= 0` would pass on a broken join.
**Acceptance:** `test_s003_kev_join_verified_and_reported`,
`test_s003_chain_end_to_end`.

## Z2 — Baseline observations from documents (§4)

**Deliverable:** U1 documents fed to U4's resolution gate; no pre-resolved
observations; the chosen form (§4) recorded.

## Z3 — Falsifiable dependents count (§5)

**Deliverable:** the published `dependents` figure derived from the enumerated
dependents, or pinned **plus** a completeness scan.

## Z4 — The report says what the numbers mean

**Deliverable:** the density report carries **§2's reasoning about the single hit**
and **§1's falsified hypothesis**, in counts-only form. Numbers without their
interpretation are how *"1"* gets read as noise and how a wrong prediction gets
quietly restated.

---

## The prediction, stated before the run

Per S-002's discipline, so that being wrong is visible:

> **Every factor will report mostly-unknown, and the reasons will converge on one
> decision.** `exposure`: 2 measured, 14 observed-but-unattributable. `baseline`:
> 1 evaluated, 4 unknown. `mission`: 7 of 26 declared. **KEV: 1 of 2,319.** The
> dominant closable cause across `exposure` and `baseline` is **the same privileged
> read** — so the report should name **one decision with four dependents**, not four
> separate gaps.

**If the assembled report does not converge that way, that is a finding about the
roadmap machinery** — report it, do not restate the prediction.

**And note what the convergence is:** it is the milestone's actual product. Four
factors, all mostly-unknown, with their reasons resolving to a single owner decision,
is the density report doing precisely what it was built for — **turning *"we don't
know"* into *"here is the one thing to decide."*** If it lands, S-003 has
demonstrated the platform's core loop end to end on data nobody authored.

## Proof

- **The join is reported**, not merely computed.
- **Positive control:** a fixture whose CVE set intersects KEV yields a non-zero
  join, and **mutating the lookup drives it to zero.** *That* is what makes a real
  zero trustworthy (§2).
- **Baseline observations trace to the U1 documents** (§4).
- **The dependents count changes when a dependent is added or removed** (§5).
- **The density report remains structurally incapable of per-asset detail** —
  mutate an attempt to pass a finding's identifying field into the emitter and
  confirm it **cannot** (ECR-0069).
- Both backends, both tenant modes, `python -O`.
- **Real-estate run: the reviewer's.** Codex has no host access and the private
  documents do not leave the estate. Count-only report attached; §6's prediction
  confirmed **either way**.

## Review protocol (Claude Code)

1. **The join is reported and its positive control fails on mutation** — check
   first; a silent zero is indistinguishable from a correct implementation finding
   nothing.
2. **Baseline observations are derived, not asserted** (§4). This is the gap that
   would reproduce the declared-estate failure inside the honesty unit.
3. **The dependents count is falsifiable** (§5) — adding a dependent must change it.
4. **No fifth vocabulary** — four factors, four existing idioms.
5. **The report carries its own interpretation** — the single hit explained, the
   hypothesis recorded as falsified.
6. **ECR-0069 structural**, mutation-verified.
7. `mypy --strict src tests`; both backends; both tenant modes; `python -O`;
   `gh pr checks` PASS.

## Carried forward

**Still owed by me:** **ECR-0074** for U2's two residuals — undeclared assets scoring
`0.000` rather than unknown, and *"decided not to declare"* recorded as *"not
declared"* — leading with *"why did GC-001 AC-3 not catch this?"* rather than with
the defect. Independent of U5; say when you want it.

**Still open:** the **privileged-read decision** (four dependents, the owner's, and
U5 makes it visible either way); U4's reason↔cause-class validator, reachable but
unexercised; the collector's absent memory bound; the two U1 doc-versus-code drift
pins; C-040's vacuous `scanned -= unassessable_inventory` assertion.
