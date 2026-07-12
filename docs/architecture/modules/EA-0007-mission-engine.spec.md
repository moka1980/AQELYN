# EA-0007 — Mission Engine — Implementation Specification

**Realizes:** EA-0007 (supersedes the placeholder `archive/EA-0007/EA-0007_Master.md` for implementation)
**Depends on:** ADR-0001, CONVENTIONS, EA-0002 (objects/relationships), EA-0005 (Knowledge Graph — impact traversal), EA-0006 (Trust — confidence), EA-0001 (`AQService`); reads the Finding model
**Consumed by:** the Finding pipeline / triage (surface the highest-business-impact issues first), UI (show business meaning of a technical finding), EA-0009 Policy (mission-aware enforcement), reporting
**Status:** Accepted
**Build milestone:** C-004 (see `C-004_Task_Bundle.md`)
**Definition of Ready:** see §11

---

## 1. Purpose

The Mission Engine answers the business question a technical finding can't
answer on its own: **so what?** It models the *missions* an organization cares
about (run payroll, serve the website, protect patient records), maps which
assets those missions depend on, and — when something is wrong with an asset —
computes **which missions are affected, how badly, and which issues to fix
first**. It is how AQELYN turns a pile of findings into a ranked, business-aware
worklist, directly serving the Charter's "prioritize" and "actionable"
principles.

## 2. Scope

**In scope:** the mission model (missions as objects + their asset
dependencies), mission criticality resolution, mission-impact analysis (which
missions depend on an affected asset), deterministic explainable prioritization
of findings, and the `MissionEngine` interface + `MissionEngineService`
(`AQService`).

**Out of scope:** collecting assets or discovering dependencies (connectors,
EA-0002), the graph traversal itself (owned by EA-0005 — the Mission Engine
*calls* it, D5), computing confidence (EA-0006), and deciding what action to take
on a prioritized finding (Finding pipeline / EA-0009 Policy). The Mission Engine
**never mutates** stored data (D7).

## 3. Design decisions

- **D1 — Missions are modeled in the existing object model.** A mission is an
  `AQObject` with `object_type = "mission"`; a mission's reliance on an asset is
  a relationship `depends_on` (mission → asset), reusing EA-0002. No separate
  mission store. Single source of truth, provenance preserved.
- **D2 — Deterministic and pure.** Identical `(inputs, graph, config)` →
  byte-identical prioritization. No randomness. Required for reproducible,
  auditable triage.
- **D3 — Explainable.** Every mission impact carries the dependency **path**
  (asset → mission) from the Knowledge Graph, and every priority carries its
  factor breakdown (which mission, which weights). Charter "explain before
  recommend."
- **D4 — Mission criticality is configured and resolvable.** A mission's
  criticality tier lives in its object attributes (`criticality_tier`, 1 = most
  critical); a config maps tier → weight `[0,1]`. Absent/unknown → documented
  default tier, flagged.
- **D5 — Impact reuses the Knowledge Graph.** Mission impact = `KG.impact(asset,
  direction="in", relation_types={"depends_on", …})` filtered to nodes with
  `object_type == "mission"`. The Mission Engine does **not** reimplement
  traversal; it composes EA-0005 (and inherits its bounded/truncated guarantees).
- **D6 — Prioritization is a documented, bounded, monotonic weighted sum.**
  `priority = wₛ·severity_weight + w_m·mission_factor + w_c·confidence`, weights
  summing to 1, every term in `[0,1]` → result in `[0,1]`, monotonic in each
  term, order-independent. The breakdown is part of the output.
- **D7 — Pure analysis, no mutation** (mirrors KG and Trust). Registered as an
  `AQService` (D8).
- **D8 — Tenant-scoped and bounded** via the object store and KG it builds on.

## 4. Ubiquitous language

| Term | Meaning |
|---|---|
| **Mission** | A business/operational objective, modeled as an `AQObject` of `object_type "mission"`. |
| **Mission dependency** | A `depends_on` edge from a mission (or higher asset) to an asset it relies on. |
| **Criticality tier / weight** | A mission's importance (tier 1–4) mapped to a weight `[0,1]`. |
| **Mission impact** | For an affected asset, the missions that (transitively) depend on it, each with the dependency path. |
| **Mission factor** | For a finding, the worst-case (max) criticality weight across its impacted missions. |
| **Priority** | A deterministic `[0,1]` score ranking a finding by business impact. |

## 5. Types

```
MissionView   = { id, display_name, criticality_tier: int, criticality_weight: float }
MissionImpact = { mission: MissionView, impact_score: float,
                  via: Path,               # asset -> mission dependency path (EA-0005 Path)
                  source_object_id: str,   # the affected asset that reaches this mission
                  reason: str }
MissionImpactResult = { impacts: list[MissionImpact], truncated: bool }

PriorityItem  = { finding_id: str, priority_score: float,
                  mission_factor: float, severity_weight: float, confidence: float,
                  top_mission: MissionView | null, reason: str }
PrioritizedList = list[PriorityItem]      # ordered high -> low, deterministic

MissionConfig = { tier_weights: dict[int, float],      # e.g. {1:1.0, 2:0.7, 3:0.4, 4:0.2}
                  default_tier: int,                    # for missions with no tier (e.g. 3)
                  severity_weights: dict[str, float],   # info..critical -> [0,1]
                  w_severity: float, w_mission: float, w_confidence: float,  # sum to 1
                  dependency_types: tuple[str, ...],    # default ("depends_on","runs_on","member_of")
                  max_depth: int, max_nodes: int }      # passed through to KG
```

Reuses EA-0005 `Path`/`NodeView` and reads the Finding model's `severity`,
`confidence`, and `affected_object_ids`.

## 6. Interfaces (Python 3.12)

```python
from typing import Protocol, Sequence

class MissionEngine(Protocol):
    async def criticality_of(self, mission_id: str) -> MissionView: ...      # from object attrs + config (D4)

    async def mission_impact(self, object_id: str) -> MissionImpactResult: ...
    # missions that depend on this asset, via KG.impact (D5), each with its path + impact_score

    async def assess_finding_impact(self, finding: "Finding") -> MissionImpactResult: ...
    # union of mission_impact over the finding's affected_object_ids, deduped by mission

    async def prioritize(self, findings: Sequence["Finding"]) -> PrioritizedList: ...
    # deterministic ranking by priority_score (D6)

    def explain_priority(self, item: PriorityItem) -> dict: ...              # factor breakdown for UI
```

`MissionEngineService` wraps a `MissionEngine` as an `AQService`
(name `"mission_engine"`, depends on the object store + knowledge graph; health
reflects their availability + config validity).

## 7. Computation (the reference model)

**Mission criticality.** `tier = mission.attributes.get("criticality_tier",
config.default_tier)`; `weight = config.tier_weights[tier]`.

**Mission impact of an asset.** `hits = KG.impact(object_id, direction="in",
relation_types=config.dependency_types, max_depth, max_nodes)`; keep hits where
`node.object_type == "mission"`; for each, `impact_score = criticality_weight`
(and the `via` path explains the dependency). `truncated` propagates from KG.

**Finding priority.** For finding `f`:
```
severity_weight = config.severity_weights[f.severity]                 # [0,1]
mission_factor  = max(criticality_weight over missions impacted by f) # or tier_weights[default_tier] if none
confidence      = f.confidence                                        # [0,1] (Trust-populated)
priority = clamp(w_severity*severity_weight + w_mission*mission_factor
                 + w_confidence*confidence, 0, 1)                      # D6
```
Ranking: sort by `priority` desc, tie-break by `severity_weight` desc then
`finding_id` (deterministic, D2). `top_mission` is the highest-criticality
impacted mission (or null).

## 8. Requirements

### Functional (testable)

- **FR-1** `mission_impact(object_id)` SHALL return the missions that transitively depend on the asset, computed via `KG.impact(direction="in")` filtered to `object_type == "mission"`, each with its dependency `via` path (D3, D5).
- **FR-2** `assess_finding_impact(finding)` SHALL union mission impact across `finding.affected_object_ids`, deduped by mission (keeping the highest impact/shortest path).
- **FR-3** `criticality_of` SHALL resolve a mission's tier from its object attributes and map it to a weight via config; absent/unknown tier SHALL use `default_tier`, flagged in `reason`.
- **FR-4** `prioritize` SHALL rank findings by the documented `priority` (§7), bounded `[0,1]`, monotonic in severity, mission factor, and confidence (D6).
- **FR-5** `mission_factor` for a finding SHALL be the **max** criticality weight across its impacted missions (worst-case business impact, FR-11 intent).
- **FR-6** Ranking SHALL be deterministic: identical `(findings, graph, config)` → identical ordered list, with documented tie-breaks (D2).
- **FR-7** Every `MissionImpact` and `PriorityItem` SHALL carry a plain-language `reason` and the factor/path detail (D3).
- **FR-8** The engine SHALL NOT mutate any object, relationship, or finding (D7).
- **FR-9** A finding with **no** impacted mission SHALL still be prioritized (using `default_tier` weight), never dropped.
- **FR-10** Results SHALL be tenant-scoped via the underlying store/KG; no cross-tenant mission or asset appears (D8).
- **FR-11** Impact SHALL inherit KG bounds; `truncated` SHALL propagate and be surfaced.
- **FR-12** Invalid config (`w_severity + w_mission + w_confidence ≠ 1 ± 1e-6`, any weight outside `[0,1]`, empty `tier_weights`) SHALL raise `MissionConfigInvalid`.
- **FR-13** `MissionEngineService` SHALL register as an `AQService` with health reflecting store/KG availability + config validity (EA-0001).

### Non-functional

- **NFR-1 (determinism)** repeated identical prioritizations serialize byte-identically.
- **NFR-2 (purity)** no mutation of stored data; only reads via object store + KG.
- **NFR-3 (bounded)** impact inherits KG hard caps; prioritization is `O(F × impact)`.
- **NFR-4 (portability & typing)** works over in-memory **and** Postgres KG/object store; `mypy --strict` + `ruff` clean.

## 9. Acceptance Criteria ↔ Tests (Definition of Ready)

| # | Criterion | Test (pytest id) |
|---|---|---|
| AC-1 | mission_impact returns depending missions with paths | `test_mission_impact_paths` |
| AC-2 | Only object_type "mission" nodes counted | `test_mission_filters_mission_type` |
| AC-3 | Criticality resolved from attrs + config | `test_mission_criticality_resolve` |
| AC-4 | Missing tier uses default, flagged | `test_mission_default_tier` |
| AC-5 | Finding impact unions + dedupes missions | `test_mission_finding_impact_dedup` |
| AC-6 | Priority formula bounded [0,1] | `test_mission_priority_bounded` |
| AC-7 | Priority monotonic in each factor | `test_mission_priority_monotonic` |
| AC-8 | mission_factor = max over impacted missions | `test_mission_factor_max` |
| AC-9 | Deterministic ranking + tie-breaks | `test_mission_prioritize_deterministic` |
| AC-10 | No-mission finding still ranked | `test_mission_unmapped_finding_ranked` |
| AC-11 | Explainable priority + impact | `test_mission_explainable` |
| AC-12 | Engine mutates nothing | `test_mission_no_side_effects` |
| AC-13 | Tenant isolation | `test_mission_tenant_isolation` |
| AC-14 | truncated propagates from KG | `test_mission_truncation_propagates` |
| AC-15 | Invalid config rejected | `test_mission_config_invalid` |
| AC-16 | Registers as AQService with health | `test_mission_service_health` |

## 10. Error taxonomy (contributions)

`MissionConfigInvalid` (added to `conventions.errors` + CONVENTIONS §9). Reuses
`ObjectNotFound` when asked for a mission id that does not exist.

## 11. Failure handling

- Invalid config → `MissionConfigInvalid` at construction; service reports
  `unavailable` until fixed.
- Object store / KG unavailable → `StoreUnavailable`; service reports `degraded`;
  no partial silent ranking.
- KG traversal truncated → surfaced via `truncated`; prioritization proceeds on
  what was found (bounded, never hangs).
- A mission object missing `criticality_tier` → default tier, flagged in
  `reason`, never a crash.

## 12. Dependencies & consumers

- **Depends on:** EA-0005 `KnowledgeGraph.impact`; EA-0002 `ObjectStore`
  (load mission objects); EA-0006 confidence (via `finding.confidence`);
  EA-0001 `AQService`; the Finding model.
- **Consumed by:** the Finding pipeline / triage UI (rank + show business
  impact); EA-0009 Policy (mission-aware decisions); reporting/executive views.
- **Registration note:** the Mission Engine registers the `"mission"`
  `object_type` (with a `criticality_tier` attribute) in the object type
  registry (EA-0002 §7) at startup.

## 13. Resolved / deferred decisions

- **Missions as objects, criticality as an attribute** (not a separate store or
  registry) — keeps one source of truth and lets missions participate in the
  graph like any asset. An optional config-driven criticality override may be
  added later without changing the interface.
- **Worst-case (max) mission factor** is chosen over an average so a finding that
  touches one tier-1 mission is not diluted by also touching low-criticality
  ones. A configurable aggregation could be added later; max is the binding
  default.
- **Transparent weighted-sum prioritization** over a learned ranker, for
  auditability — consistent with the Trust Engine's stance.
