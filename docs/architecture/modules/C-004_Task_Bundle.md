# C-004 Mission Engine — Implementation Task Bundle

**Milestone:** C-004 (Mission Engine, EA-0007)
**For:** Codex (implementer) · Claude Code (reviewer)
**Prerequisites:** EA-0005 (KG) + EA-0006 (Trust) merged & green; EA-0007 spec **Accepted**; CONVENTIONS + EA-0002/0005 read.
**Definition of Done:** every ticket's acceptance tests pass on in-memory **and** Postgres KG/object store; `ruff` clean; `mypy --strict` clean; the engine mutates nothing; nothing outside the spec; `make check` green; Claude Code sign-off per ticket.

---

## How to use this bundle

Build tickets **in order** (M1 → M4). Each names its spec section and the exact
`pytest` ids from EA-0007 §9. The engine is **pure** and **composes** existing
modules — it calls `KnowledgeGraph.impact` (EA-0005) and reads the object store
(EA-0002); it does **not** reimplement traversal or add a mission store. If a
needed behavior isn't in the spec, raise an Engineering Change Request.

## Target source layout

```
src/aqelyn/mission/
├── __init__.py       # exports MissionEngine, service, types
├── models.py         # MissionView, MissionImpact(Result), PriorityItem, MissionConfig (M1)
├── engine.py         # MissionEngine: criticality_of, mission_impact, assess_finding_impact,
│                     #   prioritize, explain_priority (M2/M3)
└── service.py        # MissionEngineService(AQService); registers the "mission" object_type (M4)
tests/mission/        # acceptance suite over in-memory + Postgres KG/object store
```

---

## M1 — Types, config, and criticality

**Spec:** §5, §6, §7 (criticality), D1/D4, FR-3/FR-12.
**Deliverables:** the models; `MissionConfig` validation (`MissionConfigInvalid`
on weights not summing to 1, out-of-range weights, empty `tier_weights`) added to
`conventions.errors` + CONVENTIONS §9; `criticality_of` (resolve tier from mission
object attributes → weight, default tier flagged).
**Depends on:** EA-0002 objects, conventions.
**Acceptance:** `test_mission_config_invalid`, `test_mission_criticality_resolve`,
`test_mission_default_tier`.

## M2 — Mission impact (compose the Knowledge Graph)

**Spec:** §7, FR-1/2/5/11, D3/D5.
**Deliverables:** `mission_impact` (via `KG.impact(direction="in")` filtered to
`object_type == "mission"`, carrying the dependency path) and
`assess_finding_impact` (union over `affected_object_ids`, deduped, `truncated`
propagated).
**Depends on:** M1.
**Acceptance:** `test_mission_impact_paths`, `test_mission_filters_mission_type`,
`test_mission_finding_impact_dedup`, `test_mission_factor_max`,
`test_mission_truncation_propagates`, `test_mission_tenant_isolation`.

## M3 — Prioritization & explanation

**Spec:** §7, FR-4/6/7/8/9, D2/D6.
**Deliverables:** `prioritize` (documented bounded/monotonic weighted-sum with
deterministic tie-breaks), `explain_priority`, `no_side_effects` guarantee.
**Depends on:** M2.
**Acceptance:** `test_mission_priority_bounded`, `test_mission_priority_monotonic`,
`test_mission_prioritize_deterministic`, `test_mission_unmapped_finding_ranked`,
`test_mission_explainable`, `test_mission_no_side_effects`.

## M4 — MissionEngineService (AQService)

**Spec:** FR-13, §11, §12 registration note.
**Deliverables:** `MissionEngineService` registering as an `AQService`
(name `"mission_engine"`, depends on object store + knowledge graph); registers
the `"mission"` object_type; health reflects store/KG availability + config
validity; wired into the kernel factory.
**Depends on:** M3.
**Acceptance:** `test_mission_service_health`.

---

## Review protocol (Claude Code)

Per ticket, confirm: (1) each named acceptance test exists and passes on
in-memory **and** Postgres; (2) impact is computed by calling `KG.impact` — no
reimplemented traversal, no mission store added; (3) prioritization is bounded
`[0,1]`, monotonic, and deterministic with documented tie-breaks; (4) every
impact/priority carries its path + factor reason; (5) the engine mutates
nothing; (6) `truncated` propagates from KG; (7) `ruff` + `mypy --strict` clean;
interfaces match the spec exactly. Merge only on green review; then **report back
to the owner** before the next module.
