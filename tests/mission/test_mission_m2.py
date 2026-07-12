"""M2 acceptance tests for Mission Engine impact analysis."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

from aqelyn.conventions import ActorRef, new_id
from aqelyn.findings import Automation, Finding, Remediation
from aqelyn.mission import MISSION_OBJECT_TYPE, MissionConfig, MissionEngine
from aqelyn.objects import AQObject, AQRelationship, ObjectStore, SourceRef

SYS = ActorRef(actor_type="system", actor_id="mission-impact-test")
TENANT_A = "018f0000-0000-7000-8000-000000000001"
TENANT_B = "018f0000-0000-7000-8000-000000000002"


def _now() -> datetime:
    return datetime.now(UTC)


def _source(method: str) -> SourceRef:
    return SourceRef(
        source_id=new_id("src"),
        evidence_id=new_id("evd"),
        observed_at=_now(),
        method=method,
    )


def _register_mission_type(store: ObjectStore) -> None:
    cast(Any, store).registry.register(MISSION_OBJECT_TYPE, 1, None)


async def _add_object(
    store: ObjectStore,
    display_name: str,
    *,
    object_type: str = "generic",
    attributes: dict[str, object] | None = None,
    tenant_id: str | None = None,
) -> AQObject:
    now = _now()
    return await store.upsert(
        AQObject(
            id="",
            object_type=object_type,
            schema_version=1,
            tenant_id=tenant_id,
            display_name=display_name,
            attributes=attributes or {},
            sources=[_source(f"object:{display_name}")],
            first_seen_at=now,
            last_seen_at=now,
            created_at=now,
            updated_at=now,
            created_by=SYS,
            updated_by=SYS,
        )
    )


async def _add_mission(
    store: ObjectStore,
    display_name: str,
    *,
    tier: int,
    tenant_id: str | None = None,
) -> AQObject:
    return await _add_object(
        store,
        display_name,
        object_type=MISSION_OBJECT_TYPE,
        attributes={"criticality_tier": tier},
        tenant_id=tenant_id,
    )


async def _add_relation(
    store: ObjectStore,
    from_obj: AQObject,
    to_obj: AQObject,
    relation_type: str = "depends_on",
) -> AQRelationship:
    now = _now()
    return await store.relate(
        AQRelationship(
            id="",
            from_id=from_obj.id,
            to_id=to_obj.id,
            relation_type=relation_type,
            sources=[_source(f"relationship:{relation_type}")],
            created_at=now,
            updated_at=now,
            created_by=SYS,
            updated_by=SYS,
        )
    )


def _engine(graph_harness: Any, *, config: MissionConfig | None = None) -> MissionEngine:
    store = cast(ObjectStore, graph_harness.object_store)
    _register_mission_type(store)
    return MissionEngine(store, graph_harness.graph, config=config)


def _finding(*object_ids: str) -> Finding:
    now = _now()
    return Finding(
        id=new_id("fnd"),
        finding_type="mission-impact-test",
        schema_version=1,
        dedup_key=new_id("fnd"),
        title="Affected asset",
        severity="high",
        severity_score=75.0,
        what_happened="An asset has a material issue.",
        why_it_matters="The asset may support business missions.",
        how_determined="Mission impact acceptance test.",
        risk_of_inaction="Dependent missions may be interrupted.",
        evidence_ids=[new_id("evd")],
        affected_object_ids=list(object_ids),
        remediation=Remediation(
            summary="Fix the affected asset.",
            steps=["Repair or replace the affected component."],
            difficulty="medium",
            expected_outcome="Mission dependency is restored.",
        ),
        automation=Automation(eligibility="none"),
        source_engine="mission-test",
        first_detected_at=now,
        last_detected_at=now,
    )


async def test_mission_impact_paths(graph_harness: Any) -> None:
    engine = _engine(
        graph_harness,
        config=MissionConfig(tier_weights={1: 1.0, 2: 0.7, 3: 0.4}, default_tier=3),
    )
    store = cast(ObjectStore, graph_harness.object_store)
    asset = await _add_object(store, "database")
    service = await _add_object(store, "payroll-api")
    mission = await _add_mission(store, "Run payroll", tier=1)
    await _add_relation(store, service, asset, "runs_on")
    await _add_relation(store, mission, service, "depends_on")

    result = await engine.mission_impact(asset.id)

    assert result.truncated is False
    assert len(result.impacts) == 1
    impact = result.impacts[0]
    assert impact.mission.id == mission.id
    assert impact.impact_score == 1.0
    assert impact.source_object_id == asset.id
    assert impact.via.node_ids == [asset.id, service.id, mission.id]
    assert impact.via.length == 2
    assert [edge.relation_type for edge in impact.via.edges] == ["runs_on", "depends_on"]
    assert impact.via.edges[0].sources[0].evidence_id is not None
    assert "Run payroll" in impact.reason


async def test_mission_filters_mission_type(graph_harness: Any) -> None:
    engine = _engine(graph_harness)
    store = cast(ObjectStore, graph_harness.object_store)
    asset = await _add_object(store, "database")
    non_mission = await _add_object(store, "generic-service")
    mission = await _add_mission(store, "Serve website", tier=2)
    await _add_relation(store, non_mission, asset)
    await _add_relation(store, mission, asset)

    result = await engine.mission_impact(asset.id)

    assert [impact.mission.id for impact in result.impacts] == [mission.id]


async def test_mission_finding_impact_dedup(graph_harness: Any) -> None:
    engine = _engine(graph_harness)
    store = cast(ObjectStore, graph_harness.object_store)
    direct_asset = await _add_object(store, "direct-db")
    indirect_asset = await _add_object(store, "indirect-db")
    service = await _add_object(store, "middle-service")
    mission = await _add_mission(store, "Process orders", tier=2)
    await _add_relation(store, mission, direct_asset)
    await _add_relation(store, service, indirect_asset, "runs_on")
    await _add_relation(store, mission, service)

    result = await engine.assess_finding_impact(_finding(indirect_asset.id, direct_asset.id))

    assert [impact.mission.id for impact in result.impacts] == [mission.id]
    assert result.impacts[0].source_object_id == direct_asset.id
    assert result.impacts[0].via.length == 1


async def test_mission_factor_max(graph_harness: Any) -> None:
    engine = _engine(
        graph_harness,
        config=MissionConfig(tier_weights={1: 1.0, 3: 0.4}, default_tier=3),
    )
    store = cast(ObjectStore, graph_harness.object_store)
    asset = await _add_object(store, "shared-db")
    low = await _add_mission(store, "Low criticality reporting", tier=3)
    high = await _add_mission(store, "Critical patient records", tier=1)
    await _add_relation(store, low, asset)
    await _add_relation(store, high, asset)

    result = await engine.assess_finding_impact(_finding(asset.id))

    assert sorted(impact.impact_score for impact in result.impacts) == [0.4, 1.0]
    assert max(impact.impact_score for impact in result.impacts) == 1.0


async def test_mission_truncation_propagates(graph_harness: Any) -> None:
    engine = _engine(graph_harness, config=MissionConfig(max_depth=1))
    store = cast(ObjectStore, graph_harness.object_store)
    asset = await _add_object(store, "deep-db")
    service = await _add_object(store, "deep-service")
    mission = await _add_mission(store, "Delayed mission", tier=1)
    await _add_relation(store, service, asset, "runs_on")
    await _add_relation(store, mission, service)

    result = await engine.mission_impact(asset.id)

    assert result.truncated is True
    assert result.impacts == []


async def test_mission_tenant_isolation(graph_harness: Any) -> None:
    engine = _engine(graph_harness)
    store = cast(ObjectStore, graph_harness.object_store)
    asset_a = await _add_object(store, "tenant-a-db", tenant_id=TENANT_A)
    asset_b = await _add_object(store, "tenant-b-db", tenant_id=TENANT_B)
    mission_a = await _add_mission(store, "Tenant A mission", tier=1, tenant_id=TENANT_A)
    mission_b = await _add_mission(store, "Tenant B mission", tier=1, tenant_id=TENANT_B)
    await _add_relation(store, mission_a, asset_a)
    await _add_relation(store, mission_b, asset_b)

    result = await engine.mission_impact(asset_a.id)

    assert [impact.mission.id for impact in result.impacts] == [mission_a.id]
    assert mission_b.id not in [impact.mission.id for impact in result.impacts]
