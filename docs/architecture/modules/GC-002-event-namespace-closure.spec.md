# GC-002 — Event-Namespace Closure Guard — Implementation Specification

**Track:** GC (guarantee conformance) — **not** an archive module
**Depends on:** GC-001 (merged, live in CI — inherits its principles and shape); `src/aqelyn/events/registry.py` (`EventTypeRegistry`, `UnknownEventType`, `CORE_EVENTS`); the constructed runtime
**Consumed by:** CI — every future module passes through it
**Status:** Accepted
**Build milestone:** GC-002 (see `GC-002_Task_Bundle.md`)
**Change control:** **ECR-0058** *(per the brief; C-034/IS-037 conformance takes ECR-0059 — re-read `ECR-LOG.md` before assigning, rule 1)*

---

## 0. What this is

**One test module**, mirroring GC-001 exactly: `tests/guarantees/` only, **no
runtime surface** — no package under `src/aqelyn/`, no service, event, capability,
`SignalKind`, or namespace. Enumeration helpers live in `tests/`, never in
`conventions`.

It **inherits GC-001 §2's three principles** without restating them:
**discovery never declaration**, **weakest form that catches the defect**, and
**every AC ships a negative control that performs the forbidden action** (rule 19).

## 1. The gap

GC-001's three ACs are engine-no-execute, `SignalKind` closure, and the scorer
registry. **None asserts anything about event namespaces.** With **51
`register_*_events` owner sites** and **~31 live `aqelyn.<owner>.*` prefixes**,
minting `aqelyn.cyber.*` for IS-037's 9 placeholder events would **pass CI
silently.**

That defect is worse than a duplicate engine, for one asymmetric reason:

> **Events are a published contract.** A duplicate engine can be deleted before
> release. **A duplicate event namespace is permanent once consumers depend on
> it** — and EA-0013 aggregation plus EA-0022 reporting would **double-count** one
> real occurrence arriving under two vocabularies.

GC-002 makes this the **fourth CI-enforced §0 guarantee**, so C-034 (IS-037
conformance) is mechanically protected rather than reviewer-protected.

## 2. AC-1 and AC-2 catch **different** defects

The brief specifies both; it is worth being explicit that they are not redundant,
because a reviewer under time pressure will otherwise be tempted to drop one:

| Defect | Example | Caught by |
|---|---|---|
| **New prefix** for an existing capability | `aqelyn.cyber.exposure_detected` | **AC-2** (no `cyber` package owns it) |
| **New event under an existing prefix** | `aqelyn.exposure.cyber_discovered` | **AC-1** (not in the frozen set) |

**Only AC-2 catches the actual IS-037 case.** AC-1 catches the subtler variant —
the same duplication smuggled in under an owner that legitimately exists — which
is the shape a future author is *more* likely to reach for once AC-2 blocks the
obvious route. Both are required, and neither substitutes for the other.

## 3. The golden set must be **structured by owner**, not flat

GC-001 AC-2 froze `SignalKind`: two literals, eight members total. GC-002 freezes
a set two orders of magnitude larger — hundreds of event types across ~31
prefixes. At that size a **flat** golden list creates a specific failure:

> Every legitimate new module adds events, so the list churns. A one-line
> addition to a flat list of hundreds is **invisible in review** — the edit
> becomes reflexive, the "deliberate reviewed edit" becomes a rubber stamp, and
> the guard degrades into a formality that still passes CI.

Therefore the golden set SHALL be **grouped by owner prefix**, so a diff reads as
*"`exposure` gained an event"* rather than *"one line added to a long list."* That
keeps the reviewable question — **why does this owner need a new event?** — in
front of the reviewer, which is the entire purpose of freezing the set. The
structure is the review affordance; a flat list has none.

## 4. Prefix ownership is **many-to-one**, and the map is derived, not guessed

Prefixes are **not** 1:1 with package names, and the mapping SHALL be **derived
from evidence** — for each registered event string, the owning package is the one
whose source registers that literal — never hardcoded from a guess.

The brief lists two prefixes as unresolved (`compliance→?`, `telemetry→?`). Both
resolve from shipped spec evidence, and the second carries a design consequence:

| Prefix | Owning package | Evidence |
|---|---|---|
| `compliance` | `governance` | EA-0010 (`register_compliance_events`) → `src/aqelyn/governance/`; emits `aqelyn.compliance.assessment_completed`, `…posture_changed` |
| `telemetry` | `lake` | EA-0019 (`register_lake_events`) → `src/aqelyn/lake/`; emits `aqelyn.telemetry.ingested`, `…quarantined` |

**EA-0019 owns *two* prefixes** — `aqelyn.lake.*` (`archived`,
`retention_applied`) **and** `aqelyn.telemetry.*` (`ingested`, `quarantined`).
So the ownership map is **many-to-one (prefix → package)**, not a bijection. A
data structure assuming one prefix per package will mis-handle EA-0019 on day
one, and would also mis-handle `object`/`relationship` (both → `objects`).

**`CORE_EVENTS` prefixes** (`aqelyn.kernel.*`, `object.*`, `relationship.*`) are
seeded by the registry itself rather than by a `register_*_events` owner, so they
need allow-list entries recording **that** as their reason — a different ownership
shape, not an exception to the rule.

Each allow-list entry carries its **reason**, following GC-001's
`EXECUTION_SCAN_EXCLUSIONS` pattern: an allow-list is safe where a registry is
not, because *adding* to it is a visible reviewable act while *omission* from a
registry is silent.

## 5. Scope — three ACs

### 5.1 AC-1 — registered event-type closure *(load-bearing)*

Enumerate every event type from a **constructed runtime's** `EventTypeRegistry`
(discovery — a new module's events appear automatically, per GC-001 §2.1). Assert
the full set equals a **frozen golden set**, grouped by owner (§3). Silent
widening fails; deliberate addition is a visible edit.

**Negative control (must FAIL):** register `aqelyn.cyber.exposure_detected` into a
registry; the closure check flags it.

### 5.2 AC-2 — prefix ownership

Assert every registered prefix `aqelyn.<owner>.` maps to a **real shipped
package**, via the derived map plus the reasoned allow-list for the non-1:1 cases
(§4). A prefix with **no owning package fails.**

**Negative control (must FAIL):** a prefix absent from the ownership map
(`aqelyn.cyber.`).

### 5.3 AC-3 — matrix and `python -O`

Enumerate from a runtime built on **both backends and both tenant modes**; run the
negative controls under **`python -O` in a subprocess** (GC-001's
`test_gc_guards_survive_optimized_python` is the template). `UnknownEventType` /
`GuaranteeViolation` SHALL be raised **explicitly**, never via a bare `assert` —
an assertion-stripped build must still refuse.

### 5.4 Out of scope (noted, not built)

The registry's `validate` raises `UnknownEventType` for an **unregistered** type.
Whether an engine can *emit* a string that never reaches `validate` is a
**different** question — an emit-path gap rather than a registration-set gap —
and GC-002 does not address it. Flagged for the reviewer to judge against shipped
code; **not assumed, and not scope here.**

## 6. Requirements

- **FR-1** GC-002 SHALL add no runtime surface; helpers live in `tests/`, not `conventions` (§0).
- **FR-2** The event-type set SHALL be enumerated from a **constructed runtime's** `EventTypeRegistry`, not from a hand-maintained list (§0, GC-001 §2.1).
- **FR-3** The golden set SHALL be **grouped by owner prefix**, so an addition is visible in review (§3).
- **FR-4** The prefix→package map SHALL be **derived from evidence** (the package whose source registers the literal), never hardcoded from a guess (§4).
- **FR-5** The map SHALL support **many-to-one** ownership — one package may own several prefixes (EA-0019: `lake` + `telemetry`; `objects`: `object` + `relationship`) (§4).
- **FR-6** `CORE_EVENTS`-seeded prefixes SHALL carry allow-list entries recording registry-seeding as their reason (§4).
- **FR-7** A registered prefix with no owning package SHALL **fail** (§5.2).
- **FR-8** Each AC SHALL ship a negative control that **performs** the forbidden registration and proves the checker raises; controls SHALL be verified **by mutation** — neutering the checker must flip the control to failing (rule 19, ECR-0007).
- **FR-9** Guards SHALL raise `UnknownEventType` / `GuaranteeViolation` explicitly, surviving `python -O` (§5.3).
- **FR-10** ACs SHALL run on both backends and both tenant modes (§5.3).
- **FR-11** GC-002 SHALL NOT weaken or duplicate GC-001; the two suites own disjoint guarantees (§1).

## 7. Acceptance Criteria ↔ Tests

| # | Criterion | Test (pytest id) |
|---|---|---|
| AC-1a | Registered set enumerated from the wired runtime registry | `test_gc_event_discovery_from_runtime` |
| AC-1b | Set equals the frozen golden set, grouped by owner | `test_gc_event_types_frozen` |
| AC-1c | **Negative control:** `aqelyn.cyber.exposure_detected` registered → FAILS | `test_gc_negative_control_new_event_type` |
| AC-2a | Every prefix maps to a real shipped package | `test_gc_prefix_ownership` |
| AC-2b | Many-to-one ownership handled (`lake`+`telemetry`; `object`+`relationship`) | `test_gc_prefix_multi_ownership` |
| AC-2c | Allow-list entries each carry a reason | `test_gc_prefix_allowlist_reasoned` |
| AC-2d | **Negative control:** unowned prefix `aqelyn.cyber.` → FAILS | `test_gc_negative_control_unowned_prefix` |
| AC-3a | Both backends, both tenant modes | `test_gc_event_matrix[...]` |
| AC-3b | Controls raise explicitly under `python -O` | `test_gc_event_guards_survive_optimized_python` |
| AC-4 | No runtime surface added | `test_gc_event_no_runtime_surface` |

## 8. Failure handling

- **A new module's event lands without a golden-set edit** → GC-002 fails in CI.
  **That is the feature.** The message SHALL name the offending event type and its
  prefix, so the reviewable question is immediate.
- **AC-2 fails on arrival because a shipped prefix has no derivable owner** → this
  is a **finding, not a blocker, and not grounds to weaken the assertion.** An
  orphaned event prefix in shipped code is exactly the defect AC-2 exists to
  catch; the correct responses are (a) derive the true owner and record the
  allow-list entry with its reason, or (b) record it as a real defect for the
  owning team. **Do not add a bare exemption to make the suite green** — that
  converts a discovered defect into a permanent blind spot.
- **A prefix is ambiguous between two packages** → **fail, do not guess.**
  Ambiguity means the ownership question is genuinely open, and a guessed mapping
  would encode it wrongly and permanently.
- **The golden set grows unreviewably large** → restructure the grouping (§3);
  do **not** relax the assertion to a prefix-only check, which would drop AC-1's
  distinct defect (§2).

## 9. Resolved decisions

- **AC-1 and AC-2 are not redundant** (§2) — only AC-2 catches the IS-037 case;
  AC-1 catches the subtler variant a future author reaches for once AC-2 blocks
  the obvious route.
- **Golden set grouped by owner** (§3) — at this size, structure *is* the review
  affordance; a flat list makes the deliberate edit invisible.
- **Ownership is many-to-one and derived from evidence** (§4) — `compliance` →
  `governance`, `telemetry` → `lake`, and EA-0019 owns two prefixes.
- **Orphaned prefix ⇒ finding, never exemption** (§8).
- **Emit-path validation is out of scope** (§5.4) — a different gap, flagged not
  assumed.
