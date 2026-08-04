# ECR-0097 - Single-Column Ordering Witnesses, Part 2

**Status:** Accepted - the ECR-0096 deferred ordering batch shipped.
**From:** claude.ai, from Claude Code's post-ECR-0096 brief; corrected by Codex
against the shipped APIs during implementation.
**Date:** 2026-08-04
**Number:** re-verified as the next contiguous number after ECR-0096.

## 1. Corrections of record

1. **`objects` is ordinarily mutatable.** The ECR-0096-era scope-out was wrong:
   replacing `insort` with `append` breaks maintained order in memory, and deleting
   Postgres's `ORDER BY id` breaks its read. `objects` therefore receives two ordinary
   witnesses here. ECR-0096 section 2 is amended accordingly.
2. **Witness location is a family property, not a new-file rule.** The executed-query
   guard belongs in its existing guarantee file. Any change to a carried-control file
   requires the full carried matrix to be rerun.
3. **Workflow is not a keyset read.** `RunStore.list` accepts a limit but no cursor. Its
   honest witness proves every ordered prefix from 1 through N; it does not pretend to
   walk pages or test a resume predicate that the API does not have.
4. **DSPM has the same CTE-backed outer-order shape as secrets and ISPM.** Its
   `DISTINCT ON (id) ... ORDER BY id, version DESC` CTE already emits ID order, so
   deleting the outer clause is behaviorally indistinguishable on the real method. The
   central executed-query AST guard now pins that clause instead.

## 2. Finding

Five correct ordered reads had no deliberately decorrelated witness. UUIDv7 insertion
order let a missing sort appear correct. Four are cursor reads (`cspm`, `dspm`, `sspm`,
and `objects`); one is workflow's bounded ordered list. The defect was in coverage, not
in the shipped implementations.

The batch boundary is reviewability, not exposure. A domain being surfaced does not
imply that every method in that domain is surface-reachable.

## 3. Resolution

Each domain pre-mints and sorts six IDs, inserts them in reverse order, and first asserts
that all six independent rows survived storage. CSPM varies account, DSPM varies its
`(tenant_id, store_id)` natural key, workflow varies playbook ID, and objects uses six
distinct natural keys. SSPM records have distinct object IDs and tenant descriptors.

The four cursor reads walk every limit from 1 through N under a
`range(len(expected) + 2)` bound with a named non-termination failure. Workflow checks
every prefix from 1 through N. Postgres cases retain `forced_keyset_plan` as insurance;
the record does not credit it as the mechanism. The decorrelated fixture is the
mechanism for behaviorally observable reads.

Memory sort removal turns each domain witness red. With the new witness deselected,
each affected domain suite stays green, proving necessity. Postgres outer-order
deletions are exercised on live Postgres for CSPM, SSPM, workflow, and objects. DSPM's
outer deletion instead turns its fail-closed executed-query AST contract red; the ECR
does not mislabel that structural proof as behavioral coverage.

## 4. Acceptance

1. The five memory regressions are red against their named witnesses and green when
   those witnesses are deselected.
2. Four behaviorally observable Postgres outer-order deletions are red on live
   Postgres. DSPM's outer-order deletion is red in the executed-query guard.
3. Every cursor walk is bounded and checks exact order with no duplicates.
4. Workflow checks exact ordered prefixes and makes no cursor claim.
5. The carried 37-mutation matrix remains unchanged. Touching the central guard
   triggers its full carried rerun.

## 5. Bounded closure and the residual population

This arc closes exactly fourteen enumerated reads: eight true single-column keyset
reads, workflow's bounded ordered list, and the five composite reads covered by
ECR-0090 through ECR-0094. For those fourteen, ordering, tiebreak, leading key,
predicate, and termination are mutation-proven or carry a named structural treatment
with measured grounds. Secrets, ISPM, and DSPM are the CTE-backed outer-order cases
pinned by the central executed-query guard.

That is not the whole paged-read population. Excluding literal `LIMIT 1` point lookups,
the source contains thirty `ORDER BY ... LIMIT` reads. Sixteen sit outside this arc:

| Read | Review mutation | Result at `34c6c07` |
|---|---|---|
| `assetconfig/postgres.py:235` | drop `id` tiebreak | GREEN |
| `decision/postgres.py:119` | drop `id` tiebreak | GREEN |
| `executive/postgres.py:167` | delete `ORDER BY version` | GREEN |
| `executive/postgres.py:257` | not yet measured | ECR-0098 |
| `exposure/postgres.py:121` | drop `id` tiebreak | GREEN |
| `forecast/postgres.py:183` | drop `id` tiebreak | GREEN |
| `forecast/postgres.py:342` | not yet measured | ECR-0098 |
| `governance/postgres.py:120` | not yet measured | ECR-0098 |
| `idthreat/postgres.py:164` | not yet measured | ECR-0098 |
| `lake/postgres.py:331` | drop `id` tiebreak | GREEN |
| `lake/postgres.py:439` | not yet measured | ECR-0098 |
| `response/postgres.py:162` | not yet measured | ECR-0098 |
| `risk/postgres.py:154` | drop `id` tiebreak | GREEN |
| `risk/postgres.py:227` | not yet measured | ECR-0098 |
| `soc/postgres.py:205` | drop `id` tiebreak | GREEN |
| `vuln/postgres.py:135` | drop `id` tiebreak | RED (`test_ordering_determinism.py` x2) |

Nine of the sixteen were measured in review: eight mutations stayed green and only
`vuln` turned red. `executive.versions(key, limit)` is a second cursorless bounded
ordered list, the same class this ECR identified for workflow. `exposure.query()` is
the unwitnessed sibling of the `query_for_read()` method covered by ECR-0090.

C-038/R3's docstring claims every SQL ordering in `src/` terminates in a unique column,
but its mechanism exercises `VulnerabilityStore` alone. Review proved that claim for
`vuln`; it did not prove the repo-wide assertion. ECR-0098 is scheduled to enumerate
and classify all sixteen residual reads, add or name their witnesses, and correct the
C-038/R3 claim. No residual read except the measured `vuln` case is claimed covered
here.

This section also supersedes ECR-0096's shorthand count of nine single-column keyset
reads, which included workflow despite its cursorless API.

## 6. Scope

Tests and records only. Production reads, schemas, dependencies, loopback behavior, and
GC postures are unchanged. ECR-0034, ECR-0061, ECR-0062, ECR-0063, rule 33,
ECR-0095's termination shapes, and ECR-0096's executed-query guard remain binding.

## 7. Method

A gap described twice was wrong both times until it was mutated. "Structurally
unmutatable" fell to `insort` becoming `append`; "surface-reachable four" fell to a
call-site check. Briefs assert, ECRs decide, and mutations settle.
