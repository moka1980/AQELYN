"""Mission Engine reference implementation (EA-0007 M1)."""

from __future__ import annotations

from typing import Any

from aqelyn.conventions.errors import ObjectNotFound, StoreUnavailable
from aqelyn.findings import Finding
from aqelyn.graph import KnowledgeGraph
from aqelyn.mission.models import (
    MISSION_OBJECT_TYPE,
    MissionConfig,
    MissionImpact,
    MissionImpactResult,
    MissionView,
)
from aqelyn.objects import ObjectStore


class MissionEngine:
    def __init__(
        self,
        object_store: ObjectStore,
        knowledge_graph: KnowledgeGraph | None = None,
        *,
        config: MissionConfig | None = None,
    ) -> None:
        self.object_store = object_store
        self.knowledge_graph = knowledge_graph
        self.config = config or MissionConfig()

    async def criticality_of(self, mission_id: str) -> MissionView:
        mission = await self.object_store.get(mission_id)
        if mission is None or mission.object_type != MISSION_OBJECT_TYPE:
            raise ObjectNotFound(f"mission not found: {mission_id}")
        tier, used_default, reason = self._resolve_tier(mission.attributes.get("criticality_tier"))
        return MissionView(
            id=mission.id,
            display_name=mission.display_name,
            criticality_tier=tier,
            criticality_weight=self.config.tier_weights[tier],
            reason=reason,
            used_default_tier=used_default,
        )

    async def mission_impact(self, object_id: str) -> MissionImpactResult:
        if self.knowledge_graph is None:
            raise StoreUnavailable("mission impact requires a knowledge graph")
        result = await self.knowledge_graph.impact(
            object_id,
            direction="in",
            relation_types=self.config.dependency_types,
            max_depth=self.config.max_depth,
            max_nodes=self.config.max_nodes,
        )
        impacts: list[MissionImpact] = []
        for hit in result.hits:
            if hit.node.object_type != MISSION_OBJECT_TYPE:
                continue
            mission = await self.criticality_of(hit.node.id)
            impacts.append(
                MissionImpact(
                    mission=mission,
                    impact_score=mission.criticality_weight,
                    via=hit.via,
                    source_object_id=object_id,
                    reason=(
                        f"{mission.display_name} depends on affected object {object_id}; "
                        f"criticality tier {mission.criticality_tier} contributes "
                        f"{mission.criticality_weight:.3f} impact."
                    ),
                )
            )
        impacts.sort(key=lambda impact: (impact.mission.id, impact.source_object_id))
        return MissionImpactResult(impacts=impacts, truncated=result.truncated)

    async def assess_finding_impact(self, finding: Finding) -> MissionImpactResult:
        by_mission: dict[str, MissionImpact] = {}
        truncated = False
        for object_id in sorted(finding.affected_object_ids):
            result = await self.mission_impact(object_id)
            truncated = truncated or result.truncated
            for impact in result.impacts:
                existing = by_mission.get(impact.mission.id)
                if existing is None or _better_impact(impact, existing):
                    by_mission[impact.mission.id] = impact
        return MissionImpactResult(
            impacts=[by_mission[mission_id] for mission_id in sorted(by_mission)],
            truncated=truncated,
        )

    def _resolve_tier(self, raw_tier: Any) -> tuple[int, bool, str]:
        if (
            isinstance(raw_tier, int)
            and not isinstance(raw_tier, bool)
            and raw_tier in self.config.tier_weights
        ):
            return (
                raw_tier,
                False,
                f"Mission criticality tier {raw_tier} maps to configured weight.",
            )
        if raw_tier is None:
            return (
                self.config.default_tier,
                True,
                f"Mission has no criticality_tier; using default tier {self.config.default_tier}.",
            )
        return (
            self.config.default_tier,
            True,
            (
                f"Mission criticality_tier {raw_tier!r} is unknown; "
                f"using default tier {self.config.default_tier}."
            ),
        )


def _better_impact(candidate: MissionImpact, existing: MissionImpact) -> bool:
    if candidate.impact_score != existing.impact_score:
        return candidate.impact_score > existing.impact_score
    if candidate.via.length != existing.via.length:
        return candidate.via.length < existing.via.length
    return (candidate.source_object_id, candidate.via.node_ids) < (
        existing.source_object_id,
        existing.via.node_ids,
    )
