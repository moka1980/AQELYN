# ECR-0092 — The Last Unguarded Keyset Property and the Offset Ruling

**Status:** Accepted — final keyset witness and surface-wide pagination ruling shipped
**From:** claude.ai (spec author), from Claude Code's brief verified at `main @bc63d5b`
**Date:** 2026-08-03
**Number:** 0092 per rule 1, re-checked against `ECR-LOG.md` in the implementation branch.

---

## 1. Classification — a missing witness in a seam

After ECR-0090/0091, every keyset ordering property in the widened-read family had a witness
except one: **secrets' Postgres leading key.** At `bc63d5b`, mutating
`secrets/postgres.py:232` from `ORDER BY kind, id` to `ORDER BY id` left the full secrets suite
plus the static guard green. The shipped SQL was correct; the witness was absent.

The gap sat between two individually correct decisions. ECR-0090 R3 scoped secrets out of the
static guard because its `DISTINCT ON` CTE has no covering index to pin. ECR-0091 R2 scoped the
covered Postgres reads out of runtime witnesses because the static guard covers them. Neither
decision owned the complement.

This was the third consecutive ECR in which the same read needed a special case. **Standing
rule:** any future guard for "the keyset reads" must name secrets' coverage explicitly, in or
out with grounds, or it is presumed to have missed it.

## 2. Requirements and implementation

**R1 — Forced-plan Postgres leading-key witness for secrets.** The existing
`forced_keyset_plan` fixture pins one connection, disables index and bitmap scans, and resets
both settings afterward. The memory and Postgres leading-key tests share one fixture that:

- asserts exact equality with `VALID_CRYPTO_ASSET_KINDS`;
- uses all three legal kinds without invention;
- reverse-inserts the kinds;
- walks limits `1..N`, asserting exhaustive, unique, kind-first order.

The mechanism is designed and explicit. With scans disabled, the CTE's
`ORDER BY id, revision DESC` emits ID order. The correct outer `ORDER BY kind, id` adds the Sort
that produces kind-first order. Deleting `kind` makes the new witness red; removing the witness
from that mutation run makes the suite green again. The result is attributable to the outer Sort,
not incidental instability.

**R2 — No weakening.** ECR-0090's eight mutations and ECR-0091's four mutations remain in
force. A leading-key deletion must not rely only on a tiebreak witness, and a tiebreak deletion
must not rely only on a leading-key witness. The static guarantee may additionally fire for the
three reads it covers, as ECR-0091's R4 amendment records.

**R3 — Cosmetic repair.** ECR-0091's exposure fixture contained
`assert sorted(ids) == list(reversed(expected))`, an identity under that fixture's construction.
It now computes `id_only = sorted(ids)` and asserts `id_only != expected`, matching the
falsifiable shape used by secrets.

## 3. Offset ruling — decided here

ECR-0089 FR-003's "never offset" is the surface-wide pagination rule for collection routes.
The two ECR-0088 routes (`/api/v1/findings` and `/api/v1/inventory`) are grandfathered
non-conformances with a scheduled end, not accepted divergence. Offset pagination under
concurrent writes can skip or repeat rows, the same failure family guarded by this witness arc.

Implementation is ECR-0093. Findings already has the ECR-0062 composite keyset at the store
level. Inventory returns a budget-governed `InventoryReport` with ECR-0034 degraded semantics;
ECR-0093 must either fit a stable keyset to that shape or record a named exemption with grounds.
The ruling holds either way: no collection route keeps offset silently.

## 4. Carried constraints

ECR-0092 changes tests and records only, with zero `src/` changes. Reads-only, loopback,
dependencies and GC postures remain untouched. ECR-0034 degraded, ECR-0061 exhaust-or-refuse,
ECR-0062 keyset, rule 33 and the ECR-0090/ECR-0091 method notes remain binding.

## 5. Method notes

- **The exception to a guard is not guarded by anything.** Every justified exclusion needs an
  explicit owner.
- **A scoping rationale true for covered cases must enumerate the uncovered cases.** Truth about
  a set is silence about its complement.
- **A witness must name its mechanism.** Remove the witness and confirm the mutation changes from
  red to green before attributing detection to the intended path.

## 6. Ball

Codex implements R1/R3 and records the mutation mechanism. Claude Code re-runs the full
14-mutation matrix, reviews and merges, then writes the ECR-0093 brief for the findings and
inventory routes. The owner has no queued decision in ECR-0092.
