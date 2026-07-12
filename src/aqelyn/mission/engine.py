"""Mission Engine reference implementation (EA-0007)."""

from __future__ import annotations

from collections.abc import Sequence
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
    PriorityItem,
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

    async def prioritize(self, findings: Sequence[Finding]) -> list[PriorityItem]:
        ordered_findings = sorted(findings, key=lambda finding: finding.id)
        items = [await self._priority_item(finding) for finding in ordered_findings]
        return sorted(
            items,
            key=lambda item: (-item.priority_score, -item.severity_weight, item.finding_id),
        )

    def explain_priority(self, item: PriorityItem) -> dict[str, object]:
        return {
            "finding_id": item.finding_id,
            "method": "weighted_sum/v1",
            "priority_score": item.priority_score,
            "factors": {
                "severity": {
                    "weight": self.config.w_severity,
                    "value": item.severity_weight,
                    "contribution": self.config.w_severity * item.severity_weight,
                },
                "mission": {
                    "weight": self.config.w_mission,
                    "value": item.mission_factor,
                    "contribution": self.config.w_mission * item.mission_factor,
                },
                "confidence": {
                    "weight": self.config.w_confidence,
                    "value": item.confidence,
                    "contribution": self.config.w_confidence * item.confidence,
                },
            },
            "top_mission": (
                None if item.top_mission is None else item.top_mission.model_dump(mode="json")
            ),
            "impacts": [_explain_impact(impact) for impact in item.impacts],
            "truncated": item.truncated,
            "reason": item.reason,
        }

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

    async def _priority_item(self, finding: Finding) -> PriorityItem:
        impact_result = await self.assess_finding_impact(finding)
        severity_weight = self.config.severity_weights[finding.severity]
        mission_factor = _mission_factor(impact_result.impacts, self.config)
        confidence = _clamp(finding.confidence)
        priority_score = _clamp(
            self.config.w_severity * severity_weight
            + self.config.w_mission * mission_factor
            + self.config.w_confidence * confidence
        )
        top_impact = _top_impact(impact_result.impacts)
        return PriorityItem(
            finding_id=finding.id,
            priority_score=priority_score,
            mission_factor=mission_factor,
            severity_weight=severity_weight,
            confidence=confidence,
            top_mission=None if top_impact is None else top_impact.mission,
            impacts=impact_result.impacts,
            truncated=impact_result.truncated,
            reason=_priority_reason(
                finding,
                priority_score=priority_score,
                mission_factor=mission_factor,
                top_impact=top_impact,
                used_default=not impact_result.impacts,
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


def _mission_factor(impacts: Sequence[MissionImpact], config: MissionConfig) -> float:
    if not impacts:
        return config.tier_weights[config.default_tier]
    return max(impact.impact_score for impact in impacts)


def _top_impact(impacts: Sequence[MissionImpact]) -> MissionImpact | None:
    if not impacts:
        return None
    return sorted(impacts, key=lambda impact: (-impact.impact_score, impact.mission.id))[0]


def _priority_reason(
    finding: Finding,
    *,
    priority_score: float,
    mission_factor: float,
    top_impact: MissionImpact | None,
    used_default: bool,
) -> str:
    if top_impact is None or used_default:
        return (
            f"Finding {finding.id} has no impacted mission; using default mission factor "
            f"{mission_factor:.3f}. Priority score is {priority_score:.3f}."
        )
    return (
        f"Finding {finding.id} is prioritized by severity {finding.severity}, confidence "
        f"{_clamp(finding.confidence):.3f}, and mission impact {mission_factor:.3f} from "
        f"{top_impact.mission.display_name}. Priority score is {priority_score:.3f}."
    )


def _clamp(value: float, *, low: float = 0.0, high: float = 1.0) -> float:
    return min(max(value, low), high)


def _explain_impact(impact: MissionImpact) -> dict[str, object]:
    return {
        "mission": impact.mission.model_dump(mode="json"),
        "impact_score": impact.impact_score,
        "source_object_id": impact.source_object_id,
        "path": {
            "node_ids": list(impact.via.node_ids),
            "length": impact.via.length,
            "edges": [edge.model_dump(mode="json") for edge in impact.via.edges],
        },
        "reason": impact.reason,
    }
