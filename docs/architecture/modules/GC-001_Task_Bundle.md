# GC-001 Central §0 Guarantee-Conformance Suite — Implementation Task Bundle

**Milestone:** GC-001 (guarantee-conformance track — **not** an archive module)
**For:** Codex (implementer) · Claude Code (reviewer)
**Prerequisites:** C-033 merged & green (main @a5696bf); **`GC-001-guarantee-conformance-suite.spec.md` §2 and §3 read**; **ECR-0057** decided by the owner; `SPEC_AUTHOR_NOTES.md` Part 1 rules 1–19 read; `src/aqelyn/workflow/` (EA-0008 `ActionSpec`/`ActionHandler`) read before starting GC2.
**Definition of Done:** all ACs green on in-memory **and** Postgres **and both tenant modes**, under normal Python **and `python -O`**; `ruff` clean; **`mypy --strict src tests`**; worktree `pytest` with `PYTHONPATH=$PWD/src`; **`gh pr checks <n>` confirmed PASS before merge**; **zero runtime surface added**; Claude Code sign-off per ticket.

**Read §1 first.** The reviewer's audit refuted the stronger worry: refusal tests
**mostly already exist** (~16 engines for detect-and-propose, five independent
integrity refusals, structural type-level guarantees). **ECR-0056 was the
exception, not the rule.** So GC-001 is **future-proofing** — making a *future*
module's omission fail — not back-filling the current 33. Scope discipline
matters: do not re-centralize what is already structural (§4.4).

**Three principles govern every ticket:**

1. **Discovery, never declaration (§2.1).** A hand-maintained registry
   reintroduces the exact gap GC-001 closes — a new module omitted from a list is
   silently unguarded. Enumerate from package structure; exemptions are an
   explicit allow-list with a reason per entry, because *adding* to an allow-list
   is visible while *omission* from a registry is not.
2. **Weakest form that catches the defect (§2.2).** An over-strong central
   assertion produces false failures on correct modules, and a suite that cries
   wolf gets `xfail`-ed or deleted — leaving the *appearance* of coverage, which
   is worse than none.
3. **Every AC ships its negative control (rule 19).** A guarantee test that only
   passes when the guarantee holds is untested. The control must **perform** the
   forbidden action, not assert about it.

> **No runtime surface.** No package under `src/aqelyn/`, no service, event,
> capability, `SignalKind`, or namespace. Enumeration helpers live in `tests/`,
> **never** in `conventions`. If this milestone touches `src/`, stop and raise an
> ECR.

## Target layout

```
tests/guarantees/
├── __init__.py
├── discovery.py          # package/scorer discovery + reasoned allow-list (GC1)
├── test_no_execute.py    # AC-1 + negative control (GC2)
├── test_signalkind.py    # AC-2 + negative control (GC3)
├── test_scorers.py       # AC-3 + negative control (GC4)
└── controls/             # negative-control stubs (rogue handler, bad kind, unguarded scorer)
```

**Nothing under `src/`.**

---

## GC1 — Discovery harness + no-runtime-surface guard

**Spec:** §2.1, FR-1/2/3, AC-1b, AC-4.
**Deliverables:** `discovery.py` enumerating every package under `src/aqelyn/*`
**from the filesystem**, so a new module is in scope the day it lands; an
**explicit allow-list with a stated reason per entry**; a guard asserting GC-001
adds no runtime surface.
**Do not** write a hand-maintained engine list.
**Acceptance:** `test_gc_engine_discovery_complete`, `test_gc_no_runtime_surface`.

## GC2 — AC-1: engine-no-execute registry *(load-bearing)*

**Spec:** §3, §4.1, FR-4/5/8.
**Deliverables:** the assertion that **EA-0008 `WorkflowEngine` is the only
production actor**, keyed on the **§3 two-part signature** — (a) outside EA-0008,
it can obtain an `ActionHandler` and directly call `execute`/`rollback`, or it
owns an alternate `ActionRegistry` and dispatches through it; **and** (b) the
effect lands on a **customer asset or external system**, not AQELYN's own storage.

**Method (preferred → supplement):** construct the kernel and assert every
registered `ActionHandler` is owned by EA-0008 and no module outside it can invoke
one except through the real `WorkflowEngine`; supplement with a structural scan
for direct handler invocation or alternate registry dispatch outside `workflow/`.
Connector implementations, kernel registration, proposal-only `ActionSpec`
construction, and calls through the real `WorkflowEngine` are safe by definition.

**These six MUST pass, by the definition and not by exemption:**
`cspm/baselines.py::apply`, `sspm/baselines.py::apply`, `cspm/route.py::apply`,
`sspm/route.py::apply` (all delegate to EA-0012/EA-0025), and
`lake/retention.py::apply` (EA-0019's own lifecycle — platform storage, fails part
**(b)**), plus `exposure/models.py::active_reachability_action_spec`
(proposal-only construction; fails part **(a)**).

**Do not match on method names or `ActionSpec` construction.** *Proposing* a run
is legitimate and universal; the discriminator is **direct invocation authority
outside EA-0008**.

**Negative control (must FAIL):** a stub engine owning an alternate registry,
registering an `ActionHandler`, and invoking it outside EA-0008.
**Depends on:** GC1.
**Acceptance:** `test_gc_only_workflow_executes`,
`test_gc_benign_apply_not_flagged`,
`test_gc_actionspec_reference_not_flagged`,
`test_gc_negative_control_rogue_handler`.

## GC3 — AC-2: `SignalKind` closure

**Spec:** §4.2, FR-6/8/9.
**Deliverables:** **(i)** a golden-set assertion freezing the membership of
`risk/models.py::SignalKind` and `dspm/models.py::ClassificationSignalKind`, so
silent widening fails and any change is a deliberate reviewed edit; **(ii)** a
runtime rejection test driving the **real construction/ingestion path** — because
a `Literal` is a **static** guarantee `mypy` enforces at authoring time, while
data from Postgres, JSON, or a handed-in descriptor is not type-checked and
carries whatever string it carries.
**Negative control (must FAIL):** a kind reaching the runtime path without being
added to the literal.
**Depends on:** GC1.
**Acceptance:** `test_gc_signalkind_frozen`, `test_gc_signalkind_runtime_rejected`,
`test_gc_negative_control_unregistered_kind`.

## GC4 — AC-3: scorer unknown-never-favourable registry

**Spec:** §4.3, FR-7/8/9.
**Deliverables:** discover the **composition scorers** (ISPM, credential/secrets,
and vulnerability priority — those with a known/unknown factor split) by
structural signature; fallback is a declared list **plus a completeness scan**
that fails when a structurally-matching scorer is missing (never a bare list).
EA-0030 supply chain supplies a reachability factor to EA-0024; it is not a
fourth scorer. Assert each ships an orientation-aware case proving **unknown is
strictly less favourable than known-good/safe**.

**Exclude `risk/scoring.py::score_risk`** — a bounded max/impact combinator with
no unknown lever; the property lives in its factor producers, which are covered.
Record the exclusion reason in the test.

> **Verified central form.** The brief's *"unknown strictly worse than
> known-bad"* does not hold universally: ISPM may place unknown equal to
> known-bad; credential governance places unknown below known-bad; vulnerability
> priority has the opposite score orientation and places unknown between proved
> unreachable and directly reachable. The central invariant is therefore
> orientation-aware: unknown is strictly less favourable than known-good/safe.
> Its relation to known-bad remains a per-scorer assertion. **Never weight-tune a
> correct scorer to satisfy the suite.**

**Negative control (must FAIL):** a stub composition scorer that maps unknown to
the favourable known result.
**Depends on:** GC1.
**Acceptance:** `test_gc_scorer_unknown_not_favourable`,
`test_gc_scorer_exclusion_documented`,
`test_gc_negative_control_unguarded_scorer`.

---

## Review protocol (Claude Code)

**Ask first:** ***does each negative control actually fail?*** A green suite whose
controls also pass is a suite that tests nothing — the rule-19 shape, one level
up. Verify by running each control and observing the failure, not by reading it.

Then:

1. **Discovery, not declaration** — confirm enumeration walks the package tree.
   Add a throwaway package under `src/aqelyn/` and assert GC-001 picks it up
   automatically; a hand-maintained list that misses it is the defect.
2. **AC-1 keys on invocation authority, not names or references** — confirm the
   five benign `apply` sites and proposal-only exposure `ActionSpec` pass
   **because they fail the §3 conjunction**, not because they're exempted. Then
   confirm the rogue-handler control fails.
3. **Unclassifiable ≠ skipped** — a package GC-001 cannot classify must **fail**,
   not be skipped; resolution is a reasoned allow-list entry (§7).
4. **AC-2 tests runtime, not just the annotation** — the rejection path must be
   driven with data (DB/JSON/descriptor), since `mypy` already covers the static
   case.
5. **AC-3 asserts the verified, orientation-aware form** — unknown is strictly
   less favourable than known-good/safe; its relation to known-bad remains local
   to each scorer. Confirm EA-0030 is treated as an EA-0024 factor source, not a
   fourth scorer, and no scorer was re-weighted to satisfy the test.
6. **No runtime surface** — nothing added under `src/aqelyn/`, nothing in
   `conventions`.
7. **No existing test weakened or duplicated** — per-module refusals remain the
   owners of their local guarantees (FR-11).
8. Both backends, both tenant modes, `python -O`; `mypy --strict src tests`;
   `gh pr checks` PASS before merge.

**Preserve, do not absorb:** ECR-0032 (shared posture base, four instances),
ECR-0034 (inventory cap), EA-0018 unclamped-duration flake, EA-0027/EA-0018
enterprise health probes, EA-0013 equal-timestamp tie-breaker.

Merge only on green review; then **report back to the owner** — after which the
sequence returns to **IS-037**, with the archive template-check first.
