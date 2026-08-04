# ECR-0096 - Single-Column Keyset Ordering Witnesses, Part 1

**Status:** Accepted - the first four single-column reads are witnessed.
**Raised by:** claude.ai from Claude Code's post-ECR-0095 review; implemented by Codex.
**Date:** 2026-08-03
**Number:** re-verified as the next contiguous number after ECR-0095.

## 1. Findings of record

1. **ECR-0095 also closed the Group B predicate class.** Its bounded walks now make a
   non-advancing cursor fail diagnostically. The `>` to `>=` mutations on
   `ispm.query_identities`, `secrets.query_assets`, and `dspm.query_assets` therefore turn
   red without a separate predicate-specific fixture. Coverage bought accidentally is
   recorded here so later scoping decisions do not re-cover or re-defer it.
2. **Memory ordering was unwitnessed across eight of the nine single-column keyset reads.**
   UUIDv7 generation correlated insertion and identifier order, so removing each of the
   four selected sort operations left its existing suite green.
3. **Postgres coverage was mixed.** The relay measured three outer-order deletions green,
   supplied by an index scan or an identically ordered `DISTINCT ON` CTE. ECR-0096's live
   mutation also showed that inventory was already covered by IS-037's conformance cursor
   contract. This ECR adds a dedicated inventory witness; it does not claim first coverage
   for that store/read pair.
4. **This batch is not an exposure boundary.** Only `AssetStore.query` feeds a surface
   route, through inventory's `_read_assets` path and `/api/v1/inventory`.
   `CryptoStore.query_assets` feeds the secrets engine, secrets exposure, and service health;
   `ISPMStore.query_identities` feeds the ISPM engine, ISPM exposure, and service health;
   `SBOMStore.query` feeds the supply-chain engine and service health. Their surface routes use
   the separate composite reads witnessed by ECR-0090 through ECR-0092. An ordering break still
   skips or repeats rows in computed intelligence; the reason of record is the actual consumer,
   not the fact that its domain also has a surface route.
5. **The implementations were correct.** This ECR adds missing witnesses; it does not repair
   a production defect.

## 2. Sizing decision

The owner-delegated sizing decision is Option B: split for reviewability, not exposure. A
roughly sixteen-mutation addition on top of 37 carried mutations makes reviewer attention the
limiting control; the batch boundary is not a claim about method reachability.

- This ECR covers the first four selected reads: `AssetStore.query`,
  `CryptoStore.query_assets`, `ISPMStore.query_identities`, and `SBOMStore.query`.
- ECR-0097 is scheduled for the interior four (`cspm`, `dspm`, `sspm`, and `workflow`) plus
  the `objects` determination. `objects` maintains an ordered list with `insort` rather than
  sorting at query time, so ECR-0097 must add an invariant witness or record a structural
  scope-out.
- Deferring the whole family is declined. The measured gap can be closed in reviewable halves
  without weakening the requirement that ECR-0097 cover every remaining member.

## 3. Resolution

Each read now has memory and Postgres witness variants. Every fixture:

- pre-mints and sorts six IDs, then inserts them in reverse ID order;
- asserts that the store retained all six rows before walking;
- walks every limit from 1 through six under a `len(expected) + 2` bound;
- asserts exhaustive, unique, ascending IDs and names the walk on non-termination.

Every Postgres variant runs under `forced_keyset_plan` as insurance against an index supplying
the order being tested. On the six-row inventory and supply-chain fixtures, review measured
the setting as currently inert: their outer-clause deletions remain red with index scans
enabled. The setting is retained for larger fixtures, but is not claimed as the mechanism that
catches those mutations today. Inventory and supply chain witness outer `ORDER BY` deletion
behaviorally.

Secrets and ISPM have a narrower structural limitation that the relay draft did not account
for: their `DISTINCT ON (id)` CTE must itself use `ORDER BY id, revision DESC`. Deleting the
identical outer `ORDER BY id` leaves the same observable row order for every fixture; planner
settings cannot make two equivalent output sequences differ. Their tests therefore combine
the forced-plan behavioral walk with a central AST assertion on the SQL argument actually
passed to `conn.fetch`. The guard resolves that argument, fails closed when it cannot, and pins
the final `ORDER BY ... LIMIT` clause so the CTE's inner ordering is not mistaken for the outer
contract. Deletion, direction reversal, and retaining a dead literal while stripping the
executed clause all turn the guard red; the record does not misdescribe that red as behavioral
evidence.

The four memory sort-neutralization mutations each fail their domain witness. Inventory and
supply chain fail their Postgres behavioral witnesses on outer-order deletion; secrets and ISPM
fail the central executed-query guard. Inventory's Postgres deletion also fails the older
IS-037 conformance control; same-read defence in depth is not misreported as isolation.

## 4. No weakening and scope

The 37 carried mutations remain in force. New witnesses live in new files; any changed
carried verdict is review-blocking.

Tests and records only: zero production source, schema, dependency, loopback, GC posture, or
pagination contract changes. ECR-0034, ECR-0061, ECR-0062, ECR-0063, rule 33, and
ECR-0095's termination shapes remain binding.

## 5. Follow-up

ECR-0097 remains a required follow-up for the interior four and the `objects` determination.
Its brief must check natural-key deduplication before constructing fixtures and identify any
other CTE-backed read whose observable ordering cannot distinguish an outer-clause deletion.
