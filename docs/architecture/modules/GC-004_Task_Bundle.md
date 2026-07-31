# GC-004 — Persisted-Field Consumers — Task Bundle

**Track:** GC (guarantee conformance)
**Milestone:** GC-004 — implements **ECR-0085**
**For:** Codex (implementer) · Claude Code (reviewer + merge)
**Prerequisites:** `main @ee98a18`; **rule 33 landed** (`SPEC_AUTHOR_NOTES.md:403`, owner 2026-07-31); **ECR-0085 read in full** — §3 and §4 especially.
**Definition of Done:** every field a store writes lands in exactly one classification; both registries pinned by equality; **the discriminating control fails a two-state implementation**; every mutation **run**, not merely specified; test-only, no runtime surface; `mypy --strict src tests`; `gh pr checks` PASS.

**Two documents, not three.** **ECR-0085 is the spec of record**; this is the implementation
path. GC-001 and GC-002 each carry a separate `.spec.md` as well — **GC-004 deliberately does
not**, because a guard with a spec, a bundle *and* an ECR is **three places for one claim to
drift**.

*(An earlier draft cited GC-003 as a cautionary example here. **ECR-0085 §8.1 is withdrawn** —
GC-003's assertion is recorded in `C-038_Task_Bundle.md` and `ECR-LOG.md:3315`. If anything it
is mild evidence **for** fewer documents: one recorded assertion, found and checked without
difficulty.)*

---

## The guarantee, in one sentence

> **Every field a store writes has a reader outside its owning package — or a recorded reason
> why it does not, or a recorded note that its reader cannot yet be reached.**

## What this guard does **not** claim

**It reports a census, not a clearance.** It does not assert *"the gap is closed"*, because
that claim is not available to it (ECR-0085 §3).

**Named limit, to be carried in the module docstring:** the guard **cannot detect undeclared
dormancy.** A reader that exists but is unreachable, and is not declared, classifies as
`consumed` and the guard is wrong. **The countermeasure is review-time** — a field gaining its
first reader requires a dormancy determination at that moment.

**Do not restate rule 33.** GC-004 enforces its persisted-field subset; the rule's text lives
in `SPEC_AUTHOR_NOTES.md` and duplicating it is how the two drift apart.

---

## H1 — The population: fields a store **writes**

**Enumerate from store INSERT/UPDATE column lists, across both backends.**

**Why write-defined and not schema-defined** (ECR-0085 §2, carry the reasoning into the
docstring): **the guard's claim is that the system does work nobody consumes. Work is
writing.** A DDL column defines **capacity**; a write defines **maintenance**.

**Two consequences to preserve, not paper over:**

- **Both backends are in scope**, so the memory-only blind spot of a DDL-based population does
  not arise.
- **If the two backends write different field sets, the guard surfaces it.** That is a contract
  divergence the one-suite requirement should already have caught — **a hit there is a finding,
  not a false positive.** Do not normalise it away.

**Reuse** `aqelyn_source_root()` and `source_python_files()` (`tests/guarantees/discovery.py`).

**Acceptance:** `test_gc004_population_is_write_defined`,
`test_gc004_backend_write_divergence_surfaces`.

## H2 — The reader detector

**Does a reader exist outside the owning package?** Mechanical, and the only part of the
classification that is computed rather than declared.

**Reuse `discover_packages()`** (`discovery.py:60`) — already tested against a temp root where a
package arriving later **must** appear, which is the property that keeps this
discovery-not-declaration.

**Acceptance:** `test_gc004_reader_outside_owning_package_detected`,
`test_gc004_reader_inside_owning_package_does_not_count`.

## H3 — Two registries, both pinned

| registry | for | reason required |
|---|---|---|
| **dormant** | a reader exists, no shipped path reaches it with the data it reads | **yes** |
| **exempt** | no external reader by design (internal bookkeeping) | **yes** |

**Copy the shape of `EXECUTION_SCAN_EXCLUSIONS`** (`discovery.py:17`) — a dict of
`field → reason`, **pinned by an equality assertion against a literal**, so an entry cannot be
added quietly. **Without the pin the reasons rot silently**, which is the whole point of
requiring them.

**`current_severity_score` is the first `dormant` entry.** Reason: *the only divergence point is
re-emission (`findings/memory.py:86-87`), and the shipped report path constructs a fresh store
per run (`reporting/analyze.py:192-196`).*

**Acceptance:** `test_gc004_dormant_registry_pinned`, `test_gc004_exempt_registry_pinned`,
`test_gc004_registry_entry_without_reason_rejected`.

## H4 — The classification must be **inspectable** — build this before H5

**This is the load-bearing design requirement and it is not optional** (ECR-0085 §4).

**A two-state implementation and a three-state one agree on every pass/fail outcome.** `dormant`
passes; `consumed` passes. **The distinction is invisible to an exit code**, and lives entirely
in what the guard **records**.

> **So the guard must expose its classification per field.** Without that, the three-state
> model is **unfalsifiable and ships as decoration** — a close relative of the defect it exists
> to catch.

**Deliverable:** a function returning `field → classification` for the whole population, usable
by tests. Not a print, not a log line — **a value the controls can assert on.**

**Acceptance:** `test_gc004_classification_is_returned_not_printed`.

## H5 — Controls, and only one of them discriminates

**Reuse `tests/guarantees/controls/`** — modules that *perform* the forbidden thing.
`health_service.py`'s docstring is the pattern: *"If the guarantee is neutered, this control
stops failing."*

| control | asserts | discriminates? |
|---|---|---|
| a written field with **no reader** | the guard **fails** | **no** — a two-state guard fails it too |
| a written field with a **declared-dormant** reader | the guard **passes** | **no** — two-state passes it too |
| **a declared-dormant field classified `dormant`, not `consumed`** | **the classification** | **YES** |

> **Only the third separates the specified rule from the rule someone would plausibly write
> instead.** The first two are necessary and prove nothing about the design.

**This is the §4.3 lesson generalised** — a 1-ULP fixture proved only that noise is suppressed,
which `math.isclose` also achieves. **A control must sit where the specified rule and the
plausible alternative disagree**, and here that is the **classification**, not the outcome.

**Acceptance:** `test_gc004_control_no_reader_fails`,
`test_gc004_control_declared_dormant_passes`,
`test_gc004_control_dormant_classified_dormant_not_consumed`.

---

## Mutations — **run them**, do not merely list them

Rule 24 is explicit: **a control never run against a broken implementation is an untested
test.**

| mutation | expected |
|---|---|
| collapse `dormant` into `consumed` | **the discriminating control goes red** |
| drop the reason requirement on either registry | red |
| remove the equality pin on either registry | red |
| classify readers **inside** the owning package as consumers | red |
| populate from DDL columns instead of writes | red — a memory-only written field goes undetected |

**Record the run, not the intention.**

## Constraints

- **Test-only, no runtime surface** — as GC-001 and GC-002 are recorded in `README.md`.
- **Both registries pinned by equality assertion.**
- **No rule-33 text duplicated.**

## Review protocol (Claude Code)

1. **The classification is inspectable** (H4) — check first; the three-state model cannot be
   tested without it, and everything below depends on it.
2. **The discriminating control exists and was run against a collapsed implementation** — a
   green suite with only the first two controls proves nothing about the design.
3. **Population is write-defined**, both backends, and backend divergence **surfaces** rather
   than being normalised away.
4. **Both registries pinned**; no entry without a reason.
5. **`current_severity_score` classifies `dormant`**, with its reason recorded.
6. **The named limit is in the docstring** — the guard cannot detect undeclared dormancy, and
   nothing in the module or its output reads as a clearance.
7. **No rule-33 restatement.**
8. `mypy --strict src tests`; `gh pr checks` PASS.

## Carried forward, not folded in

**GC-003's record — ECR-0085 §8.1 is WITHDRAWN.** An earlier draft of this bundle claimed
GC-003's assertion was unrecorded. **It is recorded** — `C-038_Task_Bundle.md` carries its
guarantee and negative control, and `ECR-LOG.md:3315` records it as owner-approved with its
scope, discovery model and mutation-proven control. **No retrospective spec is warranted.**
What remains is a **findability** gap — the record sits in a milestone document rather than a
guard one — closable by a one-line docstring cross-reference in
`tests/guarantees/test_service_health.py`. **Not GC-004's job.**

**The §4.3 sub-display test — raised in ECR-0085 §8.2 and CLOSED by PR #278.** The fixture now
uses a **±0.0004** divergence and **explicitly rejects `math.isclose`**. Carried here only
because the reasoning is H5's: **a control must sit where the specified rule and the plausible
alternative disagree**, not at the minimum magnitude that separates the rule from no rule.
