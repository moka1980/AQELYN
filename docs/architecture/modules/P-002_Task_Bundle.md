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

## R1 — The annotation

**Seam:** `reporting/html.py:141` — `_finding(item, index)` already holds
`finding = item.finding` (`:142`), so **both scores are in scope with no signature change and
no new plumbing.** `ReportFinding` needs no new field. Card region `:222-240`; score block
`:235-239`; natural placement inside `finding-lead`, adjacent to the number it qualifies.

**Renderer-only.** If a field is added to `ReportFinding`, or a query to `analyze.py`, **that
is shape (1) drifting into (1b) — stop and raise.**

### The form: a labelled pair with a disclosure sentence — **adopted**

The reviewer's §2.2 recommendation is adopted, and the reason is stronger than "clearer":

> **P-001 does not render `severity_score` at all.** The big number is `priority.score`
> (`html.py:185, 219, 236`) and the list order is `priority.score`, KEV-exploited first
> (`analyze.py:217-224`). `current_severity_score` escalates the **finding severity** — a
> different number.

**So a bare badge would manufacture a false inference that does not exist today.** Before
P-002 a reader sees a priority rank and no severity information — **no wrong conclusion is
available to them.** After P-002 with a bare *"now 88"* beside a rank, the available
conclusion is *"the rank moved"* — and it did not, and under shape (1) never will.

> **An annotation without its disclosure is worse than no annotation**, because it creates
> the misreading rather than failing to prevent one.

**Required form:**

- a **labelled pair** — *first seen* / *now* — not a bare badge or a delta;
- **one sentence** stating that **the priority rank does not reflect the escalated value**;
- rendered **only when the two differ**.

**On the sentence's wording:** it must be accurate about *how* the rank relates to severity.
**Confirm against shipped code how `priority.score` consumes the finding's severity before
writing it** — the claim *"the rank is computed from the first-seen severity"* is the
reviewer's and is very likely right, but it is a claim about shipped code and this spec is
not the place it gets asserted from memory.

This is **ECR-0081 invariant 1** in minimal form — *the caveat travels with the claim* — and
it is what keeps annotate **honest** rather than merely **literal** (ECR-0084 §7).

**No delta.** Two displayed numbers are two facts; **a displayed delta is a computed claim**
and would fall under ECR-0083 §6.6's reconciliation requirement, whose measured floor is one
display unit at one-decimal display. **Show both, compute nothing.**

**Acceptance:** `test_p002_divergent_renders_pair_and_disclosure`,
`test_p002_equal_renders_neither`.

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
3. **Anything P-001 renders must sum and reconcile** — satisfied here by showing no delta.

## R4 — The test must prove **consumption**, and the obvious test is the forbidden one

`tests/conformance/test_finding_cursor_contract.py` already asserts the column holds the right
number. **That test is the reason this defect shipped with green CI.** Do not add another of
its kind.

**Assert on rendered output, not on the model:**

- divergent values → the HTML **contains both numbers and the disclosure sentence**;
- equal values → it contains **neither**.

**Mutation-verify, and run both** (rules 21, 24, 31 — rule 24 is explicit that a control never
run against a broken implementation is an untested test):

| mutation | expected |
|---|---|
| delete the annotation branch | **red** |
| render unconditionally | the **equal-values** case goes **red** |

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
3. **A bare badge fails review.** Without the disclosure the annotation **creates** the
   misreading; that is the whole argument for the labelled pair.
4. **No delta rendered.**
5. **Dormancy recorded in all three places**, including the test.
6. **Both mutations run**, not merely specified.
7. **The fixture goes through the real re-emission path**, not a hand-set attribute.
8. **The ECR-0084 status transition** names **who chose and when** — owner, 2026-07-30 — in
   the row **and** the body.
9. `mypy --strict src tests`; `gh pr checks` PASS.
