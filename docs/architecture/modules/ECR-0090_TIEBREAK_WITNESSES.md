# ECR-0090 — Keyset Tiebreak Witnesses

**Status:** Accepted — tiebreak witnesses shipped
**From:** claude.ai (spec author), from Claude Code's tiebreak brief verified at `main @4077b40`
**Date:** 2026-08-02 · **revised 2026-08-03** per Claude Code's pre-implementation verification
(`AQELYN_ECR0090_VERIFICATION.md`): all shipped-code claims confirmed at `4077b40`; four
spec-text fixes applied below (R1 ispm conditional closed, R1 per-read tiebreak column,
R3 restated with named indexes + direction, R3 secrets scoped out).
**Number:** 0090 per rule 1, re-checked against `ECR-LOG.md` in the implementation branch.

---

## 1. Classification — reviewer-carried hardening, not spec debt and not a defect

This ECR exists because the reviewer raised a witness gap as a review finding on PR #292 and
chose to merge anyway. Nothing was deferred by ECR-0089's spec; FR-007 shipped and was
mutation-proved. The governing requirement is **ECR-0089 FR-003** verbatim: *"every collection
route pages by keyset on a stated composite key (ECR-0062 precedent; never offset)."*

**The shipped implementations are correct.** All four widened reads carry their composite
tiebreak — exposure `(discovered_at, id)`, ispm `(subject_ref, id)`, secrets `(kind, id)`,
supplychain `(provenance_status, object_id)` — in both store kinds. What is missing is the
**witness**: a test that goes RED if someone deletes one.

## 2. Findings of record

1. **The tiebreaks are unguarded, proven by mutation.** Deleting the trailing tiebreak from
   exposure (both stores), ispm (Postgres), and supplychain (Postgres) simultaneously left the
   **entire suite on live Postgres green, exit 0**. The existing keyset tests are real and
   otherwise good — they walk to exhaustion at limits 1–5 on both stores, asserting exhaustive
   and unique, and exposure even deliberately ties `discovered_at` — and they still catch
   nothing.
2. **Cause (a): the tiebreak column is correlated with insertion order.** `new_id()` mints
   UUIDv7 (`conventions/ids.py:81-90`), which is time-ordered; rows inserted in loop order make
   sorted-id order equal insertion order equal untied return order. The deliberate tie is
   genuine but invisible. For ispm it is worse: every `subject_ref` is distinct, so the shipped
   test has no tie to break at all.
3. **Cause (b): on Postgres, a covering index supplies the ordering the SQL stopped asking
   for.** `EXPLAIN`-verified: the mutated `ORDER BY discovered_at` rides
   `ix_exposure_record_tenant_discovered_read (tenant_id, discovered_at, id)` and returns
   ascending-id order anyway; with `enable_indexscan=off, enable_bitmapscan=off` it becomes
   Seq Scan + Sort and the order breaks immediately. Same shape for the ispm and supplychain
   indexes. **The tiebreak is load-bearing precisely when the planner departs from the
   covering index** — larger tables, changed statistics, bitmap or parallel plans.
4. **Secrets' RED is an accident, not a witness.** Its read runs through a `DISTINCT ON` CTE,
   forcing a real Sort node, and Postgres's sort is unstable — the catch comes from sort
   instability, not design. The other three must not be made to "look like secrets," and
   secrets itself still needs designed witnesses; an accidental catch is not a guard.
5. **Severity, measured (pre-implementation verification):** with the ispm in-memory tiebreak
   deleted, the reviewer's probe fixture (6 scores on one `subject_ref`) did not merely
   mis-order — the keyset walk **returned 2 of 6 rows, silently skipping 4**. The failure mode
   is silent data loss on a read path, not cosmetic ordering.
6. **First-class limitation, recorded so no future reader re-learns it:** under the default
   plan the Postgres tiebreak is **invisible to black-box tests**. A Postgres ordering test
   that does not force the plan proves nothing about the `ORDER BY`.

## 3. Requirements

**R1 — In-memory witnesses (all four reads; no production change).** For each read, a keyset
test whose fixture **decorrelates the read's own tiebreak column from insertion order** and
**ties the leading column across all rows**: mint the tiebreak values first, sort them,
insert in reverse; expected order is ascending by that column. Walk at limits 1..N asserting
exhaustive and unique (the reviewer's proven probe shape). **The tiebreak column is per
read**: `id` for exposure, ispm and secrets; **`object_id` for supplychain**
(`SupplyChainComponent.object_id` is an assignable typed field, `supplychain/models.py:243,
262-265`) — decorrelating `id` there would ship a vacuous witness.

**ispm is IN — the draft's scoping conditional is closed by verification, not exercised.**
`id` is the primary key and nothing constrains `subject_ref` uniqueness
(`ispm/ddl.py:36-43`, `memory.py:132-137`); the reviewer ran 6 scores on one `subject_ref`
to exhaustion, green on clean `main`, RED under the tiebreak deletion. Because
`score_identity` mints its own id, ispm uses the verified fixture shape: score one identity
once, then `put_score` copies under pre-minted ids inserted in reverse —

```python
base = await engine.score_identity(account_id, tenant_id=TENANT)
ids = sorted(new_id("ips") for _ in range(N))
for score_id in reversed(ids):
    await store.put_score(base.model_copy(update={"id": score_id}, deep=True))
expected = sorted(ids + [base.id])   # base shares the subject_ref; it joins the tie
```

**R2 — Postgres witnesses via forced plan (all four reads).** Same data shape, with
`SET enable_indexscan = off; SET enable_bitmapscan = off` **scoped to the test session and
reset after** — the forced plan is a test technique, never a production setting. Acceptance:
deleting the tiebreak from the shipped `ORDER BY` turns exactly this witness RED. This is the
only honest black-box witness available under §2.5.

**R3 — Static index/ORDER-BY conformance check (three reads; secrets scoped out with
grounds).** For each in-scope keyset read, a static test asserts, against the shipped DDL and
query constants, that the read's `ORDER BY` columns are a **prefix of the columns of the
named index on the table the read queries**, and that **sort direction matches per column
(ASC/DESC)**. The index is pinned **by name** in this ECR — name-and-column matching is not
sufficient, because `aq_exposure_record` carries two name-matching indexes and one is DESC:

| read | table queried | pinned index |
|---|---|---|
| exposure `query_for_read` | `aq_exposure_record` | `ix_exposure_record_tenant_discovered_read (tenant_id, discovered_at ASC, id ASC)` — **not** `ix_exposure_record_tenant_discovered`, whose `discovered_at DESC` does not serve the ASC keyset (the exact drift this check exists to catch; that DESC index is why exposure needed a new index in ECR-0089) |
| ispm `query_scores_for_read` | `aq_ispm_posture_score` | `ix_ispm_posture_score_tenant_subject_id (tenant_id, subject_ref ASC, id ASC)` |
| supplychain `query_components_for_read` | `aq_supplychain_component` | `ix_supplychain_component_tenant_provenance (tenant_id, provenance_status ASC, object_id ASC)` |

**Secrets is out of R3, on §2.4's own grounds:** its outer `ORDER BY kind, id` runs over the
`DISTINCT ON` CTE result and no covering index backs that read — there is nothing true to
pin. In particular, `ix_crypto_identity_tenant_kind_id` is an exact shape match **on a table
the read never queries** (`aq_crypto_asset_identity`; the read touches only
`aq_crypto_asset_revision`) — pointing R3 at it would ship a green check pinning a
relationship the query does not use, which is worse than no check. Secrets' ordering is
guarded by R1/R2 alone, and this paragraph is the recorded reason.

R3 is adopted **alongside** R1/R2, not instead: R3 pins the design agreement, R1/R2 prove
the runtime property on each store.

**R4 — Witness verification standard (amended by ECR-0091).** Every R1/R2 witness is proven
**both directions** in the implementing PR: green on clean `main`, RED under its specific
mutation. Each deletion turns its own witness RED; the static guarantee may additionally
fire on the Postgres cases, which is intended. No witness may be silently covered only by
another witness of the same kind. The PR description lists the mutation matrix and results.

## 4. Out of scope — the offset coexistence question, flagged for its own ruling

The surface now runs two pagination disciplines: keyset on the four widened routes, **offset**
cursors on `/api/v1/findings` and `/api/v1/inventory` (`surface/app.py:473`, `:523`) — shipped
by ECR-0088 before FR-003 existed. The reviewer read FR-003 as scoped to ECR-0089's routes;
this ECR concurs: **not a defect**, and not folded in here. It is recorded as an open
consistency question deserving its own ECR (natural shape: migrate the two ECR-0088 routes to
keyset — findings already has the ECR-0062 composite at the store level — or record the split
as deliberate with grounds). No owner decision is requested by this ECR.

## 5. Carried constraints

Reads-only, loopback, no new dependency, GC-002/GC-003/GC-004 postures — all unchanged; this
ECR ships **tests and one static check only**, no runtime change. ECR-0034 `degraded`,
ECR-0061 exhaust-or-refuse, ECR-0062 keyset precedent, rule 33 — untouched and binding.

## 6. Method notes carried into the record (from the brief, kept verbatim in spirit)

- A deliberately created tie proves nothing if the tiebreaking column is correlated with
  insertion order — and a covering index can silently supply the ordering the SQL forgot to
  ask for, making a correct guard permanently invisible to black-box tests. Run `EXPLAIN`;
  force the plan.
- Before requiring a mutation to go RED, check that it can: the reviewer's own round-1 probe
  had the identical blind spot, and the ask was revised rather than demanded twice.
- A static conformance check must pin its target by name, table, and direction — an
  exact-shape index on the wrong table, or a name-matching index with the wrong direction,
  turns the check into a green certificate for the very drift it exists to prevent.

## 7. Outcome

Codex implemented R1/R2 witnesses for all four reads, including the verified ispm fixture and
the supply-chain `object_id` tiebreak. The Postgres variants pin each store to the exact session
whose index and bitmap scans are disabled, then reset both settings. R3 ships as one static
conformance test for the three named indexes. Production code is unchanged.
