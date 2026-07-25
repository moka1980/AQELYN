# C-038 — Final Backlog Milestone — Task Bundle

**Milestone:** C-038 (the four remaining tracked items, as one milestone)
**For:** Claude Code (implementer **and** reviewer during the Codex outage) · Codex (retroactive re-review on return)
**Prerequisites:** ECR-0032 closed (`main @a87908f`); `SPEC_AUTHOR_NOTES.md` Part 1 rules 1–24 read; `FIRST_DEPLOYMENT_ITEMS.md` read (three items here are **not** in scope — they are deployment-gated).
**ECR numbers:** **ECR-0063** reserved for R4's re-scoring decision *(provisional — my log copy ends at 0062; re-check `ECR-LOG.md` before assigning, rule 1)*. R1 may require a second number **if diagnosis finds a real defect** rather than a test artefact.
**Definition of Done:** green on **both backends and both tenant modes**, under normal Python **and `python -O`**; `ruff` clean; **`mypy --strict src tests`**; **`gh pr checks <n>` confirmed PASS before merge**; Claude Code sign-off with self-verification disclosure.

---

## Why one milestone

A flaky test, two unscoped health probes, a tie-breaker, and a scoring question do
not each warrant a bundle, an ECR cycle, and a review pass — the same
disproportion argument that produced the archive batch decision. Four tickets, one
of which is a **decision gate** rather than a defect.

**Worth naming what this milestone is:** the last one the backlog produces. After
it there is no code-shaped work outstanding, and the deferred structural questions
— live collection and the UI surfaces — stop being deferrable, not because
anything forces them but because nothing else remains to do instead.

---

## R1 — EA-0018 unclamped negative duration: **diagnose before clamping**

`response/metrics.py` can produce a negative duration, which surfaces as an
intermittent test failure.

> **Do not clamp it to zero to make the flake stop.** A negative duration is an
> **impossible value**. Clamping it presents an impossible reading as a
> legitimate instantaneous measurement — which is the **empty-means-safe family**
> (ECR-0013, ECR-0040) arriving in a new place: an unusable measurement rendered
> as a benign one, and the underlying cause made permanently invisible.

**Diagnose first.** A negative duration has three possible causes, and they need
different fixes:

1. **Wall-clock source** — `datetime.now()`-style timestamps can go backwards
   (NTP correction, container clock drift). Fix: measure durations from a
   **monotonic** source, so the value cannot be negative by construction. This is
   the structural fix and, if it is the cause, the right one.
2. **Events recorded out of order** — the end is stamped before the start
   somewhere in the campaign/step path. That is a **real ordering defect** in
   EA-0018, and clamping would have hidden it. Needs its own ECR.
3. **Test fixture supplying inverted timestamps** — a test-only artefact. Fix the
   fixture; production is fine.

**Deliverables:** the diagnosis, recorded; the fix appropriate to it. If a value
can still be negative after the fix, it is **refused or flagged**, never clamped —
`unknown`/invalid, not zero.

**Acceptance:** `test_response_duration_never_negative`,
`test_response_duration_source_is_monotonic` *(if cause 1)*, plus the
cause-specific test. The flake test must be run **repeatedly** (or with the
triggering condition forced) — a flake that passes once proves nothing.

## R2 — Enterprise-mode health probes: `idthreat_engine`, `response_engine`

Both currently **fail enterprise startup**. `create_inmemory_runtime()` defaults to
`tenant_mode="local"`, so driving the factory-built runtime proves nothing about
enterprise (rule 11). Services whose probes issue tenant-scoped queries need a
`_health_tenant()` helper; only a minority define one.

**Deliverables:** `_health_tenant()` on both services; acceptance criteria
parametrized `(backend, tenant_mode)`; **enterprise startup asserted**, not just
`local`.

### The part that matters more than the two fixes

Rule 11 exists *because* this was found once. Two services still have it wrong, so
the rule is **reviewer-enforced** and the next service to omit it will slip the
same way. That is precisely ECR-0057's argument: the refusal tests exist but are
decentralized, and **nothing fails when a new module omits one**.

> **Owner-gated option (do not build without approval).** A discovery-based
> guarantee AC — enumerate every registered `AQService` and assert each has a
> health test in **both** tenant modes; **negative control:** a service registered
> without one fails. GC-001's discovery machinery already exists, so this is small.
> It converts rule 11 from a convention into a mechanical check.

**Acceptance:** `test_idthreat_health[local]` / `[enterprise]`,
`test_response_health[local]` / `[enterprise]`; the GC AC only if approved.

## R3 — EA-0013 equal-timestamp tie-breaker

Equal timestamps currently produce **nondeterministic ordering**.

**This is not a pagination precondition** — the reviewer's audit established that
every paginating store orders by a unique key (`id` / `object_id`), so ties cannot
bite there. This is ordinary ordering determinism, and the general rule is:
**an ordering on a non-unique key needs a tie-breaker, or results vary across runs
and across backends.**

**The backend-divergence risk is the concrete one:** Python's `sort` is stable, so
the in-memory store may return insertion order on ties while Postgres returns
whatever the plan yields. The one-contract-suite guarantee exists to catch exactly
that — **and will not, if the fixtures contain no ties.**

> **The test must contain findings with identical timestamps.** A suite whose
> timestamps are all distinct **passes against the un-tie-broken implementation**,
> which is C-037's inert-control lesson (rule 24) in its next instance. Confirm by
> mutation: remove the tie-breaker and watch the test go red on **both** backends.

**Deliverables:** a deterministic secondary key (`id`) on the affected ordering;
both backends agreeing on tied input.

**Acceptance:** `test_finding_order_deterministic_on_ties[inmemory]` /
`[postgres]`, `test_finding_order_backends_agree_on_ties`.

## R4 — **Decision gate:** finding re-scoring (ECR-0063)

**Not a defect — an owner decision.** Dedup re-emission keeps the **original**
`severity_score`: a finding that recurs more severely is never re-scored, because
`_save` does not carry the new emission's score. That may be deliberate under
EA-0013's *history is not recomputed*, or a gap.

### The constraint that makes this non-obvious

**This decision is not independent of C-037.** ECR-0062's composite keyset cursor
is safe from the skip/duplicate hazard **because `severity_score` is write-once** —
that was verified from the code and it is what removed the need for an as-of bound
or a snapshot-of-convenience caveat.

> **Making `severity_score` mutable would reintroduce the exact hazard ECR-0062
> cleared.** A finding whose score changes between page reads can move across a
> page boundary and be skipped or duplicated. The re-scoring question therefore
> cannot be decided on its own merits alone — one of its options silently reopens
> closed work in another module.

### The three options

1. **Keep original (current).** Consistent with *history is not recomputed*; the
   cursor stays safe. **Cost:** a finding that recurs more severely is listed at
   its original, lower severity — a "most severe first" surface understates
   current risk.
2. **Update to latest.** The finding reflects current severity. **Cost:** loses
   the first-seen record **and** makes the sort key mutable, reopening the C-037
   hazard (as-of bound or documented snapshot caveat now required).
3. **Record both — recommended.** Keep `severity_score` **write-once** as the
   immutable sort key, and add a separate field carrying current or maximum
   observed severity across emissions. Ordering stays deterministic and the cursor
   stays safe; the escalation becomes visible to any surface that wants it.

**Recommendation: option 3**, because it is the only one that satisfies both
properties rather than trading one for the other. But this is the owner's call,
and the deliverable if 1 is chosen is equally valid: **record that the current
behaviour is deliberate**, so the next reader does not rediscover it as a gap.

**Deliverables:** ECR-0063 recording the decision and its C-037 interaction;
implementation only if option 2 or 3 is chosen. **Rule 9** applies to any new
field (check the persisted shape before calling it additive), and **rule 18** to
any signature change.

**Acceptance (option 3):** `test_finding_sort_key_still_write_once`,
`test_finding_escalation_recorded`, and a re-run of C-037's
`test_finding_cursor_ties_span_page_boundary` proving the cursor is unaffected.

## R5 — Records, and the Codex hand-back

**Deliverables:**

- ECR-0063 (R4's decision); a second ECR only if R1's diagnosis found a real
  defect.
- Strike closed items from the backlog line; **`FIRST_DEPLOYMENT_ITEMS.md` is
  untouched** — those three are not in scope here.
- **Collate the self-verification disclosures from C-034 through C-037 into one
  document.** Four milestones were implemented and reviewed by the same actor;
  the disclosures were written precisely so the retroactive pass would know where
  independence was absent. Four PR descriptions reconstructed from memory is a
  worse starting point than one list of *independently constructed* versus
  *self-verified*, and it is cheapest to assemble now, while the context is warm.

---

## Review protocol (Claude Code)

1. **R1 was diagnosed, not clamped.** The recorded cause is one of the three, and
   the fix matches it. A residual negative value is refused or flagged, **never
   zeroed**. The flake test was run repeatedly or with the condition forced.
2. **R2 asserts enterprise startup**, not just `local`, on both services. If the
   GC AC was approved, its **negative control fails** — verified by mutation.
3. **R3's fixtures contain actual ties**, and both backends agree on them. Remove
   the tie-breaker and confirm red on **both** — a test with distinct timestamps
   tests nothing (rule 24).
4. **R4's decision is recorded with its C-037 interaction stated.** If option 2
   was chosen, the cursor caveat is reopened explicitly and not left implicit.
5. **No scope growth.** The three `FIRST_DEPLOYMENT_ITEMS.md` entries stay out;
   the GC AC is built only if approved.
6. `mypy --strict src tests`; both backends; both tenant modes; `python -O`;
   `gh pr checks` PASS before merge.
7. **Self-verification disclosure**, and R5's collation delivered.

**Preserve:** the three first-deployment items (registry), and **EA-0048**
(recorded capability gap, unscheduled).

Merge only on green; then **report back to the owner**. With this milestone the
tracked backlog is empty, and the next decision is a product decision.
