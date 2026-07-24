# GC-002 Event-Namespace Closure Guard — Implementation Task Bundle

**Milestone:** GC-002 (guarantee-conformance track — **not** an archive module)
**For:** Codex (implementer) · Claude Code (reviewer)
**Prerequisites:** GC-001 merged & live in CI (main @17cba54); **`GC-002-event-namespace-closure.spec.md` §2, §3, §4 read**; **ECR-0058** decided by the owner; `SPEC_AUTHOR_NOTES.md` Part 1 rules 1–20 read; `src/aqelyn/events/registry.py` and GC-001's `tests/guarantees/` read before starting.
**Definition of Done:** all ACs green on both backends and both tenant modes, under normal Python **and `python -O`**; `ruff` clean; **`mypy --strict src tests`**; worktree `pytest` with `PYTHONPATH=$PWD/src`; **`gh pr checks <n>` confirmed PASS before merge**; **zero runtime surface**; Claude Code sign-off per ticket.

**This mirrors GC-001 exactly** — same shape, same three principles (discovery
never declaration; weakest form that catches the defect; every AC ships a negative
control that *performs* the forbidden action). Reuse GC-001's helpers and the
`EXECUTION_SCAN_EXCLUSIONS` allow-list pattern rather than inventing new ones.

**Why it lands before C-034:** with **51** `register_*_events` sites and ~31 live
prefixes, minting `aqelyn.cyber.*` for IS-037's 9 placeholder events currently
**passes CI silently**. Events are a **published contract** — a duplicate engine
can be deleted pre-release, a duplicate event namespace is permanent once
consumers depend on it, and EA-0013 + EA-0022 would double-count. GC-002 makes
C-034 mechanically protected.

> **No runtime surface.** Nothing under `src/aqelyn/`; helpers in `tests/`, never
> in `conventions`. If this milestone touches `src/`, stop and raise an ECR.

## Target layout

```
tests/guarantees/
├── event_ownership.py         # derived prefix→package map + reasoned allow-list (E1)
├── test_event_namespace.py    # AC-1 + AC-2 + AC-3 (E2, E3)
└── controls/
    └── event_controls.py      # rogue event type + unowned prefix (E2, E3)
```

**Nothing under `src/`.**

---

## E1 — Derived ownership map (build this first)

**Spec:** §4, FR-4/5/6.
**Deliverables:** a map from each live prefix to its owning package, **derived
from evidence** — for each registered event string, find the package whose source
registers that literal. **Do not hardcode from a guess.**

Three shapes the map must handle, all already present in shipped code:

- **Non-1:1 naming** — `crypto`→`secrets`, `cloud`→`cspm`, `saas`→`sspm`,
  `data`→`dspm`, `config`→`assetconfig`, `finding`→`findings`,
  **`compliance`→`governance`** (EA-0010), **`telemetry`→`lake`** (EA-0019).
- **Many-to-one** — one package may own several prefixes: **EA-0019 owns both
  `aqelyn.lake.*` and `aqelyn.telemetry.*`**; `objects` owns both `object.*` and
  `relationship.*`. A structure assuming one prefix per package breaks on day one.
- **`CORE_EVENTS`-seeded** — `aqelyn.kernel.*`, `object.*`, `relationship.*` come
  from the registry itself, not a `register_*_events` owner; allow-list entries
  record **that** as their reason.

Every allow-list entry carries its **reason** (GC-001's
`EXECUTION_SCAN_EXCLUSIONS` pattern).
**Acceptance:** `test_gc_prefix_multi_ownership`, `test_gc_prefix_allowlist_reasoned`.

## E2 — AC-1: registered event-type closure *(load-bearing)*

**Spec:** §2, §3, §5.1, FR-2/3/8.
**Deliverables:** enumerate every event type from a **constructed runtime's**
`EventTypeRegistry` (discovery — new modules' events appear automatically);
assert the set equals a **frozen golden set grouped by owner prefix**.

**The grouping is a requirement, not a formatting preference (§3).** At hundreds
of event types, a one-line addition to a flat list is invisible in review and the
"deliberate reviewed edit" becomes a rubber stamp. Grouped, a diff reads *"`exposure`
gained an event"* and keeps the reviewable question in front of the reviewer.

**Negative control (must FAIL):** register `aqelyn.cyber.exposure_detected`; the
closure check flags it.
**Depends on:** E1.
**Acceptance:** `test_gc_event_discovery_from_runtime`, `test_gc_event_types_frozen`,
`test_gc_negative_control_new_event_type`.

## E3 — AC-2 + AC-3: prefix ownership, matrix, `-O`

**Spec:** §5.2, §5.3, FR-7/9/10.
**Deliverables:** assert every registered prefix maps to a **real shipped
package** via E1's map; a prefix with **no owner fails**. Run enumeration on
**both backends and both tenant modes**; run the negative controls under
**`python -O` in a subprocess**, with `UnknownEventType` / `GuaranteeViolation`
raised **explicitly** (never a bare `assert`).

**Negative control (must FAIL):** unowned prefix `aqelyn.cyber.`.
**Depends on:** E2.
**Acceptance:** `test_gc_prefix_ownership`,
`test_gc_negative_control_unowned_prefix`, `test_gc_event_matrix[...]`,
`test_gc_event_guards_survive_optimized_python`, `test_gc_event_no_runtime_surface`.

---

## Review protocol (Claude Code)

**Ask first:** ***do the negative controls actually fail — verified by mutation?***
Neuter each checker and confirm its control flips to failing. A green suite whose
controls also pass tests nothing (rule 19, one level up). This is how GC-001 was
verified; same standard.

Then:

1. **Discovery, not declaration** — enumeration comes from the **wired runtime
   registry**. Register an event in a throwaway module and confirm GC-002 sees it
   without any list edit. The golden set and allow-list are the *frozen review
   points*, never the discovery source.
2. **AC-1 and AC-2 are both present and distinct** (§2). Confirm AC-2 catches
   `aqelyn.cyber.*` (new prefix) **and** AC-1 catches
   `aqelyn.exposure.cyber_discovered` (new event, existing prefix). Neither
   substitutes for the other — dropping one leaves a real hole.
3. **Golden set grouped by owner** (§3) — reject a flat list; the structure is the
   review affordance.
4. **Ownership derived, not guessed** (§4) — spot-check that `compliance`→
   `governance` and `telemetry`→`lake` came from the registering source, not from
   the brief's table. **Many-to-one handled**: EA-0019 holds two prefixes.
5. **Orphaned prefix ⇒ finding, not exemption** (§8). If AC-2 fails on arrival
   because a shipped prefix has no derivable owner, that is GC-002 **working** —
   derive the true owner and record the reason, or record a real defect. **Do not
   add a bare exemption to go green**; that converts a discovered defect into a
   permanent blind spot. Ambiguous ownership → **fail, do not guess.**
6. **No runtime surface**; nothing in `conventions`.
7. **GC-001 not weakened or duplicated** — the two suites own disjoint
   guarantees (FR-11).
8. Both backends, both tenant modes, `python -O`; `mypy --strict src tests`;
   `gh pr checks` PASS before merge.

**Preserve, do not absorb:** ECR-0032 (shared posture base), **ECR-0034
(inventory cap — on C-034's critical path per the reviewer's finding)**, EA-0018
unclamped-duration flake, EA-0027/EA-0018 enterprise health probes, EA-0013
equal-timestamp tie-breaker.

Merge only on green review; then **report back to the owner** — after which
**C-034 (IS-037 conformance, ECR-0059)** lands with this guard already in place.
