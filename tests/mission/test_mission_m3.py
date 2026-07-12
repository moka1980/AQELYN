"""M3 acceptance tests for Mission Engine prioritization."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, cast

import pytest

from aqelyn.conventions import ActorRef, new_id
from aqelyn.findings import Automation, Finding, Remediation
from aqelyn.findings.models import Severity
from aqelyn.mission import MISSION_OBJECT_TYPE, MissionConfig, MissionEngine, PriorityItem
from aqelyn.objects import AQObject, AQRelationship, ObjectStore, SourceRef

SYS = ActorRef(actor_type="system", actor_id="mission-priority-test")


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
) -> AQObject:
    now = _now()
    return await store.upsert(
        AQObject(
            id="",
            object_type=object_type,
            schema_version=1,
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


async def _add_mission(store: ObjectStore, display_name: str, *, tier: int) -> AQObject:
    return await _add_object(
        store,
        display_name,
        object_type=MISSION_OBJECT_TYPE,
        attributes={"criticality_tier": tier},
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


def _finding(
    affected_object_ids: Sequence[str] = (),
    *,
    finding_id: str | None = None,
    severity: Severity = "high",
    confidence: float = 0.8,
) -> Finding:
    now = _now()
    return Finding(
        id=finding_id or new_id("fnd"),
        finding_type="mission-priority-test",
        schema_version=1,
        dedup_key=finding_id or new_id("fnd"),
        title="Mission-aware finding",
        severity=severity,
        severity_score=75.0,
        what_happened="An asset has a material issue.",
        why_it_matters="The asset may support business missions.",
        how_determined="Mission prioritization acceptance test.",
        risk_of_inaction="Dependent missions may be interrupted.",
        evidence_ids=[new_id("evd")],
        affected_object_ids=list(affected_object_ids),
        remediation=Remediation(
            summary="Fix the affected asset.",
            steps=["Repair or replace the affected component."],
            difficulty="medium",
            expected_outcome="Mission dependency is restored.",
        ),
        automation=Automation(eligibility="none"),
        confidence=confidence,
        source_engine="mission-test",
        first_detected_at=now,
        last_detected_at=now,
    )


async def _asset_with_mission(
    store: ObjectStore, *, mission_name: str, tier: int
) -> tuple[AQObject, AQObject]:
    asset = await _add_object(store, f"{mission_name}-asset")
    mission = await _add_mission(store, mission_name, tier=tier)
    await _add_relation(store, mission, asset)
    return asset, mission


def _scores(items: Sequence[PriorityItem]) -> dict[str, float]:
    return {item.finding_id: item.priority_score for item in items}


async def test_mission_priority_bounded(graph_harness: Any) -> None:
    engine = _engine(
        graph_harness,
        config=MissionConfig(tier_weights={1: 1.0, 3: 0.4}, default_tier=3),
    )
    store = cast(ObjectStore, graph_harness.object_store)
    asset, _ = await _asset_with_mission(store, mission_name="Run payroll", tier=1)
    finding = _finding([asset.id], severity="high", confidence=0.5)

    [item] = await engine.prioritize([finding])

    assert 0.0 <= item.priority_score <= 1.0
    assert item.priority_score == pytest.approx(0.4 * 0.75 + 0.4 * 1.0 + 0.2 * 0.5)
    assert item.mission_factor == 1.0
    assert item.severity_weight == 0.75
    assert item.confidence == 0.5


async def test_mission_priority_monotonic(graph_harness: Any) -> None:
    engine = _engine(
        graph_harness,
        config=MissionConfig(tier_weights={1: 1.0, 3: 0.4}, default_tier=3),
    )
    store = cast(ObjectStore, graph_harness.object_store)
    low_asset, _ = await _asset_with_mission(store, mission_name="Reporting", tier=3)
    high_asset, _ = await _asset_with_mission(store, mission_name="Patient records", tier=1)
    base = _finding([low_asset.id], severity="low", confidence=0.4)
    higher_severity = _finding([low_asset.id], severity="critical", confidence=0.4)
    higher_mission = _finding([high_asset.id], severity="low", confidence=0.4)
    higher_confidence = _finding([low_asset.id], severity="low", confidence=0.9)

    scores = _scores(
        await engine.prioritize([base, higher_severity, higher_mission, higher_confidence])
    )

    assert scores[higher_severity.id] > scores[base.id]
    assert scores[higher_mission.id] > scores[base.id]
    assert scores[higher_confidence.id] > scores[base.id]


async def test_mission_prioritize_deterministic(graph_harness: Any) -> None:
    engine = _engine(graph_harness)
    first = _finding(finding_id=new_id("fnd"), severity="medium", confidence=0.5)
    second = _finding(finding_id=new_id("fnd"), severity="medium", confidence=0.5)

    forward = await engine.prioritize([first, second])
    reverse = await engine.prioritize([second, first])

    assert [item.finding_id for item in forward] == sorted([first.id, second.id])
    assert [item.model_dump(mode="json") for item in forward] == [
        item.model_dump(mode="json") for item in reverse
    ]


async def test_mission_unmapped_finding_ranked(graph_harness: Any) -> None:
    engine = _engine(
        graph_harness,
        config=MissionConfig(tier_weights={1: 1.0, 3: 0.4}, default_tier=3),
    )
    finding = _finding([], severity="medium", confidence=0.6)

    [item] = await engine.prioritize([finding])

    assert item.finding_id == finding.id
    assert item.top_mission is None
    assert item.impacts == []
    assert item.mission_factor == 0.4
    assert item.priority_score == pytest.approx(0.4 * 0.5 + 0.4 * 0.4 + 0.2 * 0.6)
    assert "no impacted mission" in item.reason


async def test_mission_explainable(graph_harness: Any) -> None:
    engine = _engine(
        graph_harness,
        config=MissionConfig(tier_weights={1: 1.0, 2: 0.7, 3: 0.4}, default_tier=3),
    )
    store = cast(ObjectStore, graph_harness.object_store)
    asset = await _add_object(store, "database")
    service = await _add_object(store, "orders-api")
    mission = await _add_mission(store, "Process orders", tier=2)
    await _add_relation(store, service, asset, "runs_on")
    await _add_relation(store, mission, service)
    [item] = await engine.prioritize([_finding([asset.id], severity="critical", confidence=0.9)])

    explanation = engine.explain_priority(item)

    assert explanation["method"] == "weighted_sum/v1"
    assert explanation["priority_score"] == item.priority_score
    assert explanation["top_mission"] is not None
    factors = cast(dict[str, object], explanation["factors"])
    assert cast(dict[str, object], factors["mission"])["value"] == 0.7
    impacts = cast(list[dict[str, object]], explanation["impacts"])
    assert impacts[0]["source_object_id"] == asset.id
    assert cast(dict[str, object], impacts[0]["mission"])["id"] == mission.id
    path = cast(dict[str, object], impacts[0]["path"])
    assert path["node_ids"] == [asset.id, service.id, mission.id]
    edges = cast(list[dict[str, object]], path["edges"])
    assert [edge["relation_type"] for edge in edges] == ["runs_on", "depends_on"]
    assert edges[0]["sources"]


async def test_mission_no_side_effects(graph_harness: Any) -> None:
    engine = _engine(graph_harness)
    store = cast(ObjectStore, graph_harness.object_store)
    asset, mission = await _asset_with_mission(store, mission_name="Protect records", tier=1)
    finding = _finding([asset.id], severity="high", confidence=0.8)
    asset_before_obj = await store.get(asset.id)
    mission_before_obj = await store.get(mission.id)
    assert asset_before_obj is not None
    assert mission_before_obj is not None
    asset_before = asset_before_obj.model_dump(mode="json")
    mission_before = mission_before_obj.model_dump(mode="json")
    rels_before = [
        rel.model_dump(mode="json") for rel in await store.relationships(asset.id, direction="in")
    ]
    finding_before = finding.model_dump(mode="json")

    await engine.prioritize([finding])

    asset_after_obj = await store.get(asset.id)
    mission_after_obj = await store.get(mission.id)
    assert asset_after_obj is not None
    assert mission_after_obj is not None
    asset_after = asset_after_obj.model_dump(mode="json")
    mission_after = mission_after_obj.model_dump(mode="json")
    rels_after = [
        rel.model_dump(mode="json") for rel in await store.relationships(asset.id, direction="in")
    ]
    assert finding.model_dump(mode="json") == finding_before
    assert asset_after == asset_before
    assert mission_after == mission_before
    assert rels_after == rels_before
