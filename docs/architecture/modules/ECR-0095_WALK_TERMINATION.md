# ECR-0095 — Walk Termination Guards (a predicate defect must fail, not hang)

**Status:** Accepted
**From:** claude.ai (spec author), from Claude Code's brief verified at `main @cb99ea6`
**Date:** 2026-08-03
**Number:** 0095 per rule 1, re-checked against `ECR-LOG.md` in the implementation branch.

---

## 1. Classification — witness-quality defect, house-wide idiom, production correct

ECR-0094 R4's measurement across the four widened reads produced neither green nor clean
red: **eight of eight `>` → `>=` predicate mutations hang** (four reads × two stores, killed
at 90 s), while ECR-0094's findings witnesses catch the identical defect cleanly — which
isolates the cause to the test idiom, not the shipped code. **Every shipped predicate is
correct.** Under `>=` the boundary row repeats and `next_cursor` never becomes `None`; the
witnesses' unbounded `while True:` loop then spins, and in CI the failing test becomes a job
timeout — the signal survives, the diagnosis does not.

The tree sweep makes it 14 unbounded cursor walks in 11 files, not four: **Group A**, the
arc's seven witness loops (the eight measured hangs); **Group B**, seven walks outside the
arc sharing the same production construction (`dspm/memory.py:169` is the identical shape),
whose predicates nobody has ever mutated — including two that deserve their names in the
record: `tests/surface/test_surface_api.py:311`, which walks **findings over HTTP** (so the
surface-level walk is unguarded even though ECR-0094 guarded the store-level one), and
`tests/conformance/test_finding_cursor_contract.py:255`, a **cursor-contract test that
cannot survive a cursor defect**.

## 2. Requirements

**R1 — Every cursor walk in `tests/` is bounded.** All 14 sites, using the two shapes —
mandating one would make several walks unimplementable:

- **known N** (all of Group A carries an `expected` list):
  `for _page in range(len(expected) + 2): ... else: raise AssertionError(...)` — the
  ECR-0094 pattern verbatim;
- **unknown N** (the surface HTTP walk pages an uncounted total; the read-services walk uses
  `limit=1`): a named module-level constant (`MAX_WALK_PAGES`), generous enough never to
  fire on a healthy walk, same `else: raise AssertionError(...)`.

**The assertion message names the walk** — a future timeout-turned-assertion must be
diagnosable from the CI log alone. Whether the 14 sites share one helper is the
implementer's call; the naming requirement is not.

**R2 — Acceptance: the eight Group A mutations go from ⏱️ HANG to 🔴 clean RED.** Directly
measurable, re-run by the reviewer at review, results in the PR description. This is the
whole ECR's pass/fail.

**R3 — Group B's status, recorded honestly: guarded-but-unwitnessed, coverage deferred with
grounds.** After R1 all seven Group B walks terminate on defect, but their keyset predicates
remain unmutated by anyone. Per ECR-0092 §1's standing rule that sentence is the named
coverage, and the deferral grounds are the reviewer's: R1+R2 is a clean mechanical ECR;
extending mutation coverage to five more domains is its own arc. **Priority marker for that
arc:** the surface HTTP findings walk and the findings cursor-contract test lead it — the
first because a store-level witness does not guard the HTTP layer above it, the second
because a conformance test that hangs on the defect it exists to catch is the §1 failure
mode in its purest form.

**R4 — Amend ECR-0094 R4's wording, via ECR-LOG amendment row.** From *"any green result is
recorded as a follow-up finding"* to *"any result that is not a clean RED"* — a hang is not
green, and it is exactly the case that occurred. The amendment cites this ECR as the worked
example.

**R5 — No weakening.** The carried matrix is now **29 mutations** (19 from ECR-0090–0093,
10 from ECR-0094); all stay in force and the reviewer re-runs them at review. Expected
effect of R1 on the carried matrix: none — bounded walks change how witnesses *fail*, never
what they *catch*; any carried mutation whose verdict changes under R1 is a review-blocking
finding.

## 3. Carried constraints

Tests only; zero `src/` changes — the production pagination shape (`WHERE key > cursor`,
`next_cursor = last if len(rows) > limit else None`) is correct and explicitly out of
bounds. Reads-only, loopback, no new dependency, GC postures untouched. ECR-0034 · ECR-0061
· ECR-0062 · ECR-0063 · rule 33 · all prior method notes.

## 4. Method notes carried into the record (the brief's three, kept whole)

- **A mutation harness needs a HANG verdict, not just RED and GREEN.** "The test never
  finished" is diagnostically distinct from "the test passed"; a harness that cannot say so
  will eventually mislead its operator. The reviewer's 90-second cap treating `rc == 124`
  as its own result is the reference shape.
- **A test that hangs instead of failing is a harness with only one outcome** — it reports
  "something is wrong" without reporting what. Bounding the walk converts an infrastructure
  symptom back into a test result.
- **A defect found in one member of a family is a question about the family.** ECR-0094
  fixed the idiom where the work happened; the same idiom sat in 14 places. Every fix
  written against a shared pattern owes the tree a sweep.

## 5. Outcome

All 14 cursor walks in `tests/` are bounded and name themselves on non-termination. The eight
Group A predicate mutations now fail with clean assertions instead of hanging; Group B is
guarded-but-unwitnessed with its follow-up arc named. Production code and pagination semantics
are unchanged. Claude Code independently re-runs the eight hang-to-red controls, the 29 carried
mutations, and healthy-corpus bound checks before merge.
