# S-003 U4 — `baseline` — Task Bundle

**Milestone:** S-003 U4 (the fourth tied factor)
**For:** Codex (implementer) · Claude Code (reviewer + merge)
**Prerequisites:** U1, U2, U3, C-039, C-040, ECR-0071/0072/0073 merged (`main @3691eb1`); working tree clean.
**Data handling (ECR-0069):** the baseline's **contents are owner-declared estate configuration** — the never-leaves-the-box column. Claims are identified **only as C1…C5**. No claim text, port, address, path or service name appears in this bundle, in any test, in any fixture, or in any output that leaves the estate.
**Definition of Done:** the real owner-confirmed baseline evaluates against the real U1 documents; **no unevaluated claim is reported as either compliant or drifted**; the three unknown reasons are **distinct by closability class**; both backends, both tenant modes, `python -O`; `mypy --strict src tests`; `gh pr checks` PASS; real-estate run before merge.

---

## 1. U4's condition is met — the baseline is real

The S-003 bundle made U4 conditional and warned: *"do not invent a baseline to make
the output look better."* **A genuine baseline exists** — five owner-confirmed
claims, written as **assertions someone stands behind** rather than a snapshot of
running state, with the declaration recording why a snapshot was refused:

> *"A baseline that is just 'whatever is running now' asserts nothing. It would
> return 100% compliant on the first run by construction."*

**And one claim was dropped before confirmation** for having been proposed as
checkable without having been checked — *a baseline claim that is wrong is worse
than one that is missing.* That is the discipline this unit inherits.

## 2. Measured: one claim of five is fully checkable

| claim | verdict | cause |
|---|---|---|
| **C1** | **not checkable** | 6 externally-bound listeners, **0 attributable** |
| **C2** | **not checkable** | the required evidence is **not among U1's enumerated commands** |
| **C3** | **partial** | one half checkable from the unit inventory; the other **not collected** |
| **C4** | **checkable** | derivable from the socket table |
| **C5** | **not checkable** | requires a **forbidden probe**, or evidence from an unavailable source |

**One fully checkable, one partial, three not.** This is the honest-unknown result
the milestone exists to produce, arriving in a fourth factor. **The claims are good;
the evidence is thin. Those are different problems with different fixes**, and U4's
job is to keep them distinguishable.

---

## 3. The decision: **three buckets** — because *both* settings of `unknown_is_fail` are collapses

`ACGConfig.unknown_is_fail` defaults to **`True`**, folding every `unknown` into the
**failed** count and the failing-items list. Inheriting it would report **three
not-evaluated claims as three failures.**

**But setting it to `False` alone is worse, and this is the part that must not be
missed.**

| setting | what happens to an unevaluated claim |
|---|---|
| `unknown_is_fail=True` | counted as **failed** — a drift finding against a claim never evaluated |
| `unknown_is_fail=False` **alone** | **drops out of the failed count and appears nowhere** — invisible |

**Both are collapses.** `True` collapses unknown into *fail*; `False` collapses it
into *silence*, which a reader will take as *pass*. At least `True` makes them
visible, wrongly. **Shipping the flag change without a visible unknown bucket is the
worse half of the fix**, and it is the likely accident.

> **Required: `unknown_is_fail=False` AND a visible `unknown` bucket reported
> alongside pass and fail.** The flag is what makes three buckets possible; the
> buckets are the deliverable. **Neither alone is acceptable.**

### The two biases only look contradictory

Elsewhere this platform insists *unknown must not look safe*. Here the shipped
default makes unknown look **unsafe**. Both are the same rule — **never collapse
unknown into a value** — applied to different consumers:

| where the unknown goes | the collapse that harms |
|---|---|
| into a **decision** (score, gate, priority) | **unknown read as safe** — something dangerous proceeds |
| into a **report to a human** (drift findings) | **unknown read as violation** — work is manufactured that does not exist |

A false drift finding has the cost the owner's own declaration named when it dropped
its fifth claim: *"the noise trains people to ignore the real ones."*

**`unknown_is_fail=True` remains a defensible fail-closed default for a compliance
engine generally.** S-003 overrides it deliberately, and **the override is stated,
not inherited** — if the owner prefers fail-closed, that is legitimate **provided the
count of not-evaluated claims is visible alongside.**

## 4. Where "unevaluable" is decided: **before `compare()`**

`compare(comparator, observed, expected) -> bool` has **no third value.** A
comparator handed an unresolved observed value **silently returns `False` — a
fail** — which is §3's collapse one layer lower and much harder to see.

**Required: a check is evaluated only if its observed value can be resolved.**
Resolution happens first; an unresolved value short-circuits to `status="unknown"`
with a reason, and **`compare()` is never called.**

EA-0012 already expresses the outcome — `DriftStatus = "pass" | "fail" | "unknown"`,
`DriftItem.observed: Any = None`, `status`, and a **required** `reason`. **Nothing
needs widening.** What is missing is the gate in front of the comparator.

> **Optional, stronger, and worth considering rather than dismissing:** make the
> unresolved case **unconstructible** at the call — resolution returns
> `Resolved(value) | Unresolved(reason)`, and `compare()` accepts only the first.
> *"Remember not to call `compare()` with `None`"* is precisely the class of rule
> this project has repeatedly found erodes. If that is judged too large for U4, the
> short-circuit plus its mutation test is the minimum — but record which was chosen
> and why.

## 5. The three unknowns have **two** different fixes — the reasons must say which

The three unverifiable claims **do not share a cause**, and a reader will otherwise
assume one fix:

| class | claims | closed by |
|---|---|---|
| **privileged read** | **C1**, **C5** | ECR-0073 §6/§7's single owner decision |
| **collection scope** | **C2**, **C3's second half** | adding an unprivileged read — **but that changes U1's enumerated command list, which is a contract under ECR-0070** |

**A test asserting three identical unknown reasons would miss the entire point.**
Each unknown carries its **closability class**, because that is the actionable part
— the same discipline as S-002's reason taxonomy and U3's three states, third
application.

**And amplify this in the output:** the privileged-read decision now gates **four
things** — U3's proxy topology, U3's listener attribution, C1, and C5. It was one
decision when ECR-0073 raised it; it is **the same decision with more riding on it.**
The report should present it as **one item with four dependents**, not four items —
so the owner sees one choice unblocking four, which is the argument the instrument
should be making rather than the prose.

---

## Y1 — Resolution gate

**Deliverable:** evidence resolution ahead of comparison; unresolved ⇒
`status="unknown"` with a required reason; **`compare()` never receives an
unresolved value.** Record which form was chosen (§4).
**Acceptance:** `test_u4_unresolved_never_reaches_compare`,
`test_u4_missing_observed_is_unknown_not_false`.

## Y2 — Three buckets, both halves

**Deliverable:** `unknown_is_fail=False` **and** a visible `unknown` bucket in the
aggregate — counts for pass, fail, **and unknown**. Per-item status is already
honest; this makes the aggregate honest too.
**Acceptance:** `test_u4_unknown_not_counted_as_failed`,
`test_u4_unknown_bucket_visible`, `test_u4_three_bucket_totals_reconcile`.

## Y3 — Closability reasons, and the four-way dependency

**Deliverable:** each unknown carries its closability class (§5); the density/roadmap
output presents the privileged-read decision as **one item with four dependents**.
**Acceptance:** `test_u4_unknown_reasons_distinct_by_class`,
`test_u4_privileged_read_is_one_roadmap_item`.

## Y4 — The no-baseline path stays

**Deliverable:** keep `test_s003_no_baseline_is_unknown_with_reason`. This estate has
a baseline; **another will not**, and the path must not rot for want of exercise.

---

## Proof

- **The real estate's shape reproduces:** one evaluated, one partial, three unknown
  **with distinct reasons**.
- **Negative controls, both directions:** an unevaluable claim must **not** report
  `pass`, and must **not** report `fail` unless fail-closed was explicitly chosen.
  Mutation-verify **both** — one direction alone leaves the other collapse open.
- **The `compare()` seam — the highest-value single test in the unit:** feed a
  missing observed value and confirm **`unknown`, not `False`.**
- **The unknown bucket is visible**, not merely uncounted-as-failed.
- Both backends, both tenant modes, `python -O`.
- **Real-estate run before merge**, counts only in any output.

## Review protocol (Claude Code)

1. **Both halves of §3 shipped.** `unknown_is_fail=False` **without** a visible
   unknown bucket is the worse half of the fix — check this first.
2. **`compare()` never sees an unresolved value** — mutation-verified.
3. **Three unknown reasons, distinct by closability class** — identical reasons fail
   the review even if the counts are right.
4. **The privileged-read decision appears once** with four dependents.
5. **The no-baseline path still tested.**
6. **ECR-0069 respected** — no claim text, port, address, path or service name in the
   diff, fixtures, PR body, or report. Claims stay C1…C5.
7. `mypy --strict src tests`; both backends; both tenant modes; `python -O`;
   `gh pr checks` PASS.

## Carried forward, and two ECRs recommended

**Recommended, not folded in:**

- **Collection-scope widening** for C2 and C3's second half — unprivileged and cheap,
  **but it changes U1's enumerated command list, which is a contract under
  ECR-0070.** Small, not free; it needs its own ECR.
- **The ISPM residual** (`ispm/scoring.py:347`) — already recommended in the U3
  bundle, leading with *"why did GC-001 AC-3 not catch this?"* rather than with the
  defect.

> ⚠️ **Numbering:** I have now recommended two ECRs without assigning either. The log
> was contiguous to 0073 at `3691eb1`, so the next free is 0074 — **but two
> recommendations cannot both take it.** Assign in the order they are raised and
> **re-check the log before each** (rule 1); the 0058 collision earlier in this
> project is what that rule exists to prevent repeating.

**Still open:** the privileged-read decision (now gating four things); the
collector's absent memory bound; the two U1 doc-versus-code drift pins; C-040's
vacuous `scanned -= unassessable_inventory` assertion; U2's `used_default_tier`
refusal, untested because reachable only under a non-default `tier_weights`.

**Next: U5** — run, KEV re-check, density report.
