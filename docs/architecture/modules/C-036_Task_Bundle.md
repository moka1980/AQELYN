# C-036 — ECR-0034 Cursor Half — Implementation Task Bundle

**Milestone:** C-036 (`AssetStore` cursor pagination; the open half of ECR-0034)
**For:** Claude Code (implementer **and** reviewer during the Codex outage) · Codex (retroactive re-review on return)
**Prerequisites:** C-035 merged & green (`main @3334fe7`); **ECR-0061** decided by the owner *(verified free at 3334fe7 — re-check before assigning, rule 1)*; `SPEC_AUTHOR_NOTES.md` Part 1 rules 1–21 read; **`ispm/engine.py::_identity_for_account` read before writing the loop.**
**Definition of Done:** all tickets green on **both backends and both tenant modes**, under normal Python **and `python -O`**; `ruff` clean; **`mypy --strict src tests`**; worktree `pytest` with `PYTHONPATH=$PWD/src`; **`gh pr checks <n>` confirmed PASS before merge**; C-034's guards rewritten **deliberately**, not deleted; Claude Code sign-off with self-verification disclosure.

---

## The framing that must survive into the code

> **Cursor pagination does not remove `degraded`. It moves the threshold.**

C-034 made `inventory()` refuse rather than lie above 10 000 assets. This milestone
raises the point at which the platform still has to say *"I could not read it
all"* — tenants between 10 000 and the work budget get **answered** instead of
correctly refused. A tenant larger than the budget is **still a truncated read**
and must still flag or refuse.

**Do not describe this milestone as closing ECR-0034.** A work budget that
truncates is still a cap — a better-behaved one. The honest description is
*"silent cap at 10 000 → explicit budget at N with truncation reported,"* which is
rule 10 verbatim. A PR titled "closes ECR-0034" produces an implementation that
re-opens the original defect at a higher number.

**This is conforming to a house pattern, not designing one.** The cursor shape
already ships in four modules (`findings/store.py:44`, `ispm/postgres.py:192` /
`memory.py:107`, `secrets/postgres.py:165` / `memory.py:97`,
`ispm/normalize.py:74`). `AssetStore` is the outlier. Mirror
**`ispm/engine.py::_identity_for_account`** exactly — it already solves the three
things a naive loop gets wrong: a **work budget** bounding total rows,
`min(100, remaining)` bounding each page *and* preventing budget overshoot, and a
**repeated-cursor check** that turns a malfunctioning store into a refusal instead
of an infinite loop. Deviating buys nothing and costs a second pattern to review
forever.

---

## The owner decision: refuse or flag-and-return-partial at budget exhaustion

**The number is not the decision** — `InventoryConfig` (`inventory/models.py:354`)
already carries `max_relationship_work = 50_000` with a `_positive_int` validator,
so `page_budget` has a home; ISPM uses `10_000`. **The decision is what happens
when the budget is exhausted.**

**Recommendation: flag and return the partial.** Reasoning, for the owner to
accept or override:

1. **Downstream behaviour is identical either way.** C-034 established that
   `degraded=True` already causes the known-surface and coverage consumers to
   refuse. So a flagged partial becomes a refusal one layer up **without touching
   the gates** — which is the change the brief rightly says must not be smuggled
   in.
2. **It is strictly more informative at zero safety cost.** A producer-side
   refusal tells the caller nothing about *how much* was read. A flagged partial
   says *"here are 50 000 assets, coverage incomplete"* — actionable (raise the
   budget, or the estate genuinely is that large). The refusal destroys that
   information for no gain, because the gates refuse to **score** on it either way.
3. **The refusal is the producer deciding something that belongs to the caller.**
   `sweep_unreported` requires exhaustion; the coverage gates require
   completeness; a listing surface does not. If the producer refuses, it
   forecloses the legitimate callers. Returning partial + flag lets each caller
   apply its own correctness requirement — the same principle as *one capability,
   one owner*.

**The residual risk is a *future* consumer that ignores `degraded`.** Mitigate by
recording, with the enumerated consumer list from C-034, that **any new consumer
of `inventory()` must read `degraded`** — and keep every existing one
mutation-verified (rule 21).

**If the owner prefers refuse**, that is defensible for consistency with C-034 and
`sweep_unreported`, and the bundle works unchanged apart from P2's exhaustion
branch. State the choice in the ECR either way; do not leave it to the
implementer to discover.

---

## P1 — `AssetStore` protocol, implementations, **and every double** (one ticket)

**Rule 18 requires these together.** A Protocol change that lands without its
implementers leaves doubles that keep assertions green while testing a different
call shape — the C-030 case.

**Deliverables:** `AssetStore.query` becomes
`(..., cursor: str | None = None, limit: int) -> tuple[list[AssetRecord], str | None]`,
mirroring the house shape. Update **production**: `inventory/store.py` (Protocol),
`inventory/memory.py`, `inventory/postgres.py` — with EA-0002 D8 semantics (stable
id order, **exclusive** cursor, `next_cursor` non-null **exactly when** another
matching row exists, filters applied **before** `LIMIT`).

**Sweep every double in the same ticket:** `tests/inventory/test_inv_n3.py`,
`tests/secrets/test_secrets_w2.py`, `tests/sspm/test_sspm_z3.py`,
`tests/dspm/test_dspm_p2.py`, `tests/dspm/test_dspm_p3.py`, and
`tests/conformance/test_is037_caasm_chain.py::_LimitRecordingAssetStore`.

> **`mypy --strict src tests` catches signature drift but not behavioural
> vacancy.** A double that returns `(rows, None)` on the first call satisfies the
> new signature perfectly and type-checks clean **while never exercising the
> loop**. Six conforming doubles can test nothing at all. So each updated double
> must actually **exercise the contract** — return a cursor, then exhaust — and
> the check is **mutation**: break the paging loop and confirm each module's tests
> go red, not only inventory's. This is C-034's "honest flag is necessary but not
> sufficient" one level over.

**Acceptance:** `test_asset_store_cursor_contract[inmemory]` / `[postgres]`,
`test_asset_store_d8_semantics`, `test_asset_store_doubles_exercise_paging`.

## P2 — Engine paging loop + `page_budget`

**Deliverables:** replace the capped reads at `inventory/engine.py:263`
(`inventory()`) with the **house paging loop**, mirroring
`_identity_for_account`: work budget from `InventoryConfig.page_budget`,
`min(100, remaining)` page sizing, **repeated-cursor guard raising
`StoreUnavailable`**. Add `page_budget` to `InventoryConfig` with the existing
`_positive_int` validator.

**Exhaustion branch per the owner's decision above** — partial + `degraded=True`
(recommended), or refuse. **Below the budget, `degraded` must become `False` where
it was previously `True`** — that is the user-visible win, and it needs its own
assertion.

**Acceptance:** `test_inventory_pages_to_exhaustion_under_budget`,
`test_inventory_below_budget_not_degraded`,
`test_inventory_budget_exhausted_behaviour`,
`test_inventory_repeated_cursor_refused`.

## P3 — `sweep_unreported`: **exhaust or refuse, never partial**

**The sharpest correctness edge in the ticket.** `sweep_unreported`
(`inventory/engine.py:178`) refuses today because a half-sweep marks **live assets
as unreported** — the *absence ≠ decommission* error EA-0025 exists to prevent.

Under paging it can finally sweep a large tenant — **but only on exhaustion.**

**The apparent dilemma and its resolution:** respecting a truncating budget
produces a partial sweep (catastrophic); ignoring the budget produces an unbounded
scan (rule 10 forbids trading a silent cap for unbounded per-request scanning).
Neither is required. **Page under the budget, and refuse if the budget is
exhausted before the store is.** Work stays bounded; a partial sweep is never
produced. Exhaustion is a *precondition* for sweeping, not a target to approximate.

**Acceptance:** `test_sweep_unreported_exhausts_and_sweeps`,
`test_sweep_unreported_refuses_when_budget_exhausted`,
`test_sweep_never_marks_on_partial_read`.

## P4 — Guards: rewrite C-034's deliberately, re-verify all four consumers

**Deliverables.** C-034's `test_inventory_call_sites_pass_the_production_constant`
pins `_ASSET_QUERY_CAP == 10_000` and asserts both capped reads request
`_ASSET_QUERY_PROBE`. If the cursor replaces the probe, that test is **rewritten
deliberately and visibly — never deleted because it went red.**

> **The replacement must pin the same property one level up:** that the paging
> loop uses the **production budget constant**, not a literal. A drift guard that
> goes red during a refactor is the single most likely thing to be quietly
> dropped, and C-034's mutation-verified protection would evaporate in the very
> change that made it necessary. Mutation-verify the replacement both ways —
> raising the constant fails; a call site reverting to a literal fails.

Same treatment for `test_inventory_degraded_when_capped` and the boundary test at
exactly 10 000.

**All four consumers stay wired (rule 21):** known-surface refuses, coverage
refuses, the ISPM note flags, the service passes through. **Mutate each consumer,
not only the producer** — this is the rule that C-034 earned by finding a consumer
wired in prose but not in code.

**Acceptance:** `test_inventory_budget_constant_pinned`,
`test_inventory_consumers_still_act_on_degraded[*]`.

## P5 — Proof

Mirror C-034: **real engines, real stores, no spies**, both backends, both tenant
modes, `python -O`.

**The proof must exercise a tenant larger than the page budget** — not merely
larger than one page. One-page-plus proves the loop iterates; it does not prove
the budget holds. Include a store returning a **repeated cursor** and assert the
refusal.

**Proof-cost decision — stated here rather than left to the implementer.** If the
budget lands at 50 000, a 50 001-row fixture is disproportionate on *both*
backends, not just Postgres. **Use a reduced `page_budget` in the test config**
(e.g. `page_budget=5` against 6 rows) to exercise the exhaustion logic, **paired
with P4's constant pin** so the reduced-budget test cannot drift from the shipped
value. That is exactly C-034's pattern — small-N shape proof plus a production
constant pin — and it is the right answer again. Do **not** insert 50 001 rows.

**Acceptance:** `test_inventory_cursor_proof[inmemory]` / `[postgres]`,
`test_inventory_cursor_proof_optimized_python`.

---

## Review protocol (Claude Code)

1. **Threshold moved, not removed.** Confirm nothing claims ECR-0034 is closed;
   above-budget reads still flag or refuse. Assert the win explicitly: a tenant
   between 10 000 and the budget now returns `degraded=False`.
2. **House pattern followed** — budget, `min(100, remaining)`, repeated-cursor
   guard. No second pagination idiom introduced.
3. **Doubles exercise paging, not just the signature** (P1). Mutation: break the
   loop; every affected module's tests go red. `mypy` green is necessary, not
   sufficient.
4. **`sweep_unreported` never partially sweeps** — exhaust or refuse, proven at
   the budget boundary.
5. **C-034's guards rewritten, not dropped**, and the replacement pins the
   production constant — mutation-verified both ways.
6. **Rule 21** — all four consumers mutated individually.
7. **Rule 20** — cite **ECR-0038** for the paging-under-budget *shape* only; it is
   not scope, and the archive's EA-0038 (Vulnerability Intelligence Correlation)
   is unrelated to both.
8. **The exhaustion decision is recorded in the ECR**, not implied by the code.
9. `mypy --strict src tests`; both backends; both tenant modes; `python -O`;
   `gh pr checks` PASS before merge.
10. **Self-verification disclosure** — state which checks were independently
    constructed and which were self-verified, for Codex's retroactive pass.

**Preserve, do not absorb:** ECR-0032 (shared posture base), EA-0018
unclamped-duration flake, EA-0027/EA-0018 enterprise health probes, EA-0013
equal-timestamp tie-breaker, **EA-0048** (recorded capability gap, unscheduled).

Merge only on green; then **report back to the owner**. With this landed, the
tracked backlog is the four remaining follow-ups — and the two structural gaps
every spec defers, **live collection** and **the UI surfaces**, become the next
real decision.
