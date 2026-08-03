# ECR-0094 — Findings Keyset Witnesses (closing the read arc)

**Status:** Accepted
**From:** claude.ai (spec author), from Claude Code's brief verified at `main @365da16`
**Date:** 2026-08-03
**Number:** 0094 per rule 1, re-checked against `ECR-LOG.md` in the implementation branch.

---

## 1. Classification — ECR-0093's deferred measurement came back green

ECR-0093 §4 asked the reviewer to run the findings deletion mutations and record the result
either way. Both in-memory deletions came back **green — nothing caught them**, and both
Postgres deletions were caught by the static guard **only**. No test in `tests/findings/`
mentioned `cursor`. This ECR is that recorded follow-up: the surface's highest-volume route
joins the witness standard the other four reads already meet. The shipped composite was correct;
the witness was missing.

## 2. Findings of record

1. **The static guard cannot reach the in-memory store, by construction.** It parses
   Postgres SQL out of store source; `memory.py` uses a Python sort key. Behavioural witnesses
   are the only instrument.
2. **The static guard pins `ORDER BY`, never the keyset predicate — across all five reads.**
   A wrong direction, `>=` for `>`, or a dropped tie clause skips or duplicates rows while
   `ORDER BY` and the static guard stay green. The four widened reads cover this only
   incidentally through exhaustive walks; findings did not cover it.
3. **ECR-0093's index recreates the invisibility trap.** An Index Only Scan can supply
   `(severity_score DESC, id)` order after the SQL drops a component, so the Postgres witness
   must use `forced_keyset_plan`.
4. **Walking is what tests the predicate.** A witness asserting one ordered page is not
   equivalent to paging to exhaustion and proving exhaustive, unique order.

## 3. Requirements and resolution

**R1 — In-memory tiebreak and leading-key witnesses, walking.** Both fixtures page to
exhaustion at limits `1..N`, asserting exhaustive, unique and correctly ordered results.

- **Tiebreak:** every row has the same `severity_score`; IDs are minted first and inserted
  in reverse; expected order is ascending ID.
- **Leading key:** IDs are minted ascending and increasing scores are assigned to increasing
  IDs. Correct severity-descending order is therefore descending ID, the exact reverse of an
  ID-only sort. The fixture asserts `id_only != expected` before walking.

Both fixtures use a distinct `dedup_key` per row and assert the store contains N rows before
walking. Otherwise `raise_finding` would merge the corpus into one row and manufacture a
vacuous pass. The fixtures vary and assert `severity_score`, never
`current_severity_score`; ECR-0063 deliberately keeps the former stable under escalation so
the cursor remains safe.

**R2 — Postgres included under `forced_keyset_plan`.** The same two fixtures run against the
real Postgres store with index and bitmap scans disabled on the pinned connection. Scope-out is
declined: the predicate gap is not covered by the static guard, so the Postgres walk provides
coverage no other control provides.

**R3 — Predicate witnesses are first-class.** The two walks must turn red when either store's
resume comparison is changed in each of these ways:

- severity direction flipped;
- the exclusive ID comparison changed from `>` to `>=`;
- the equal-severity ID clause dropped.

Each mutation and the witness that catches it is recorded in the implementation PR.

**R4 — No weakening.** The 19 mutations of ECR-0090–0093 remain in force. At review, the
reviewer also runs the R3 predicate mutations against the four widened reads. Any green result
is recorded as a follow-up finding rather than silently folded into this ECR.

## 4. Carried constraints

Tests only; zero `src/` changes. Reads-only, loopback, dependencies and GC postures remain
unchanged. ECR-0034 `degraded` · ECR-0061 exhaust-or-refuse · ECR-0062 keyset · ECR-0063
severity stability · rule 33 · all prior method notes.

## 5. Outcome

Findings now has deliberate leading-key, tiebreak and predicate witnesses on both stores. The
memory mutation matrix is measured in the implementing PR; Postgres uses the same fixtures under
the proven forced-plan mechanism. When review completes the carried and widened-read mutation
runs, every keyset ordering property on every surface collection read is mutation-proven or
named-exempt with grounds. No silent member remains.
