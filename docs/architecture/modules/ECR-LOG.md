# Engineering Change Request (ECR) Log

Records approved changes to **Accepted** module specs, so amendments happen
under change control rather than silent edits (per `START_HERE.md`).

| ECR | Against | Status | Summary |
|---|---|---|---|
| ECR-0001 | EA-0005 Knowledge Graph | Accepted | Add a `max_work` enumeration budget to `paths()`. |

---

## ECR-0001 — `paths()` enumeration work budget

**Raised by:** Claude Code (post-EA-0005 review).
**Severity:** non-blocking hardening.

**Problem.** EA-0005 traversals are bounded, but the bound was uneven. The
Postgres CTE traversals are limited by `LIMIT` (max_nodes) and depth. The
Python-side `paths()` enumeration was bounded only by `max_depth` and
`max_paths` — on a dense graph it could expand a very large number of partial
paths before collecting `max_paths` complete ones, so worst-case effort was not
explicitly capped. This violates the spirit of EA-0005 D2 ("bounded, never
hang").

**Resolution.** Add `max_work: int = 50_000` to `paths()` (§6). It caps the
number of nodes/partial-paths expanded during enumeration; on reaching it,
`paths()` returns the paths found so far rather than continuing. Hard cap
`max_work ≤ 1_000_000`. Captured as **FR-13** and **AC-15**
(`test_kg_paths_work_budget`).

**Impact.** Additive, backward-compatible (new keyword arg with a default).
Implemented via C-002 follow-up ticket **G3a**. No change to other methods or to
the contract of already-passing tests.
