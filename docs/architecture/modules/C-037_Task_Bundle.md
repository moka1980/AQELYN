# C-037 — ECR-0062: `FindingStore` Cursor Implementation — Task Bundle

**Milestone:** C-037 (implement the `findings` cursor; close the pagination-contract defect)
**For:** Claude Code (implementer **and** reviewer during the Codex outage) · Codex (retroactive re-review on return)
**Prerequisites:** C-036 merged; ECR-0061's `page_budget` note landed (`main @aa67014`); **`AQELYN_SPEC_BRIEF_ECR-0062.md` read**; **ECR-0062** decided by the owner *(verified free at `4c4b642`; #225 amended ECR-0061 rather than allocating — re-check before assigning, rule 1)*; `SPEC_AUTHOR_NOTES.md` Part 1 rules 1–23 read.
**Definition of Done:** one contract suite green on **both backends** and **both tenant modes**, under normal Python **and `python -O`**; `ruff` clean; **`mypy --strict src tests`**; worktree `pytest` with `PYTHONPATH=$PWD/src`; **`gh pr checks <n>` confirmed PASS before merge**; the index migration applied; Claude Code sign-off with self-verification disclosure.

---

## What this is

`FindingStore.query` has a **pagination-shaped signature that never paginates**.
`FindingQuery.cursor` (`findings/models.py:99`) exists and is validated; **neither
backend reads it**. Both return `…, None` unconditionally while truncating at
`limit` (default 100). Since `next_cursor is None` means *"exhausted"*, a caller
paging until the cursor is `None` gets one page and believes the read was
complete.

**`findings` is the sole outlier** — cursor references per backend: `objects` 3/4,
`ispm` 2/3, `secrets` 3/4, `cspm` 2/3, `sspm` 4/9, `inventory` 2/4, **`findings`
0/0**.

**State the severity precisely, and do not dramatise it.** The one real consumer
does not get a wrong answer today: `risk/correlate.py::_finding_signals` reads
under `RiskConfig._correlation_limit` and re-truncates with `gathered[:limit]`,
which with `ORDER BY severity_score DESC` is a deliberate **top-N by severity**
read. It is correct by intent — and correct only because it never asks for
completeness. **This is a latent contract defect with no known wrong answer
today.** The trap is for the next caller, which is precisely any UI listing
surface.

**Implement rather than remove.** Removing the cursor renames the defect: a store
that can only ever return `limit` rows, for the platform's primary output emitted
by every engine, is ECR-0034 relocated rather than resolved.

### This is store-level only — do not copy C-036's apparatus

C-036 added an engine-side paging loop, a `page_budget`, and a `degraded` flag
**because `inventory()` promises a complete answer**. `FindingStore.query`
promises **a page**. So:

- **no engine-side paging loop**, **no `page_budget`**, **no `degraded` flag**;
- the fix is: read `q.cursor`, emit a truthful `next_cursor`, and index for it.

The default `limit=100` does not change. **The fix does not change the page size;
it makes the page size truthful** — a non-null `next_cursor` now tells the caller
there is more, which is the whole of what was missing.

---

## Q1 — Composite cursor, both backends, one contract suite

**Deliverables.** Read `q.cursor`; emit `next_cursor` per EA-0002 D8 — stable
order, **exclusive** cursor, `next_cursor` **non-null exactly when another
matching row exists**, filters applied **before** `LIMIT`.

**The cursor must encode the complete sort key.** Ordering is
`severity_score DESC, id`, so an **`id`-only cursor is wrong** — rows with
`id > i` can sort *before* `i` when their severity is higher, producing skips and
duplicates. The predicate is:

```sql
WHERE severity_score < $s OR (severity_score = $s AND id > $i)
```

with the cursor encoding `(severity_score, id)`. Memory sorts by
`(-severity_score, id)` and applies the same comparison.

**`severity_score` is write-once** — verified at `4c4b642`: Postgres `_save`
(`findings/postgres.py:194`) updates only `status`, `last_detected_at`,
`resolved_at`, `version`; memory dedup never touches it; every other
`severity_score=` is a construction site. **So the keyset is safe from the
mutable-sort-key skip/duplicate hazard** — no as-of bound, no
snapshot-of-convenience caveat.

**Index migration.** Shipped is
`ix_finding_status_sev ON aq_finding (tenant_id, status, severity_score DESC)`
(`findings/ddl.py:37`) — **`id` is absent**, so within a severity tie the database
filters rather than seeks. Extend to
`(tenant_id, status, severity_score DESC, id)`, with
`CREATE INDEX IF NOT EXISTS` / `ALTER` for existing deployments (rule 9: check the
persisted shape before calling anything additive).

**Acceptance:** `test_finding_cursor_contract[inmemory]` / `[postgres]`,
`test_finding_cursor_d8_semantics`, `test_finding_index_covers_tiebreak`.

## Q2 — Doubles: the inverted rule-18 case

**The signature does not change** — `query(q: FindingQuery) -> tuple[list[Finding],
str | None]` already has the right shape. The fix is **behavioural**. So rule 18's
usual risk (a double left behind by a signature change) does not apply, and the
real risk inverts:

> **A double that faithfully models broken behaviour becomes a broken double the
> moment the behaviour is fixed.** Every existing `FindingStore` double that
> returns `rows, None` is *accurate today*. After Q1 it models a store that never
> paginates — so any test using it to exercise paging silently tests nothing, and
> `mypy --strict` cannot see it because nothing about the types changed.

**Enumerate `FindingStore` implementers with `mypy --strict`, not grep** (rule 22
— grep was wrong in both directions on C-036's list). Update each to model the
fixed contract, and **verify by mutation**: break the cursor logic and confirm the
tests that claim to cover paging go red.

The three health-probe callers (`ispm`, `secrets`, `dspm`, `limit=1`) **discard**
the result and are safe — leave them alone, and record that they were checked
rather than silently skipped.

**Acceptance:** `test_finding_doubles_model_paging`,
`test_finding_health_probes_unaffected`.

## Q3 — Proof: the tie-spanning boundary is the only test that matters

Mirror C-036: real stores, both backends, both tenant modes, `python -O`, no spies.

- **Round-trip:** page through `N > limit` findings; assert **every row appears
  exactly once** — no skips, no duplicates.
- **D8:** `next_cursor` non-null **exactly when** another matching row exists;
  exclusive cursor; filters before `LIMIT`.

> **The critical case:** several findings with **identical `severity_score`
> straddling a page boundary.** A test whose severity scores are all distinct
> **passes with an `id`-only cursor** — so without ties spanning a boundary, the
> proof does not test the composite property at all and would green-light exactly
> the wrong implementation the brief warns about. This is the negative-control
> discipline applied to the fix's own correctness: **the test must fail against
> the plausible wrong implementation.**

Build it that way explicitly, and confirm by writing the id-only cursor, watching
this test fail, then reverting.

**Acceptance:** `test_finding_cursor_no_skip_no_duplicate`,
`test_finding_cursor_ties_span_page_boundary`,
`test_finding_cursor_optimized_python`.

## Q4 — Records, and the caveat the fix must not imply away

**ECR-0062** records the decision, the composite-cursor requirement, and the
index change.

**State what the cursor does and does not promise.** After Q1 the read is stable
**with respect to ordering** — no row skipped or duplicated because of sort
position. It is **not** a stable *set*: `status` is mutable, is the most common
filter, and is the leading index column, so a finding can enter or leave the
filtered set between page reads. That is the ordinary phase-change of keyset
pagination over a mutable **predicate** — not a sort-key defect, and not
cursor-fixable.

> **Say so explicitly, because the consumer class matters.** A live listing
> surface tolerates phase-change fine — it is a live view. A caller needing a
> **reproducible** read does not: if EA-0022 pages findings for an issued report,
> or a compliance evidence set is assembled across pages, a status change
> mid-read silently omits or duplicates a finding and the resulting figure is not
> reproducible — which collides with EA-0022's *no number without provenance* and
> its immutable issued reports. **Not scope here**; recorded so the first such
> caller inherits the constraint rather than discovering it.

**EA-0013's tie-breaker:** the composite-cursor requirement above **supersedes**
it for this store and is specified here rather than separately. EA-0013's
equal-timestamp item stays where it is on the backlog.

**Flagged, explicitly NOT absorbed:** dedup re-emission keeps the **original**
`severity_score` — a finding that recurs more severely is never re-scored, because
`_save` does not carry the new emission's score. That may be deliberate under
EA-0013's *history is not recomputed*, or a gap. It is adjacent to this ticket in
a way worth one sentence: **the cursor makes the ordering reliable; whether the
ordering reflects current severity is the other question.** Record it as its own
item; do not decide it here.

**Acceptance:** records landed; no test required.

---

## Review protocol (Claude Code)

1. **The cursor keys on the full sort key.** Write the id-only version, confirm
   `test_finding_cursor_ties_span_page_boundary` **fails**, revert. If that test
   passes against an id-only cursor, it is not testing the property.
2. **D8 semantics honoured** — exclusive, non-null exactly when more exists,
   filters before `LIMIT`.
3. **Index extended** and the tie-break actually seeks rather than filters;
   migration safe for existing deployments.
4. **Doubles updated** (Q2's inverted rule-18 case) and **mutation-verified** —
   break the cursor, watch the paging claims go red. Implementers enumerated with
   `mypy --strict`, not grep (rule 22).
5. **No C-036 apparatus copied** — no engine loop, no `page_budget`, no
   `degraded`. This store promises a page, not completeness.
6. **Severity stated accurately** in the records: latent contract defect, no known
   wrong answer today, `risk/correlate.py` correct by intent.
7. **The ordering-vs-set distinction is recorded** and the fix is not described as
   making pagination "stable" without qualification.
8. **The re-scoring observation is recorded separately**, not absorbed.
9. `mypy --strict src tests`; both backends; both tenant modes; `python -O`;
   `gh pr checks` PASS before merge.
10. **Self-verification disclosure** for Codex's retroactive pass.

**Preserve, do not absorb:** ECR-0032 (shared posture base), EA-0018
unclamped-duration flake, EA-0027/EA-0018 enterprise health probes, EA-0013
equal-timestamp tie-breaker, the finding re-scoring question (new), **EA-0048**
(recorded capability gap, unscheduled).

Merge only on green; then **report back to the owner**. After this the tracked
backlog is ECR-0032, the EA-0018 flake, the enterprise health probes, the EA-0013
tie-breaker, and the re-scoring question — after which the two structural gaps,
**live collection** and **the UI surfaces**, are the next real decision.
