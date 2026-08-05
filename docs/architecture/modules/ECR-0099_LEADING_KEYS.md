# ECR-0099 — The Leading-Key Class, and the Close of the Witness Arc

**Status:** Accepted - implementation complete; closing review pending
**From:** claude.ai (spec author), from Claude Code's brief verified at `main @0fc7cff`;
the §4 matrix policy decided under the owner's standing delegation
**Date:** 2026-08-05
**Number:** 0099 per rule 1 at `0fc7cff` — **re-check `ECR-LOG.md` at merge.**

---

## 1. Findings of record

1. **Ten reads are open on the leading-key class, both stores, measured.** The four that
   fire do so where the fixture's id/leading-key correspondence happens to break (`risk` and
   `response` order DESC; forecast's `method` is a string), and `forecast query` is caught
   on both stores **only** by a pre-existing contract test — defence-in-depth, not coverage.
2. **The symmetry is the finding, and it becomes a rule.** Round 1 gave every row a distinct
   leading key and the tail was invisible; round 2 tied the leading key to expose the tail
   and the head became invisible. **Fixture symmetry rule, adopted into the standing method
   notes: every component of a sort tuple must decide at least one comparison in the same
   fixture.** A fixture tuned to expose one component is, until proven otherwise, blinding
   another.
3. **Two classes are inapplicable, with measured grounds, recorded per the standing rule:**
   resume predicate requires a cursor and all sixteen reads are cursorless (verified in
   ECR-0098's classification); termination requires a walk loop and
   `grep -rn "while True:" tests/` is 0 repo-wide with the ordered-prefix witnesses
   containing no loops. Named inapplicable — neither silence nor invented work.
4. **All implementations are correct**; ECR-0098's one production fix (quarantine memory
   ordering) already landed. This ECR, like the arc, ships witnesses.

## 2. Requirements

**R1 — Amend eleven fixtures; add none.** The fix is the brief's, adopted verbatim: keep
the tie groups that expose the tail, and make the **group order conflict with the id
order** — group timestamps (or group key values) assigned descending while ids ascend
within and across groups, so one fixture makes both components decisive. This amends the
eleven ECR-0098 fixtures covering the ten open reads; `forecast query` additionally gains
its first owned witness (per §1.1 it currently rides a contract test), with the
pre-existing `test_fc_p2` catch recorded as a defence-in-depth cell alongside it.

**R2 — Acceptance is two-sided, per read, per store — the amendment must not trade one
class back for the other:**

- **leading-key deletion** turns exactly that read's (amended) witness RED — the new
  coverage;
- **tail deletion** (ECR-0098's sixteen mutations) **stays RED** on the amended fixtures —
  round 2's coverage survives round 3's fix, proven, not presumed;
- green on clean `main`; necessity by deselection — **with target sets that include
  `tests/conformance/` and `tests/guarantees/`** (binding, per the brief's §5.1: a
  domain-suite-only necessity run structurally cannot see a cross-suite catcher, which is
  how a sole-catcher record went wrong once already);
- the full matrix — 20 amended-fixture leading mutations, 2 forecast-query additions, 16
  surviving tail mutations — in the PR description with isolation, necessity, and
  defence-in-depth columns.

**R3 — No weakening, and this review runs the whole carried matrix one final time.** The
carried **84** stay in force. Because this ECR closes the arc, its review is the arc's
**closing audit**: the reviewer re-runs all 84 plus R2's additions — the last full-matrix
run under the old policy, and the baseline the new policy (§4) samples against.

**The count is 84, and earlier documents said 89.** The drift entered at ECR-0094 §4, which
wrote *"the reviewer re-runs the 19 carried mutations"* for a block that is fourteen. ECR-0092's
review of record states it plainly — *"Full matrix — 14 mutations × 16 witness cases"* — and the
reviewer's harness has executed fourteen there in every run since. Every later total inherited
the +5: 37 → 47 → 57 → 89, where the truth is 32 → 42 → 52 → 84. Corrected here because §4
installs a sampling policy, and a sample whose denominator is wrong is not auditable.

**The carried population, enumerated.** §4's rotation needs a list, not a running total:

| block | mutations | source of record |
|---|---|---|
| ECR-0090 + ECR-0091 + ECR-0092 | 14 | ECR-0092 review, "14 mutations × 16 witness cases" |
| ECR-0094 findings witnesses | 10 | ECR-0094 review |
| ECR-0095 walk termination | 8 | ECR-0095 review |
| ECR-0096 single-column keysets, batch 1 | 10 | ECR-0096 review |
| ECR-0097 single-column keysets, batch 2 | 10 | ECR-0097 review |
| ECR-0098 residual sixteen | 32 | ECR-0098 §6 matrix |
| **total** | **84** | |

## 3. Closure statement

On merge, the witness arc — ECR-0090 through ECR-0099 — closes. Within the census
(`grep -rn "ORDER BY" src/ | grep LIMIT`, excluding `LIMIT 1` point lookups; the boundary
every claim cites): **thirty paged reads carry mutation-proven witnesses for every
applicable defect class** — ordering, tiebreak, leading key, predicate, termination — **on
both stores, or a named exemption/inapplicability with measured grounds** (the CTE-backed
outer orders behind the AST guard; the two legally-necessary pins; the two cursorless-class
inapplicabilities of §1.3). Defence-in-depth cells are recorded as such, not as coverage.
Future reads join the family by the standing rules: enumerate methods not files; state the
census command; name secrets-class coverage explicitly; every tuple component decides a
comparison.

## 4. The carried-matrix policy — decided, not drifted into

The reviewer escalated rather than quietly sampling; the decision is taken here under the
owner's standing delegation, adopting the recommendation with structure:

- **Full carried re-run** is required when: (a) a carried-control file changes (the
  existing trigger); (b) an ECR claims closure of a family or amends carried fixtures
  (this ECR triggers both); (c) at every tenth ECR as a checkpoint audit.
- **Otherwise:** a **named rotating sample** (composition listed in the review comment, so
  the sampling is auditable, rotation ensuring every carried mutation runs at least once
  per five reviews) **plus** every carried mutation touching modules in the ECR's scope.
- **Any verdict change anywhere — sample or scope — triggers the full re-run** before
  merge.
- The policy is recorded in `SPEC_AUTHOR_NOTES` as **rule 34**, so it binds future specs
  and reviews equally, and it is reversible by the same mechanism that created it: a
  recorded decision, not an accretion.

Grounds: the review is this arc's actual control, and a control that costs three rounds and
two days re-proving never-changed verdicts is spending its budget where the risk is not.
Sampling with named composition, scope-priority, and a hard escalation trigger keeps the
evidence honest while returning review attention to the mutations most likely to move.

## 5. Carried constraints

Tests only; zero `src/` changes. Reads-only, loopback, no new dependency, GC postures
untouched. ECR-0034 · ECR-0061 · ECR-0062 · ECR-0063 · rule 33 · ECR-0095 termination
shapes · ECR-0096 executed-query guard · ECR-0097 classification lesson · ECR-0098 census
rule · all prior method notes, extended by §1.2's symmetry rule.

## 6. Method note carried into the record (the brief's, kept whole)

**"The reasoning sounds too good to check" is the signal to check.** Prefix witnesses
assert every prefix from 1 to N, so surely they exercise the leading key — ten of fifteen
said otherwise, and twenty minutes of mutation turned a confident wrong answer into a
table. Three consecutive briefs were wrong in exactly this way. The arc's last method note
is its first one restated: briefs assert, ECRs decide, mutations settle.

## 7. Ball

**Next: Codex implements** — R1's eleven amendments plus forecast-query's witness, R2's
two-sided matrix with full-target necessity runs. **Then: Claude Code** reviews — the
closing audit of §2 R3 (all 84 + additions), the two-sided acceptance, the
defence-in-depth ledger — and merges; re-check ECR number at merge. **Owner:** nothing
queued; §4 consumed the delegation and is reversible by recorded decision. On merge the
witness arc closes, and the next brief opens a new subject — the standing suggestion on
the table is the dashboard arc's opening brief (route inventory, the unexposed domains'
read shapes, asset-pipeline constraints).
