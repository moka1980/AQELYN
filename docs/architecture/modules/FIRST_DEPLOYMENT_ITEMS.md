# Items settled only by a first real deployment

**Purpose:** a registry of open questions that are **not** engineering backlog —
they cannot be resolved by more work, only by running the platform against a real
estate with real data at real scale.
**Status:** live index. Each item points at the ECR that owns it; **this file
restates nothing and is not a source of truth.**

---

## Why this category is separate

The tracked backlog holds work with a right answer somebody can produce:
the EA-0018 unclamped-duration flake, the EA-0027/EA-0018 enterprise health
probes, the EA-0013 equal-timestamp tie-breaker, the finding re-scoring question.
Each is a defect or a decision, and each closes when someone does the work.

The items below are different in kind. **None of them is an open defect**, and no
amount of effort closes them, because the missing input is a production
deployment. Left un-named they accumulate silently in ECR bodies and start to read
as unresolved risk — or worse, get "closed" by a guess that looks like a decision.

**Entry criterion.** An item belongs here if its answer requires production data,
production scale, or a live database — *and* if the current shipped behaviour is
already correct without it. An item that is **wrong** today is a backlog defect,
not a deployment item.

---

## The items

### 1. `page_budget = 50_000` is chosen, not derived — ECR-0061

`InventoryConfig.page_budget` bounds `inventory()`'s paging work and is the
refusal threshold for `sweep_unreported`. **Nobody can set it correctly yet**,
because no real estate exists to measure read cost against.

The asymmetry is recorded and argues for erring high: **too low is a silent
capability loss** — `sweep_unreported` refuses forever on a large tenant and the
platform looks broken rather than slow — while **too high is one slow read**.
Configurable is the correct shipped state; tuning belongs to the first deployment
that has an estate to measure.

**Settled by:** measuring read cost and estate size on a real tenant.
**Not a defect:** the value is honest and the behaviour at the boundary is
correct.

### 2. Does Postgres **seek** on the extended index, or filter? — ECR-0062

C-037 extended `ix_finding_status_sev` to
`(tenant_id, status, severity_score DESC, id)` so the keyset tie-break on `id` is
covered rather than filtered.

**The index change is correct regardless** — the old index was a strict prefix of
the new one, so the change cannot be wrong. `EXPLAIN` answers whether it is
**effective**, not whether it is **correct**. This is a performance verification,
and recording it as an open correctness question would misstate it.

**Why it is not a CI gate.** On a small test table the planner will sequential-scan
regardless of any index, so a plan assertion needs either unrealistic row counts or
`enable_seqscan = off` — and both change what is being asked. The honest form is
**one manual run against a realistic instance**, with the plan output pasted into
ECR-0062 as evidence.

**What to read:** whether the tie-break on `id` appears as an **Index Cond** or
drops into **Filter**. If it is in `Filter`, the extension did not achieve its
purpose.

**SETTLED 2026-07-25 — the answer is *no*, and the item is struck.**

Run against a local Postgres 16 (the repo's own `docker-compose.yml`) with 60 000
findings and dense severity ties, after `ANALYZE`:

| Form | Keyset in the plan | Rows removed by filter | Buffers | Execution |
|---|---|---|---|---|
| **Shipped** — `OR` predicate, `(… severity_score DESC, id)` index | **`Filter`** | 28 500 | 29 366 | 18.2 ms |
| Row comparison, `(… severity_score DESC, id DESC)` index | **`Index Cond`** | 0 | 6 | 0.156 ms |

**The extension did not achieve its purpose.** The index is used — but only for
`tenant_id` and `status`; the keyset predicate drops into `Filter`, scanning and
discarding 28 500 rows to return 101.

**Cause.** An `OR` predicate cannot become an index range scan. A `ROW(a, b) < ROW(x, y)`
comparison can — but PostgreSQL requires every ordering column to run the **same
direction**, and the shipped ordering is `severity_score DESC, id` (ascending), which is
mixed. So the row-comparison form is unavailable without changing the tie-break to
`id DESC`.

**Correctness is unaffected** — results are right, merely scanned rather than sought,
which is exactly why this was filed as performance verification rather than an open
correctness question. That framing held.

**Consequence:** a fix is a real change (ordering semantics within a tie, the cursor
predicate, the index, and C-037's tests) and therefore needs its own ECR. It is **not**
urgent: at 60 000 rows the shipped form answers in 18 ms.

**Method note.** This was recorded as needing a first deployment; it needed a
**database**, which `docker compose up postgres` supplies. See item 4.

### 3. Live-deployment migration sequencing — ECR-0062

The shipped DDL is a plain `DROP INDEX` + `CREATE INDEX`, which is **correct for a
fresh deployment** and is what the PG matrix exercises. A live deployment needs
more care:

- `CREATE INDEX CONCURRENTLY` and `DROP INDEX CONCURRENTLY` **cannot run inside a
  transaction block** — a migration wrapped in one needs explicit handling.
- **Build before drop.** Create the new index concurrently, confirm it is valid,
  *then* drop the old one; dropping first opens a window with no index at all.
- A **failed** `CREATE INDEX CONCURRENTLY` leaves an **invalid index** behind that
  must be dropped before retry.

**Settled by:** the first migration against a live database. Until one exists,
the current DDL is correct for every deployment that does exist.

---

### 4. Postgres-parameterized tests skip silently without a database — ECR-0062 / C-038

Not a deployment question at all, and the reason item 2 sat here longer than it needed to.

Without `AQELYN_DATABASE_URL` set, every `postgres` parameterization **skips**, and a
skip reports as success. A green local run can therefore conceal tests that never
executed — which is how C-038 shipped a suite that truncated a table (`aq_vulnerability`)
that does not exist; the real tables are `aq_vuln_record` and `aq_vuln_history`. Only CI's
matrix caught it.

**Mitigation available today:** `docker compose up -d postgres` (already in the repo) plus
`AQELYN_DATABASE_URL=postgresql://aqelyn:aqelyn@localhost:5432/aqelyn`. Verified
2026-07-25: the full suite passes against real Postgres, and doing so settled item 2.

**Settled by:** reading the skip count, or making an expected-but-absent backend fail
rather than skip. Recorded here because the *category* is the same — verification that
cannot happen without infrastructure in the loop — even though the infrastructure turned
out to be one command away rather than a deployment.

## What this category implies

All three items — a budget nobody can tune, an optimization nobody can measure, a
migration path nobody can exercise — have the same root: **the platform has no
deployment.** 33 engines ship with structural safety properties, and none of them
has met production data.

That is the same boundary the two deferred structural gaps sit on: **live
collection** (specs defer it to a future EA-0008-gated connector) and **the UI
surfaces** (specs name a WCAG 2.2 AA consumer that does not exist). This registry
is not an argument for building either — that is an owner decision — but it is
evidence for what the tracked backlog cannot tell you: **the remaining
uncertainty is increasingly about contact with reality rather than about the
code.**

**Maintenance.** When an item is settled, record the answer in its owning ECR and
strike it here. When a new item qualifies, add it here rather than letting it sit
in an ECR body reading as unresolved risk.
