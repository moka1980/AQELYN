# Self-verification disclosures — C-034 through C-038

**Purpose:** during the Codex outage, five consecutive milestones were **implemented and
reviewed by the same actor** (Claude Code). The two-actor loop supplies independence;
naming where it was absent is the cheapest substitute. This is the starting point for
Codex's retroactive pass.

**How to read it.** *Independently constructed* means the check was derived from shipped
code before, or against, the spec that commissioned it — a second source of truth was
involved. *Self-verified* means the code and the test asserting it were written in one
pass by one actor, with mutation testing as the only independence. **Mutation proves a
control fires; it does not prove the control is the right one.** The third column is
where to look first.

| Milestone | Merged | Subject |
|---|---|---|
| C-034 | `2b003e4` | ECR-0034 silent truncation → honest `degraded` |
| C-035 | `3334fe7` | EA-0038–0050 batch conformance (ECR-0060) |
| C-036 | `4c4b642` | `AssetStore` cursor pagination (ECR-0061) |
| C-037 | `2ea087e` | `FindingStore` cursor (ECR-0062) |
| C-038 | *this PR* | final backlog milestone (ECR-0063) |

---

## C-034 — ECR-0034, the honest flag

**Independently constructed.** The shipped-code analysis of ECR-0034 — cap sites,
cursorless store, consumer enumeration — was derived from the repo *before* the task
bundle arrived, and found the third consumer (`ispm/engine.py`) and the third cap site
(`engine.py:169`) that the brief did not list. The §6.1 SBOM claim was verified against
`supplychain/engine.py:212` rather than accepted from the analysis.

**Self-verified.** The conformance tests and the code they exercise were written in one
pass. Mutation testing is the substitute — and it earned its place: **mutation 3
initially did not fail.** The ISPM consumer read `degraded` and a docstring claimed
coverage, and neither was true. A control was added and the docstring corrected.

**Look first at:** whether refusing in `sweep_unreported` (rather than flagging) is right
for callers expecting a list; and that the >10k proof was memory-backend-only, with the
Postgres probe shape proven separately at small N.

## C-035 — batch conformance

**Independently constructed.** The whole capability map. All eleven owner confirmations
were read from shipped package docstrings and exports rather than accepted from the
analysis table, which produced **two corrections**: EA-0046's row was titled "Compliance
Assurance" when the archive reads *"Control Validation & Continuous Assurance Engine"*,
and the EA-0048 grep reported as hitting "only `secrets/`" was a substring artefact —
bare `llm` matching `fullmatch(`. The precise term list returns **zero hits anywhere**,
which matters because "hits only in `secrets/`" reads as partial coverage.

**Self-verified.** The two guard tests and the records they support were written in one
pass.

**Look first at:** whether `test_batch_ea0048_no_owner`'s term list is the right net — it
is a keyword guard, so AI-governance code under unanticipated naming would pass it; and
whether EA-0046 and EA-0049, the two rows resting on the broadest owner (`governance/`),
deserve firmer evidence than a docstring plus API surface.

## C-036 — `AssetStore` cursor

**Independently constructed.** The implementer/caller enumeration, via `mypy --strict`
after establishing that grep had produced a wrong list twice. The `len()`-on-tuple
discovery came from the suite rather than from review. The D8 cursor-contract test and
the mutation battery.

**Self-verified.** The paging loop and the tests exercising it, written in one pass.

**Look first at:** whether `page_budget = 50_000` suits the largest expected estate — it
is now the refusal threshold for `sweep_unreported`, so **too low is a functional
regression, not merely conservative** (registered in `FIRST_DEPLOYMENT_ITEMS.md`); and
that only the memory backend exercises the multi-page loop at scale.

## C-037 — `FindingStore` cursor

**Independently constructed.** The implementer enumeration via the Protocol-break
technique — temporarily breaking the signature and reading what `mypy` named — which
established that **no `FindingStore` doubles exist at all**. The fixture
anti-correlation, which came from the negative control *failing to fail* rather than from
review.

**Self-verified.** The cursor predicate and its tests, written in one pass.

**Look first at:** whether Postgres actually **seeks** on the extended index rather than
filtering — asserted structurally, not by reading a query plan (registered in
`FIRST_DEPLOYMENT_ITEMS.md`); and that `DROP INDEX` takes a lock, so a live migration
needs the concurrent variants.

## C-038 — final backlog milestone

**Independently constructed.** The R1 diagnosis — the mixed-time-base cause was found by
reading the fixture and demonstrated by forcing the condition, and it surfaced a
**shipped** clamp (`max(0.0, ...)`) that the bundle had not named. The R3 audit
establishing that **every** ordering in `src/` already terminates in a unique key, which
turned that item from *implement* into *already met*. The two enterprise-startup failures
were confirmed by reverting the fix and watching the kernel refuse to start.

**Self-verified.** GC-003 and the code it checks; the `current_severity_score` field and
its tests; the ordering-determinism suite. All mutation-verified, none independently
reviewed.

**Look first at:**

- **GC-003's scope.** It asserts every registered service is *ready*, which is stronger
  than the bundle's "has a health test" but still only covers services reachable through
  `create_inmemory_runtime()`. A service registered by some other path is invisible to it.
- **`current_severity_score` semantics.** *Latest emission*, not *maximum observed*. If a
  "never let a finding look less severe than it has been" requirement exists, this is the
  wrong choice and the field would need `max()` instead.
- **R1's residual.** `_elapsed_seconds` returns `None` for impossible pairs, so they are
  excluded from the mean. Nothing yet **surfaces** that an exclusion happened — a caller
  cannot distinguish "no data" from "data that was unusable". That was judged out of
  scope; it may not be.
- **R3's coverage.** The tie fixtures cover `vuln` (`discovered_at, id`). The audit
  covered every ordering by reading, but only one is pinned by a tie test.

---

## The pattern worth carrying into the retroactive pass

Across five milestones, **every defect found in review was found by executing something,
not by reading it.** The `len()`-on-tuple breakage passed `mypy --strict`. C-037's tie
test passed against the implementation it was written to catch. The cursor suites passed
against a store with no ordering at all. C-034's ISPM consumer was wired in prose and not
in code.

In each case the artefact looked right. What distinguished the real proofs from the
vacuous ones was running them against a broken implementation — which is now rules 21,
23, and 24. **Reading these disclosures is not a substitute for re-running the mutations;
it is a map of where they are most likely to be inert.**
