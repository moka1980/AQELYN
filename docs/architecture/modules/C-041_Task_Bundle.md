# C-041 — ECR-0076: Absence Is the Fold's Identity — Task Bundle

**Milestone:** C-041 (implement ECR-0076's cross-cutting repair)
**For:** Codex (implementer) · Claude Code (reviewer + merge)
**Prerequisites:** ECR-0074, ECR-0075, ECR-0076 merged (`main @87ece71`); **ECR-0076 read in full**, §1 and §2 especially; `SPEC_AUTHOR_NOTES.md` rules 1–32.
**ECR:** none by default. One is required only if A4 finds a site the guarantee cannot reach and the remedy exceeds a stopgap (§A4).
**Definition of Done:** the **enumeration is delivered before any fix**; every site has a recorded disposition **with its reason**; each repaired site's reversion turns a guard **red**; both backends, both tenant modes, `python -O`; `mypy --strict src tests`; `gh pr checks` PASS.

---

## The governing sentence

> **The named sites are evidence of the class, not the scope.**

`secrets/scoring.py`, `risk/engine.py`, `exposure/engine.py` and
`soc/correlate.py:_mission_context` are the four the audit found. **Repairing exactly
those four would be rule 29 committed inside the repair for a class** — the error
ECR-0074 was raised to correct.

**And the fourth site is the proof of that.** `soc/correlate.py` is a **correlation**
path, not a scorer. An enumeration scoped to *"scorers"* would have missed it. **The
class is folds over optional contributors, wherever they occur.**

---

## A1 — The enumeration, **delivered before any fix**

**This is the first deliverable and it is a table, not a change.**

The precedent is ECR-0066's factor audit, which was required to cover all seven rather
than the three the density report surfaced — and **found a fourth (`epss`) that the
instrument could not have revealed.** The same structure applies: the enumeration will
likely find sites the audit table did not, and that is the point of doing it
separately.

**Two passes, because they find different things:**

1. **Byte-identity** — cheap, finds the copies. `secrets/scoring.py` is byte-identical
   to the pre-fix ISPM function; a copied function propagates, so more copies are
   likely.
2. **Structural** — a copy that has since **drifted matches neither name nor body**.
   Enumerate by shape: *a fold over optional contributors that returns a bare value on
   the empty case.* **Type system, not grep** (rule 22).

### The output shape — record the mechanism, not the verdict

Per site:

| column | why |
|---|---|
| **fold operator** | `max`, `sum`, `any`, … |
| **identity element** | the value absence actually contributes |
| **is that identity favourable here?** | the mechanism, made checkable rather than asserted |
| **absence class** (A2) | decides the fix |
| **disposition** | fixed / not affected **+ reason** |

**A "not affected" verdict without its reason is not an audit result.** There are
three reasons and **only one of them is stable:**

| reason | stability |
|---|---|
| **no fold over optional contributors** | **structural** — cannot regress |
| **fold exists, identity is not favourable in this context** | **context-dependent** — a change of sign or direction reopens it |
| **fold exists, identity favourable, but absence cannot occur** | **fragile** — safe *because of an invariant elsewhere* |

**The third must record which invariant it depends on.** It is safe by something
else's behaviour, and if that behaviour changes this becomes a defect **silently** —
ECR-0068's decay shape, one layer down.

**Acceptance:** the enumeration is committed as a document with a per-site row; no
production change lands in the same commit.

## A2 — Classify the absence at each site

ECR-0076 §5: ***not supplied*** and ***supplied as not-applicable*** look identical at
the fold and are different states.

| class | fix |
|---|---|
| **not supplied** | `unknown`, **excluded from the denominator** (ECR-0040) |
| **supplied as not-applicable** | a **declared** value — not an absence, and must not become one |

**Determine which actually occurs per site before choosing the fix.** Treating a
declared not-applicable as unknown is the inverse error, and U4 already priced what
that costs in roadmap noise.

Where genuinely unclear: **record it as unknown and say so.** An honest wrong-cause is
better than an invented right one, and it stays visible.

## A3 — The repair, **`secrets` first**

**Why first:** a **credential** scorer producing a favourable number for an input it
could not assess means an **unassessable credential presents as well-governed** —
precisely what **ECR-0054 §3.1a** was written to prevent (*"a score must not average
away a known exposure"*), arriving through a different door. It is simultaneously the
highest-consequence site and the cheapest, since it is **the same function** and
ECR-0074's remedy applies unchanged.

**The `secrets` assertion is domain-specific, not generic.** *"Unknown is not
favourable"* is necessary but insufficient here — the test must show that **an
unassessable credential does not appear in the well-governed bucket.**

**Then the remainder**, in enumeration order.

**Acceptance:** per site, the **real composition** driven with a missing contributor
yields `unknown`, excluded from the denominator — **not a spy** (the ECR-0040 method,
and the method that verified ECR-0074). Plus
`test_secrets_unassessable_not_well_governed`.

## A4 — Verify the guarantee reaches each repaired site

**ECR-0075's discovery is half the work; this is the other half.**

**Per site: revert the fix and confirm a guard turns red.**

**A green reversion is not a note — it is a fork:**

| outcome | what it means | required |
|---|---|---|
| guard turns **red** | the site is covered | done |
| guard stays **green** | **the site is unguarded** — the fix can regress silently | **one of the two below** |

1. **Extend ECR-0075's discovery to reach it** — preferred, and if the extension is
   substantial it warrants its own ECR rather than being folded here.
2. **Add a local guard as an explicit stopgap** — acceptable, **but recorded as a
   stopgap with the reason**, because a locally-guarded site is exactly the
   decentralised state GC-001 was built to end.

**Doing neither leaves a fixed-but-unguarded site**, which is worse than an unfixed
one: it looks closed.

**Acceptance:** per site, a mutation record showing red — or a recorded disposition
under 1 or 2.

## A5 — Record the score change

**Every repaired site changes shipped scores.** An asset, credential or finding with a
missing contributor previously scored at the identity — the favourable end — and will
now score **worse**, because the contributor is excluded and coverage adjusts down.

**This is the ECR-0040 situation across four-plus modules rather than one factor**: a
**correction surfacing a pre-existing wrong answer, not a regression.**

**There are no deployments, so this is a record rather than a communication.** Put it
in the PR and the ECR so the **first** deployment inherits it, and so nobody reading
the diff later concludes scores drifted.

---

## Proof

- **The enumeration exists as its own deliverable**, both passes, with per-site reason.
- **Per site: the real composition** driven with a missing contributor → `unknown`,
  excluded from the denominator. Not a spy.
- **`secrets`:** an unassessable credential does **not** present as well-governed.
- **Per site: mutation** → guard red, or a recorded A4 disposition.
- **A2 classification recorded per site.**
- Both backends, both tenant modes, `python -O`.

## Review protocol (Claude Code)

1. **The enumeration landed before the fixes** — check the commit order. A repair
   commit that also contains the audit has skipped the step that finds the sites
   nobody named.
2. **Every "not affected" carries its reason**, and every *fragile* one names the
   invariant it depends on.
3. **`secrets` asserts the domain claim**, not merely the generic one.
4. **Every repaired site's reversion turns a guard red** — or has an A4 disposition.
   **A fixed site with no guard is worse than an unfixed one.**
5. **Absence class determined, not assumed** (A2).
6. **The score change is recorded.**
7. `mypy --strict src tests`; both backends; both tenant modes; `python -O`;
   `gh pr checks` PASS.

## Carried forward

**Owner's, neither blocking:** the **19 declined units** (ECR-0074 §4 — *deliberately
unweighted*, *deferred*, or *inherited* produce three different rows), and the
**privileged read with four dependents**, which S-003 now surfaces in the instrument.

**Open, unscheduled:** EA-0048; `FIRST_DEPLOYMENT_ITEMS.md`; U4's reason↔cause-class
validator, reachable but unexercised; the collector's absent memory bound; the two U1
doc-versus-code drift pins; C-040's vacuous `scanned -= unassessable_inventory`
assertion.
