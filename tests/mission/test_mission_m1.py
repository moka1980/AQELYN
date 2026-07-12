"""M1 acceptance tests for Mission Engine config and criticality."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

import pytest

from aqelyn.conventions import ActorRef, new_id
from aqelyn.conventions.errors import ALL_ERROR_CODES, MissionConfigInvalid
from aqelyn.mission import MISSION_OBJECT_TYPE, MissionConfig, MissionEngine
from aqelyn.objects import AQObject, ObjectStore, SourceRef

SYS = ActorRef(actor_type="system", actor_id="mission-test")


def _now() -> datetime:
    return datetime.now(UTC)


def _source(method: str = "mission-test") -> SourceRef:
    return SourceRef(source_id=new_id("src"), observed_at=_now(), method=method)


def _register_mission_type(store: ObjectStore) -> None:
    cast(Any, store).registry.register(MISSION_OBJECT_TYPE, 1, None)


async def _add_mission(
    store: ObjectStore, display_name: str, *, attributes: dict[str, object] | None = None
) -> AQObject:
    now = _now()
    return await store.upsert(
        AQObject(
            id="",
            object_type=MISSION_OBJECT_TYPE,
            schema_version=1,
            display_name=display_name,
            attributes=attributes or {},
            sources=[_source(f"mission:{display_name}")],
            first_seen_at=now,
            last_seen_at=now,
            created_at=now,
            updated_at=now,
            created_by=SYS,
            updated_by=SYS,
        )
    )


def test_mission_config_invalid() -> None:
    with pytest.raises(MissionConfigInvalid, match="tier_weights"):
        MissionConfig(tier_weights={})
    with pytest.raises(MissionConfigInvalid, match="tier_weights"):
        MissionConfig(tier_weights={1: 1.1})
    with pytest.raises(MissionConfigInvalid, match="severity_weights"):
        MissionConfig(severity_weights={"critical": -0.1})
    with pytest.raises(MissionConfigInvalid, match="priority weight"):
        MissionConfig(w_mission=1.2)
    with pytest.raises(MissionConfigInvalid, match="sum to 1"):
        MissionConfig(w_severity=0.4, w_mission=0.4, w_confidence=0.3)
    with pytest.raises(MissionConfigInvalid, match="default_tier"):
        MissionConfig(tier_weights={1: 1.0}, default_tier=2)

    assert "MissionConfigInvalid" in ALL_ERROR_CODES


async def test_mission_criticality_resolve(graph_harness: Any) -> None:
    store = cast(ObjectStore, graph_harness.object_store)
    _register_mission_type(store)
    mission = await _add_mission(
        store, "Payroll", attributes={"criticality_tier": 1, "owner": "finance"}
    )
    engine = MissionEngine(
        store, config=MissionConfig(tier_weights={1: 0.95, 3: 0.4}, default_tier=3)
    )

    view = await engine.criticality_of(mission.id)

    assert view.id == mission.id
    assert view.display_name == "Payroll"
    assert view.criticality_tier == 1
    assert view.criticality_weight == 0.95
    assert view.used_default_tier is False
    assert "tier 1" in view.reason

    stored = await store.get(mission.id)
    assert stored is not None
    assert stored.attributes == {"criticality_tier": 1, "owner": "finance"}


async def test_mission_default_tier(graph_harness: Any) -> None:
    store = cast(ObjectStore, graph_harness.object_store)
    _register_mission_type(store)
    missing = await _add_mission(store, "Unmarked mission")
    unknown = await _add_mission(store, "Unexpected tier", attributes={"criticality_tier": 99})
    engine = MissionEngine(
        store, config=MissionConfig(tier_weights={1: 1.0, 3: 0.35}, default_tier=3)
    )

    missing_view = await engine.criticality_of(missing.id)
    unknown_view = await engine.criticality_of(unknown.id)

    assert missing_view.criticality_tier == 3
    assert missing_view.criticality_weight == 0.35
    assert missing_view.used_default_tier is True
    assert "default tier 3" in missing_view.reason

    assert unknown_view.criticality_tier == 3
    assert unknown_view.criticality_weight == 0.35
    assert unknown_view.used_default_tier is True
    assert "unknown" in unknown_view.reason
