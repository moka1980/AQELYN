# ECR-0091 — Leading-Key Witnesses (and an ECR-0090 R4 correction)

**Status:** Accepted — leading-key witnesses shipped
**From:** claude.ai (spec author), from Claude Code's leading-key brief verified at `main @c41395a`
**Date:** 2026-08-03
**Number:** 0091 per rule 1, re-checked against `ECR-LOG.md` in the implementation branch.

---

## 1. Classification — the mirror gap, pre-existing, not a regression

ECR-0090 proved the **trailing tiebreak** of each composite keyset is load-bearing. Nothing
proved the **leading column** was: deleting it from any of the four in-memory sort keys left
the entire ECR-0090 witness family green, measured on all four against all four witnesses plus
the static guard.

**This is not a regression from PR #293, and this ECR must not read as a defect report against
it.** The reviewer ran the replaced pre-ECR-0090 ISPM test (five distinct `subject_ref` values,
with the leading column not tied) at `4077b40` against the same mutation: green, 13 passed. The
gap predates the witnesses; ECR-0090's fixtures made it structural by tying the leading column
to expose the tiebreak, but they did not create it.

**Postgres is already covered and is out of scope, verified rather than assumed:** mutating
`exposure/postgres.py:152` to `ORDER BY id` turns the ECR-0090 static guard red
(`tests/guarantees/test_read_keyset_indexes.py`). R3's pinned column lists guard the Postgres
`ORDER BY`; only the in-memory sort keys were unwitnessed.

## 2. Findings of record

1. **The leading column of every in-memory keyset was unwitnessed.** Four mutations remained
   green against the full ECR-0090 witness family.
2. **Distinct is not decorrelated — the root cause, second appearance.** The old ISPM test had
   five distinct `subject_ref` values and still missed the mutation because `new_id("obj")`
   produces time-ordered UUIDv7 values: leading-column order equalled insertion order and ID
   order. A requirement for distinct values alone can pass for the wrong reason.
3. **The mirror of a guard is not guarded by the guard.** Whenever a witness works by holding
   column A constant, another witness must prove A.

## 3. Requirements and implementation

**R1 — Leading-key witnesses, four in-memory reads.** Each read has a second fixture mirroring
its ECR-0090 witness: the leading values vary in an order deliberately decorrelated from
insertion order, while the unique tiebreak's standalone order cannot reproduce the correct
leading-key sequence. Every fixture walks limits `1..N`, asserting exhaustive, unique and
correctly ordered results. Removing the leading column from the corresponding memory sort turns
that fixture red.

| read | leading column | witness shape |
|---|---|---|
| exposure | `discovered_at` | timestamps generated first and reverse-inserted; IDs run in the opposite direction |
| supply chain | `provenance_status` | all legal statuses reverse-inserted; object IDs are exact anti-order |
| ISPM | `subject_ref` | typed `obj_` refs generated first, sorted and reverse-inserted; score IDs are exact anti-order |
| secrets | `kind` via `asset_kind(item)` | all three legal kinds enumerated and reverse-inserted; mandatory kind-specific ID prefixes produce a proven nonmatching ID-only order |

Secrets' legal set is `certificate`, `key`, `secret`; the fixture asserts exact equality with
`VALID_CRYPTO_ASSET_KINDS` before inserting anything. It never invents a kind. Mandatory
`x509_`, `cky_` and `sct_` ID prefixes make a perfect reverse ID sequence impossible across all
three legal kinds, so the test states and proves the actual discriminating property rather than
claiming an impossible fixture shape.

**R2 — Postgres scoped out, with grounds recorded.** ECR-0090's static guard already pins each
covered Postgres query's `ORDER BY` column list by name, table and direction, and a leading-column
deletion makes it fail. A forced-plan witness would add run cost for coverage that exists. If a
future change unpins an index from R3's table, the Postgres leading key re-enters scope with it.

## 4. Correction to ECR-0090 R4 — amendment of record

ECR-0090 R4 originally said each tiebreak deletion turns exactly its own witness red with no
cross-coverage. That was stronger than the measurement: the three R3-covered Postgres deletions
also fire the static guard, which is intended defence in depth. R4 is amended to:

> Each deletion turns its own witness red; the static guarantee may additionally fire on the
> Postgres cases, which is intended.

The surviving isolation discipline is precise: no witness may be silently covered only by
another witness of the same kind. The amendment appears here, in ECR-0090 itself and in the
ECR-0090 log body.

## 5. Out of scope — recorded state, not folded in

The offset-versus-keyset split (`/api/v1/findings` and `/api/v1/inventory` against ECR-0089
FR-003) remains out of scope. It has been recorded twice as deserving its own ruling. The spec
author intends to draft it next after ECR-0091 lands unless the owner objects or a more urgent
review finding supersedes it.

## 6. Carried constraints

Tests and records only; zero `src/` changes. Reads-only, loopback, dependencies and
GC-002/GC-003/GC-004 remain untouched. ECR-0034 `degraded`, ECR-0061 exhaust-or-refuse,
ECR-0062 keyset, rule 33 and the ECR-0090 method notes remain binding.

## 7. Method notes

- **The mirror of a guard is not guarded by the guard.** When a witness holds column A
  constant, ask what proves A.
- **Distinct is not decorrelated.** Every ordering fixture must state which correlation it
  breaks and how.
- **A uniform result can indict the harness.** Before trusting a mutation matrix in which
  nothing works, prove the worktree under test with one hand-run mutation.

## 8. Ball

Codex implements the four R1 witnesses, proves both directions, and publishes the R4 amendment.
Claude Code re-runs the leading-column mutations and its own full-family matrix before merge.
The owner has no queued decision for this ECR.
