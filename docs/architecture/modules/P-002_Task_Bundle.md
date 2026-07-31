# P-002 — Annotate Escalation (ECR-0084 shape 1) — Task Bundle

**Track:** P (product)
**Milestone:** P-002 — `current_severity_score` gains **exactly one consumer**
**For:** Codex (implementer) · Claude Code (reviewer + merge)
**Prerequisites:** P-001 merged; **ECR-0084 read**, and the shape-(1) brief read in full — §2.1 and §2.2 especially, because both change what the FR text can say.
**No new ECR.** ECR-0084 moves `Proposed` → **`Accepted (shape 1)`**, recording **who chose and when: the owner, 2026-07-30**, after the §6 costing table. Both the index row and the body.
**Line references** below are the reviewer's at `main @278bfdd`. **They expire** — a dead index name shipped from stale notes two rounds ago is a recorded lesson. **Re-derive before editing.**

---

## The decision

**Shape (1), annotate only.** Not (1b) the escalation filter, not (2) a second ordering, not
(3) re-emission-raises-a-new-finding.

> **`current_severity_score` gains one consumer — the P-001 renderer — and nothing else
> changes.** No index, no cursor, no ordering contract, no query predicate.

---

## R1 — The annotation *(revised — supersedes the original R1)*

**Seam:** `reporting/html.py:141` — `_finding(item, index)` already holds
`finding = item.finding` (`:142`), so **both scores are in scope with no signature change and
no new plumbing.** `ReportFinding` needs no new field. Card region `:222-240`; score block
`:235-239`; natural placement inside `finding-lead`, adjacent to the number it qualifies.

**Renderer-only.** If a field is added to `ReportFinding`, or a query to `analyze.py`, **that
is shape (1) drifting into (1b) — stop and raise.**

### 1.1 The data flow, corrected

`vuln/engine.py:511-512` computes `priority.score` **first** and derives the finding's
`severity_score` **from it** (`round(priority.score / 100.0, 6)`).

> **The rank and the first-seen severity are the same measurement at two scales.**

The original R1 carried *"the rank is computed from the first-seen severity"*, which
**inverts the data flow**. It was flagged as a claim about shipped code rather than asserted,
and verification is what caught it. **The form survived; the claim did not** — and separating
them is what made the correction cheap.

On re-emission `current_severity_score` takes the new emission's value
(`findings/memory.py:86-87`); the rank and `severity_score` both stay at their first-raise
values.

### 1.2 Render **one** added number, not a pair

**The headline already *is* "first seen"** — same value, same first raise, at 0–100 scale.
A labelled pair would **re-derive a number already on the card.**

> **Render the current severity, rescaled, beside the disclosure. Nothing else.**

| | pair | single |
|---|---|---|
| numbers on the card | 3 | **2** |
| derivations of the first-raise value | 2 | **1** |
| reconciliation required | yes, by test | **none — satisfied by construction** |

**The reconciliation requirement the original R1 imposed was self-inflicted.** ECR-0083
§6.6 applied *because* R1 specified a second derivation of a value already on screen.
**Removing the derivation removes the requirement rather than satisfying it** — and **a
constraint satisfied by construction beats one satisfied by a test**, because a test can be
deleted and a construction cannot. That is ECR-0069's structural discipline applied to a
rendering decision.

**The trade, stated rather than hidden:** a pair shows the movement in one glance; a single
number requires the reader to compare it against the headline. **The headline is adjacent and
labelled `of 100`, and the disclosure sentence names the relationship explicitly**, so the
cost is small — but it is not zero, and it is the reason the sentence is mandatory rather than
helpful.

### 1.3 Scale — `× 100`, one decimal

Both severity fields are on **0–1**. The card headline is on **0–100** (`html.py:236-237`
renders the total above the literal `of 100`; `:219` clamps the bar to 100).

**Render the added number on the card's scale, one decimal. A reader must not hold two scales
at once.**

**Decision attribution:** selected by **the reviewer, 2026-07-31**; **the owner may overrule**.

**The annotation renders only when the two values differ at display precision.** Compare the
formatted one-decimal strings, not the underlying floats. A finer comparison would make a
claim below the resolution the card renders: the sentence would assert a change while the
reader sees the same number twice.

**Never assert string equality between two re-derived numbers.** They would reach the screen
by different rounding paths — `round(x/100, 6)` then `× 100`, versus the headline's
`Decimal(f"{x:.1f}")` (`html.py:376`) — which agree at one decimal for every realistic value
but **not provably for all**. A test asserting equality would assert something the code does
not guarantee. **Under 1.2 the question does not arise**, and that is the point.

### 1.4 The disclosure sentence

**Required form** — it must state **identity**, not derivation:

> *This priority is the severity recorded when the finding was first raised. Its current
> severity is **88.0**, which does not change the priority or its position in this list.*

**Requirements on the wording:**

- **Name both things the escalated value does not move** — the **score** *and* the
  **ordering**. `analyze.py:217-224` orders on `priority.score`, KEV-exploited first, so
  ordering is a **separate claim** from the number.
- **Do not say "computed from."** The data flow runs the other way (1.1).
- **Do not imply a recomputation is pending.** Under shape (1) there is none, **by choice**.

### 1.5 The disclosure is *more* load-bearing after the collapse, not less

**A single added number is more naked than a pair, not less.** *"first seen 30.0 / now 88.0"*
at least implies a progression a reader can partly infer. **`88.0` beside a headline of
`30.0` states two facts and no relationship** — so the sentence carries the entire
interpretation.

> **A bare number fails review.** Without the sentence the annotation *creates* the *"the rank
> moved"* misreading rather than failing to prevent one — **worse than no annotation**,
> because before P-002 no wrong conclusion was available to the reader at all.

**Acceptance:** `test_p002_divergent_renders_current_and_disclosure`,
`test_p002_equal_renders_neither`,
`test_p002_sub_display_precision_difference_renders_neither`.

## R2 — Record the dormancy, in three places

`current_severity_score == severity_score` **on every row P-001 has ever rendered**, and will
stay so until a store persists across runs: `analyze.py:192-196` builds a **fresh
`InMemoryFindingStore` per run**, `memory.py:108-109` seeds the two equal on creation, and
`memory.py:86-87` — the only divergence point — runs on **re-emission**, which a per-run store
never reaches.

**The branch will be correct, test-reachable, and unreachable through `aqelyn-report`.**

**This is not a reason to refuse the work** — the owner chose shape (1) with that framing in
front of them, and it is what gives the field its first consumer. **But it must be recorded in
three places, and the third is the one that gets forgotten:**

| where | why |
|---|---|
| **the ECR-0084 entry** | so the status reads *accepted and dormant*, not *accepted and working* |
| **a comment at the branch** | so nobody deletes it as dead code |
| **the test** | ← **the one that gets forgotten** |

**Why the test.** A green consumption test is the artifact that will most look like proof of
consumption. **It proves the renderer *would* render an escalation, not that anything ever
*has*.** Without a line saying so, the next reader takes the passing test as evidence the
feature is live.

### And a limit on ECR-0084's own proposed rule, found by applying it

ECR-0084 proposed: *a test that a field holds the right value proves maintenance, not use*,
with the mechanical form `grep -rn current_severity_score src/ | grep -v findings/`.

> **After P-002 that check returns a hit in `reporting/` — and the field still has never been
> read in any run.**

**The check answers *"is there a reader in the code?"* It does not answer *"has anything ever
been read?"*** Those diverge exactly when a consumer is dormant, which is this case.

**Record it as a refinement, not a repeal** — the rule caught this defect and remains right.
It simply needs its second clause: **a consumer that cannot be reached by any shipped path is
a consumer for the checker and not for the user.** Worth carrying into the GC candidate, which
would otherwise certify P-002 as closing the gap.

**Acceptance:** the dormancy statement present in all three locations.

## R3 — Invariants: confirm, do not restate

These are **ECR-0084 §8, still binding**. Shape (1) goes near none of them — **confirm that,
rather than re-specifying them as new work.**

1. **`severity_score` stays write-once** — `postgres.py:206-215` excludes it from the UPDATE
   *by design*, because the ECR-0062 cursor keys on it.
2. **No second sort key, mutable or otherwise.** Ordering by the escalated value is **shape
   (2), not chosen**, and measured expensive: the shipped ECR-0062 keyset lands in `Filter`,
   not `Index Cond` (28,500 rows / 29,366 buffers / 18.2 ms versus 0 / 6 / 0.156 ms), so a
   second cursor on a **mutable** key would have to be **redesigned, not copied**.
3. **No duplicate first-seen derivation.** ECR-0083 §6.6's reconciliation obligation is
   **removed here, not satisfied by a test**: R1 keeps the existing headline and only rescales
   `current_severity_score` for display.

## R4 — The test must prove **consumption**, and the obvious test is the forbidden one

`tests/conformance/test_finding_cursor_contract.py` already asserts the column holds the right
number. **That test is the reason this defect shipped with green CI.** Do not add another of
its kind.

**Assert on rendered output, not on the model — and scope both assertions to the escalation
annotation element.** The headline renders on every card, so card-wide number matching cannot
distinguish the branch:

- divergent values → the annotation element exists and contains the **current severity
  rescaled to 0–100 at one decimal**, plus the disclosure sentence;
- equal values → the annotation element and disclosure sentence are both absent; the existing
  headline is outside the assertion and remains unchanged;
- values that differ as floats but format to the same one-decimal string → the annotation
  element and disclosure sentence are both absent.

**Mutation-verify, and run all three** (rules 21, 24, 31 — rule 24 is explicit that a control
never run against a broken implementation is an untested test):

| mutation | expected |
|---|---|
| delete the annotation branch | **red** |
| render unconditionally | the **equal-values** case goes **red** |
| suppress with `math.isclose(current, first_seen)` instead of comparing rendered strings | the **sub-display-precision** case goes **red** |

**Fixture warning (rules 27, 32).** The divergent state **cannot arise from the P-001 path**
(R2), so the fixture must construct it. **A synthesized fixture can manufacture a defect as
readily as hide one** — so it must go through `InMemoryFindingStore`'s **real re-emission
path** (`memory.py:86-87`), **not by setting the attribute by hand.** A hand-set attribute
proves the renderer reads a field; only the real path proves it reads *the value escalation
actually produces*.

---

## Non-goals — carried explicitly so the implementer cannot drift

| not in scope | why |
|---|---|
| **(1b) an escalation filter** | a query predicate; wants an index and inherits the mutable-predicate phase-change recorded for `status` |
| **(2) a second ordering** | **ranking is a claim about priority, and two rankings is no ranking**; measured expensive; not chosen |
| **(3) re-emission raises a new finding** | changes dedup semantics EA-0003 chose deliberately |
| **the GC candidate** (enumerate persisted fields, assert an external consumer) | **stays raised, not folded in** |
| **the standing rule becoming rule 33** | remains an ECR candidate **until the owner says otherwise** |

## Review protocol (Claude Code)

1. **Renderer-only.** No change to `analyze.py`, no new `ReportFinding` field. Either is drift
   into (1b).
2. **The disclosure sentence is present and accurate** — and its claim about how the rank
   relates to severity was **verified against shipped code**, not carried from the brief.
3. **A bare current-severity number fails review.** Without the mandatory disclosure the
   annotation **creates** the misreading; after the collapse, the sentence carries the entire
   relationship between the headline and the added number.
4. **No delta rendered.**
5. **Dormancy recorded in all three places**, including the test.
6. **Both mutations run**, not merely specified.
7. **The fixture goes through the real re-emission path**, not a hand-set attribute.
8. **The ECR-0084 status transition** names **who chose and when** — owner, 2026-07-30 — in
   the row **and** the body.
9. **The scale contract is under test:** the annotation element renders
   `current_severity_score × 100` at one decimal, while equal and display-equal values suppress
   the element.
10. `mypy --strict src tests`; `gh pr checks` PASS.
