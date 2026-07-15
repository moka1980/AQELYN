"""Threat Detection scoring via Trust and Mission (EA-0017 D3)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from aqelyn.conventions import is_valid
from aqelyn.evidence import EvidenceRecord
from aqelyn.findings.models import Severity
from aqelyn.mission.models import MissionConfig, MissionImpactResult
from aqelyn.trust import TrustEngine


class MissionImpactProvider(Protocol):
    async def mission_impact(self, object_id: str) -> MissionImpactResult: ...


@dataclass(frozen=True)
class DetectionScore:
    confidence: float
    severity_score: float
    mission_factor: float
    severity_weight: float
    trust_method: str


async def score_detection(
    *,
    subject_ref: str,
    severity: Severity,
    evidence: Sequence[EvidenceRecord],
    trust_engine: TrustEngine,
    detected_at: datetime,
    mission_engine: MissionImpactProvider | None = None,
    mission_config: MissionConfig | None = None,
) -> DetectionScore:
    selected_config = mission_config or MissionConfig()
    assessment = await trust_engine.assess(subject_ref, evidence, now=detected_at)
    severity_weight = selected_config.severity_weights[severity]
    mission_factor = await _mission_factor(
        subject_ref,
        mission_engine=mission_engine,
        config=selected_config,
    )
    return DetectionScore(
        confidence=_clamp(assessment.score),
        severity_score=100.0 * _clamp(severity_weight * mission_factor),
        mission_factor=mission_factor,
        severity_weight=severity_weight,
        trust_method=assessment.method,
    )


async def _mission_factor(
    subject_ref: str,
    *,
    mission_engine: MissionImpactProvider | None,
    config: MissionConfig,
) -> float:
    if mission_engine is not None and is_valid(subject_ref, "obj"):
        impact = await mission_engine.mission_impact(subject_ref)
        if impact.impacts:
            return _clamp(max(item.impact_score for item in impact.impacts))
    return _clamp(config.tier_weights[config.default_tier])


def _clamp(value: float, *, low: float = 0.0, high: float = 1.0) -> float:
    return min(max(value, low), high)
