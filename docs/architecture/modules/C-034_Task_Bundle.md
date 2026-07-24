# C-034 IS-037 Conformance — Implementation Task Bundle

**Milestone:** C-034 (IS-037 conformance, **ECR-0059**; no CAASM module)
**For:** Claude Code (implementer **and** reviewer during the Codex outage) · Codex (retroactive re-review on return)
**Prerequisites:** GC-002 merged & live (main @91b2f45); **corrected `IS-037_Conformance_Analysis.md` §6 read**; `SPEC_AUTHOR_NOTES.md` Part 1 rules 1–20 read; **ECR-0059 already landed in `ECR-LOG.md` — do not re-raise it.**
**Definition of Done:** proof test green on **both backends and both tenant modes**, under normal Python **and `python -O`**; `ruff` clean; **`mypy --strict src tests`**; worktree `pytest` with `PYTHONPATH=$PWD/src`; **`gh pr checks <n>` confirmed PASS before merge**; the ECR-0034 route recorded explicitly; Claude Code sign-off with self-verification disclosure (see review protocol §11).

**Read the corrected analysis §6 first.** IS-037 is the fifth distributed-
conformance case: CAASM ships across **EA-0023** (exposure/attack surface),
**EA-0024** (prioritization), **EA-0025** (inventory), **EA-0005** (graph), with
intake via **EA-0028/0029**. The `Cyber*` events are **0/9 in `src/`** — net-new
naming, not capability — and **GC-002 now fails CI the day anyone mints
`aqelyn.cyber.*`**, so §3's primary trap is mechanically closed.

**What is left is not the naming trap. It is the denominator.**

> This analysis certifies conformance by pointing at EA-0023's known-surface
> denominator and EA-0024's coverage base — both derived from `inventory()`, which
> reads `store.query(limit=10_000)`, returns **`degraded=False` unconditionally**,
> over a **cursorless** store. A tenant above 10 000 assets has its first 10 000
> reported as complete, and the `degraded`-keyed fail-closed gates **cannot trip**.
> **Certifying an exhaustive attack surface on a silently-capped read is the
> platform asserting something it cannot know.**

**Forbid list:** no package under `src/aqelyn/` for CAASM; no unified CAASM
engine; **no `Cyber*` event namespace**; no second composer/scorer over
assets → exposure → priority; no new `SignalKind`.

---

## M1 — Conformance verification against shipped code

**Source:** analysis §2.
**Deliverables:** confirm each ownership row at the current SHA with **real
engines**, not grep or spies:

- **EA-0023** — `derive_surface`, `list_known_surface`, `reachable_paths`
  (`exposure/engine.py:137,174,270`); package docstring.
- **EA-0025** — `InventoryIntelligenceEngine` (ingest / reconcile / ownership);
  package docstring.
- **EA-0024** — prioritization composing the reachability `PriorityFactor`.
- **EA-0005** — relationships; **EA-0028/0029** — `KnownSurfaceSource` /
  `KnownSurfaceRecord` intake.
- **`aqelyn.cyber.*` / `Cyber*` = 0 occurrences** in `src/`.

Any row that fails becomes a ticket here — **not** a reason to build a module.
**Acceptance:** `test_is037_owner_seams_present`, `test_is037_no_cyber_namespace`.

## M2 — **The one real decision: ECR-0034** (do this before M3)

**Source:** analysis §6. **Route (A) is preferred; §6.1 gives the reason.**
Record which route was taken and why, in the ECR-LOG and the analysis.

### Route (A) — fix ECR-0034 *(preferred)*

**Deliverables:** a more-remaining signal on `AssetStore.query` (**`limit+1` or
`has_more`** — the minimal honest signal), and `inventory()` setting
**`degraded=True`** when the cap is hit, so the existing `degraded`-keyed gates in
EA-0023/EA-0024 fail closed on a truncated denominator. Touch the store, the
engine, and **both** call sites (`engine.py:245`, `:169`, `service.py:115`);
**watch the EA-0024 coverage path.**

**Two things this ticket must get right (§6.2):**

1. **An honest flag is necessary but not sufficient.** Prove that **every**
   consumer of the capped denominator *demonstrably refuses or flags* — by
   **driving the chain past the cap**, never by observing that a gate mentions
   `degraded`. A gate that reads the flag and only logs it, or a third consumer
   that never reads it, leaves a truthful field nobody acts on: the **ECR-0013
   unwired-default shape**. Enumerate the consumers; assert each one.
2. **`limit+1` is not a cursor.** `limit+1`/`has_more` says *more exists* — the
   safety-critical half, and all that is required to stop the platform claiming
   completeness it lacks. **Completeness** needs cursor pagination (EA-0002 D8 /
   rule 10: page under a work budget, report `truncated`), which is a larger
   change with its own blast radius and **belongs in its own ticket.** Do not
   expand C-034 into it; do not let its absence block the honest flag.

**Rule 9:** check the persisted shape before treating any new field as additive.

### Route (B) — bounded residual *(only if (A) is not small and self-contained)*

**Deliverables:** the conformance claim recorded **explicitly bounded** —
*"IS-037 conformant for inventories ≤ 10 000 assets/tenant; above the cap the
denominator is silently truncated (ECR-0034, unresolved)"* — ECR-0034 left
**Proposed** with C-034 recorded as the ticket that re-confirmed it on the
critical path, and **§6.1's caveat recorded with it**: the bound is already
routinely exceeded via EA-0030 SBOM ingest, so (B) is a temporary posture with the
fix scheduled, **not a resting state**. **Do not certify unconditionally.**

**Either route:** M3 still exercises the >10k case, so the residual is
**demonstrated, not asserted.**

**Acceptance (A):** `test_inventory_degraded_when_capped`,
`test_is037_downstream_gates_refuse_on_degraded`, `test_inventory_cap_signal_shape`.
**Acceptance (B):** `test_is037_bounded_residual_demonstrated`.

## M3 — Real-runtime chain proof test

**Source:** analysis §7 item 4; mirror **C-033's** conformance-test shape.
**Deliverable:** one proof driving the **whole owner chain** — handed-in inventory
→ **EA-0023** known surface → exposure / reachable paths → **EA-0024**
vulnerability priority — with **no spies and no event-name greps**, asserting:

- **replay** determinism,
- **no-network** — no live collection; intake is handed-in per EA-0023's shipped
  boundary,
- **tenant isolation**,
- **unknown-not-safe** — unknown reachability/coverage is never the favourable
  result,
- **the >10k case** per M2's route.

**Placement:** the test's subject is the **chain**, not any one owner. Follow
C-033's precedent for where conformance proofs live; wherever it lands, it must
not be filed so as to imply that a single owner owns the IS-037 claim.

**Both backends, both tenant modes**, as the guarantee suites do.
**Depends on:** M2.
**Acceptance:** `test_is037_chain_replay`, `test_is037_chain_no_network`,
`test_is037_chain_tenant_isolation`, `test_is037_chain_unknown_not_safe`,
`test_is037_chain_matrix[...]`.

## M4 — Records

**Deliverables:** the **corrected `IS-037_Conformance_Analysis.md`** (ECR-0059;
§5 GC-002-enforced; **§6 ECR-0034 condition**) replacing the staged copy; the
ECR-0034 route recorded in `ECR-LOG.md` (status note for (B), or resolution for
(A)); README row — *IS-037 — conformant via EA-0023+0024+0025+0005*, status
**Analysis**, "see ECR-0059".

**If route (A):** announce the behavioural change (§6.3) in the PR description —
**deployments above 10 000 assets will see gates begin refusing where they
previously proceeded.** That is the **ECR-0040 situation again**: a correction
surfacing a pre-existing wrong answer, **not a regression**. Say it plainly before
someone reads the diff and misreads it.

---

## Review protocol (Claude Code)

1. **Conformance uses real engines** (M1) — every row exercised, not grepped.
2. **No CAASM module, no `Cyber*` namespace, no second composer** — and confirm
   **GC-002 actually fails** on a minted `cyber` prefix (verify by mutation; the
   guard's value is that it fires, not that it exists).
3. **The ECR-0034 route is explicit and recorded.** Certification must not read as
   unconditional under either route.
4. **If (A): the flag is honest AND acted upon.** Drive a >10k tenant; assert
   `degraded=True`, then assert **each enumerated downstream consumer refuses or
   flags**. A truthful field nobody reads is the defect, not the fix.
5. **If (A): scope held.** `limit+1`/`has_more` only; cursor pagination is a
   separate ticket and must not be smuggled in.
6. **If (B): the residual is demonstrated**, and §6.1's "bound already exceeded"
   caveat is recorded with it.
7. **Chain proof is real** — replay, no-network, tenant isolation,
   unknown-not-safe; both backends, both tenant modes, `python -O`.
8. **Rule 20** — nothing from Blueprint Volume_037's *Distributed Scan Engine* or
   the broad index's *Pre-Coding Baseline* enters scope. A matching number
   transfers no scope, and importing active scanning would **reverse EA-0023's
   no-scan boundary**.
9. **Rule 18/19 sweep** — Protocol changes reach every implementer including test
   doubles; no fixture reaches its assertion by performing a forbidden action.
10. `mypy --strict src tests`; `gh pr checks` PASS before merge.
11. **Self-verification disclosure.** With one actor implementing and reviewing,
    state on merge **which checks were independently constructed and which were
    self-verified against the same harness**, so Codex's retroactive review knows
    where to look first. Independence is the thing the two-actor loop supplied;
    naming its absence is the cheapest substitute.

**Preserve, do not absorb:** ECR-0032 (shared posture base, four instances),
**ECR-0034 (resolved here or re-confirmed)**, EA-0018 unclamped-duration flake,
EA-0027/EA-0018 enterprise health probes, EA-0013 equal-timestamp tie-breaker.

Merge only on green; then **report back to the owner** — including whether
EA-0038's master is another template stub, which decides whether the remaining
batch warrants per-module passes or one batch-level decision (analysis §8).
