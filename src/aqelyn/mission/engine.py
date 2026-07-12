"""Mission Engine reference implementation (EA-0007 M1)."""

from __future__ import annotations

from typing import Any

from aqelyn.conventions.errors import ObjectNotFound
from aqelyn.mission.models import MISSION_OBJECT_TYPE, MissionConfig, MissionView
from aqelyn.objects import ObjectStore


class MissionEngine:
    def __init__(self, object_store: ObjectStore, *, config: MissionConfig | None = None) -> None:
        self.object_store = object_store
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
